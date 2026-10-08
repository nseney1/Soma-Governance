from pathlib import Path
"""TDD Gate 1 tests for `soma promote` CLI command.

Wires lifecycle engine's evaluate_promotions into a CLI subcommand.
"""
import argparse
import json
import os
import sys

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from tests.helpers_cell import make_cell, write_evidence


class TestPromoteCLI:
    """Tests for soma promote subcommand."""

    def test_run_promote_importable(self):
        from soma_cli.promote import run_promote
        assert callable(run_promote)

    def test_promote_registered_in_cli(self):
        from soma_cli.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["promote", "--dry-run"])
        assert args.command == "promote"
        assert args.dry_run is True

    def test_promote_dry_run_shows_candidates(self, tmp_path, capsys):
        """--dry-run lists candidates without performing mutations."""
        from soma_cli.promote import run_promote

        cells_dir = tmp_path / ".soma" / "cells" / "vacuoles"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".soma" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "ready-cell", created_days_ago=45)
        write_evidence(str(evidence_dir), "ready-cell", triggers=25, tp=23, fp=2)

        args = argparse.Namespace(dry_run=True, json=False, _project_root=tmp_path)
        exit_code = run_promote(args)

        assert exit_code == 0
        output = capsys.readouterr().out
        assert "ready-cell" in output

    def test_promote_no_candidates_exits_zero(self, tmp_path):
        """No promotion candidates → exit 0."""
        from soma_cli.promote import run_promote

        (tmp_path / ".soma" / "cells").mkdir(parents=True)
        (tmp_path / ".soma" / "evidence").mkdir(parents=True)

        args = argparse.Namespace(dry_run=True, json=False, _project_root=tmp_path)
        exit_code = run_promote(args)
        assert exit_code == 0

    def test_promote_json_output(self, tmp_path, capsys):
        """--json returns structured output."""
        from soma_cli.promote import run_promote

        cells_dir = tmp_path / ".soma" / "cells" / "vacuoles"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".soma" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "promo-cell", created_days_ago=45)
        write_evidence(str(evidence_dir), "promo-cell", triggers=25, tp=23, fp=2)

        args = argparse.Namespace(dry_run=True, json=True, _project_root=tmp_path)
        run_promote(args)

        output = capsys.readouterr().out
        data = json.loads(output)
        assert "candidates" in data
        assert len(data["candidates"]) == 1

    # ── --force tests ─────────────────────────────────────────────────

    def test_force_promote_requires_cell_flag(self, tmp_path):
        """--force without --cell should exit 1 with error."""
        from soma_cli.promote import run_promote

        (tmp_path / ".soma" / "cells").mkdir(parents=True)
        (tmp_path / ".soma" / "evidence").mkdir(parents=True)

        args = argparse.Namespace(
            force=True, cell=None, dry_run=False, json=False,
            _project_root=tmp_path,
        )
        exit_code = run_promote(args)
        assert exit_code == 1

    def test_force_promote_vacuole_to_wall(self, tmp_path, capsys):
        """--force --cell should move vacuole to walls/ and set enforcement: gate."""
        from soma_cli.promote import run_promote

        cells_dir = tmp_path / ".soma" / "cells" / "vacuoles"
        cells_dir.mkdir(parents=True)
        walls_dir = tmp_path / ".soma" / "cells" / "walls"
        walls_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "force-cell", cell_type="vacuole",
                  created_days_ago=10)

        args = argparse.Namespace(
            force=True, cell="force-cell", dry_run=False, json=False,
            _project_root=tmp_path,
        )
        exit_code = run_promote(args)

        assert exit_code == 0
        # Original file should be gone
        assert not (cells_dir / "force-cell.md").exists()
        # New file should exist in walls/
        promoted = walls_dir / "force-cell.md"
        assert promoted.exists()
        # Frontmatter should have enforcement: gate
        content = promoted.read_text()
        assert "enforcement: gate" in content

    def test_force_promote_nonexistent_cell(self, tmp_path):
        """--force --cell with bad ID should exit 1."""
        from soma_cli.promote import run_promote

        (tmp_path / ".soma" / "cells" / "vacuoles").mkdir(parents=True)

        args = argparse.Namespace(
            force=True, cell="does-not-exist", dry_run=False, json=False,
            _project_root=tmp_path,
        )
        exit_code = run_promote(args)
        assert exit_code == 1

    def test_force_promote_dry_run(self, tmp_path, capsys):
        """--force --cell --dry-run should not move files."""
        from soma_cli.promote import run_promote

        cells_dir = tmp_path / ".soma" / "cells" / "vacuoles"
        cells_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "dry-cell", cell_type="vacuole",
                  created_days_ago=10)

        args = argparse.Namespace(
            force=True, cell="dry-cell", dry_run=True, json=False,
            _project_root=tmp_path,
        )
        exit_code = run_promote(args)

        assert exit_code == 0
        # File should still be in vacuoles/ (not moved)
        assert (cells_dir / "dry-cell.md").exists()
        output = capsys.readouterr().out
        assert "dry-cell" in output
