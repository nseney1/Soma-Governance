#!/usr/bin/env python3
"""Oracle Checkpoint — Mid-Session Fitness Feedback.

Reads cell metadata and canonical signal evidence to produce an actionable health
report. Integrates cell_expiry for staleness detection and signals.jsonl for
behavioral scoring.

Usage:
    python3 enzymes/oracle_checkpoint.py [workspace]
    python3 enzymes/oracle_checkpoint.py [workspace] --json
"""
import argparse
import collections
import glob
import json
import os
import sys
from datetime import datetime

from soma_core.evidence import aggregate_signals
from soma_resolve import resolve_workspace
from soma_sdk.cells import parse_cell_file
from cell_expiry import audit_expiry


def _load_fitness_evidence(workspace):
    """Load canonical signal evidence aggregated per cell id.

    Returns:
        Dict mapping cell_id to canonical trigger and outcome dimensions.
    """
    evidence_dir = os.path.join(workspace, '.soma', 'evidence')
    return aggregate_signals(evidence_dir).counts


def _load_cells(workspace):
    """Load all cell metadata from .soma/cells/."""
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    cells = []

    if not os.path.isdir(cells_dir):
        return cells

    for md_file in sorted(glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True)):
        if os.path.basename(md_file) == 'README.md':
            continue
        try:
            metadata, _body = parse_cell_file(md_file)
            metadata['_filepath'] = md_file
            cells.append(metadata)
        except Exception:
            continue

    return cells


def _classify_cell(cell, evidence, expired_ids):
    """Classify a single cell's health status.

    Returns:
        (classification, details) where classification is one of:
        healthy, unobserved, noisy, underperforming, expired
    """
    cell_id = cell.get('id', '')

    # Check expiry first
    if cell_id in expired_ids:
        return 'expired', 'Past expiry limit'

    # Check evidence
    ev = evidence.get(cell_id)
    if not ev or ev['triggers'] == 0:
        return 'unobserved', 'No trigger data recorded'

    triggers = ev['triggers']
    tp = ev['tp']
    fp = ev['fp']
    has_outcomes = ev['has_outcomes']

    if has_outcomes:
        # We have outcome data — classify by precision
        if triggers >= 3 and fp > tp:
            precision = tp / triggers if triggers > 0 else 0
            return 'noisy', f'{fp}/{triggers} false positives (precision: {precision:.0%})'
        return 'healthy', f'{tp}/{triggers} true positives'

    # No outcome data yet — classify by trigger volume only
    if triggers >= 5:
        return 'active', f'{triggers} triggers (no outcome data yet)'
    return 'healthy', f'{triggers} trigger(s) recorded'


def generate_checkpoint(workspace, session_count=None):
    """Generate a mid-session health checkpoint report.

    Args:
        workspace: Path to project root.
        session_count: Optional session count for session-based expiry.

    Returns:
        Dict with keys: total_cells, classifications, recommendations, timestamp.
    """
    cells = _load_cells(workspace)
    evidence = _load_fitness_evidence(workspace)
    expiry_results = audit_expiry(workspace, session_count=session_count)

    expired_ids = {
        r['cell_id'] for r in expiry_results
        if r['status'] in ('EXPIRED', 'EXPIRY_WARNING')
    }

    # Classify each cell
    classifications = collections.defaultdict(list)
    for cell in cells:
        cell_id = cell.get('id', '')
        category, details = _classify_cell(cell, evidence, expired_ids)
        classifications[category].append({
            'cell_id': cell_id,
            'type': cell.get('type', 'unknown'),
            'details': details,
        })

    # Generate recommendations
    recommendations = []

    expired_count = len(classifications.get('expired', []))
    if expired_count > 0:
        recommendations.append({
            'severity': 'critical',
            'action': 'prune_expired',
            'message': f'{expired_count} cell(s) past expiry limit. '
                       f'Run: python3 enzymes/cell_expiry.py . --prune',
        })

    noisy_count = len(classifications.get('noisy', []))
    if noisy_count > 0:
        noisy_ids = [c['cell_id'] for c in classifications['noisy']]
        recommendations.append({
            'severity': 'warning',
            'action': 'review_noisy',
            'message': f'{noisy_count} noisy cell(s): {", ".join(noisy_ids)}. '
                       f'Consider tightening hypotheses or target_paths.',
        })

    unobserved_count = len(classifications.get('unobserved', []))
    if unobserved_count > 0 and len(cells) > 0:
        pct = unobserved_count / len(cells) * 100
        if pct > 50:
            recommendations.append({
                'severity': 'info',
                'action': 'collect_evidence',
                'message': f'{unobserved_count}/{len(cells)} cells ({pct:.0f}%) have no '
                           f'fitness evidence. Run post-session hook to collect data.',
            })

    return {
        'total_cells': len(cells),
        'classifications': dict(classifications),
        'recommendations': recommendations,
        'timestamp': datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main():
    parser = argparse.ArgumentParser(
        description='Generate mid-session fitness checkpoint report'
    )
    parser.add_argument('workspace', nargs='?', default='.',
                        help='Project workspace root')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON')
    parser.add_argument('--session-count', type=int, default=None,
                        help='Session count for session-based expiry')
    args = parser.parse_args()

    # Set SOMA_ROOT so resolve_workspace uses the explicit path
    if args.workspace != '.':
        os.environ['SOMA_ROOT'] = os.path.abspath(args.workspace)
    workspace = resolve_workspace()
    report = generate_checkpoint(workspace, session_count=args.session_count)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"=== Oracle Checkpoint ({report['timestamp']}) ===")
        print(f"Total cells: {report['total_cells']}")
        for category, items in report['classifications'].items():
            icon = {'healthy': '✅', 'unobserved': '🔍', 'noisy': '📢',
                    'underperforming': '📉', 'expired': '⏰'}.get(category, '❓')
            print(f"\n{icon} {category.upper()} ({len(items)}):")
            for item in items:
                print(f"  - {item['cell_id']} ({item['type']}): {item['details']}")

        if report['recommendations']:
            print("\n📋 Recommendations:")
            for rec in report['recommendations']:
                sev = {'critical': '🔴', 'warning': '🟡', 'info': 'ℹ️'}.get(rec['severity'], '❓')
                print(f"  {sev} {rec['message']}")

    return 0


if __name__ == '__main__':
    # Output uses non-ASCII symbols; on a cp1252 stdout printing them
    # raised UnicodeEncodeError and the script exited 1 (BUG-038).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
