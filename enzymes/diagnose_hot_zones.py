#!/usr/bin/env python3
"""Diagnose Hot Zones — monitoring hook for hot zone threshold health.

Usage:
    python3 enzymes/diagnose_hot_zones.py [--workspace PATH]

Reports threshold proximity, distribution health, and tuning recommendations.
Read-only: never modifies BUG_REGISTRY.json. Exit code always 0 (diagnostic).
"""
from __future__ import annotations

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from soma_sdk.hot_zones import compute_hot_zones, load_config


def load_registry(workspace: str) -> dict | None:
    """Load BUG_REGISTRY.json, returning None if missing."""
    path = os.path.join(workspace, 'docs', 'project', 'BUG_REGISTRY.json')
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def proximity_alerts(report) -> list[str]:
    """Report how close each category/file is to activating."""
    alerts = []
    config = report.config

    for cat, count in sorted(report.pattern_heat.items(), key=lambda x: -x[1]):
        remaining = config.pattern_heat_threshold - count
        if remaining <= 0:
            alerts.append(f"  🔥 {cat}: {count}/{config.pattern_heat_threshold} — ACTIVE")
        elif remaining <= 2:
            alerts.append(
                f"  ⚠️  {cat}: {count}/{config.pattern_heat_threshold} "
                f"— {remaining} more bug(s) to activate"
            )
        else:
            alerts.append(f"  ·  {cat}: {count}/{config.pattern_heat_threshold}")

    for f, count in sorted(report.file_heat.items(), key=lambda x: -x[1]):
        remaining = config.file_heat_threshold - count
        if remaining <= 0:
            alerts.append(f"  🔥 {f}: {count}/{config.file_heat_threshold} — ACTIVE")
        elif remaining == 1:
            alerts.append(
                f"  ⚠️  {f}: {count}/{config.file_heat_threshold} "
                f"— 1 more bug to activate"
            )

    return alerts


def threshold_sanity(report) -> list[str]:
    """Check if thresholds seem miscalibrated."""
    warnings = []
    total = report.total_bugs_analyzed
    config = report.config
    active_count = len(report.active_file_zones) + len(report.active_pattern_zones)

    if total < 10:
        warnings.append(
            f"ℹ️  Insufficient data ({total} bugs). "
            f"Thresholds untested — revisit after 10+ bugs."
        )
        return warnings

    if total >= 20 and active_count == 0:
        warnings.append(
            f"⚠️  {total} bugs registered but zero hot zones activated. "
            f"Consider lowering thresholds "
            f"(file: {config.file_heat_threshold}, pattern: {config.pattern_heat_threshold})."
        )

    total_files = len(report.file_heat)
    if total_files > 0 and len(report.active_file_zones) > total_files / 3:
        warnings.append(
            f"⚠️  {len(report.active_file_zones)}/{total_files} files are hot zones. "
            f"Thresholds may be too low — consider raising file_heat_threshold "
            f"from {config.file_heat_threshold}."
        )

    total_patterns = len(report.pattern_heat)
    if total_patterns > 0 and len(report.active_pattern_zones) > total_patterns / 2:
        warnings.append(
            f"⚠️  {len(report.active_pattern_zones)}/{total_patterns} categories "
            f"are hot zones. Consider raising pattern_heat_threshold "
            f"from {config.pattern_heat_threshold}."
        )

    return warnings


def run_diagnostic(workspace: str) -> dict:
    """Run full diagnostic and return structured results."""
    registry = load_registry(workspace)
    if registry is None:
        return {'error': 'BUG_REGISTRY.json not found'}

    report = compute_hot_zones(registry)

    return {
        'total_bugs': report.total_bugs_analyzed,
        'proximity': proximity_alerts(report),
        'sanity': threshold_sanity(report),
        'active_files': report.active_file_zones,
        'active_patterns': report.active_pattern_zones,
        'file_heat': report.file_heat,
        'pattern_heat': report.pattern_heat,
        'config': {
            'file_heat_threshold': report.config.file_heat_threshold,
            'pattern_heat_threshold': report.config.pattern_heat_threshold,
            'max_file_boost': report.config.max_file_boost,
            'max_pattern_boost': report.config.max_pattern_boost,
        },
    }


def main():
    workspace = '.'
    if '--workspace' in sys.argv:
        idx = sys.argv.index('--workspace')
        workspace = sys.argv[idx + 1]

    result = run_diagnostic(workspace)

    if 'error' in result:
        print(f"ERROR: {result['error']}")
        sys.exit(0)

    print(f"=== Hot Zone Diagnostic ({result['total_bugs']} bugs) ===\n")

    print("Proximity to activation:")
    for line in result['proximity']:
        print(line)

    print(f"\nActive hot zones: "
          f"{len(result['active_files'])} files, "
          f"{len(result['active_patterns'])} patterns")

    if result['sanity']:
        print("\nThreshold health:")
        for line in result['sanity']:
            print(f"  {line}")

    print(f"\nConfig: file_heat≥{result['config']['file_heat_threshold']}, "
          f"pattern_heat≥{result['config']['pattern_heat_threshold']}, "
          f"max_file_boost={result['config']['max_file_boost']}, "
          f"max_pattern_boost={result['config']['max_pattern_boost']}")


if __name__ == '__main__':
    # Output uses non-ASCII symbols; on a cp1252 stdout printing them
    # raised UnicodeEncodeError and the script exited 1 (BUG-038).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    main()
