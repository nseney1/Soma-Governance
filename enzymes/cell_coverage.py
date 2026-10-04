#!/usr/bin/env python3
import os, sys, argparse, glob, json, subprocess
from fnmatch import fnmatch
from soma_resolve import resolve_workspace
from soma_sdk.cells import parse_cell_file

def main():
    parser = argparse.ArgumentParser(description='Cell coverage map: visualize governance blind spots')
    parser.add_argument('--json', action='store_true', help='JSON output')
    args = parser.parse_args()
    
    workspace = resolve_workspace(__file__)
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    
    # Get all tracked files
    result = subprocess.run(['git', 'ls-files'], capture_output=True, text=True, cwd=workspace)
    all_files = [f for f in result.stdout.strip().split('\n') if f]
    EXCLUDE_PATTERNS = ['.soma/', 'vendor/', '.git/', 'node_modules/']
    all_files = [f for f in all_files if not any(p in f for p in EXCLUDE_PATTERNS)]
    
    # Load all cell target_paths
    cell_patterns = []
    for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
        if os.path.basename(cell_file) == 'README.md': continue
        try:
            fm, _body = parse_cell_file(cell_file)
            paths = fm.get('target_paths', [])
            name = os.path.splitext(os.path.basename(cell_file))[0]
            cell_patterns.append({
                'name': name,
                'patterns': paths,
                'type': fm.get('type', ''),
                'enforcement': fm.get('enforcement', 'advisory')
            })
        except Exception: pass
    
    # Compute coverage
    covered_files = set()
    uncovered_files = set()
    coverage_map = {}  # dir -> {covered, total}
    
    # Track highest enforcement tier per directory
    tier_rank = {'advisory': 0, 'mechanical': 1, 'gate': 2}
    dir_tiers = {}  # dir -> highest tier

    for f in all_files:
        is_covered = False
        for cell in cell_patterns:
            for pattern in cell['patterns']:
                if fnmatch(f, pattern):
                    is_covered = True
                    break
            if is_covered: break
        
        if is_covered:
            covered_files.add(f)
        else:
            uncovered_files.add(f)
        
        # Track by directory
        d = os.path.dirname(f) or '.'
        if d not in coverage_map:
            coverage_map[d] = {'covered': 0, 'total': 0, 'tier': 'none'}
        coverage_map[d]['total'] += 1
        if is_covered:
            coverage_map[d]['covered'] += 1
            
        for cell in cell_patterns:
            for pattern in cell['patterns']:
                if fnmatch(f, pattern):
                    current = dir_tiers.get(d, 'none')
                    cell_tier = cell.get('enforcement', 'advisory')
                    if tier_rank.get(cell_tier, 0) > tier_rank.get(current, -1):
                        dir_tiers[d] = cell_tier
                    break
            
        coverage_map[d]['tier'] = dir_tiers.get(d, 'none')
    
    total = len(all_files)
    covered = len(covered_files)
    pct = (covered / total * 100) if total > 0 else 0
    
    if args.json:
        print(json.dumps({
            'total_files': total, 'covered': covered, 'uncovered': total - covered,
            'coverage_pct': round(pct, 1),
            'by_directory': coverage_map
        }, indent=2))
    else:
        print(f'\n📊 Cell Coverage: {covered}/{total} files ({pct:.1f}%)\n')
        print(f'{"Directory":<40} {"Coverage":>10}  Bar                  Tier')
        print('─' * 90)
        tier_icons = {'gate': '🔒', 'mechanical': '⚙️', 'advisory': '💬', 'none': '⬜'}
        for d in sorted(coverage_map.keys()):
            info = coverage_map[d]
            dpct = info['covered'] / info['total'] * 100 if info['total'] > 0 else 0
            bar_len = int(dpct / 5)
            bar = '█' * bar_len + '░' * (20 - bar_len)
            status = '✅' if dpct == 100 else '⚠️' if dpct > 0 else '🔴'
            tier = info.get('tier', 'none')
            print(f'{d:<40} {info["covered"]:>3}/{info["total"]:<3} {status} {bar} {tier_icons.get(tier, "")} {tier}')
        
        if uncovered_files:
            print(f'\n🔴 Blind Spots ({len(uncovered_files)} uncovered files):')
            # Show top uncovered dirs
            uncovered_dirs = {}
            for f in uncovered_files:
                d = os.path.dirname(f) or '.'
                uncovered_dirs[d] = uncovered_dirs.get(d, 0) + 1
            for d, count in sorted(uncovered_dirs.items(), key=lambda x: -x[1])[:10]:
                print(f'   {d}/ ({count} files)')

if __name__ == '__main__':
    # A cp1252 stdout can't encode this script's symbols (BUG-038).
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    main()
