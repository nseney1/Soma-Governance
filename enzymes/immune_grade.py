#!/usr/bin/env python3
import argparse
import glob
import json
import math
import os
import subprocess
import sys

from soma_resolve import resolve_workspace
from soma_sdk.cells import parse_cell_file


def letter_grade(pct):
    if pct >= 97: return 'A+'
    if pct >= 93: return 'A'
    if pct >= 90: return 'A-'
    if pct >= 87: return 'B+'
    if pct >= 83: return 'B'
    if pct >= 80: return 'B-'
    if pct >= 77: return 'C+'
    if pct >= 73: return 'C'
    if pct >= 70: return 'C-'
    if pct >= 67: return 'D+'
    if pct >= 60: return 'D'
    return 'F'

def main():
    parser = argparse.ArgumentParser(description='Governance report card: single-grade summary')
    parser.add_argument('--json', action='store_true', help='JSON output')
    args = parser.parse_args()
    
    workspace = resolve_workspace(__file__)
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    
    # Load cells
    cells = []
    for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
        if os.path.basename(cell_file) == 'README.md': continue
        try:
            fm, _body = parse_cell_file(cell_file)
            if isinstance(fm.get('fitness'), (int, float)):
                fm['fitness'] = {'score': float(fm['fitness'])}
            cells.append(fm | {'_name': os.path.splitext(os.path.basename(cell_file))[0]})
        except Exception: pass
    
    if not cells:
        print('No cells found. Run Genesis first.')
        return
    
    # 1. Coverage
    result = subprocess.run(['git', 'ls-files'], capture_output=True, text=True, cwd=workspace)
    all_files = [f for f in result.stdout.strip().split('\n') if f]
    exclude = ['.soma/', 'vendor/', '.git/', 'node_modules/']
    all_files = [f for f in all_files if not any(p in f for p in exclude)]
    
    from fnmatch import fnmatch
    all_patterns = []
    for c in cells:
        all_patterns.extend(c.get('target_paths', []))
    
    covered = sum(1 for f in all_files if any(fnmatch(f, p) for p in all_patterns))
    coverage_pct = (covered / len(all_files) * 100) if all_files else 0
    
    # 2. Avg Fitness
    scores = [(c.get('fitness') or {}).get('score') for c in cells if (c.get('fitness') or {}).get('score') is not None]
    avg_fitness = (sum(scores) / len(scores)) if scores else 0
    fitness_pct = avg_fitness * 100
    
    # 3. Diversity (Shannon entropy)
    type_counts = {}
    for c in cells:
        ct = c.get('type', 'unknown')
        type_counts[ct] = type_counts.get(ct, 0) + 1
    total = sum(type_counts.values())
    if len(type_counts) > 1:
        entropy = -sum((n/total) * math.log(n/total) for n in type_counts.values() if n > 0)
        max_entropy = math.log(len(type_counts))
        diversity = (entropy / max_entropy) * 100
    else:
        diversity = 0
    
    # 4. Staleness (cells with no triggers in 30 days - approximate by triggers=0)
    stale = sum(1 for c in cells if (c.get('fitness') or {}).get('triggers', 0) == 0)
    staleness_pct = 100 - (stale / len(cells) * 100) if cells else 100
    
    # 5. Wall Integrity
    walls = [c for c in cells if c.get('type') == 'wall']
    healthy_walls = sum(1 for w in walls if ((w.get('fitness') or {}).get('score') is not None and (w.get('fitness') or {}).get('score', 0) > 0.3))
    wall_pct = (healthy_walls / len(walls) * 100) if walls else 100
    
    # Overall
    overall_pct = (coverage_pct * 0.3 + fitness_pct * 0.25 + diversity * 0.15 + staleness_pct * 0.15 + wall_pct * 0.15)
    
    # Enforcement tier distribution
    tier_counts = {}
    for c in cells:
        tier = c.get('enforcement', 'advisory')
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    
    # Find top improvement
    uncovered_dirs = {}
    for f in all_files:
        if not any(fnmatch(f, p) for p in all_patterns):
            d = os.path.dirname(f) or '.'
            uncovered_dirs[d] = uncovered_dirs.get(d, 0) + 1
    top_gap = max(uncovered_dirs.items(), key=lambda x: x[1]) if uncovered_dirs else ('none', 0)
    
    if args.json:
        print(json.dumps({
            'coverage': {'pct': round(coverage_pct, 1), 'grade': letter_grade(coverage_pct)},
            'avg_fitness': {'pct': round(fitness_pct, 1), 'grade': letter_grade(fitness_pct)},
            'diversity': {'pct': round(diversity, 1), 'grade': letter_grade(diversity)},
            'staleness': {'pct': round(staleness_pct, 1), 'grade': letter_grade(staleness_pct)},
            'wall_integrity': {'pct': round(wall_pct, 1), 'grade': letter_grade(wall_pct)},
            'tiers': tier_counts,
            'overall': {'pct': round(overall_pct, 1), 'grade': letter_grade(overall_pct)},
            'top_improvement': f'Add cells for {top_gap[0]}/ ({top_gap[1]} uncovered files)'
        }, indent=2))
    else:
        print()
        print('═══════════════════════════════════════════')
        print('  📊 Governance Report Card')
        print('═══════════════════════════════════════════')
        print(f'  Coverage:        {coverage_pct:5.1f}%  ({letter_grade(coverage_pct)})')
        print(f'  Avg Fitness:     {avg_fitness:.2f}   ({letter_grade(fitness_pct)})')
        print(f'  Diversity:       {diversity:5.1f}%  ({letter_grade(diversity)})')
        print(f'  Staleness:       {staleness_pct:5.1f}%  ({letter_grade(staleness_pct)})')
        print(f'  Wall Integrity:  {wall_pct:5.1f}%  ({letter_grade(wall_pct)})')
        print()
        print(f'  Tiers:           A: {tier_counts.get("advisory", 0)} | M: {tier_counts.get("mechanical", 0)} | G: {tier_counts.get("gate", 0)}')
        print()
        print(f'  Overall Grade:   {letter_grade(overall_pct)}')
        print()
        if top_gap[1] > 0:
            print(f'  Top Improvement: Add cells for {top_gap[0]}/ ({top_gap[1]} uncovered files)')
        print('═══════════════════════════════════════════')

if __name__ == '__main__':
    # A cp1252 stdout can't encode this script's symbols (BUG-038).
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    main()
