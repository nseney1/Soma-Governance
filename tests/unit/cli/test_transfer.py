"""Unit tests for soma_cli/transfer.py."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from soma_cli.transfer import resolve_workspace, transfer_cell, run_transfer


def test_resolve_workspace_env_override(tmp_path):
    env_dir = tmp_path / "env_root"
    (env_dir / ".soma" / "cells").mkdir(parents=True)
    with patch.dict(os.environ, {"SOMA_ROOT": str(env_dir)}):
        assert resolve_workspace() == env_dir.resolve()


def test_resolve_workspace_from_cwd(tmp_path, monkeypatch):
    proj_dir = tmp_path / "project"
    (proj_dir / ".soma" / "cells").mkdir(parents=True)
    sub = proj_dir / "sub" / "deep"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    with patch.dict(os.environ, {}, clear=True):
        assert resolve_workspace() == proj_dir.resolve()


def test_transfer_cell_no_source_project(tmp_path, capsys):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    target_dir = tmp_path / "target"
    (target_dir / ".soma").mkdir(parents=True)

    rc = transfer_cell("nonexistent", str(target_dir), source_workspace=empty_dir)
    assert rc == 1
    assert "No Soma project found" in capsys.readouterr().err


def test_transfer_cell_no_target_soma(tmp_path, capsys):
    src = tmp_path / "src"
    (src / ".soma" / "cells").mkdir(parents=True)
    target = tmp_path / "target"
    target.mkdir()

    rc = transfer_cell("guard", str(target), source_workspace=src)
    assert rc == 1
    assert "Target directory does not have a .soma/" in capsys.readouterr().err


def test_transfer_cell_cell_not_found(tmp_path, capsys):
    src = tmp_path / "src"
    (src / ".soma" / "cells").mkdir(parents=True)
    target = tmp_path / "target"
    (target / ".soma").mkdir(parents=True)

    rc = transfer_cell("missing-cell", str(target), source_workspace=src)
    assert rc == 1
    assert "Cell matching 'missing-cell' not found" in capsys.readouterr().err


def test_transfer_cell_malformed_frontmatter(tmp_path, capsys):
    src = tmp_path / "src"
    cells = src / ".soma" / "cells" / "walls"
    cells.mkdir(parents=True)
    (cells / "bad-cell.md").write_text("No frontmatter here", encoding="utf-8")

    target = tmp_path / "target"
    (target / ".soma").mkdir(parents=True)

    rc = transfer_cell("bad-cell", str(target), source_workspace=src)
    assert rc == 1
    assert "Cell does not have YAML frontmatter" in capsys.readouterr().err


def test_transfer_cell_success_resets_fitness(tmp_path):
    src = tmp_path / "src"
    cells = src / ".soma" / "cells" / "chloroplasts"
    cells.mkdir(parents=True)
    (cells / "opt-guard.md").write_text(
        "---\n"
        "id: opt-guard\n"
        "type: chloroplast\n"
        "fitness:\n"
        "  score: 0.88\n"
        "  triggers: 50\n"
        "  true_positives: 45\n"
        "  false_positives: 5\n"
        "lineage:\n"
        "  generation: 1\n"
        "---\n"
        "# Optimization Guard\n",
        encoding="utf-8",
    )

    target = tmp_path / "target"
    (target / ".soma").mkdir(parents=True)

    rc = transfer_cell("opt-guard", str(target), source_workspace=src)
    assert rc == 0

    dest = target / ".soma" / "cells" / "chloroplasts" / "opt-guard.md"
    assert dest.exists()
    content = dest.read_text(encoding="utf-8")
    assert "score: null" in content or "score: None" in content
    assert "triggers: 0" in content
    assert "generation: 2" in content
    assert "created_by: transfer" in content

    # Check transfers log
    log = src / ".soma" / "metrics" / "transfers.jsonl"
    assert log.exists()
    assert "opt-guard.md" in log.read_text(encoding="utf-8")


def test_run_transfer_argparse_validation(capsys):
    args_empty = argparse.Namespace(cell_id="", target_dir="")
    rc = run_transfer(args_empty)
    assert rc == 1
    assert "Missing cell_id or --to directory" in capsys.readouterr().err


def test_transfer_cell_plasmodesmata_correct_directory(tmp_path):
    src = tmp_path / "src"
    cells = src / ".soma" / "cells" / "plasmodesmata"
    cells.mkdir(parents=True)
    (cells / "bridge-contract.md").write_text(
        "---\n"
        "id: bridge-contract\n"
        "type: plasmodesmata\n"
        "target_paths:\n"
        "  - \"src/bridge/*.py\"\n"
        "---\n"
        "# Plasmodesmata Bridge\n",
        encoding="utf-8",
    )

    target = tmp_path / "target"
    (target / ".soma").mkdir(parents=True)

    rc = transfer_cell("bridge-contract", str(target), source_workspace=src)
    assert rc == 0

    dest = target / ".soma" / "cells" / "plasmodesmata" / "bridge-contract.md"
    assert dest.exists(), "Plasmodesmata cell must be placed in plasmodesmata/, not plasmodesmatas/"
    wrong_dest = target / ".soma" / "cells" / "plasmodesmatas"
    assert not wrong_dest.exists(), "plasmodesmatas directory should not be created"


def test_transfer_cell_without_yaml_module(tmp_path, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "yaml", None)

    src = tmp_path / "src"
    cells = src / ".soma" / "cells" / "walls"
    cells.mkdir(parents=True)
    (cells / "stdlib-wall.md").write_text(
        "---\n"
        "id: stdlib-wall\n"
        "type: wall\n"
        "description: pure stdlib test\n"
        "---\n"
        "# Wall Body\n",
        encoding="utf-8",
    )

    target = tmp_path / "target"
    (target / ".soma").mkdir(parents=True)

    rc = transfer_cell("stdlib-wall", str(target), source_workspace=src)
    assert rc == 0
    dest = target / ".soma" / "cells" / "walls" / "stdlib-wall.md"
    assert dest.exists()

