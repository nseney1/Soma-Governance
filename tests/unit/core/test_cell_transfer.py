import os
import sys
import pytest
from conftest import REPO_ROOT, read, run

CELL = """---
id: vac-transfer-me
type: vacuole
fitness:
  triggers: 7
  true_positives: 3
---
# Vacuole: transfer me
"""

@pytest.fixture
def projects(tmp_path):
    src = tmp_path / "src"
    (src / ".soma" / "cells" / "vacuoles").mkdir(parents=True)
    (src / ".soma" / "cells" / "vacuoles" / "vac-transfer-me.md").write_text(CELL, encoding="utf-8")
    (src / "sub" / "dir").mkdir(parents=True)
    dst = tmp_path / "dst"
    (dst / ".soma").mkdir(parents=True)
    return src, dst

def _env(tmp_path, **extra):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"HOME": str(home), "USERPROFILE": str(home), "SOMA_PYTHON": sys.executable,
           "SOMA_PYTHON_RESOLVED": "", "PYTHONPATH": REPO_ROOT}
    env.update(extra)
    return env

def _assert_transferred(src, dst, cwd):
    out = dst / ".soma" / "cells" / "vacuoles" / "vac-transfer-me.md"
    assert out.exists(), "cell was not copied"
    assert "true_positives: 0" in read(str(out))
    log = src / ".soma" / "metrics" / "transfers.jsonl"
    assert log.exists(), "transfer was not logged in the source project"
    if cwd != src:
        assert not (cwd / ".soma").exists(), "metrics written relative to CWD"

def test_cell_transfer_resolves_repo_from_subdirectory(tmp_path, projects):
    src, dst = projects
    cwd = src / "sub" / "dir"
    proc = run([sys.executable, "-m", "soma_cli.cli", "transfer", "transfer-me",
                "--to", str(dst)], cwd=str(cwd), env=_env(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    _assert_transferred(src, dst, cwd)

def test_cell_transfer_honours_soma_root(tmp_path, projects):
    src, dst = projects
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    proc = run([sys.executable, "-m", "soma_cli.cli", "transfer", "transfer-me",
                "--to", str(dst)], cwd=str(elsewhere),
               env=_env(tmp_path, SOMA_ROOT=str(src)))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    _assert_transferred(src, dst, elsewhere)

def test_cell_transfer_without_a_project_fails_clearly(tmp_path):
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    dst = tmp_path / "dst"
    (dst / ".soma").mkdir(parents=True)
    proc = run([sys.executable, "-m", "soma_cli.cli", "transfer", "x",
                "--to", str(dst)], cwd=str(nowhere), env=_env(tmp_path, SOMA_ROOT=""))
    assert proc.returncode != 0
    assert ".soma" in proc.stderr and "SOMA_ROOT" in proc.stderr, proc.stderr
