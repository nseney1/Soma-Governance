from pathlib import Path
"""TDD Gate 1 tests for `soma demote` CLI command.

Wires lifecycle engine's evaluate_demotions into a CLI subcommand.
"""
import argparse
import json
import os
import sys

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)

from tests.helpers_cell import make_cell, write_evidence


class TestDemoteCLI:
    """Tests for soma demote subcommand."""

    def test_run_demote_importable(self):
        from soma_cli.demote import run_demote
        assert callable(run_demote)

    def test_demote_registered_in_cli(self):
        from soma_cli.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["demote", "--dry-run"])
        assert args.command == "demote"
        assert args.dry_run is True

    def test_demote_dry_run_shows_candidates(self, tmp_path, capsys):
        """--dry-run lists demotion candidates."""
        from soma_cli.demote import run_demote

        cells_dir = tmp_path / ".soma" / "cells" / "walls"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".soma" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "bad-wall", cell_type="wall", created_days_ago=60)
        write_evidence(str(evidence_dir), "bad-wall", triggers=20, tp=6, fp=14)

        args = argparse.Namespace(dry_run=True, json=False, _project_root=tmp_path)
        exit_code = run_demote(args)

        assert exit_code == 0
        output = capsys.readouterr().out
        assert "bad-wall" in output

    def test_demote_no_candidates_exits_zero(self, tmp_path):
        """No demotion candidates → exit 0."""
        from soma_cli.demote import run_demote

        (tmp_path / ".soma" / "cells").mkdir(parents=True)
        (tmp_path / ".soma" / "evidence").mkdir(parents=True)

        args = argparse.Namespace(dry_run=True, json=False, _project_root=tmp_path)
        exit_code = run_demote(args)
        assert exit_code == 0

    def test_demote_json_output(self, tmp_path, capsys):
        """--json returns structured output."""
        from soma_cli.demote import run_demote

        cells_dir = tmp_path / ".soma" / "cells" / "walls"
        cells_dir.mkdir(parents=True)
        evidence_dir = tmp_path / ".soma" / "evidence"
        evidence_dir.mkdir(parents=True)

        make_cell(str(cells_dir), "noisy-wall", cell_type="wall", created_days_ago=60)
        write_evidence(str(evidence_dir), "noisy-wall", triggers=20, tp=5, fp=15)

        args = argparse.Namespace(dry_run=True, json=True, _project_root=tmp_path)
        run_demote(args)

        output = capsys.readouterr().out
        data = json.loads(output)
        assert "candidates" in data
        assert len(data["candidates"]) == 1

    # ── --force / --cell tests ──────────────────────────────────────────

    def test_force_demote_wall_to_vacuole(self, tmp_path, capsys):
        """--force --cell should move wall to vacuoles/ and remove enforcement."""
        from soma_cli.demote import run_demote

        cells_dir = tmp_path / ".soma" / "cells"
        walls_dir = cells_dir / "walls"
        vacuoles_dir = cells_dir / "vacuoles"
        walls_dir.mkdir(parents=True)
        vacuoles_dir.mkdir(parents=True)

        make_cell(str(walls_dir), "demo-wall", cell_type="wall", created_days_ago=30)
        # Inject enforcement: gate into the cell (make_cell writes enforcement: advisory)
        wall_file = walls_dir / "demo-wall.md"
        content = wall_file.read_text()
        content = content.replace("enforcement: advisory", "enforcement: gate")
        wall_file.write_text(content)

        args = argparse.Namespace(
            force=True, cell="demo-wall", dry_run=False, json=False,
            _project_root=tmp_path,
        )
        exit_code = run_demote(args)

        assert exit_code == 0
        assert not wall_file.exists(), "Old wall file should be removed"
        target = vacuoles_dir / "demo-wall.md"
        assert target.exists(), "Cell should be moved to vacuoles/"
        new_content = target.read_text()
        assert "type: vacuole" in new_content
        assert "enforcement: gate" not in new_content

    def test_force_demote_genome_to_wall(self, tmp_path, capsys):
        """--force --cell should move genome cell to walls/ and add enforcement: gate."""
        from soma_cli.demote import run_demote

        genome_dir = tmp_path / "genome"
        genome_dir.mkdir(parents=True)
        cells_dir = tmp_path / ".soma" / "cells"
        walls_dir = cells_dir / "walls"
        walls_dir.mkdir(parents=True)
        (tmp_path / "soma_core").mkdir(parents=True)
        (tmp_path / "soma_cli").mkdir(parents=True)
        (tmp_path / "pyproject.toml").write_text('name = "soma-governance"\n', encoding="utf-8")

        make_cell(str(genome_dir), "core-rule", cell_type="genome", created_days_ago=90)

        args = argparse.Namespace(
            force=True, cell="core-rule", dry_run=False, json=False,
            _project_root=tmp_path,
        )
        exit_code = run_demote(args)

        assert exit_code == 0
        assert not (genome_dir / "core-rule.md").exists()
        target = walls_dir / "core-rule.md"
        assert target.exists(), "Cell should be moved to walls/"
        new_content = target.read_text()
        assert "type: wall" in new_content
        assert "enforcement: gate" in new_content

    def test_force_demote_vacuole_cannot_demote(self, tmp_path, capsys):
        """Vacuole is minimum tier — should exit 1."""
        from soma_cli.demote import run_demote

        vacuoles_dir = tmp_path / ".soma" / "cells" / "vacuoles"
        vacuoles_dir.mkdir(parents=True)

        make_cell(str(vacuoles_dir), "bottom-cell", cell_type="vacuole", created_days_ago=10)

        args = argparse.Namespace(
            force=True, cell="bottom-cell", dry_run=False, json=False,
            _project_root=tmp_path,
        )
        exit_code = run_demote(args)

        assert exit_code == 1
        output = capsys.readouterr().out
        assert "minimum tier" in output

    def test_force_demote_nonexistent_cell(self, tmp_path, capsys):
        """Bad cell ID should exit 1."""
        from soma_cli.demote import run_demote

        (tmp_path / ".soma" / "cells").mkdir(parents=True)
        (tmp_path / "genome").mkdir(parents=True)

        args = argparse.Namespace(
            force=True, cell="no-such-cell", dry_run=False, json=False,
            _project_root=tmp_path,
        )
        exit_code = run_demote(args)

        assert exit_code == 1
        output = capsys.readouterr().out
        assert "not found" in output

    def test_force_demote_dry_run(self, tmp_path, capsys):
        """--dry-run should not move files."""
        from soma_cli.demote import run_demote

        walls_dir = tmp_path / ".soma" / "cells" / "walls"
        walls_dir.mkdir(parents=True)

        make_cell(str(walls_dir), "dry-wall", cell_type="wall", created_days_ago=30)

        args = argparse.Namespace(
            force=True, cell="dry-wall", dry_run=True, json=False,
            _project_root=tmp_path,
        )
        exit_code = run_demote(args)

        assert exit_code == 0
        # File should still be in its original location
        assert (walls_dir / "dry-wall.md").exists()
        # No file should appear in vacuoles/
        vacuoles_dir = tmp_path / ".soma" / "cells" / "vacuoles"
        assert not vacuoles_dir.exists() or not (vacuoles_dir / "dry-wall.md").exists()
        output = capsys.readouterr().out
        assert "Would demote" in output

    def test_force_demote_requires_cell_flag(self, tmp_path, capsys):
        """--force without --cell should exit 1."""
        from soma_cli.demote import run_demote

        (tmp_path / ".soma" / "cells").mkdir(parents=True)

        args = argparse.Namespace(
            force=True, cell=None, dry_run=False, json=False,
            _project_root=tmp_path,
        )
        exit_code = run_demote(args)

        assert exit_code == 1
        output = capsys.readouterr().out
        assert "--force requires --cell" in output

    def test_force_demote_core_rule_rejected(self, tmp_path, capsys):
        """--force --cell on a protected core rule must fail."""
        from soma_cli.demote import run_demote

        genome_dir = tmp_path / "genome"
        genome_dir.mkdir(parents=True)
        (genome_dir / "providence.md").write_text("# Providence\n")

        for rule in ("providence", "rule-providence", "cost-optimization.md"):
            args = argparse.Namespace(
                force=True, cell=rule, dry_run=False, json=False,
                _project_root=tmp_path,
            )
            exit_code = run_demote(args)
            assert exit_code == 1
            output = capsys.readouterr().out
            assert "Cannot demote core rule" in output

    def test_force_demote_with_md_extension(self, tmp_path, capsys):
        """--cell ending in .md should be found and demoted cleanly."""
        from soma_cli.demote import run_demote

        cells_dir = tmp_path / ".soma" / "cells"
        walls_dir = cells_dir / "walls"
        vacuoles_dir = cells_dir / "vacuoles"
        walls_dir.mkdir(parents=True)
        vacuoles_dir.mkdir(parents=True)

        make_cell(str(walls_dir), "ext-wall", cell_type="wall", created_days_ago=30)
        args = argparse.Namespace(
            force=True, cell="ext-wall.md", dry_run=False, json=False,
            _project_root=tmp_path,
        )
        exit_code = run_demote(args)
        assert exit_code == 0
        assert (vacuoles_dir / "ext-wall.md").exists()

