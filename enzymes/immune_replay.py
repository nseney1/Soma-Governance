#!/usr/bin/env python3
import os, sys, argparse, glob, json, subprocess
from fnmatch import fnmatch
from datetime import datetime
from soma_resolve import resolve_workspace
from soma_sdk.cells import parse_cell_file

def main():
    parser = argparse.ArgumentParser(description='Governance replay: test cells against historical commits')
    parser.add_argument('--commits', type=int, default=20, help='Number of recent commits to replay (default: 20)')
    parser.add_argument('--counterfactual', action='store_true', help='Counterfactual analysis mode')
    parser.add_argument('--cell', help='Specific cell name for counterfactual analysis')
    parser.add_argument('--since', help='Start date for counterfactual (YYYY-MM-DD)')
    parser.add_argument('--json', action='store_true', help='JSON output')
    args = parser.parse_args()
    
    workspace = resolve_workspace(__file__)
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    
    # Load all cells
    cells = []
    for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
        if os.path.basename(cell_file) == 'README.md': continue
        try:
            fm, _body = parse_cell_file(cell_file)
            cells.append({
                'name': os.path.splitext(os.path.basename(cell_file))[0],
                'type': fm.get('type', ''),
                'target_paths': fm.get('target_paths', []),
                'hypothesis': fm.get('hypothesis', ''),
                'minimum_mode': fm.get('minimum_mode', 'breeze'),
                'fitness': fm.get('fitness', {})
            })
        except Exception: pass
    
    if args.counterfactual:
        if not args.cell:
            print('Error: --counterfactual requires --cell <cell-name>')
            sys.exit(1)
        
        # Find the specific cell
        target_cell = None
        for cell in cells:
            if cell['name'] == args.cell:
                target_cell = cell
                break
        
        if not target_cell:
            print(f'Error: Cell "{args.cell}" not found')
            sys.exit(1)
        
        # Get commits since date
        git_args = ['git', 'log', '--format=%H %s']
        if args.since:
            git_args.append(f'--since={args.since}')
        else:
            git_args.append(f'--max-count={args.commits}')
        
        result = subprocess.run(git_args, capture_output=True, text=True, cwd=workspace)
        commits = []
        for line in result.stdout.strip().split('\n'):
            if not line: continue
            sha, *msg = line.split(' ')
            commits.append({'sha': sha, 'message': ' '.join(msg)})
        
        # Replay cell against each commit
        trigger_count = 0
        for commit in commits:
            diff_result = subprocess.run(
                ['git', 'diff', '--name-only', f'{commit["sha"]}~1', commit['sha']],
                capture_output=True, text=True, cwd=workspace
            )
            changed_files = set(diff_result.stdout.strip().split('\n')) - {''}
            for pattern in target_cell['target_paths']:
                if any(fnmatch(f, pattern) for f in changed_files):
                    trigger_count += 1
                    break
        
        # Estimate ROI
        tp_rate = 0.78  # default estimate, or use cell's actual TP rate
        fitness = target_cell.get('fitness') or {}
        if fitness:
            tp = fitness.get('true_positives', 0)
            fp = fitness.get('false_positives', 0)
            if tp + fp > 0:
                tp_rate = tp / (tp + fp)
        
        est_tp = int(trigger_count * tp_rate)
        avg_rework_hours = 3.0
        hourly_rate = 150.0
        est_hours_saved = est_tp * avg_rework_hours
        est_dollars_saved = est_hours_saved * hourly_rate
        
        period = f'since {args.since}' if args.since else f'last {len(commits)} commits'
        
        if args.json:
            print(json.dumps({
                'cell': args.cell,
                'period': period,
                'commits_analyzed': len(commits),
                'would_have_triggered': trigger_count,
                'estimated_true_positives': est_tp,
                'tp_rate': round(tp_rate, 2),
                'estimated_bugs_prevented': est_tp,
                'estimated_hours_saved': est_hours_saved,
                'estimated_dollars_saved': est_dollars_saved
            }, indent=2))
        else:
            print(f'\n\U0001f52e Counterfactual Analysis: {args.cell}')
            print(f'Period: {period} ({len(commits)} commits)\n')
            print(f'Would have triggered: {trigger_count} times')
            print(f'Estimated true positives: {est_tp} (based on {tp_rate:.0%} TP rate)')
            print(f'Estimated bugs prevented: {est_tp}')
            print(f'Estimated rework saved: ~{est_hours_saved:.0f} developer-hours ({avg_rework_hours:.0f}h avg rework per bug)')
            print(f'\nROI: This cell would have saved ~${est_dollars_saved:,.0f} in developer time.')
        return
    
    # Get recent commits
    result = subprocess.run(
        ['git', 'log', f'--max-count={args.commits}', '--format=%H %s'],
        capture_output=True, text=True, cwd=workspace
    )
    commits = []
    for line in result.stdout.strip().split('\n'):
        if not line: continue
        sha, *msg = line.split(' ')
        commits.append({'sha': sha, 'message': ' '.join(msg)})
    
    replay_results = []
    for commit in commits:
        # Get files changed in this commit
        diff_result = subprocess.run(
            ['git', 'diff', '--name-only', f'{commit["sha"]}~1', commit['sha']],
            capture_output=True, text=True, cwd=workspace
        )
        changed_files = set(diff_result.stdout.strip().split('\n')) - {''}
        
        # Check which cells would have triggered
        would_trigger = []
        for cell in cells:
            for pattern in cell['target_paths']:
                if any(fnmatch(f, pattern) for f in changed_files):
                    would_trigger.append(cell['name'])
                    break
        
        replay_results.append({
            'sha': commit['sha'][:8],
            'message': commit['message'][:60],
            'files_changed': len(changed_files),
            'cells_would_trigger': len(would_trigger),
            'triggered': would_trigger
        })
    
    if args.json:
        print(json.dumps(replay_results, indent=2))
    else:
        print(f'\n🔄 Governance Replay: {len(commits)} commits × {len(cells)} cells\n')
        total_triggers = sum(r['cells_would_trigger'] for r in replay_results)
        covered = sum(1 for r in replay_results if r['cells_would_trigger'] > 0)
        print(f'Commits with coverage: {covered}/{len(replay_results)} ({covered/len(replay_results)*100:.0f}%)')
        print(f'Total retroactive triggers: {total_triggers}\n')
        for r in replay_results:
            indicator = '✅' if r['cells_would_trigger'] > 0 else '🔴'
            print(f'{indicator} {r["sha"]} ({r["files_changed"]} files, {r["cells_would_trigger"]} cells) {r["message"]}')
            if r['triggered']:
                print(f'   Cells: {", ".join(r["triggered"])}')

if __name__ == '__main__':
    # Output uses non-ASCII symbols; on a cp1252 stdout printing them
    # raised UnicodeEncodeError and the script exited 1 (BUG-038).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    main()
