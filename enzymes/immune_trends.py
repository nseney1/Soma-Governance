#!/usr/bin/env python3
import os, sys, argparse, glob, json
from datetime import datetime, timedelta
from soma_resolve import resolve_workspace

def main():
    parser = argparse.ArgumentParser(description='Cross-session governance trends dashboard')
    parser.add_argument('--days', type=int, default=30, help='Number of days to analyze (default: 30)')
    parser.add_argument('--json', action='store_true', help='JSON output')
    args = parser.parse_args()
    
    workspace = resolve_workspace(__file__)
    metrics_dir = os.path.join(workspace, '.soma', 'metrics')
    
    if not os.path.isdir(metrics_dir):
        print('No metrics directory found.')
        return
    
    # Collect all metric events
    events = {'fitness': [], 'decay': [], 'quorum': [], 'signals': []}
    
    for jsonl_file in glob.glob(os.path.join(metrics_dir, '*.jsonl')):
        basename = os.path.basename(jsonl_file)
        try:
            with open(jsonl_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    try:
                        data = json.loads(line)
                        data['_source'] = basename
                        if 'decay' in basename:
                            events['decay'].append(data)
                        elif 'quorum' in basename:
                            events['quorum'].append(data)
                        else:
                            events['signals'].append(data)
                    except Exception: pass
        except Exception: pass
    
    # Count cells
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    total_cells = 0
    cell_types = {}
    if os.path.isdir(cells_dir):
        try:
            import yaml
        except ImportError:
            yaml = None
        for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
            if os.path.basename(cell_file) == 'README.md': continue
            total_cells += 1
            try:
                with open(cell_file, encoding="utf-8") as f: content = f.read()
                if content.startswith('---'):
                    fm = yaml.safe_load(content[3:content.find('---', 3)])
                    ct = fm.get('type', 'unknown')
                    cell_types[ct] = cell_types.get(ct, 0) + 1
            except Exception: pass
    
    if args.json:
        print(json.dumps({
            'total_cells': total_cells,
            'cell_types': cell_types,
            'decay_events': len(events['decay']),
            'quorum_events': len(events['quorum']),
            'signal_events': len(events['signals'])
        }, indent=2))
    else:
        print(f'\n📈 Governance Trends ({args.days}-Day Window)\n')
        print(f'Cell Population: {total_cells}')
        for ct, count in sorted(cell_types.items()):
            print(f'  {ct}: {count}')
        print(f'\nEvents:')
        print(f'  Decay transitions: {len(events["decay"])}')
        print(f'  Quorum events:     {len(events["quorum"])}')
        print(f'  Signal events:     {len(events["signals"])}')
        
        # Shannon diversity
        if cell_types:
            import math
            total = sum(cell_types.values())
            entropy = -sum((c/total) * math.log(c/total) for c in cell_types.values() if c > 0)
            max_entropy = math.log(len(cell_types)) if len(cell_types) > 1 else 1
            evenness = entropy / max_entropy if max_entropy > 0 else 0
            print(f'\nDiversity:')
            print(f'  Shannon entropy: {entropy:.3f}')
            print(f'  Evenness index:  {evenness:.3f} ({"healthy" if evenness > 0.6 else "monoculture risk"})')

if __name__ == '__main__':
    main()
