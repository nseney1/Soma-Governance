#!/usr/bin/env python3
import os, sys, argparse, random, glob, json
from datetime import datetime
from datetime import timezone

from soma_resolve import resolve_workspace

def main():
    parser = argparse.ArgumentParser(description='Stochastic cell genesis: inject random diversity')
    parser.add_argument('--force', action='store_true', help='Force genesis regardless of interval')
    args = parser.parse_args()
    
    workspace = resolve_workspace(__file__)
    
    # Check interval
    metrics_dir = os.path.join(workspace, '.soma', 'metrics')
    counter_file = os.path.join(metrics_dir, 'session_counter.json')
    
    os.makedirs(metrics_dir, exist_ok=True)
    
    counter = {'sessions': 0, 'last_stochastic': 0}
    if os.path.exists(counter_file):
        try:
            with open(counter_file, encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    counter.update(loaded)
        except Exception:
            pass
    
    counter['sessions'] += 1
    
    # Read interval from soma.conf or env
    interval = int(os.environ.get('STOCHASTIC_GENESIS_INTERVAL', '10'))
    
    sessions_since = counter['sessions'] - counter['last_stochastic']
    
    if not args.force and sessions_since < interval:
        with open(counter_file, 'w', encoding="utf-8") as f:
            json.dump(counter, f)
        return
    
    # Find available templates
    templates_dir = os.path.join(workspace, 'templates')
    template_files = []
    if os.path.isdir(templates_dir):
        for root, _, files in os.walk(templates_dir):
            for fname in files:
                if fname.endswith('.md') and fname != 'README.md':
                    template_files.append(os.path.join(root, fname))
    
    if not template_files:
        print('No templates available for stochastic genesis.')
        return
    
    # Pick a random template
    template = random.choice(template_files)
    template_name = os.path.splitext(os.path.basename(template))[0]
    
    # Check if a cell with this name already exists
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    existing = glob.glob(os.path.join(cells_dir, '**', f'{template_name}*.md'), recursive=True)
    if existing:
        # Slightly mutate the name
        template_name = f'{template_name}-gen{counter["sessions"]}'
    
    print(f'🌋 STOCHASTIC GENESIS: Injecting random cell from template')
    print(f'   Template: {os.path.relpath(template, workspace)}')
    print(f'   Sessions since last: {sessions_since}')
    
    # Log the event
    with open(os.path.join(metrics_dir, 'stochastic_genesis.jsonl'), 'a', encoding="utf-8") as f:
        f.write(json.dumps({
            'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
            'template': os.path.relpath(template, workspace),
            'session': counter['sessions']
        }) + '\n')
    
    counter['last_stochastic'] = counter['sessions']
    with open(counter_file, 'w', encoding="utf-8") as f:
        json.dump(counter, f)

if __name__ == '__main__':
    # Output uses non-ASCII symbols; on a cp1252 stdout printing them
    # raised UnicodeEncodeError and the script exited 1 (BUG-038).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    main()
