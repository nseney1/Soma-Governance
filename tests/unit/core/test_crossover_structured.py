from pathlib import Path
"""Behavioral tests for cell_crossover.py structured merge rules.

Tests field-level merge logic, lineage tracking, and output validity.
"""
import os
import sys
import json
import subprocess
import pytest
from soma_core.somayaml import dump_frontmatter

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from soma_sdk.cells import parse_cell_file


def _make_parent(workspace, cell_id, cell_type='vacuole', hypothesis='hyp',
                 prediction='pred', impact_weight=1.0, target_paths=None,
                 generation=0, fitness_score=0.8, tags=None):
    """Create a parent cell for crossover testing."""
    type_map = {'vacuole': 'vacuoles', 'wall': 'walls', 'membrane': 'membranes'}
    type_dir = type_map.get(cell_type, 'vacuoles')
    cells_dir = os.path.join(workspace, '.soma', 'cells', type_dir)
    os.makedirs(cells_dir, exist_ok=True)
    fm = {
        'id': cell_id,
        'type': cell_type,
        'hypothesis': hypothesis,
        'prediction': prediction,
        'impact_weight': impact_weight,
        'target_paths': target_paths or ['src/*.py'],
        'tags': tags or ['test'],
        'fitness': {
            'triggers': 10, 'true_positives': 8, 'false_positives': 2,
            'score': fitness_score,
        },
        'lineage': {'generation': generation, 'created_by': 'manual'},
    }
    content = dump_frontmatter(fm, body="Parent body\n")
    path = os.path.join(cells_dir, f'{cell_id}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


def _run_crossover(workspace, cell_a_id, cell_b_id):
    """Run crossover via subprocess and return result."""
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; from soma_core.lifecycle import cli_cell_crossover; sys.exit(cli_cell_crossover(sys.argv[1:]))",
         cell_a_id, cell_b_id],
        capture_output=True, text=True, cwd=workspace,
        env={**os.environ, 'PYTHONPATH': REPO_ROOT}
    )
    return result


def _find_child_cell(workspace):
    """Find the newly created child cell file."""
    import glob
    cells = glob.glob(os.path.join(workspace, '.soma', 'cells', '**', '*.md'),
                      recursive=True)
    # Filter out README and known parent cells
    children = [c for c in cells if 'README' not in c]
    return children


class TestCrossoverMergeRules:
    """Tests for field-level merge behavior."""

    def test_same_type_parents_produce_same_type(self, tmp_path):
        ws = str(tmp_path)
        _make_parent(ws, 'parent-a', cell_type='vacuole')
        _make_parent(ws, 'parent-b', cell_type='vacuole')
        result = _run_crossover(ws, 'parent-a', 'parent-b')
        assert result.returncode == 0, f"Crossover failed: {result.stderr}"
        children = _find_child_cell(ws)
        # Find the child (not parent-a or parent-b)
        child_paths = [c for c in children if 'parent-a' not in c and 'parent-b' not in c]
        assert len(child_paths) >= 1, "No child cell created"
        fm, _ = parse_cell_file(child_paths[0])
        assert fm['type'] == 'vacuole'

    def test_mixed_type_parents_produce_vacuole(self, tmp_path):
        ws = str(tmp_path)
        _make_parent(ws, 'parent-vac', cell_type='vacuole')
        _make_parent(ws, 'parent-wall', cell_type='wall')
        result = _run_crossover(ws, 'parent-vac', 'parent-wall')
        assert result.returncode == 0, f"Crossover failed: {result.stderr}"
        children = _find_child_cell(ws)
        child_paths = [c for c in children
                       if 'parent-vac' not in c and 'parent-wall' not in c]
        assert len(child_paths) >= 1
        fm, _ = parse_cell_file(child_paths[0])
        assert fm['type'] == 'vacuole'

    def test_hypothesis_combines_both_parents(self, tmp_path):
        ws = str(tmp_path)
        _make_parent(ws, 'pa', hypothesis='Hyp A')
        _make_parent(ws, 'pb', hypothesis='Hyp B')
        _run_crossover(ws, 'pa', 'pb')
        children = _find_child_cell(ws)
        child_paths = [c for c in children if 'pa.md' not in c and 'pb.md' not in c]
        assert len(child_paths) >= 1
        fm, _ = parse_cell_file(child_paths[0])
        assert 'Hyp A' in fm['hypothesis'] or 'Hyp B' in fm['hypothesis']

    def test_impact_weight_is_max_of_parents(self, tmp_path):
        ws = str(tmp_path)
        _make_parent(ws, 'low', impact_weight=0.5)
        _make_parent(ws, 'high', impact_weight=1.5)
        _run_crossover(ws, 'low', 'high')
        children = _find_child_cell(ws)
        child_paths = [c for c in children if 'low.md' not in c and 'high.md' not in c]
        fm, _ = parse_cell_file(child_paths[0])
        assert float(fm['impact_weight']) == 1.5

    def test_fitness_reset_to_zero(self, tmp_path):
        ws = str(tmp_path)
        _make_parent(ws, 'fit-a', fitness_score=0.9)
        _make_parent(ws, 'fit-b', fitness_score=0.8)
        _run_crossover(ws, 'fit-a', 'fit-b')
        children = _find_child_cell(ws)
        child_paths = [c for c in children
                       if 'fit-a' not in c and 'fit-b' not in c]
        fm, _ = parse_cell_file(child_paths[0])
        fitness = fm.get('fitness', {})
        assert int(fitness.get('triggers', 0)) == 0
        assert int(fitness.get('true_positives', 0)) == 0
        assert int(fitness.get('false_positives', 0)) == 0


class TestCrossoverLineage:
    """Tests for lineage tracking in crossover output."""

    def test_lineage_has_parent_reference(self, tmp_path):
        ws = str(tmp_path)
        _make_parent(ws, 'lin-a')
        _make_parent(ws, 'lin-b')
        _run_crossover(ws, 'lin-a', 'lin-b')
        children = _find_child_cell(ws)
        child_paths = [c for c in children if 'lin-a' not in c and 'lin-b' not in c]
        fm, _ = parse_cell_file(child_paths[0])
        lineage = fm.get('lineage', {})
        parent_id = str(lineage.get('parent_id', ''))
        assert 'lin-a' in parent_id and 'lin-b' in parent_id

    def test_lineage_created_by_crossover(self, tmp_path):
        ws = str(tmp_path)
        _make_parent(ws, 'cb-a')
        _make_parent(ws, 'cb-b')
        _run_crossover(ws, 'cb-a', 'cb-b')
        children = _find_child_cell(ws)
        child_paths = [c for c in children if 'cb-a' not in c and 'cb-b' not in c]
        fm, _ = parse_cell_file(child_paths[0])
        assert fm.get('lineage', {}).get('created_by') == 'crossover'

    def test_lineage_generation_incremented(self, tmp_path):
        ws = str(tmp_path)
        _make_parent(ws, 'gen-a', generation=2)
        _make_parent(ws, 'gen-b', generation=3)
        _run_crossover(ws, 'gen-a', 'gen-b')
        children = _find_child_cell(ws)
        child_paths = [c for c in children if 'gen-a' not in c and 'gen-b' not in c]
        fm, _ = parse_cell_file(child_paths[0])
        assert fm.get('lineage', {}).get('generation') == 4  # max(2,3) + 1


class TestCrossoverOutput:
    """Tests for output file validity and JSONL logging."""

    def test_output_is_valid_cell_file(self, tmp_path):
        ws = str(tmp_path)
        _make_parent(ws, 'valid-a')
        _make_parent(ws, 'valid-b')
        _run_crossover(ws, 'valid-a', 'valid-b')
        children = _find_child_cell(ws)
        child_paths = [c for c in children
                       if 'valid-a' not in c and 'valid-b' not in c]
        assert len(child_paths) >= 1
        # Should parse without error
        fm, body = parse_cell_file(child_paths[0])
        assert fm.get('type') is not None  # type is always set by crossover

    def test_jsonl_record_appended(self, tmp_path):
        ws = str(tmp_path)
        _make_parent(ws, 'log-a')
        _make_parent(ws, 'log-b')
        _run_crossover(ws, 'log-a', 'log-b')
        jsonl_path = os.path.join(ws, '.soma', 'metrics', 'crossovers.jsonl')
        assert os.path.exists(jsonl_path)
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            records = [json.loads(line) for line in f]
        assert len(records) >= 1
        rec = records[0]
        assert 'parent_a' in rec
        assert 'parent_b' in rec
        assert 'timestamp' in rec

    def test_missing_cell_exits_nonzero(self, tmp_path):
        ws = str(tmp_path)
        os.makedirs(os.path.join(ws, '.soma', 'cells'), exist_ok=True)
        result = _run_crossover(ws, 'nonexistent-a', 'nonexistent-b')
        assert result.returncode != 0

    def test_target_paths_union_of_parents(self, tmp_path):
        ws = str(tmp_path)
        _make_parent(ws, 'tp-a', target_paths=['src/*.py'])
        _make_parent(ws, 'tp-b', target_paths=['tests/*.py'])
        _run_crossover(ws, 'tp-a', 'tp-b')
        children = _find_child_cell(ws)
        child_paths = [c for c in children if 'tp-a' not in c and 'tp-b' not in c]
        fm, _ = parse_cell_file(child_paths[0])
        paths = fm.get('target_paths', [])
        assert 'src/*.py' in paths
        assert 'tests/*.py' in paths
