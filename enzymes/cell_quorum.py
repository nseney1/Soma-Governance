#!/usr/bin/env python3
import os, sys, argparse, glob, json
try:
    import yaml
except ImportError:
    yaml = None
from fnmatch import fnmatch
from datetime import datetime
from datetime import timezone
from soma_resolve import resolve_workspace

def main():
    parser = argparse.ArgumentParser(description='Quorum sensing: detect systemic issues from multi-cell triggers')
    parser.add_argument('--threshold', type=int, default=3, help='Minimum cells for quorum (default: 3)')
    parser.add_argument('--json', action='store_true', help='JSON output')
    args = parser.parse_args()
    
    workspace = resolve_workspace(__file__)
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    
    # Get changed files from git
    import subprocess
    result = subprocess.run(['git', 'diff', '--name-only', 'HEAD'], capture_output=True, text=True, cwd=workspace)
    staged = subprocess.run(['git', 'diff', '--name-only', '--cached'], capture_output=True, text=True, cwd=workspace)
    changed_files = set((result.stdout + staged.stdout).strip().split('\n')) - {''}
    
    if not changed_files:
        print('No changes detected.')
        return
    
    # Load cells with target_paths
    triggered = []
    for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
        if os.path.basename(cell_file) == 'README.md': continue
        try:
            with open(cell_file, encoding="utf-8") as f: content = f.read()
            if not content.startswith('---'): continue
            fm = yaml.safe_load(content[3:content.find('---', 3)])
            target_paths = fm.get('target_paths', [])
            hypothesis = fm.get('hypothesis', '')
            
            # Check target_paths match
            matched = False
            for tp in target_paths:
                for cf in changed_files:
                    if fnmatch(cf, tp):
                        matched = True
                        break
            
            # Check hypothesis keyword match
            if not matched:
                for cf in changed_files:
                    basename = os.path.basename(cf)
                    if basename in hypothesis:
                        matched = True
                        break
            
            if matched:
                triggered.append({
                    'name': os.path.splitext(os.path.basename(cell_file))[0],
                    'type': fm.get('type', 'unknown'),
                    'minimum_mode': fm.get('minimum_mode', 'breeze'),
                    'fitness': (fm.get('fitness') or {}).get('score'),
                    'hypothesis': hypothesis[:80]
                })
        except Exception: pass
    
    if len(triggered) >= args.threshold:
        modes = {'breeze': 0, 'gale': 1, 'trident': 2, 'maelstrom': 3, 'tempest': 4}
        max_mode = max(triggered, key=lambda t: modes.get(t.get('minimum_mode', 'breeze'), 0))['minimum_mode']
        quorum = {
            'quorum': True,
            'cells_triggered': len(triggered),
            'cell_types': list({t['type'] for t in triggered}),
            'escalate_to': max_mode,
            'changed_files': list(changed_files),
            'triggered_cells': triggered
        }
        if args.json:
            print(json.dumps(quorum, indent=2))
        else:
            print(f'🔬 QUORUM: {len(triggered)} cells triggered simultaneously!')
            print(f'   Cell types: {", ".join(quorum["cell_types"])}')
            print(f'   Escalating to: {max_mode}')
            for t in triggered:
                print(f'   - {t["name"]} ({t["type"]}): {t["hypothesis"]}')
        
        # Log quorum event
        metrics_dir = os.path.join(workspace, '.soma', 'metrics')
        os.makedirs(metrics_dir, exist_ok=True)
        with open(os.path.join(metrics_dir, 'quorum_events.jsonl'), 'a', encoding="utf-8") as f:
            quorum['timestamp'] = datetime.now(timezone.utc).isoformat() + 'Z'
            f.write(json.dumps(quorum) + '\n')
    else:
        if args.json:
            print(json.dumps({'quorum': False, 'cells_triggered': len(triggered)}))
        else:
            print(f'No quorum ({len(triggered)}/{args.threshold} cells triggered)')

if __name__ == '__main__':
    main()
