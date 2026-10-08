"""Shared test helpers for cell lifecycle tests.

Provides factory functions for creating cell files and JSONL evidence
used by test_cli_promote.py, test_cli_demote.py, test_cli_oracle.py,
test_lifecycle.py, and test_oracle_checkpoint.py.
"""
import json
import os
from datetime import datetime, timedelta

import pytest
from soma_core.somayaml import dump_frontmatter

__all__ = [
    "make_cell",
    "write_cell_with_fitness",
    "make_cell_dict",
    "soma_workspace",
    "write_evidence",
]


def make_cell(cells_dir, name, cell_type="vacuole", created_days_ago=10,
              expiry_days=365, expiry_sessions=100):
    """Create a minimal cell markdown file with YAML frontmatter.

    Args:
        cells_dir: Directory to write the cell file into.
        name: Cell ID and filename stem.
        cell_type: One of vacuole, wall, genome.
        created_days_ago: How old the cell should appear.
        expiry_days: Days until cell expires.
        expiry_sessions: Sessions until cell expires.

    Returns:
        Path to the created cell file.
    """
    created = (datetime.now() - timedelta(days=created_days_ago)).strftime("%Y-%m-%d")
    fm = {
        'id': name,
        'type': cell_type,
        'enforcement': 'advisory',
        'hypothesis': f'Test cell {name}',
        'prediction': 'test',
        'falsification': 'test',
        'target_paths': ['*.py'],
        'expiry_sessions': expiry_sessions,
        'expiry_days': expiry_days,
        'created': created,
    }
    cell_file = os.path.join(str(cells_dir), f"{name}.md")
    with open(cell_file, 'w') as f:
        f.write("---\n")
        f.write(dump_frontmatter(fm))
        f.write("---\n")
        f.write(f"# {name}\nTest cell.\n")
    return cell_file


def write_cell_with_fitness(cells_dir, name, enforcement="advisory",
                            triggers=0, tp=0, fp=0, cell_type="vacuole",
                            hypothesis=None):
    """Write a cell markdown file with fitness data in YAML frontmatter.

    Unlike ``make_cell``, this helper embeds fitness counters (triggers, tp,
    fp, score) and supports arbitrary enforcement tiers, which is needed by
    integration tests that exercise decay and tier-check logic.

    Args:
        cells_dir: Directory (pathlib.Path or str) to write the cell into.
        name: Cell filename stem.
        enforcement: Enforcement tier (advisory, mechanical, gate).
        triggers: Number of triggers.
        tp: True positives.
        fp: False positives.
        cell_type: Cell type (vacuole, wall, chloroplast, etc).
        hypothesis: Optional hypothesis text; defaults to cell name.

    Returns:
        Path to the created cell file.
    """
    score = tp / max(triggers, 1)
    hyp = hypothesis or f"Test cell {name}"
    content = (
        f"---\n"
        f"type: {cell_type}\n"
        f"hypothesis: {hyp}\n"
        f"enforcement: {enforcement}\n"
        f"target_paths:\n  - \"*.py\"\n"
        f"fitness:\n"
        f"  triggers: {triggers}\n"
        f"  true_positives: {tp}\n"
        f"  false_positives: {fp}\n"
        f"  score: {score:.4f}\n"
        f"---\n# {name}\nContent\n"
    )
    cell_path = os.path.join(str(cells_dir), f"{name}.md")
    with open(cell_path, 'w') as f:
        f.write(content)
    return cell_path


def make_cell_dict(tp=0, triggers=0, fp=0, impact_weight=1.0, score=None):
    """Build a minimal in-memory cell dict matching the frontmatter structure.

    Used for testing ``jit_engine.get_fitness_score()`` and similar functions
    that operate on cell metadata dicts rather than on-disk files.
    """
    fitness = {'true_positives': tp, 'triggers': triggers, 'false_positives': fp}
    if score is not None:
        fitness['score'] = score
    return {'fitness': fitness, 'impact_weight': impact_weight}


@pytest.fixture
def soma_workspace(tmp_path):
    """Create a minimal Soma workspace with cells and metrics directories.

    Returns a ``pathlib.Path`` pointing at the workspace root.  Tests that
    need specific cell files should create them via ``make_cell``,
    ``write_cell_with_fitness``, or direct writes.
    """
    workspace = tmp_path / "project"
    cells_dir = workspace / ".soma" / "cells"
    cells_dir.mkdir(parents=True)
    metrics_dir = workspace / ".soma" / "metrics"
    metrics_dir.mkdir(parents=True)
    (workspace / "soma.conf").write_text("TOTAL_SESSIONS=100\n")
    return workspace


def write_evidence(evidence_dir, cell_id, triggers=0, tp=0, fp=0):
    """Write canonical trigger and outcome signals for one cell."""
    evidence_dir = str(evidence_dir)
    signals_file = os.path.join(evidence_dir, "signals.jsonl")

    with open(signals_file, "a", encoding="utf-8") as f:
        for _ in range(triggers):
            f.write(json.dumps({
                "cell": cell_id,
                "signal": "trigger",
                "source": "manual",
                "timestamp": datetime.now().isoformat(),
                "metadata": {"matched_files": ["test.py"]},
            }) + "\n")
        for _ in range(tp):
            f.write(json.dumps({
                "cell": cell_id, "signal": "tp", "source": "manual",
            }) + "\n")
        for _ in range(fp):
            f.write(json.dumps({
                "cell": cell_id, "signal": "fp", "source": "manual",
            }) + "\n")
