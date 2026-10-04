#!/usr/bin/env python3
"""Adversarial cell testing: probe cells for bypass vulnerabilities."""
import os, sys, argparse, glob, json, subprocess
from soma_sdk.cells import parse_cell_file
from fnmatch import fnmatch
from soma_resolve import resolve_workspace


def load_cell(cells_dir, cell_name):
    """Load a specific cell by name."""
    for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
        if os.path.basename(cell_file) == 'README.md': continue
        if os.path.splitext(os.path.basename(cell_file))[0] == cell_name:
            try:
                fm, body = parse_cell_file(cell_file)
            except Exception:
                continue
            fm['_name'] = cell_name
            fm['_path'] = cell_file
            fm['_body'] = body.strip()
            return fm
    return None


def test_rename_bypass(cell, workspace):
    """Can the cell be bypassed by renaming a file?"""
    target_paths = cell.get('target_paths', [])
    if not target_paths:
        return {'test': 'Rename bypass', 'result': 'SKIP', 'detail': 'No target_paths defined'}
    
    # Check if patterns are specific files vs globs
    specific = [p for p in target_paths if '*' not in p and '?' not in p]
    glob_patterns = [p for p in target_paths if '*' in p or '?' in p]
    
    if specific and not glob_patterns:
        return {'test': 'Rename bypass', 'result': 'VULNERABLE',
                'detail': f'Only specific files targeted ({len(specific)}). Renamed copies would be ungoverned.'}
    elif glob_patterns:
        return {'test': 'Rename bypass', 'result': 'PROTECTED',
                'detail': f'Glob patterns ({len(glob_patterns)}) catch renamed files.'}
    return {'test': 'Rename bypass', 'result': 'SKIP', 'detail': 'No paths to test'}


def test_indirect_import(cell, workspace):
    """Can the cell be bypassed by importing the protected code indirectly?"""
    target_paths = cell.get('target_paths', [])
    if not target_paths:
        return {'test': 'Indirect import bypass', 'result': 'SKIP', 'detail': 'No target_paths'}
    
    # Check if any target file is imported by non-targeted files
    result = subprocess.run(['git', 'ls-files', '*.py'], capture_output=True, text=True, cwd=workspace)
    all_py = [f for f in result.stdout.strip().split('\n') if f]
    
    targeted = set()
    for f in all_py:
        for p in target_paths:
            if fnmatch(f, p):
                targeted.add(f)
    
    # Check for imports of targeted files from non-targeted files
    importers = 0
    for f in all_py:
        if f in targeted: continue
        try:
            full_path = os.path.join(workspace, f)
            with open(full_path, encoding="utf-8") as fh:
                content = fh.read()
            for t in targeted:
                module = os.path.splitext(t)[0].replace('/', '.').replace('\\', '.')
                basename = os.path.splitext(os.path.basename(t))[0]
                if f'import {basename}' in content or f'from {module}' in content:
                    importers += 1
                    break
        except Exception: pass
    
    if importers > 0:
        return {'test': 'Indirect import bypass', 'result': 'VULNERABLE',
                'detail': f'{importers} non-targeted file(s) import targeted code. Changes there won\'t trigger this cell.'}
    return {'test': 'Indirect import bypass', 'result': 'PROTECTED',
            'detail': 'No non-targeted files import targeted code.'}


def test_config_bypass(cell, workspace):
    """Can behavior be changed via config files not covered by target_paths?"""
    target_paths = cell.get('target_paths', [])
    config_patterns = ['*.yaml', '*.yml', '*.json', '*.toml', '*.cfg', '*.conf', '*.ini', '*.env']
    
    covers_config = any(
        any(fnmatch(cp, tp) for tp in target_paths)
        for cp in config_patterns
    )
    
    if not covers_config:
        # Check if config files exist in same dirs as targeted files
        target_dirs = set(os.path.dirname(p) for p in target_paths)
        result = subprocess.run(['git', 'ls-files'], capture_output=True, text=True, cwd=workspace)
        config_in_target_dirs = []
        for f in result.stdout.strip().split('\n'):
            if not f: continue
            fdir = os.path.dirname(f)
            fext = os.path.splitext(f)[1]
            if fdir in target_dirs and fext in ['.yaml', '.yml', '.json', '.toml', '.cfg', '.conf']:
                config_in_target_dirs.append(f)
        
        if config_in_target_dirs:
            return {'test': 'Config file bypass', 'result': 'VULNERABLE',
                    'detail': f'{len(config_in_target_dirs)} config file(s) in targeted directories not covered: {", ".join(config_in_target_dirs[:3])}'}
    
    return {'test': 'Config file bypass', 'result': 'PROTECTED',
            'detail': 'Config files are covered or not present in targeted directories.'}


def test_test_bypass(cell, workspace):
    """Can tests be modified to hide regressions?"""
    target_paths = cell.get('target_paths', [])
    covers_tests = any('test' in p.lower() for p in target_paths)
    
    if not covers_tests:
        return {'test': 'Test modification bypass', 'result': 'WARNING',
                'detail': 'Cell does not monitor test files. Test changes could mask regressions.'}
    return {'test': 'Test modification bypass', 'result': 'PROTECTED',
            'detail': 'Test files are covered by target_paths.'}


def test_hypothesis_staleness(cell, workspace):
    """Is the hypothesis still relevant to the codebase?"""
    hypothesis = cell.get('hypothesis', '')
    target_paths = cell.get('target_paths', [])
    
    # Check if targeted files exist
    missing = []
    for p in target_paths:
        if '*' in p or '?' in p:
            matches = glob.glob(os.path.join(workspace, p), recursive=True)
            if not matches:
                missing.append(p)
        else:
            if not os.path.exists(os.path.join(workspace, p)):
                missing.append(p)
    
    if missing:
        return {'test': 'Hypothesis staleness', 'result': 'STALE',
                'detail': f'{len(missing)} target path(s) no longer exist: {", ".join(missing[:3])}'}
    return {'test': 'Hypothesis staleness', 'result': 'CURRENT',
            'detail': 'All target paths exist in the codebase.'}


def main():
    parser = argparse.ArgumentParser(description='Adversarial cell testing: probe for bypass vulnerabilities')
    parser.add_argument('cell_name', nargs='?', help='Name of the cell to test (omit for all cells)')
    parser.add_argument('--json', action='store_true', help='JSON output')
    args = parser.parse_args()
    
    workspace = resolve_workspace(__file__)
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    
    if args.cell_name:
        cell = load_cell(cells_dir, args.cell_name)
        if not cell:
            print(f'Error: Cell "{args.cell_name}" not found')
            sys.exit(1)
        cells_to_test = [cell]
    else:
        # Test all cells
        cells_to_test = []
        for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
            if os.path.basename(cell_file) == 'README.md': continue
            try:
                fm, _body = parse_cell_file(cell_file)
                fm['_name'] = os.path.splitext(os.path.basename(cell_file))[0]
                cells_to_test.append(fm)
            except Exception: pass
    
    all_results = []
    tests = [test_rename_bypass, test_indirect_import, test_config_bypass, test_test_bypass, test_hypothesis_staleness]
    
    for cell in cells_to_test:
        cell_results = {'cell': cell['_name'], 'type': cell.get('type', ''), 'tests': []}
        for test_fn in tests:
            result = test_fn(cell, workspace)
            cell_results['tests'].append(result)
        
        vulns = sum(1 for t in cell_results['tests'] if t['result'] in ('VULNERABLE', 'STALE'))
        warnings = sum(1 for t in cell_results['tests'] if t['result'] == 'WARNING')
        protected = sum(1 for t in cell_results['tests'] if t['result'] == 'PROTECTED')
        total = len([t for t in cell_results['tests'] if t['result'] != 'SKIP'])
        
        cell_results['score'] = f'{protected}/{total} protected'
        cell_results['vulnerabilities'] = vulns
        cell_results['warnings'] = warnings
        all_results.append(cell_results)
    
    if args.json:
        print(json.dumps(all_results, indent=2))
    else:
        for cr in all_results:
            print(f'\n\U0001f6e1\ufe0f  Testing: {cr["cell"]} ({cr["type"]})')
            print(f'   Score: {cr["score"]}\n')
            for t in cr['tests']:
                icons = {'PROTECTED': '\u2705', 'VULNERABLE': '\u274c', 'WARNING': '\u26a0\ufe0f', 'SKIP': '\u23ed\ufe0f', 'STALE': '\U0001f4a4', 'CURRENT': '\u2705'}
                icon = icons.get(t['result'], '\u2753')
                print(f'   {icon} {t["test"]}: {t["result"]}')
                print(f'      {t["detail"]}')
        
        # Summary
        total_vulns = sum(r['vulnerabilities'] for r in all_results)
        total_warnings = sum(r['warnings'] for r in all_results)
        print(f'\n{"=" * 50}')
        print(f'Summary: {len(all_results)} cells tested, {total_vulns} vulnerabilities, {total_warnings} warnings')
        if total_vulns > 0:
            print('Recommendations:')
            for cr in all_results:
                for t in cr['tests']:
                    if t['result'] == 'VULNERABLE':
                        print(f'  - {cr["cell"]}: {t["detail"]}')

if __name__ == '__main__':
    # A cp1252 stdout can't encode this script's symbols (BUG-038).
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    main()
