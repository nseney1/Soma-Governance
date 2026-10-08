"""TDD tests for enzymes/ci_outcome_reporter — CI outcome report generator.

Tests written BEFORE implementation (Red phase).
"""
import json
import os
import sys
import textwrap
import pytest
from soma_core.somayaml import dump_frontmatter

# Imports from soma_core.enforcement
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _make_cell(cells_dir, name, target_paths, cell_type='wall'):
    """Helper: create a minimal cell .md file with frontmatter."""
    cell_path = os.path.join(cells_dir, f'{name}.md')
    frontmatter = {
        'name': name,
        'type': cell_type,
        'target_paths': target_paths,
        'fitness': {
            'triggers': 0,
            'true_positives': 0,
            'false_positives': 0,
            'score': None,
        },
    }
    content = dump_frontmatter(frontmatter, body=f"# {name}\n\nTest cell.\n")
    os.makedirs(os.path.dirname(cell_path), exist_ok=True)
    with open(cell_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return cell_path


class TestCellMatching:
    """Cells are matched to changed files via target_paths globs."""

    def test_matched_cells_have_target_paths(self, tmp_path):
        """Only cells whose target_paths match a changed file appear in report."""
        from soma_core.enforcement import generate_ci_report

        cells_dir = tmp_path / '.soma' / 'cells'
        _make_cell(str(cells_dir), 'membrane-enzymes', ['enzymes/*'])
        _make_cell(str(cells_dir), 'wall-docs', ['docs/*'])
        _make_cell(str(cells_dir), 'wall-tests', ['tests/*'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['enzymes/cell_quorum.py'],
            test_passed=True,
        )

        cell_names = [c['cell'] for c in report['matched_cells']]
        assert 'membrane-enzymes' in cell_names
        assert 'wall-docs' not in cell_names
        assert 'wall-tests' not in cell_names

    def test_no_matches_produces_empty_report(self, tmp_path):
        """Changed files matching no cells → empty matched_cells list."""
        from soma_core.enforcement import generate_ci_report

        cells_dir = tmp_path / '.soma' / 'cells'
        _make_cell(str(cells_dir), 'wall-docs', ['docs/*'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['README.md'],
            test_passed=True,
        )

        assert report['matched_cells'] == []

    def test_multiple_cells_match_same_file(self, tmp_path):
        """Multiple cells can match the same changed file."""
        from soma_core.enforcement import generate_ci_report

        cells_dir = tmp_path / '.soma' / 'cells'
        _make_cell(str(cells_dir), 'cell-a', ['enzymes/*'])
        _make_cell(str(cells_dir), 'cell-b', ['enzymes/cell_*.py'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['enzymes/cell_quorum.py'],
            test_passed=True,
        )

        cell_names = [c['cell'] for c in report['matched_cells']]
        assert 'cell-a' in cell_names
        assert 'cell-b' in cell_names


class TestCreditWeights:
    """Credit weights are conserved per changed file (1/N matching cells)."""

    def test_credit_weights_conserved(self, tmp_path):
        """If 2 cells match the same file, each gets credit_weight = 0.5."""
        from soma_core.enforcement import generate_ci_report

        cells_dir = tmp_path / '.soma' / 'cells'
        _make_cell(str(cells_dir), 'cell-a', ['enzymes/*'])
        _make_cell(str(cells_dir), 'cell-b', ['enzymes/*'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['enzymes/cell_quorum.py'],
            test_passed=True,
        )

        total_credit = sum(c['credit_weight'] for c in report['matched_cells'])
        assert abs(total_credit - 1.0) < 0.01, f'Credit sum {total_credit} != 1.0'

    def test_sole_cell_gets_full_credit(self, tmp_path):
        """A single matching cell gets credit_weight = 1.0."""
        from soma_core.enforcement import generate_ci_report

        cells_dir = tmp_path / '.soma' / 'cells'
        _make_cell(str(cells_dir), 'cell-solo', ['enzymes/*'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['enzymes/cell_quorum.py'],
            test_passed=True,
        )

        assert len(report['matched_cells']) == 1
        assert report['matched_cells'][0]['credit_weight'] == 1.0


class TestSignalSemantics:
    """CI pass → trigger, CI fail → fp for all matched cells."""

    def test_pass_generates_trigger_signals(self, tmp_path):
        """When tests pass, matched cells get signal='trigger'."""
        from soma_core.enforcement import generate_ci_report

        cells_dir = tmp_path / '.soma' / 'cells'
        _make_cell(str(cells_dir), 'cell-a', ['enzymes/*'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['enzymes/cell_quorum.py'],
            test_passed=True,
        )

        assert report['matched_cells'][0]['proposed_signal'] == 'trigger'

    def test_fail_generates_fp_signals(self, tmp_path):
        """When tests fail, matched cells get signal='fp'."""
        from soma_core.enforcement import generate_ci_report

        cells_dir = tmp_path / '.soma' / 'cells'
        _make_cell(str(cells_dir), 'cell-a', ['enzymes/*'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['enzymes/cell_quorum.py'],
            test_passed=False,
        )

        assert report['matched_cells'][0]['proposed_signal'] == 'fp'


class TestMarkdownReport:
    """The markdown summary is human-readable for step summary output."""

    def test_report_markdown_format(self, tmp_path):
        """Markdown output contains expected table headers."""
        from soma_core.enforcement import generate_ci_report

        cells_dir = tmp_path / '.soma' / 'cells'
        _make_cell(str(cells_dir), 'membrane-enzymes', ['enzymes/*'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['enzymes/cell_quorum.py'],
            test_passed=True,
            commit_sha='abc123',
        )

        md = report['summary']
        assert '| Cell' in md
        assert 'membrane-enzymes' in md
        assert 'trigger' in md

    def test_report_includes_commit_sha(self, tmp_path):
        """Commit SHA appears in the report header."""
        from soma_core.enforcement import generate_ci_report

        cells_dir = tmp_path / '.soma' / 'cells'
        _make_cell(str(cells_dir), 'cell-x', ['src/*'])

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['src/main.py'],
            test_passed=True,
            commit_sha='deadbeef',
        )

        assert 'deadbeef' in report['summary']

    def test_empty_report_still_valid_markdown(self, tmp_path):
        """Report with no matches still produces valid markdown."""
        from soma_core.enforcement import generate_ci_report

        cells_dir = tmp_path / '.soma' / 'cells'
        os.makedirs(str(cells_dir), exist_ok=True)

        report = generate_ci_report(
            workspace=str(tmp_path),
            changed_files=['unmatched/file.txt'],
            test_passed=True,
        )

        md = report['summary']
        assert 'Soma CI Outcome Report' in md
        assert 'Cells matched' in md or '0' in md

    def test_cli_main_supports_skipped_and_cancelled(self, tmp_path, monkeypatch):
        """CLI main parser accepts skipped and cancelled outcomes without crashing."""
        from soma_core.enforcement import main

        cells_dir = tmp_path / '.soma' / 'cells'
        _make_cell(str(cells_dir), 'cell-x', ['src/*'])

        for outcome in ['skipped', 'cancelled']:
            monkeypatch.setattr(
                'sys.argv',
                [
                    'ci_outcome_reporter.py',
                    '--changed-files',
                    'src/main.py',
                    '--test-result',
                    outcome,
                    '--workspace',
                    str(tmp_path),
                ],
            )
            main()

