"""Tests for Horizontal Gene Transfer (soma transfer export and import).

Verifies:
1. soma transfer export <cell_id> --tags "python,pytest" --output rule.soma.json
2. soma transfer import rule.soma.json
3. Schema integrity, metadata sanitization, and fitness reset upon export/import.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import pytest

from soma_cli.transfer import export_cell, import_cell, run_transfer
from soma_core.somayaml import dump_frontmatter, parse_frontmatter
from soma_core.workspace import Workspace


@pytest.fixture
def source_repo(tmp_path: Path) -> Path:
    src = tmp_path / "source_repo"
    src.mkdir()
    walls_dir = src / ".soma" / "cells" / "walls"
    walls_dir.mkdir(parents=True)

    cell_content = dump_frontmatter(
        {
            "id": "pytest-isolate",
            "type": "wall",
            "enforcement": "gate",
            "fitness": {"triggers": 40, "true_positives": 38, "false_positives": 2},
        },
        body="# Pytest Isolation Rule\nAlways isolate pytest environments.\n",
    )
    (walls_dir / "pytest-isolate.md").write_text(cell_content, encoding="utf-8")
    return src


@pytest.fixture
def target_repo(tmp_path: Path) -> Path:
    tgt = tmp_path / "target_repo"
    tgt.mkdir()
    (tgt / ".soma" / "cells" / "walls").mkdir(parents=True)
    return tgt


def test_export_cell_creates_json_packet(source_repo: Path, tmp_path: Path):
    """export_cell serializes the cell into portable JSON with tags and reset fitness."""
    output_file = tmp_path / "pytest-isolate.soma.json"
    rc = export_cell(
        cell_id="pytest-isolate",
        tags="python,pytest,testing",
        output_path=output_file,
        source_workspace=source_repo,
    )
    assert rc == 0
    assert output_file.exists()

    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["cell_id"] == "pytest-isolate"
    assert data["type"] == "wall"
    assert data["tags"] == ["python", "pytest", "testing"]
    assert "exported_at" in data
    assert "# Pytest Isolation Rule" in data["content"]
    assert data["metadata"]["fitness"]["triggers"] == 0


def test_import_cell_installs_packet(target_repo: Path, tmp_path: Path):
    """import_cell reads the portable JSON packet and creates the cell in target workspace."""
    packet_file = tmp_path / "rule.soma.json"
    packet_data = {
        "schema_version": "1.0",
        "cell_id": "imported-guard",
        "type": "wall",
        "tags": ["python"],
        "metadata": {
            "id": "imported-guard",
            "type": "wall",
            "enforcement": "gate",
        },
        "content": "# Imported Guard\nGuards something important.\n",
        "exported_at": "2026-10-07T00:00:00Z",
    }
    packet_file.write_text(json.dumps(packet_data), encoding="utf-8")

    rc = import_cell(packet_path=packet_file, target_workspace=target_repo)
    assert rc == 0

    dest_cell = target_repo / ".soma" / "cells" / "walls" / "imported-guard.md"
    assert dest_cell.exists()
    content = dest_cell.read_text(encoding="utf-8")
    meta = parse_frontmatter(content)
    assert meta["id"] == "imported-guard"
    assert meta["type"] == "wall"
    assert meta["expiry_sessions"] == 5
    assert meta["fitness"]["triggers"] == 0
    assert "# Imported Guard" in content


def test_cli_transfer_export_and_import(source_repo: Path, target_repo: Path, tmp_path: Path):
    """CLI dispatcher handles transfer export and transfer import syntax."""
    out_json = tmp_path / "exported.soma.json"

    # 1. soma transfer export <cell_id> --tags "python,pytest" --output exported.soma.json
    args_export = argparse.Namespace(
        action_or_cell_id="export",
        extra_cell_id="pytest-isolate",
        tags="python,pytest",
        output=str(out_json),
        target_dir="",
        ws=source_repo,
    )
    rc_export = run_transfer(args_export)
    assert rc_export == 0
    assert out_json.exists()

    # 2. soma transfer import exported.soma.json
    args_import = argparse.Namespace(
        action_or_cell_id="import",
        extra_cell_id=str(out_json),
        tags="",
        output="",
        target_dir=str(target_repo),
        ws=target_repo,
    )
    rc_import = run_transfer(args_import)
    assert rc_import == 0
    assert (target_repo / ".soma" / "cells" / "walls" / "pytest-isolate.md").exists()
