"""Test suite for soma_cli/harvest.py and git retro-harvesting."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
from pathlib import Path
from unittest.mock import patch

from soma_cli.harvest import run_harvest, _print_harvest_summary
from tests.unit.core.test_git_retro_harvest import (
    test_harvest_git_history_seeds_baseline,
    test_harvest_git_history_dry_run_does_not_write,
    test_harvest_git_history_idempotent,
    test_cli_harvest_git_command,
    git_workspace,
    _create_cell,
    _commit_file,
)


def test_harvest_seeds_baseline(git_workspace):
    test_harvest_git_history_seeds_baseline(git_workspace)


def test_harvest_dry_run(git_workspace):
    test_harvest_git_history_dry_run_does_not_write(git_workspace)


def test_harvest_idempotent(git_workspace):
    test_harvest_git_history_idempotent(git_workspace)


def test_harvest_cli_command(git_workspace):
    test_cli_harvest_git_command(git_workspace)


def test_cli_harvest_dry_run(git_workspace):
    _create_cell(git_workspace, "cell-dry", ["dry/*.py"])
    _commit_file(git_workspace, "dry/mod.py", "x = 1\n", "add dry mod")

    args = argparse.Namespace(
        git=True,
        limit=5,
        dry_run=True,
        json=False,
        workspace=str(git_workspace),
    )
    rc = run_harvest(args)
    assert rc == 0
    assert not (git_workspace / ".soma" / "evidence" / "signals.jsonl").exists()


def test_cli_harvest_json_output(git_workspace, capsys):
    _create_cell(git_workspace, "cell-json", ["json/*.py"])
    _commit_file(git_workspace, "json/mod.py", "y = 2\n", "add json mod")

    args = argparse.Namespace(
        git=True,
        limit=5,
        dry_run=False,
        json=True,
        workspace=str(git_workspace),
    )
    rc = run_harvest(args)
    assert rc == 0
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert "commits_inspected" in data
    assert data["commits_inspected"] >= 1


def test_cli_harvest_error_handling(git_workspace):
    args = argparse.Namespace(
        git=True,
        limit=5,
        dry_run=False,
        json=False,
        workspace=str(git_workspace),
    )
    with patch("soma_cli.harvest.harvest_git_history", return_value={"commits_inspected": 0, "error": "fatal git error"}):
        rc = run_harvest(args)
        assert rc == 1


def test_cli_harvest_exception_safety(git_workspace):
    args = argparse.Namespace(
        git=True,
        limit=5,
        dry_run=False,
        json=False,
        workspace=str(git_workspace),
    )
    with patch("soma_cli.harvest.harvest_git_history", side_effect=RuntimeError("unexpected disk error")):
        rc = run_harvest(args)
        assert rc == 1


def test_harvest_concurrent_contention(git_workspace):
    """Multiple concurrent harvest runs must serialize via evidence_lock without state corruption."""
    _create_cell(git_workspace, "cell-concur", ["concur/*.py"])
    _commit_file(git_workspace, "concur/worker.py", "z = 3\n", "add concur worker")

    args = argparse.Namespace(
        git=True,
        limit=10,
        dry_run=False,
        json=False,
        workspace=str(git_workspace),
    )

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(run_harvest, args) for _ in range(3)]
        results = [f.result() for f in futures]

    assert all(r == 0 for r in results)
    sig_file = git_workspace / ".soma" / "evidence" / "signals.jsonl"
    assert sig_file.is_file()


def test_harvest_default_git_fallback(git_workspace):
    """When git flag is False or not specified, defaults to use_git=True."""
    _create_cell(git_workspace, "cell-default", ["default/*.py"])
    _commit_file(git_workspace, "default/mod.py", "w = 4\n", "add default mod")

    args = argparse.Namespace(
        git=False,
        limit=5,
        dry_run=True,
        json=False,
        workspace=str(git_workspace),
    )
    rc = run_harvest(args)
    assert rc == 0

