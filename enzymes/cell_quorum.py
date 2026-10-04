#!/usr/bin/env python3
import os, sys, argparse, glob, json
from soma_sdk.cells import parse_cell_file
from fnmatch import fnmatch
from datetime import datetime
from datetime import timezone

try:
    from soma_resolve import resolve_workspace
except ImportError:
    resolve_workspace = None


_MODES = {'breeze': 0, 'gale': 1, 'trident': 2, 'maelstrom': 3, 'tempest': 4}


def evaluate_quorum(cells_dir, changed_files, threshold=3):
    """Core quorum evaluation — pure function, no CLI or git dependency.

    Args:
        cells_dir: Path to .soma/cells/ directory.
        changed_files: List of changed file paths (relative to workspace).
        threshold: Minimum cells for quorum (default: 3).

    Returns:
        dict with keys: quorum (bool), cells_triggered (int),
        and when quorum is True: cell_types, escalate_to, triggered_cells.
    """
    if not changed_files:
        return {'quorum': False, 'cells_triggered': 0}

    triggered = []
    for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
        if os.path.basename(cell_file) == 'README.md':
            continue
        try:
            fm, _body = parse_cell_file(cell_file)
            target_paths = fm.get('target_paths', [])
            if isinstance(target_paths, str):
                target_paths = [target_paths]
            hypothesis = fm.get('hypothesis', '')

            matched = False
            for tp in target_paths:
                for cf in changed_files:
                    if fnmatch(cf, tp):
                        matched = True
                        break
                if matched:
                    break

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
        except Exception:
            pass

    if len(triggered) >= threshold:
        max_mode = max(triggered, key=lambda t: _MODES.get(t.get('minimum_mode', 'breeze'), 0))['minimum_mode']
        return {
            'quorum': True,
            'cells_triggered': len(triggered),
            'cell_types': list({t['type'] for t in triggered}),
            'escalate_to': max_mode,
            'triggered_cells': triggered,
        }
    else:
        return {
            'quorum': False,
            'cells_triggered': len(triggered),
        }


def main():
    parser = argparse.ArgumentParser(description='Quorum sensing: detect systemic issues from multi-cell triggers')
    parser.add_argument('--threshold', type=int, default=3, help='Minimum cells for quorum (default: 3)')
    parser.add_argument('--json', action='store_true', help='JSON output')
    args = parser.parse_args()

    if resolve_workspace is None:
        print('ERROR: soma_resolve not available', file=sys.stderr)
        sys.exit(1)

    workspace = resolve_workspace(__file__)
    cells_dir = os.path.join(workspace, '.soma', 'cells')

    # Get changed files from git
    import subprocess
    result = subprocess.run(['git', 'diff', '--name-only', 'HEAD'], capture_output=True, text=True, cwd=workspace)
    staged = subprocess.run(['git', 'diff', '--name-only', '--cached'], capture_output=True, text=True, cwd=workspace)
    changed_files = list(set((result.stdout + staged.stdout).strip().split('\n')) - {''})

    if not changed_files:
        print('No changes detected.')
        return

    quorum = evaluate_quorum(cells_dir, changed_files, threshold=args.threshold)

    if quorum['quorum']:
        if args.json:
            print(json.dumps(quorum, indent=2))
        else:
            print(f'🔬 QUORUM: {quorum["cells_triggered"]} cells triggered simultaneously!')
            print(f'   Cell types: {", ".join(quorum["cell_types"])}')
            print(f'   Escalating to: {quorum["escalate_to"]}')
            for t in quorum['triggered_cells']:
                print(f'   - {t["name"]} ({t["type"]}): {t["hypothesis"]}')

        # Log quorum event
        metrics_dir = os.path.join(workspace, '.soma', 'metrics')
        os.makedirs(metrics_dir, exist_ok=True)
        with open(os.path.join(metrics_dir, 'quorum_events.jsonl'), 'a', encoding='utf-8') as f:
            quorum['timestamp'] = datetime.now(timezone.utc).isoformat() + 'Z'
            f.write(json.dumps(quorum) + '\n')
    else:
        if args.json:
            print(json.dumps(quorum))
        else:
            print(f'No quorum ({quorum["cells_triggered"]}/{args.threshold} cells triggered)')


if __name__ == '__main__':
    # A cp1252 stdout can't encode this script's symbols (BUG-038).
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    main()

