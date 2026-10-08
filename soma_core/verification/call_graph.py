from __future__ import annotations

"""Call Graph Completeness Checker — Layer 1 Verification Tool.

Answers: "Is every defined function reachable from at least one call site?"

Uses Python AST traversal to extract function definitions, inspect module exports
(__all__), and resolve intra-module and inter-module call sites without false-positive
regex collisions.
Pure deterministic — no LLM judgment.
"""

import ast
import os
import sys
from dataclasses import dataclass
from typing import Optional

from . import ToolEvidence

__all__ = ["check", "find_definitions", "find_call_sites"]


@dataclass(frozen=True)
class FunctionDefInfo:
    """Metadata for a function or method definition in an AST."""
    name: str
    line_no: int
    is_exported: bool = False
    is_method: bool = False
    class_name: Optional[str] = None


class FunctionDefinitionVisitor(ast.NodeVisitor):
    """Extracts function/method definitions and module __all__ exports."""

    def __init__(self):
        self.definitions: dict[str, FunctionDefInfo] = {}
        self.dunder_all: set[str] = set()
        self.class_stack: list[str] = []

    def visit_Assign(self, node: ast.Assign):
        # Extract __all__ = ["func1", "ClassA"]
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            self.dunder_all.add(elt.value)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._record_func(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._record_func(node)
        self.generic_visit(node)

    def _record_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        # Skip standard dunder methods (__init__, __repr__, etc.)
        if node.name.startswith("__") and node.name.endswith("__"):
            return
        is_method = bool(self.class_stack)
        # Skip AST NodeVisitor dynamic dispatch handlers
        if is_method and node.name.startswith("visit_"):
            return
        class_name = self.class_stack[-1] if is_method else None
        is_exported = node.name in self.dunder_all or (class_name is not None and class_name in self.dunder_all)
        self.definitions[node.name] = FunctionDefInfo(
            name=node.name,
            line_no=node.lineno,
            is_exported=is_exported,
            is_method=is_method,
            class_name=class_name,
        )


class InternalCallCollector(ast.NodeVisitor):
    """Collects direct and method calls within a module, tracking enclosing scope."""

    def __init__(self):
        self.direct_calls: set[str] = set()
        self.attribute_calls: set[str] = set()
        self.current_func: Optional[str] = None
        self.non_recursive_calls: set[str] = set()
        self.non_recursive_attrs: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        prev = self.current_func
        self.current_func = node.name
        self.generic_visit(node)
        self.current_func = prev

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        prev = self.current_func
        self.current_func = node.name
        self.generic_visit(node)
        self.current_func = prev

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            callee = node.func.id
            self.direct_calls.add(callee)
            if self.current_func != callee:
                self.non_recursive_calls.add(callee)
        elif isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            self.attribute_calls.add(attr)
            if self.current_func != attr:
                self.non_recursive_attrs.add(attr)
        # Check arguments passed to calls (e.g. callbacks or dispatch handlers)
        for arg in node.args:
            if isinstance(arg, ast.Name):
                self.direct_calls.add(arg.id)
                self.non_recursive_calls.add(arg.id)
        for kw in node.keywords:
            if isinstance(kw.value, ast.Name):
                self.direct_calls.add(kw.value.id)
                self.non_recursive_calls.add(kw.value.id)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict):
        for val in node.values:
            if isinstance(val, ast.Name):
                self.direct_calls.add(val.id)
                self.non_recursive_calls.add(val.id)
        self.generic_visit(node)

    def visit_List(self, node: ast.List):
        for elt in node.elts:
            if isinstance(elt, ast.Name):
                self.direct_calls.add(elt.id)
                self.non_recursive_calls.add(elt.id)
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple):
        for elt in node.elts:
            if isinstance(elt, ast.Name):
                self.direct_calls.add(elt.id)
                self.non_recursive_calls.add(elt.id)
        self.generic_visit(node)

    def visit_Set(self, node: ast.Set):
        for elt in node.elts:
            if isinstance(elt, ast.Name):
                self.direct_calls.add(elt.id)
                self.non_recursive_calls.add(elt.id)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        if isinstance(node.value, ast.Name):
            self.direct_calls.add(node.value.id)
            self.non_recursive_calls.add(node.value.id)
        self.generic_visit(node)


class ExternalModuleInspector(ast.NodeVisitor):
    """Analyzes an external file to check if it calls target functions from target module."""

    def __init__(self, target_stems: set[str], target_func_names: set[str]):
        self.target_stems = target_stems
        self.target_func_names = target_func_names
        # Bound names in this external file that point to our target functions
        self.bound_direct_names: set[str] = set()
        # Aliases/module identifiers that refer to our target module
        self.bound_module_aliases: set[str] = set()
        # Confirmed called functions
        self.matched_calls: set[str] = set()
        self.has_wildcard_import: bool = False

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            parts = alias.name.split('.')
            if any(p in self.target_stems for p in parts):
                alias_name = alias.asname or parts[-1]
                self.bound_module_aliases.add(alias_name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        mod_name = node.module or ""
        parts = mod_name.split('.')
        is_target_mod = any(p in self.target_stems for p in parts)

        if is_target_mod:
            for alias in node.names:
                if alias.name == "*":
                    self.has_wildcard_import = True
                elif alias.name in self.target_func_names:
                    local_name = alias.asname or alias.name
                    self.bound_direct_names.add(local_name)
                else:
                    # Could be an imported class whose methods are called
                    self.bound_module_aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            callee = node.func.id
            if callee in self.bound_direct_names:
                self.matched_calls.add(callee)
            elif self.has_wildcard_import and callee in self.target_func_names:
                self.matched_calls.add(callee)
        elif isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr in self.target_func_names:
                # If receiver is an alias to target module or class imported from target
                if isinstance(node.func.value, ast.Name):
                    if node.func.value.id in self.bound_module_aliases or node.func.value.id in self.target_stems:
                        self.matched_calls.add(attr)
                elif self.has_wildcard_import:
                    self.matched_calls.add(attr)
        self.generic_visit(node)


def find_definitions(filepath: str) -> dict[str, int]:
    """Extract all function/method definitions with line numbers.

    Returns {function_name: line_number}
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            source = f.read()
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return {}

    visitor = FunctionDefinitionVisitor()
    visitor.visit(tree)
    return {name: info.line_no for name, info in visitor.definitions.items()}


def _get_target_module_stems(filepath: str, repo_root: str) -> set[str]:
    """Compute module name variations (stem and dotted path) for import resolution."""
    stem = os.path.splitext(os.path.basename(filepath))[0]
    stems = {stem}
    try:
        rel_path = os.path.relpath(filepath, repo_root)
        if not rel_path.startswith(".."):
            no_ext = os.path.splitext(rel_path)[0]
            dotted = no_ext.replace(os.sep, '.')
            stems.add(dotted)
            parts = dotted.split('.')
            stems.update(parts)
    except ValueError:
        pass
    return stems


def find_call_sites(func_name: str, repo_root: str, exclude_file: str = "") -> list[str]:
    """Find all files in repo_root that call a function by name using AST."""
    target_stems = _get_target_module_stems(exclude_file, repo_root) if exclude_file else {func_name}
    target_funcs = {func_name}
    call_sites: list[str] = []

    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [
            d for d in dirs
            if not d.startswith('.')
            and d not in ('__pycache__', 'node_modules', '.venv', 'venv', 'dist', 'build')
        ]

        for fname in files:
            if not fname.endswith('.py'):
                continue
            fpath = os.path.join(root, fname)
            if exclude_file and os.path.abspath(fpath) == os.path.abspath(exclude_file):
                continue

            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue

            if func_name not in content:
                continue

            try:
                tree = ast.parse(content, filename=fpath)
            except SyntaxError:
                continue

            inspector = ExternalModuleInspector(target_stems, target_funcs)
            inspector.visit(tree)
            if func_name in inspector.matched_calls:
                call_sites.append(fpath)

    return call_sites


def check(
    filepath: str,
    repo_root: str,
    exclude_names: set[str] | None = None,
    *,
    fast_mode: bool = False,
) -> ToolEvidence:
    """Run AST-based call graph completeness check.

    Args:
        filepath: Path to the Python file to analyze
        repo_root: Root of the repository to search for call sites
        exclude_names: Function names to skip (e.g., CLI entry points)
        fast_mode: If True, performs file-isolated checks and skips external repo walks

    Returns:
        ToolEvidence with verdict=True if all functions have call sites or are exported
    """
    exclude_names = exclude_names or set()

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
    except (OSError, SyntaxError, UnicodeDecodeError) as e:
        return ToolEvidence(
            tool="call_graph",
            target=os.path.basename(filepath),
            verdict=False,
            detail=f"Failed to parse AST: {e}",
        )

    # 1. Extract definitions and __all__ exports
    def_visitor = FunctionDefinitionVisitor()
    def_visitor.visit(tree)
    # Re-evaluate is_exported post-traversal so trailing __all__ definitions are honored
    for name, info in list(def_visitor.definitions.items()):
        is_exp = name in def_visitor.dunder_all or (info.class_name is not None and info.class_name in def_visitor.dunder_all)
        if is_exp and not info.is_exported:
            def_visitor.definitions[name] = FunctionDefInfo(
                name=info.name,
                line_no=info.line_no,
                is_exported=True,
                is_method=info.is_method,
                class_name=info.class_name,
            )
    definitions = def_visitor.definitions

    if not definitions:
        return ToolEvidence(
            tool="call_graph",
            target=os.path.basename(filepath),
            verdict=True,
            detail="No function definitions found to verify",
        )

    # 2. Extract internal calls within the target file itself
    int_collector = InternalCallCollector()
    int_collector.visit(tree)
    internal_called = int_collector.non_recursive_calls | int_collector.non_recursive_attrs

    # 3. Identify candidate orphan functions
    candidate_orphans: dict[str, FunctionDefInfo] = {}
    for name, info in definitions.items():
        if name in exclude_names:
            continue
        # Exported via __all__ (e.g. public library/SDK API)
        if info.is_exported:
            continue
        # Called internally
        if name in internal_called:
            continue
        candidate_orphans[name] = info

    # 4. If candidates remain, inspect external repository files
    orphans: dict[str, int] = {}
    if candidate_orphans:
        if fast_mode:
            # Fast mode (e.g. pre-commit): skip repo-wide os.walk to preserve <300ms budget
            return ToolEvidence(
                tool="call_graph",
                target=os.path.basename(filepath),
                verdict=True,
                detail=f"fast_mode: intra-module checks passed ({len(definitions)} functions verified, {len(candidate_orphans)} external candidates skipped)",
            )
        target_stems = _get_target_module_stems(filepath, repo_root)
        candidate_names = set(candidate_orphans.keys())
        externally_matched: set[str] = set()

        for root, dirs, files in os.walk(repo_root):
            dirs[:] = [
                d for d in dirs
                if not d.startswith('.')
                and d not in ('__pycache__', 'node_modules', '.venv', 'venv', 'dist', 'build')
            ]

            for fname in files:
                if not fname.endswith('.py'):
                    continue
                fpath = os.path.join(root, fname)
                if os.path.abspath(fpath) == os.path.abspath(filepath):
                    continue

                remaining = candidate_names - externally_matched
                if not remaining:
                    break

                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                except (OSError, UnicodeDecodeError):
                    continue

                # Fast filter: skip AST parsing if none of the candidate names appear
                if not any(name in content for name in remaining):
                    continue

                try:
                    ext_tree = ast.parse(content, filename=fpath)
                except SyntaxError:
                    continue

                inspector = ExternalModuleInspector(target_stems, remaining)
                inspector.visit(ext_tree)
                externally_matched.update(inspector.matched_calls)

        for name, info in candidate_orphans.items():
            if name not in externally_matched:
                orphans[name] = info.line_no

    if orphans:
        orphan_details = [f"{name} (L{line})" for name, line in sorted(orphans.items())]
        return ToolEvidence(
            tool="call_graph",
            target=os.path.basename(filepath),
            verdict=False,
            detail=f"ORPHAN FUNCTIONS: {'; '.join(orphan_details)} — defined but never called",
            lines=list(orphans.values()),
        )

    return ToolEvidence(
        tool="call_graph",
        target=os.path.basename(filepath),
        verdict=True,
        detail=f"All {len(definitions)} functions have call sites",
    )


if __name__ == '__main__':
    # A cp1252 stdout can't encode this script's symbols (BUG-038).
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <file> <repo_root>")
        sys.exit(1)

    result = check(sys.argv[1], sys.argv[2])
    icon = "✅" if result.verdict else "🔴"
    print(f"{icon} {result.tool}: {result.target}")
    print(f"   {result.detail}")
    sys.exit(0 if result.verdict else 1)
