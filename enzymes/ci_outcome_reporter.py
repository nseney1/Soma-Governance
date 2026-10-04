#!/usr/bin/env python3
"""CI Outcome Reporter — generates a report of which cells matched changed files.

This is a read-only advisory tool. It does NOT update cell fitness counters.
It produces a markdown summary for GitHub Actions step summaries showing which
cells are relevant to the changes in a PR/push, what credit weights they'd
receive, and what signals would be applied.

Usage (CLI):
    python3 enzymes/ci_outcome_reporter.py \\
        --changed-files "file1.py file2.py" \\
        --test-result pass \\
        --commit-sha abc123 \\
        --format markdown

Usage (library):
    from ci_outcome_reporter import generate_ci_report
    report = generate_ci_report(workspace, changed_files, test_passed)
"""
import argparse
import fnmatch
import glob
import os
import sys

import yaml


def _parse_cell_frontmatter(filepath):
    """Parse YAML frontmatter from a cell markdown file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    if not content.startswith('---'):
        return {}

    end = content.find('---', 3)
    if end == -1:
        return {}

    frontmatter_text = content[3:end].strip()
    try:
        return yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError:
        return {}


def _match_cells(workspace, changed_files):
    """Match cells to changed files using target_paths fnmatch globs.

    Returns list of dicts with keys: cell, type, target_match, path.
    """
    matched = []
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    if not os.path.isdir(cells_dir):
        return matched

    for cell_file in glob.glob(
        os.path.join(cells_dir, '**', '*.md'), recursive=True
    ):
        if os.path.basename(cell_file) == 'README.md':
            continue

        try:
            fm = _parse_cell_frontmatter(cell_file)
        except Exception:
            continue

        target_paths = fm.get('target_paths', [])
        if isinstance(target_paths, str):
            target_paths = [target_paths]

        matched_pattern = None
        for fpath in changed_files:
            for tp in target_paths:
                if fnmatch.fnmatch(fpath, tp) or fnmatch.fnmatch(
                    os.path.basename(fpath), tp
                ):
                    matched_pattern = tp
                    break
            if matched_pattern:
                break

        if matched_pattern:
            cell_name = os.path.splitext(os.path.basename(cell_file))[0]
            matched.append({
                'cell': cell_name,
                'type': fm.get('type', 'unknown'),
                'target_match': matched_pattern,
                'path': cell_file,
            })

    return matched


def _compute_credit_weights(matched_cells, changed_files):
    """Compute per-cell credit weights with per-file conservation.

    For each changed file, cells matching that file share 1/N credit.
    A cell's total credit is the sum across all files it matches.
    """
    if not matched_cells or not changed_files:
        return {c['cell']: 1.0 for c in matched_cells}

    # Build map: cell_name → target_paths
    cell_targets = {}
    for cell in matched_cells:
        cell_name = cell['cell']
        cell_path = cell['path']
        try:
            fm = _parse_cell_frontmatter(cell_path)
        except Exception:
            fm = {}
        tp = fm.get('target_paths', [])
        if isinstance(tp, str):
            tp = [tp]
        cell_targets[cell_name] = tp

    weights = {c['cell']: 0.0 for c in matched_cells}

    for fpath in changed_files:
        # Find which cells match this specific file
        matching_for_file = []
        for cell_name, targets in cell_targets.items():
            for tp in targets:
                if fnmatch.fnmatch(fpath, tp) or fnmatch.fnmatch(
                    os.path.basename(fpath), tp
                ):
                    matching_for_file.append(cell_name)
                    break

        if matching_for_file:
            share = 1.0 / len(matching_for_file)
            for cell_name in matching_for_file:
                weights[cell_name] += share

    return weights


def generate_ci_report(workspace, changed_files, test_passed, commit_sha=None):
    """Generate a CI outcome report.

    Args:
        workspace: Root workspace directory containing .soma/
        changed_files: List of changed file paths (relative to workspace)
        test_passed: Boolean — did the test suite pass?
        commit_sha: Optional commit SHA for the report header

    Returns:
        dict with keys:
          - matched_cells: list of dicts with cell, type, target_match,
                           credit_weight, proposed_signal
          - summary: markdown string for step summary
    """
    matched = _match_cells(workspace, changed_files)
    weights = _compute_credit_weights(matched, changed_files)

    # Assign signals
    signal = 'trigger' if test_passed else 'fp'
    for cell in matched:
        cell['credit_weight'] = weights.get(cell['cell'], 1.0)
        cell['proposed_signal'] = signal

    # Generate markdown
    summary = _format_markdown(matched, test_passed, commit_sha, changed_files)

    return {
        'matched_cells': matched,
        'summary': summary,
    }


def _format_markdown(matched_cells, test_passed, commit_sha, changed_files):
    """Format the report as a markdown summary."""
    status = '\u2705 Passed' if test_passed else '\u274c Failed'
    sha_display = commit_sha[:8] if commit_sha else 'unknown'

    lines = [
        '## \U0001f52c Soma CI Outcome Report',
        '',
        f'**Commit**: `{sha_display}` | **Tests**: {status} '
        f'| **Cells matched**: {len(matched_cells)} '
        f'| **Files changed**: {len(changed_files)}',
        '',
    ]

    if matched_cells:
        lines.extend([
            '| Cell | Type | Target Match | Credit | Signal |',
            '|:-----|:-----|:-------------|:-------|:-------|',
        ])
        for cell in sorted(matched_cells, key=lambda c: c['cell']):
            lines.append(
                f'| {cell["cell"]} | {cell["type"]} '
                f'| `{cell["target_match"]}` '
                f'| {cell["credit_weight"]:.2f} '
                f'| {cell["proposed_signal"]} |'
            )
    else:
        lines.append('No cells matched the changed files.')

    lines.append('')
    return '\n'.join(lines)


def main():
    """CLI entrypoint for CI integration."""
    parser = argparse.ArgumentParser(description='Soma CI Outcome Reporter')
    parser.add_argument(
        '--changed-files',
        required=True,
        help='Space-separated list of changed files',
    )
    parser.add_argument(
        '--test-result',
        required=True,
        choices=['pass', 'fail', 'success', 'failure', 'skipped', 'cancelled'],
        help='CI test result',
    )
    parser.add_argument('--commit-sha', default=None, help='Commit SHA')
    parser.add_argument(
        '--workspace',
        default='.',
        help='Workspace root (default: current directory)',
    )
    parser.add_argument(
        '--format',
        choices=['markdown', 'json'],
        default='markdown',
        help='Output format',
    )

    args = parser.parse_args()

    changed = [f for f in args.changed_files.split() if f.strip()]
    test_passed = args.test_result in ('pass', 'success')

    report = generate_ci_report(
        workspace=args.workspace,
        changed_files=changed,
        test_passed=test_passed,
        commit_sha=args.commit_sha,
    )

    if args.format == 'json':
        import json
        print(json.dumps(report, indent=2))
    else:
        print(report['summary'])


if __name__ == '__main__':
    # A cp1252 stdout can't encode this script's symbols (BUG-038).
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    main()
