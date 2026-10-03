#!/usr/bin/env python3
"""Track defects that escaped governance coverage.

For each failure event (test regression, crash, build failure):
1. Identify which files were involved
2. Check which cells cover those files via target_paths
3. If a cell covers the file but didn't fire → escaped defect
4. Log the escaped defect to metrics/escaped_defects.jsonl

Usage:
    python cell_escaped_defects.py --event crash --files agent/ppo/optimizer.py
    python cell_escaped_defects.py --event test_failure --files tests/test_env.py
    python cell_escaped_defects.py --scan-git --since "3 days ago"
    python cell_escaped_defects.py --report
"""
import os, sys, argparse, glob, json, subprocess, math
from pathlib import Path
from datetime import datetime
from datetime import timezone
try:
    from soma_resolve import resolve_workspace
except ImportError:
    resolve_workspace = None
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
from soma_sdk.cells import parse_cell_file

def match_glob(filepath, pattern):
    """Match a filepath against a glob pattern, supporting ** globstar."""
    import re
    # Convert glob to regex
    regex = pattern.replace('.', r'\.')
    regex = regex.replace('**/', '(?:.+/)?')  # ** matches any number of directories
    regex = regex.replace('*', '[^/]*')       # * matches within a single directory
    regex = regex.replace('?', '[^/]')        # ? matches single char
    return bool(re.match(regex + '$', filepath))


def load_cells(cells_dir):
    """Load all cells with their metadata."""
    cells = []
    for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
        if os.path.basename(cell_file) == 'README.md':
            continue
        try:
            fm, body = parse_cell_file(cell_file)
            fm['_path'] = cell_file
            fm['_name'] = os.path.splitext(os.path.basename(cell_file))[0]
            fm['_body'] = body.strip()
            with open(cell_file, encoding="utf-8") as f:
                fm['_raw'] = f.read()
            cells.append(fm)
        except Exception:
            pass
    return cells


def find_covering_cells(cells, files):
    """Find cells whose target_paths match the given files."""
    covering = []
    for cell in cells:
        target_paths = cell.get('target_paths', [])
        matched_files = []
        for f in files:
            for pattern in target_paths:
                if match_glob(f, pattern):
                    matched_files.append(f)
                    break
        if matched_files:
            covering.append({
                'cell': cell,
                'matched_files': matched_files
            })
    return covering


def record_escaped_defect(cell, event_type, files, severity, workspace):
    """Record an escaped defect against a cell."""
    metrics_dir = os.path.join(workspace, '.soma', 'metrics')
    os.makedirs(metrics_dir, exist_ok=True)
    
    log_path = os.path.join(metrics_dir, 'escaped_defects.jsonl')
    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
        'cell': cell['_name'],
        'cell_type': cell.get('type', ''),
        'enforcement': cell.get('enforcement', 'advisory'),
        'event': event_type,
        'files': files,
        'severity': severity
    }
    with open(log_path, 'a', encoding="utf-8") as f:
        f.write(json.dumps(entry) + '\n')
    
    return entry


def update_cell_escaped_rate(cell, workspace):
    """Recalculate a cell's escaped_defect_rate from the log."""
    metrics_dir = os.path.join(workspace, '.soma', 'metrics')
    log_path = os.path.join(metrics_dir, 'escaped_defects.jsonl')
    if not os.path.exists(log_path):
        return 0.0
    
    escaped = 0
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if entry.get('cell') == cell['_name']:
                    escaped += 1
            except Exception:
                continue
    
    # escaped_defect_rate = escaped / (escaped + true_positives)
    tp = cell.get('fitness', {}).get('true_positives', 0)
    total = escaped + tp
    if total == 0:
        return 0.0
    
    return round(escaped / total, 4)


# Note: This is a simplified fitness for reporting purposes.
# The canonical fitness function is in cell_fitness.py which also includes
# specificity penalty, antifragile bonus, and impact weighting.
# For authoritative fitness scores, use cell_fitness.py --json.
def compute_enhanced_fitness(cell, escaped_defect_rate):
    """Compute fitness with independent outcome signal.
    
    fitness = bayesian_mean(TP, FP) * (1 - escaped_defect_rate) * tier_weight
    """
    tier_weights = {'advisory': 1.0, 'mechanical': 1.2, 'gate': 1.5}
    
    tp = cell.get('fitness', {}).get('true_positives', 0)
    fp = cell.get('fitness', {}).get('false_positives', 0)
    
    # Bayesian mean with Jeffrey's prior
    a = tp + 0.5
    b = fp + 0.5
    bayesian_mean = a / (a + b)
    
    enforcement = cell.get('enforcement', 'advisory')
    tier_weight = tier_weights.get(enforcement, 1.0)
    
    enhanced = bayesian_mean * (1 - escaped_defect_rate) * tier_weight
    return round(enhanced, 4)


def scan_git_for_defects(workspace, since):
    """Scan git history for reverted commits, fix-after-fix patterns."""
    # Find commits that are fixes/reverts of recent commits
    git_args = ['git', 'log', '--format=%H %s', f'--since={since}']
    result = subprocess.run(git_args, capture_output=True, text=True, cwd=workspace)
    
    defect_commits = []
    for line in result.stdout.strip().split('\n'):
        if not line:
            continue
        sha, *msg_parts = line.split(' ')
        msg = ' '.join(msg_parts).lower()
        
        # Heuristic: fix, revert, hotfix, patch, workaround indicate escaped defects
        if any(kw in msg for kw in ['revert', 'hotfix', 'fix:', 'bugfix', 'patch:', 'workaround']):
            # Get files changed in this commit
            try:
                diff_result = subprocess.run(
                    ['git', 'diff', '--name-only', f'{sha}~1', sha],
                    capture_output=True, text=True, cwd=workspace
                )
                if diff_result.returncode != 0:
                    continue
                files = [f for f in diff_result.stdout.strip().split('\n') if f]
            except Exception:
                continue
            if files:
                defect_commits.append({
                    'sha': sha[:8],
                    'message': ' '.join(msg_parts),
                    'files': files,
                    'severity': 'high' if 'revert' in msg else 'medium'
                })
    
    return defect_commits


def generate_report(cells, workspace):
    """Generate escaped defects report."""
    metrics_dir = os.path.join(workspace, '.soma', 'metrics')
    log_path = os.path.join(metrics_dir, 'escaped_defects.jsonl')
    
    # Count escaped defects per cell
    cell_escapes = {}
    total_escapes = 0
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    name = entry.get('cell', '')
                    cell_escapes[name] = cell_escapes.get(name, 0) + 1
                    total_escapes += 1
                except Exception:
                    continue
    
    report = []
    for cell in cells:
        name = cell['_name']
        escapes = cell_escapes.get(name, 0)
        tp = cell.get('fitness', {}).get('true_positives', 0)
        fp = cell.get('fitness', {}).get('false_positives', 0)
        enforcement = cell.get('enforcement', 'advisory')
        
        escaped_rate = update_cell_escaped_rate(cell, workspace)
        enhanced_fitness = compute_enhanced_fitness(cell, escaped_rate)
        
        # Defect prevention rate = 1 - escaped_defect_rate
        prevention_rate = 1 - escaped_rate
        
        report.append({
            'cell': name,
            'type': cell.get('type', ''),
            'enforcement': enforcement,
            'tp': tp,
            'fp': fp,
            'escaped': escapes,
            'escaped_defect_rate': escaped_rate,
            'defect_prevention_rate': round(prevention_rate, 4),
            'enhanced_fitness': enhanced_fitness
        })
    
    return report, total_escapes


def main():
    parser = argparse.ArgumentParser(
        description='Track defects that escaped governance coverage'
    )
    parser.add_argument('--event', choices=['crash', 'test_failure', 'build_failure', 'rework', 'regression'],
                       help='Type of escaped defect event')
    parser.add_argument('--files', nargs='+', help='Files involved in the defect')
    parser.add_argument('--severity', choices=['low', 'medium', 'high', 'critical'],
                       default='medium', help='Defect severity')
    parser.add_argument('--scan-git', action='store_true',
                       help='Auto-detect escaped defects from git history')
    parser.add_argument('--since', default='7 days ago',
                       help='Git history lookback for --scan-git')
    parser.add_argument('--report', action='store_true',
                       help='Generate escaped defects report')
    parser.add_argument('--json', action='store_true', help='JSON output')
    args = parser.parse_args()
    
    workspace = resolve_workspace(__file__)
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    cells = load_cells(cells_dir)
    
    if not cells:
        print('No cells found.')
        return
    
    if args.report:
        report, total = generate_report(cells, workspace)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f'\n🛡️  Escaped Defects Report ({total} total escaped defects)\n')
            print(f'{"Cell":<25} {"Type":<10} {"Tier":<12} {"TP":>4} {"FP":>4} {"Esc":>4} {"Prevention":>10} {"Enhanced":>10}')
            print('─' * 90)
            for r in sorted(report, key=lambda x: x['enhanced_fitness'], reverse=True):
                print(f'{r["cell"]:<25} {r["type"]:<10} {r["enforcement"]:<12} {r["tp"]:>4} {r["fp"]:>4} {r["escaped"]:>4} {r["defect_prevention_rate"]:>9.1%} {r["enhanced_fitness"]:>10.4f}')
        return
    
    if args.scan_git:
        defects = scan_git_for_defects(workspace, args.since)
        if not defects:
            print(f'No escaped defects found in git history since "{args.since}".')
            return
        
        total_recorded = 0
        for defect in defects:
            covering = find_covering_cells(cells, defect['files'])
            for cov in covering:
                record_escaped_defect(
                    cov['cell'], 'git_' + defect['severity'],
                    defect['files'], defect['severity'], workspace
                )
                total_recorded += 1
                if not args.json:
                    print(f'⚠️  {defect["sha"]} "{defect["message"][:60]}"')
                    print(f'   Escaped cell: {cov["cell"]["_name"]} (covers {len(cov["matched_files"])} of {len(defect["files"])} files)')
        
        if args.json:
            print(json.dumps({'scanned_commits': len(defects), 'escaped_recorded': total_recorded}))
        else:
            print(f'\nRecorded {total_recorded} escaped defects from {len(defects)} commits.')
        return
    
    if args.event and args.files:
        covering = find_covering_cells(cells, args.files)
        if not covering:
            if not args.json:
                print(f'No cells cover the affected files: {", ".join(args.files)}')
                print('This is a governance blind spot — consider creating cells for these paths.')
            return
        
        recorded = []
        for cov in covering:
            entry = record_escaped_defect(
                cov['cell'], args.event, args.files, args.severity, workspace
            )
            recorded.append(entry)
            if not args.json:
                escaped_rate = update_cell_escaped_rate(cov['cell'], workspace)
                print(f'⚠️  Escaped defect recorded against: {cov["cell"]["_name"]}')
                print(f'   Event: {args.event} | Severity: {args.severity}')
                print(f'   Escaped defect rate: {escaped_rate:.1%}')
                print(f'   Files: {", ".join(cov["matched_files"])}')
        
        if args.json:
            print(json.dumps(recorded, indent=2))
        return
    
    parser.print_help()


if __name__ == '__main__':
    # Output uses non-ASCII symbols; on a cp1252 stdout printing them
    # raised UnicodeEncodeError and the script exited 1 (BUG-038).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    main()
