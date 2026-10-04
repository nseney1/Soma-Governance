from __future__ import annotations

"""Lightweight mutation testing for the verification framework.

Parses a target function from a file using AST, generates mutations
(operator swaps, constant replacements, line removals), runs the test
suite against each mutant, and reports surviving mutations.
"""

import ast
import copy
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from . import ToolEvidence


# ── AST Mutation Visitors ──────────────────────────────────────────────────

# Operator swap pairs
_BINOP_SWAPS: dict[type, type] = {
    ast.Add: ast.Sub,
    ast.Sub: ast.Add,
    ast.Mult: ast.Div,
    ast.Div: ast.Mult,
}

_UNARYOP_SWAPS: dict[type, type] = {
    ast.UAdd: ast.USub,
    ast.USub: ast.UAdd,
}

_CMPOP_SWAPS: dict[type, type] = {
    ast.Gt: ast.Lt,
    ast.Lt: ast.Gt,
    ast.GtE: ast.LtE,
    ast.LtE: ast.GtE,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
}

_BOOLOP_SWAPS: dict[type, type] = {
    ast.And: ast.Or,
    ast.Or: ast.And,
}


class _Mutation:
    """Represents a single mutation to apply."""

    __slots__ = ("lineno", "apply")

    def __init__(self, lineno: int, apply):
        self.lineno = lineno
        self.apply = apply  # callable(tree) -> mutated tree


def _is_deletable_stmt(node: ast.AST) -> bool:
    # A docstring is an Expr too, but deleting it changes nothing a test can
    # observe: an equivalent mutant that would always "survive".
    if not isinstance(node, (ast.Assign, ast.AugAssign, ast.Expr)):
        return False
    return not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str))


def _is_mutable_return(node: ast.AST) -> bool:
    # `return None` -> `return None` is not a mutation.
    if not isinstance(node, ast.Return) or node.value is None:
        return False
    return not (isinstance(node.value, ast.Constant) and node.value.value is None)


def _collect_mutations(source: str, function_name: str) -> list[_Mutation]:
    """Walk the AST of *function_name* and collect all possible mutations."""
    tree = ast.parse(source)
    func_node: Optional[ast.FunctionDef] = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            func_node = node
            break

    if func_node is None:
        return []

    mutations: list[_Mutation] = []

    for node in ast.walk(func_node):
        # 1) Binary operator swaps (+↔-, *↔/)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOP_SWAPS:
            mutations.append(_Mutation(node.lineno, None))

        # 2) Unary operator swaps
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOP_SWAPS:
            mutations.append(_Mutation(node.lineno, None))

        # 3) Constant replacement
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if node.value != 0:
                mutations.append(_Mutation(node.lineno, None))

        # 4) Comparison operator swaps (<↔>, <=↔>=, ==↔!=)
        if isinstance(node, ast.Compare):
            for op in node.ops:
                if type(op) in _CMPOP_SWAPS:
                    mutations.append(_Mutation(node.lineno, None))
                    break  # One mutation per Compare node

        # 5) Boolean operator swaps (and↔or)
        if isinstance(node, ast.BoolOp) and type(node.op) in _BOOLOP_SWAPS:
            mutations.append(_Mutation(node.lineno, None))

    # 6) Statement deletion (replace with pass) — one per non-trivial stmt
    for node in ast.walk(func_node):
        if _is_deletable_stmt(node):
            mutations.append(_Mutation(node.lineno, None))

    # 7) Return value mutation (return X → return None)
    for node in ast.walk(func_node):
        if _is_mutable_return(node):
            mutations.append(_Mutation(node.lineno, None))

    return mutations


def _apply_mutation_by_index(
    source: str, function_name: str, mutation_index: int
) -> Optional[str]:
    """Apply the i-th mutation to *source* and return the mutated source."""
    tree2 = ast.parse(source)

    # Collect mutation targets in the exact order of _collect_mutations
    targets2: list[ast.AST] = []
    kinds2: list[str] = []
    func_node2: Optional[ast.FunctionDef] = None
    for node in ast.walk(tree2):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            func_node2 = node
            break
    if func_node2 is None:
        return None

    for node in ast.walk(func_node2):
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOP_SWAPS:
            targets2.append(node)
            kinds2.append("binop")
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOP_SWAPS:
            targets2.append(node)
            kinds2.append("unaryop")
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if node.value != 0:
                targets2.append(node)
                kinds2.append("const")
        if isinstance(node, ast.Compare):
            for op in node.ops:
                if type(op) in _CMPOP_SWAPS:
                    targets2.append(node)
                    kinds2.append("cmpop")
                    break
        if isinstance(node, ast.BoolOp) and type(node.op) in _BOOLOP_SWAPS:
            targets2.append(node)
            kinds2.append("boolop")

    # Statement deletion targets
    for node in ast.walk(func_node2):
        if _is_deletable_stmt(node):
            targets2.append(node)
            kinds2.append("stmt_del")

    # Return value mutation targets
    for node in ast.walk(func_node2):
        if _is_mutable_return(node):
            targets2.append(node)
            kinds2.append("return_val")

    if mutation_index >= len(targets2):
        return None

    node_to_mutate = targets2[mutation_index]
    k = kinds2[mutation_index]

    if k == "binop":
        node_to_mutate.op = _BINOP_SWAPS[type(node_to_mutate.op)]()
    elif k == "unaryop":
        node_to_mutate.op = _UNARYOP_SWAPS[type(node_to_mutate.op)]()
    elif k == "const":
        if isinstance(node_to_mutate.value, int):
            node_to_mutate.value = node_to_mutate.value + 1
        else:
            node_to_mutate.value = node_to_mutate.value + 1.0
    elif k == "cmpop":
        node_to_mutate.ops = [
            _CMPOP_SWAPS.get(type(op), type(op))() for op in node_to_mutate.ops
        ]
    elif k == "boolop":
        node_to_mutate.op = _BOOLOP_SWAPS[type(node_to_mutate.op)]()
    elif k == "stmt_del":
        # Replace the statement with `pass`
        pass_node = ast.Pass()
        ast.copy_location(pass_node, node_to_mutate)
        # Find parent and replace
        for parent_node in ast.walk(tree2):
            for field, value in ast.iter_fields(parent_node):
                if isinstance(value, list):
                    for idx, item in enumerate(value):
                        if item is node_to_mutate:
                            value[idx] = pass_node
    elif k == "return_val":
        node_to_mutate.value = ast.Constant(value=None)
        ast.copy_location(node_to_mutate.value, node_to_mutate)

    ast.fix_missing_locations(tree2)
    try:
        return ast.unparse(tree2)
    except Exception:
        return None


def _run_tests(test_file: str, timeout: int = 30) -> bool:
    """Run pytest on *test_file*. Returns True if tests PASS."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file, "-x", "-q", "--no-header", "--tb=no"],
            capture_output=True,
            timeout=timeout,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        return False


# ── Public API ─────────────────────────────────────────────────────────────

def check(
    target_file: str,
    target_function: str,
    test_file: str,
    max_mutations: int | None = None,
) -> ToolEvidence:
    """Run mutation testing on *target_function* in *target_file*.

    For each generated mutation, writes a mutated copy and runs *test_file*.
    If the tests still pass, the mutation survived (indicating a weak test).

    Returns ToolEvidence with verdict=True if no mutations survive.
    """
    source = Path(target_file).read_text()
    mutations = _collect_mutations(source, target_function)

    if max_mutations is not None:
        mutations = mutations[:max_mutations]

    total = len(mutations)
    survived: list[int] = []

    # A mutant counts as killed whenever the tests fail, so tests that can't
    # pass against the original code (syntax/import error, wrong assertion)
    # would "kill" every mutant and pass (BUG-034). Fail closed instead.
    if mutations and not _run_tests(test_file):
        return ToolEvidence(
            tool="mutation_tester",
            target=f"{target_file}::{target_function}",
            verdict=False,
            detail="Baseline tests fail against the unmutated code; cannot assess mutations",
            lines=[-1],
        )

    for i, mutation in enumerate(mutations):
        mutated_source = _apply_mutation_by_index(source, target_function, i)
        if mutated_source is None:
            continue

        # Write mutant to a temp file at the same location so imports work
        target_path = Path(target_file)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            dir=str(target_path.parent),
            delete=False,
            prefix="_mutant_",
        ) as tmp:
            tmp.write(mutated_source)
            tmp_path = tmp.name

        try:
            # Patch test file to import from mutant instead of original
            test_source = Path(test_file).read_text()
            original_stem = target_path.stem
            mutant_stem = Path(tmp_path).stem

            patched_test = test_source.replace(
                f"from {original_stem} import",
                f"from {mutant_stem} import",
            )

            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                dir=str(Path(test_file).parent),
                delete=False,
                prefix="_test_mutant_",
            ) as test_tmp:
                test_tmp.write(patched_test)
                test_tmp_path = test_tmp.name

            try:
                if _run_tests(test_tmp_path):
                    # Tests passed with mutation → mutation survived
                    survived.append(mutation.lineno)
            finally:
                Path(test_tmp_path).unlink(missing_ok=True)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    survived_count = len(survived)
    verdict = survived_count == 0

    return ToolEvidence(
        tool="mutation_tester",
        target=f"{target_file}::{target_function}",
        verdict=verdict,
        detail=f"{survived_count}/{total} survived",
        lines=sorted(set(survived)),
    )
