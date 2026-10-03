"""BUG-038: standalone entry points must survive a cp1252 stdout.

Enzyme scripts print emoji/arrows from their ``__main__`` entry points. On a
Windows console or redirected pipe stdout is cp1252 with errors="strict", so
the first non-ASCII print raised UnicodeEncodeError and the script exited 1.
Each such entry point must apply the BUG-012 guard
(``sys.stdout.reconfigure(errors="replace")`` behind ``hasattr``).
"""
import ast
import os
import shutil
import subprocess
import sys

import pytest

from conftest import REPO_ROOT, read

ENTRY_GUARD = 'if __name__ == '
RECONFIGURE = "sys.stdout.reconfigure(errors="
HASATTR = "hasattr(sys.stdout,"
# Modules run with ``python -m`` because they use relative imports.
PACKAGE_MODULES = {
    os.path.join("immune_system", "verification", "runner.py"):
        "immune_system.verification.runner",
}


_DOC_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _docstring_nodes(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, _DOC_OWNERS) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                ids.add(id(first.value))
    return ids


def _has_non_ascii_literal(source):
    """True if a non-docstring str constant has non-ASCII *decoded* text.

    Tests the value, not the token, so escapes such as ``"\\u2705"`` count.
    f-string literal parts (``ast.JoinedStr`` constants) are included.
    """
    tree = ast.parse(source)
    docstrings = _docstring_nodes(tree)
    for node in ast.walk(tree):
        parts = node.values if isinstance(node, ast.JoinedStr) else [node]
        for part in parts:
            if (isinstance(part, ast.Constant) and isinstance(part.value, str)
                    and id(part) not in docstrings and not part.value.isascii()):
                return True
    return False


def _entry_points():
    rels = sorted(
        os.path.join("enzymes", name)
        for name in os.listdir(os.path.join(REPO_ROOT, "enzymes"))
        if name.endswith(".py")
    ) + sorted(PACKAGE_MODULES)
    found = []
    for rel in rels:
        source = read(os.path.join(REPO_ROOT, rel))
        if ENTRY_GUARD in source and _has_non_ascii_literal(source):
            found.append(rel)
    return found


ENTRY_POINTS = _entry_points()


def test_entry_point_discovery_finds_known_offenders():
    # Guards the discovery heuristic itself: the scripts named in BUG-038.
    for rel in ("enzymes/cell_crossover.py", "enzymes/soma_sleep.py",
                "immune_system/verification/runner.py"):
        assert os.path.normpath(rel) in ENTRY_POINTS


def test_discovery_decodes_escape_sequences():
    # A "\u2705" escape is pure ASCII in the token but prints U+2705.
    assert _has_non_ascii_literal('print("\\u2705 ok")\n')
    assert _has_non_ascii_literal('x = 1\nprint(f"{x} \\u2192 done")\n')
    assert not _has_non_ascii_literal('"""Doc \u2705."""\nprint("ok")\n')
    assert not _has_non_ascii_literal('def f():\n    """\u2705"""\n    return 1\n')


@pytest.mark.parametrize("rel", ENTRY_POINTS)
def test_entry_point_reconfigures_stdout(rel):
    source = read(os.path.join(REPO_ROOT, rel))
    assert RECONFIGURE in source and HASATTR in source, (
        f"{rel} prints non-ASCII from __main__ without the BUG-012 "
        "hasattr-guarded sys.stdout.reconfigure(errors=...)"
    )


@pytest.fixture(scope="module")
def repo_copy(tmp_path_factory):
    """A throwaway copy of the checkout: scripts run with no arguments may
    write state relative to their own location, never into the worktree."""
    dest = tmp_path_factory.mktemp("cp1252") / "repo"
    shutil.copytree(
        REPO_ROOT, str(dest),
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache",
                                      "node_modules", ".venv", "venv"),
    )
    return dest


@pytest.mark.parametrize("rel", ENTRY_POINTS)
def test_entry_point_survives_cp1252_stdout(rel, repo_copy, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    if rel in PACKAGE_MODULES:
        cmd = [sys.executable, "-m", PACKAGE_MODULES[rel], str(tmp_path)]
    else:
        cmd = [sys.executable, os.path.join(str(repo_copy), rel)]
    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "USERPROFILE": str(home),  # BUG-010
        "PYTHONPATH": str(repo_copy),
        "PYTHONIOENCODING": "cp1252",
        "PYTHONUTF8": "0",
        "SOMA_ROOT": str(repo_copy),
    })
    # conftest.run decodes strict UTF-8; the output here is cp1252 bytes.
    proc = subprocess.run(
        cmd, cwd=str(repo_copy), env=env, stdin=subprocess.DEVNULL,
        capture_output=True, encoding="utf-8", errors="replace", timeout=60,
    )
    assert "UnicodeEncodeError" not in proc.stderr, (
        f"{rel} crashed on a cp1252 stdout:\n{proc.stderr[-800:]}"
    )
