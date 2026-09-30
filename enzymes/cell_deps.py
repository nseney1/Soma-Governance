#!/usr/bin/env python3
import os, sys, argparse, glob
try:
    import yaml
except ImportError:
    yaml = None
from fnmatch import fnmatch
from soma_resolve import resolve_workspace

def main():
    parser = argparse.ArgumentParser(description='Cell dependency graph: visualize co-trigger relationships')
    parser.add_argument('--format', choices=['text', 'mermaid'], default='text', help='Output format')
    parser.add_argument('--json', action='store_true', help='JSON output')
    args = parser.parse_args()
    
    workspace = resolve_workspace(__file__)
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    
    # Load all cells with target_paths
    cells = []
    for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
        if os.path.basename(cell_file) == 'README.md': continue
        try:
            with open(cell_file, encoding="utf-8") as f: content = f.read()
            if not content.startswith('---'): continue
            fm = yaml.safe_load(content[3:content.find('---', 3)])
            cells.append({
                'name': os.path.splitext(os.path.basename(cell_file))[0],
                'type': fm.get('type', ''),
                'target_paths': fm.get('target_paths', []),
            })
        except Exception: pass
    
    # Find overlapping target_paths between cell pairs
    import json
    edges = []
    for i, a in enumerate(cells):
        for j, b in enumerate(cells):
            if i >= j: continue
            shared = set(a['target_paths']) & set(b['target_paths'])
            if shared:
                edges.append({'from': a['name'], 'to': b['name'], 'shared_paths': list(shared)})
    
    if args.json:
        print(json.dumps({'cells': len(cells), 'edges': edges}, indent=2))
    elif args.format == 'mermaid':
        print('graph LR')
        for e in edges:
            label = e['shared_paths'][0] if len(e['shared_paths']) == 1 else f"{len(e['shared_paths'])} paths"
            print(f'    {e["from"]} -->|"{label}"| {e["to"]}')
        if not edges:
            print('    no_dependencies["No shared target_paths found"]')
    else:
        print(f'\n🔗 Cell Dependency Graph ({len(cells)} cells, {len(edges)} connections)\n')
        if not edges:
            print('No co-trigger relationships found.')
        for e in edges:
            print(f'  {e["from"]} <-> {e["to"]}')
            for p in e['shared_paths']:
                print(f'    via: {p}')

if __name__ == '__main__':
    main()
