from pathlib import Path
"""TDD Gate 1 tests for `soma oracle` CLI command.

The oracle CLI exposes oracle_checkpoint.py's cell health classification
as a subparser of the soma CLI, completing contract-mcp-cli-parity.

Tests verify:
1. Subparser is registered and importable
2. CLI invocation with --json flag returns valid JSON
3. CLI invocation without --json returns human-readable table
4. Exit code 0 for healthy workspace, 1 for critical issues
5. --session-count parameter is passed through
"""
import argparse
import json
import os
import sys
import pytest
from datetime import datetime, timedelta

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from tests.helpers_cell import make_cell, write_evidence


class TestOracleCLI:
    """Tests for soma oracle subcommand."""

    def test_run_oracle_is_importable(self):
        """run_oracle must be importable from soma_cli.oracle."""
        from soma_cli.oracle import run_oracle
        assert callable(run_oracle)

    def test_oracle_registered_in_cli(self):
        """soma oracle must be a registered subparser."""
        from soma_cli.cli import _build_parser
        parser = _build_parser()
        # Parse 'oracle' subcommand — should not raise
        args = parser.parse_args(["oracle"])
        assert args.command == "oracle"

    def test_oracle_json_flag_parsed(self):
        """soma oracle --json must set args.json = True."""
        from soma_cli.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["oracle", "--json"])
        assert args.json is True

    def test_oracle_session_count_parsed(self):
        """soma oracle --session-count N must set args.session_count."""
        from soma_cli.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["oracle", "--session-count", "42"])
        assert args.session_count == 42

    def test_oracle_empty_workspace_returns_zero(self, tmp_path):
        """Empty workspace (no cells) exits 0."""
        from soma_cli.oracle import run_oracle

        # Create minimal .soma structure
        (tmp_path / ".soma" / "cells" / "vacuoles").mkdir(parents=True)
        (tmp_path / ".soma" / "evidence").mkdir(parents=True)

        args = argparse.Namespace(
            json=False,
            session_count=None,
            _project_root=tmp_path,
        )
        exit_code = run_oracle(args)
        assert exit_code == 0

    def test_oracle_json_output_structure(self, tmp_path):
        """--json output has required keys: total_cells, classifications, recommendations."""
        from soma_cli.oracle import run_oracle

        cells_dir = tmp_path / ".soma" / "cells" / "vacuoles"
        cells_dir.mkdir(parents=True)
        (tmp_path / ".soma" / "evidence").mkdir(parents=True)
        make_cell(str(cells_dir), "test-cell-alpha")

        args = argparse.Namespace(
            json=True,
            session_count=None,
            _project_root=tmp_path,
        )
        # Capture stdout
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = run_oracle(args)

        output = buf.getvalue()
        data = json.loads(output)
        assert "total_cells" in data
        assert "classifications" in data
        assert "recommendations" in data
        assert exit_code == 0

    def test_oracle_healthy_workspace_exits_zero(self, tmp_path):
        """Workspace with healthy cells exits 0."""
        from soma_cli.oracle import run_oracle

        cells_dir = tmp_path / ".soma" / "cells" / "vacuoles"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".soma" / "evidence"
        evidence_dir.mkdir(parents=True)
        make_cell(str(cells_dir), "good-cell")

        # Add trigger evidence so cell is not unobserved
        with open(evidence_dir / "fitness.jsonl", "w") as f:
            for i in range(5):
                f.write(json.dumps({
                    "cell_id": "good-cell",
                    "triggered_at": datetime.now().isoformat(),
                    "matched_files": ["test.py"],
                }) + "\n")
        # Add good outcomes
        with open(evidence_dir / "outcomes.jsonl", "w") as f:
            for i in range(5):
                f.write(json.dumps({
                    "cell_id": "good-cell",
                    "outcome": "tp",
                }) + "\n")

        args = argparse.Namespace(
            json=False,
            session_count=None,
            _project_root=tmp_path,
        )
        exit_code = run_oracle(args)
        assert exit_code == 0

    def test_oracle_critical_issues_exits_one(self, tmp_path):
        """Workspace with expired cells exits 1."""
        from soma_cli.oracle import run_oracle

        cells_dir = tmp_path / ".soma" / "cells" / "vacuoles"
        cells_dir.mkdir(parents=True)
        (tmp_path / ".soma" / "evidence").mkdir(parents=True)
        # Create a cell that's way past expiry
        make_cell(str(cells_dir), "expired-cell", created_days_ago=365,
                  expiry_days=30, expiry_sessions=5)

        args = argparse.Namespace(
            json=False,
            session_count=100,  # way past expiry_sessions=5
            _project_root=tmp_path,
        )
        exit_code = run_oracle(args)
        assert exit_code == 1
