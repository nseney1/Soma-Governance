"""Layer 1 Runner — orchestrates all deterministic verification tools.

Runs mandatory checks on changed files and produces a combined evidence package.
The output feeds directly into the Arbiter as Layer 1 evidence.
"""
import os
import sys
from typing import Optional

from . import ToolEvidence
from . import persistence_checker
from . import call_graph
from . import import_guard
from . import mutation_tester
from . import branch_coverage


def _find_test_file(filepath: str, repo_root: str) -> Optional[str]:
    """Find the test file for a source file by convention.

    Searches for test_<stem>.py in:
      1. Same directory
      2. tests/ directory at repo root
      3. tests/ subdirectory mirroring source path
    """
    stem = os.path.splitext(os.path.basename(filepath))[0]
    test_name = f"test_{stem}.py"

    # 1. Same directory
    same_dir = os.path.join(repo_root, os.path.dirname(filepath), test_name)
    if os.path.exists(same_dir):
        return same_dir

    # 2. tests/ at repo root
    tests_root = os.path.join(repo_root, "tests", test_name)
    if os.path.exists(tests_root):
        return tests_root

    # 3. tests/ mirroring subdirectory
    parent = os.path.dirname(filepath)
    tests_sub = os.path.join(repo_root, "tests", parent, test_name)
    if os.path.exists(tests_sub):
        return tests_sub

    return None


def _discover_functions(filepath: str) -> list[str]:
    """Extract top-level function names from a Python file via AST."""
    import ast
    try:
        with open(filepath) as f:
            tree = ast.parse(f.read())
    except (SyntaxError, OSError):
        return []
    return [
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and not node.name.startswith('_')
        and not node.name.startswith('test_')
    ]


def run_layer1(
    changed_files: list[str],
    repo_root: str,
    persistence_targets: Optional[list[tuple[str, str]]] = None,
    mutation_targets: Optional[list[tuple[str, str, str]]] = None,
    coverage_targets: Optional[list[tuple[str, str]]] = None,
    max_mutations: int = 5,
) -> list[ToolEvidence]:
    """Run all Layer 1 verification tools.

    Args:
        changed_files: List of file paths that were modified
        repo_root: Root of the repository
        persistence_targets: List of (filepath, dict_name) tuples for
            persistence checking. If None, auto-detects from changed_files.
        mutation_targets: List of (source_file, func_name, test_file) tuples.
            If None, auto-discovers from changed_files using convention.
        coverage_targets: List of (source_file, test_file) tuples.
            If None, auto-discovers from changed_files using convention.
        max_mutations: Maximum mutations per function (default: 5).

    Returns:
        List of ToolEvidence results for the Arbiter
    """
    results: list[ToolEvidence] = []

    # ── Persistence Completeness ──────────────────────────────────────
    if persistence_targets:
        for filepath, dict_name in persistence_targets:
            full_path = os.path.join(repo_root, filepath)
            if os.path.exists(full_path):
                results.append(persistence_checker.check(full_path, dict_name))

    # ── Call Graph Completeness ───────────────────────────────────────
    for filepath in changed_files:
        full_path = os.path.join(repo_root, filepath)
        if os.path.exists(full_path) and filepath.endswith('.py'):
            # Skip test files and __init__.py
            basename = os.path.basename(filepath)
            if basename.startswith('test_') or basename == '__init__.py':
                continue
            results.append(call_graph.check(
                full_path, repo_root,
                exclude_names={'main', '_parse_args', 'parse_args'}
            ))

    # ── Import Guards ─────────────────────────────────────────────────
    for filepath in changed_files:
        full_path = os.path.join(repo_root, filepath)
        if os.path.exists(full_path) and filepath.endswith('.py'):
            results.append(import_guard.check(full_path, project_root=repo_root))

    # ── Mutation Testing ───────────────────────────────────────────────
    if mutation_targets:
        for source, func, test in mutation_targets:
            src_path = os.path.join(repo_root, source)
            tst_path = os.path.join(repo_root, test)
            if os.path.exists(src_path) and os.path.exists(tst_path):
                results.append(mutation_tester.check(
                    src_path, func, tst_path, max_mutations=max_mutations,
                ))
    else:
        # Auto-discover: for each changed .py file, find test file and functions
        for filepath in changed_files:
            if not filepath.endswith('.py'):
                continue
            basename = os.path.basename(filepath)
            if basename.startswith('test_') or basename == '__init__.py':
                continue
            full_path = os.path.join(repo_root, filepath)
            if not os.path.exists(full_path):
                continue
            test_file = _find_test_file(filepath, repo_root)
            if test_file is None:
                continue
            funcs = _discover_functions(full_path)
            for func_name in funcs[:3]:  # Limit auto-discovery to 3 functions
                results.append(mutation_tester.check(
                    full_path, func_name, test_file,
                    max_mutations=max_mutations,
                ))

    # ── Branch Coverage ───────────────────────────────────────────────
    if coverage_targets:
        for source, test in coverage_targets:
            src_path = os.path.join(repo_root, source)
            tst_path = os.path.join(repo_root, test)
            if os.path.exists(src_path) and os.path.exists(tst_path):
                results.append(branch_coverage.check(src_path, tst_path))
    else:
        # Auto-discover: pair changed files with test files by convention
        for filepath in changed_files:
            if not filepath.endswith('.py'):
                continue
            basename = os.path.basename(filepath)
            if basename.startswith('test_') or basename == '__init__.py':
                continue
            full_path = os.path.join(repo_root, filepath)
            if not os.path.exists(full_path):
                continue
            test_file = _find_test_file(filepath, repo_root)
            if test_file is None:
                continue
            results.append(branch_coverage.check(full_path, test_file))

    return results


# ── Layer 2: Adversarial Verification Orchestrator ────────────────────────


def _strip_code_fence(text: str) -> str:
    """Strip markdown code fences (```json ... ```) from LLM output."""
    import re
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def run_layer2(
    changed_files: list[str],
    repo_root: str,
    task_plan: str,
    layer1_evidence: list[ToolEvidence],
    llm_backend,
    test_names: Optional[list[str]] = None,
    test_results: Optional[str] = None,
) -> 'ArbitrationResult':
    """Run the two-layer adversarial verification protocol.

    Orchestrates the information-partitioned Spec Agent and Code Agent
    through a pluggable LLM backend, then feeds everything into the
    deterministic Arbiter.

    Args:
        changed_files: List of file paths that were modified.
        repo_root: Root of the repository.
        task_plan: Natural language description of what was planned.
        layer1_evidence: Layer 1 tool results from run_layer1().
        llm_backend: Callable(prompt: str) -> str. Required, no default.
        test_names: Optional list of test function names.
        test_results: Optional test output string.

    Returns:
        ArbitrationResult with verdict, divergences, and convergences.
    """
    import json as _json
    from . import immune_verify, arbiter, ArbitrationResult, Prediction, Claim

    if llm_backend is None:
        raise TypeError("llm_backend must be a callable, got None")

    # ── 1. Extract signatures and implementation from changed files ────
    all_signatures: list[str] = []
    all_implementation: list[str] = []

    for filepath in changed_files:
        full_path = os.path.join(repo_root, filepath)
        if not os.path.exists(full_path) or not filepath.endswith('.py'):
            continue
        # Filter out test files and __init__.py from Layer 2 analysis
        basename = os.path.basename(filepath)
        if basename.startswith('test_') or basename in ('__init__.py', 'conftest.py'):
            continue
        try:
            sigs = immune_verify.extract_signatures(full_path)
            all_signatures.extend(sigs)
            with open(full_path) as f:
                all_implementation.append(f.read())
        except (SyntaxError, OSError, ValueError, UnicodeDecodeError):
            continue

    implementation_text = "\n\n".join(all_implementation)

    # ── 2. Build prompts with information partitioning ─────────────────
    # Spec Agent sees: plan + signatures + test names (NEVER implementation)
    spec_prompt = immune_verify.build_spec_prompt(
        plan=task_plan,
        signatures=all_signatures,
        test_names=test_names or [],
    )

    # Code Agent sees: implementation + test results + Layer 1 (NEVER plan)
    layer1_output: dict[str, list] = {}
    for e in layer1_evidence:
        layer1_output.setdefault(e.tool, []).append(
            {"target": e.target, "verdict": e.verdict, "detail": e.detail}
        )
    code_prompt = immune_verify.build_code_prompt(
        implementation=implementation_text,
        test_results=test_results or "",
        layer1_output=layer1_output,
    )

    # ── 3. Dispatch to LLM backend ────────────────────────────────────
    spec_response = llm_backend(spec_prompt)
    code_response = llm_backend(code_prompt)

    # ── 4. Parse structured responses ─────────────────────────────────
    spec_agent_failed = False
    try:
        raw_predictions = _json.loads(_strip_code_fence(spec_response))
    except (_json.JSONDecodeError, TypeError):
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "Spec Agent returned unparseable JSON; defaulting to empty predictions"
        )
        raw_predictions = []
        spec_agent_failed = True

    try:
        raw_claims = _json.loads(_strip_code_fence(code_response))
    except (_json.JSONDecodeError, TypeError):
        raw_claims = []

    predictions = immune_verify.parse_predictions(raw_predictions)
    claims = immune_verify.parse_claims(raw_claims)

    # ── 5. Arbitrate ──────────────────────────────────────────────────
    return arbiter.arbitrate(
        predictions, claims, layer1_evidence,
        spec_agent_failed=spec_agent_failed,
    )


def gate_verdict(results: list[ToolEvidence]) -> bool:
    """Simple gate: PASS if all tools pass, FAIL if any fails."""
    return all(r.verdict for r in results)


def format_summary(results: list[ToolEvidence]) -> str:
    """One-line summary of Layer 1 results."""
    passed = sum(1 for r in results if r.verdict)
    failed = sum(1 for r in results if not r.verdict)
    total = len(results)
    if failed:
        return f"Layer 1: {failed}/{total} FAILED — {', '.join(r.tool for r in results if not r.verdict)}"
    return f"Layer 1: {passed}/{total} PASSED"


if __name__ == '__main__':
    # A cp1252 stdout can't encode this script's symbols (BUG-038).
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <repo_root> [file1 file2 ...]")
        sys.exit(1)

    repo_root = sys.argv[1]
    changed = sys.argv[2:] if len(sys.argv) > 2 else []

    results = run_layer1(changed, repo_root)
    for r in results:
        icon = "✅" if r.verdict else "🔴"
        print(f"{icon} {r.tool}: {r.target} — {r.detail}")

    print(f"\n{format_summary(results)}")
    sys.exit(0 if gate_verdict(results) else 1)
