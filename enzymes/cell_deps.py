#!/usr/bin/env python3
import os, sys, argparse, glob
from fnmatch import fnmatch
from soma_resolve import resolve_workspace
from soma_sdk.cells import parse_cell_file

def main():
    parser = argparse.ArgumentParser(description='Cell dependency graph: visualize co-trigger relationships')
    parser.add_argument('--format', choices=['text', 'mermaid'], default='text', help='Output format')
    parser.add_argument('--json', action='store_true', help='JSON output')
    parser.add_argument('--workspace', type=str, default=None, help='Override workspace root')
    args = parser.parse_args()
    
    workspace = args.workspace if args.workspace else resolve_workspace(__file__)
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    
    # Load all cells with target_paths
    cells = []
    for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
        if os.path.basename(cell_file) == 'README.md': continue
        try:
            fm, _body = parse_cell_file(cell_file)
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
    # A cp1252 stdout can't encode this script's symbols (BUG-038).
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    main()
