"""BUG-038: standalone enzyme scripts and the verification runners print emoji
and other non-ASCII symbols. On a cp1252 stdout (Windows with redirected or
captured output, including hook runs) they raised UnicodeEncodeError and
exited 1."""
import ast
import glob
import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Scripts that reach a non-ASCII print with no arguments in an empty workspace.
# verify_readme_claims also does, but a full run takes ~45 s, so only the
# structural test covers it.
NO_ARG_SCRIPTS = [
    "cell_adversarial",
    "cell_coverage",
    "cell_deps",
    "cell_fitness",
    "immune_entropy",
    "immune_grade",
    "immune_replay",
    "resilience_engine",
    "soma_coherence",
    "soma_interoception",
    "soma_sleep",
]


def _run(script, workspace, encoding):
    home = workspace / "home"
    home.mkdir(exist_ok=True)
    pythonpath = REPO_ROOT + (os.pathsep + os.environ["PYTHONPATH"] if "PYTHONPATH" in os.environ else "")
    env = dict(os.environ, PYTHONIOENCODING=encoding,
               HOME=str(home), USERPROFILE=str(home), PYTHONPATH=pythonpath)
    return subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "enzymes", f"{script}.py")],
        capture_output=True, encoding=encoding, errors="replace",
        timeout=60, cwd=str(workspace), env=env,
    )


def _assert_same_as_utf8(script, tmp_path):
    utf8_ws = tmp_path / "utf8"
    cp1252_ws = tmp_path / "cp1252"
    for ws in (utf8_ws, cp1252_ws):
        ws.mkdir()
        _seed(script, ws)
    expected = _run(script, utf8_ws, "utf-8")
    # Otherwise the run never reached the output this test is about.
    assert any(ord(c) > 127 for c in expected.stdout), expected.stdout + expected.stderr
    assert "Traceback" not in expected.stderr, expected.stderr
    proc = _run(script, cp1252_ws, "cp1252")
    assert "UnicodeEncodeError" not in proc.stderr, proc.stderr
    assert proc.returncode == expected.returncode, proc.stderr
    assert len(proc.stdout.splitlines()) == len(expected.stdout.splitlines())


def _seed(script, workspace):
    if script == "diagnose_hot_zones":
        registry = workspace / "docs" / "project" / "BUG_REGISTRY.json"
        registry.parent.mkdir(parents=True)
        registry.write_text(json.dumps({"bugs": []}), encoding="utf-8")


@pytest.mark.parametrize("script", NO_ARG_SCRIPTS)
def test_no_arg_run_survives_cp1252_stdout(script, tmp_path):
    _assert_same_as_utf8(script, tmp_path)


def test_hot_zone_report_survives_cp1252_stdout(tmp_path):
    """The config line prints '≥', which cp1252 has no mapping for."""
    _assert_same_as_utf8("diagnose_hot_zones", tmp_path)


def _docstring_nodes(tree):
    nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                nodes.add(body[0].value)
    return nodes


def _main_block(tree):
    for node in tree.body:
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__"):
            return node
    return None


def _is_stdout_guard(stmt):
    """`if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(errors='replace')`"""
    if not (isinstance(stmt, ast.If)
            and ast.unparse(stmt.test) == "hasattr(sys.stdout, 'reconfigure')"):
        return False
    call = stmt.body[0].value if isinstance(stmt.body[0], ast.Expr) else None
    return (isinstance(call, ast.Call)
            and ast.unparse(call) == "sys.stdout.reconfigure(errors='replace')")


def _guarded_before_output(tree, main_block):
    if _is_stdout_guard(main_block.body[0]):
        return True
    # The BUG-012 fixes guard inside main() instead.
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return _is_stdout_guard(node.body[0])
    return False


def _entry_points_with_non_ascii_strings():
    """Scripts with a __main__ block and a non-ASCII string literal anywhere
    but a docstring. Literals reach stdout through variables, dict lookups and
    sys.stdout.write as well as print(), so any such literal counts."""
    paths = glob.glob(os.path.join(REPO_ROOT, "enzymes", "**", "*.py"), recursive=True)
    paths += glob.glob(os.path.join(REPO_ROOT, "immune_system", "**", "*.py"), recursive=True)
    found = {}
    for path in sorted(paths):
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        main_block = _main_block(tree)
        if main_block is None:
            continue
        docstrings = _docstring_nodes(tree)
        if any(isinstance(node, ast.Constant) and isinstance(node.value, str)
               and node not in docstrings and any(ord(c) > 127 for c in node.value)
               for node in ast.walk(tree)):
            rel = os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
            found[rel] = _guarded_before_output(tree, main_block)
    return found


def test_every_entry_point_with_non_ascii_output_guards_stdout():
    """Most of these scripts need inputs (cells, an LLM, a repo) before they
    print, so the behavioral tests above can't reach them all."""
    entry_points = _entry_points_with_non_ascii_strings()
    # The scan must see the cases the behavioral tests and BUG-012 cover,
    # including an escaped literal ('\\u221e' in cell_fitness).
    for known in ("enzymes/cell_crossover.py", "enzymes/cell_fitness.py",
                  "enzymes/verify_bug_registry.py",
                  "immune_system/verification/runner.py"):
        assert known in entry_points
    unguarded = sorted(path for path, guarded in entry_points.items() if not guarded)
    assert unguarded == []
