from __future__ import annotations

"""Call Graph Completeness Checker — Layer 1 Verification Tool.

Answers: "Is every defined function reachable from at least one call site?"

Uses AST to extract function definitions and grep to find call sites.
Pure deterministic — no LLM judgment.
"""

import ast
import os
import re
import sys

from . import ToolEvidence


def find_definitions(filepath: str) -> dict[str, int]:
    """Extract all function/method definitions with line numbers.

    Returns {function_name: line_number}
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()

    tree = ast.parse(source)
    defs: dict[str, int] = {}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip dunder methods and private helpers
            if not node.name.startswith('__'):
                defs[node.name] = node.lineno

    return defs


def find_call_sites(func_name: str, repo_root: str, exclude_file: str = "") -> list[str]:
    """Find all files that call a function by name.

    Uses regex to find function calls (name followed by '(').
    Excludes the definition file itself.

    Returns list of file paths containing calls.
    """
    pattern = re.compile(rf'\b{re.escape(func_name)}\s*\(')
    call_sites = []

    for root, dirs, files in os.walk(repo_root):
        # Skip hidden dirs, __pycache__, .git
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']

        for fname in files:
            if not fname.endswith(('.py', '.sh')):
                continue
            fpath = os.path.join(root, fname)
            if os.path.abspath(fpath) == os.path.abspath(exclude_file):
                continue
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if pattern.search(content):
                    call_sites.append(fpath)
            except (OSError, UnicodeDecodeError):
                continue

    return call_sites


def check(
    filepath: str,
    repo_root: str,
    exclude_names: set[str] | None = None,
) -> ToolEvidence:
    """Run call graph completeness check.

    Args:
        filepath: Path to the Python file to analyze
        repo_root: Root of the repository to search for call sites
        exclude_names: Function names to skip (e.g., CLI entry points)

    Returns:
        ToolEvidence with verdict=True if all functions have call sites
    """
    exclude_names = exclude_names or set()
    definitions = find_definitions(filepath)

    orphans: dict[str, int] = {}
    for func_name, line_no in definitions.items():
        if func_name in exclude_names:
            continue
        # Also skip if it's called within the same file (internal helpers)
        with open(filepath, 'r', encoding='utf-8') as f:
            source_lines = f.readlines()
        # Count call-site occurrences (exclude the def line itself)
        pattern = re.compile(rf'\b{re.escape(func_name)}\s*\(')
        internal_calls = 0
        for line in source_lines:
            if pattern.search(line) and not line.lstrip().startswith('def '):
                internal_calls += 1
        if internal_calls > 0:
            continue

        external_sites = find_call_sites(func_name, repo_root, filepath)
        if not external_sites:
            orphans[func_name] = line_no

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
