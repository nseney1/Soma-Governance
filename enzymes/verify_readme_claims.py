#!/usr/bin/env python3
"""CI gate: verify all README claims have passing behavioral tests.

This script enforces the documentation gating mandate:
- 'unlocked' claims: all required tests must pass
- 'removed' claims: their text must NOT appear in README
- 'locked' claims: their text must NOT appear in README

Exit 0 if all claims verified. Exit 1 if any regression or overclaim found.
"""
import json
import subprocess
import sys
import os


def main():
    # Find project root (where README.md lives)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    
    registry_path = os.path.join(project_root, 'docs', 'project', 'CLAIM_REGISTRY.json')
    readme_path = os.path.join(project_root, 'README.md')
    
    if not os.path.exists(registry_path):
        print(f'ERROR: Claim registry not found: {registry_path}')
        sys.exit(1)
    
    with open(registry_path, encoding='utf-8') as f:
        registry = json.load(f)
    
    with open(readme_path, encoding='utf-8') as f:
        readme = f.read()
    
    failures = []
    stats = {'unlocked': 0, 'locked': 0, 'removed': 0, 'total': 0}
    
    for claim_id, claim in registry['claims'].items():
        stats['total'] += 1
        status = claim['status']
        stats[status] = stats.get(status, 0) + 1
        
        if status == 'unlocked':
            # Verify all required tests pass
            for test in claim['required_tests']:
                result = subprocess.run(
                    [sys.executable, '-m', 'pytest', test, '-x', '-q', '--tb=short'],
                    capture_output=True, text=True,
                    cwd=project_root
                )
                if result.returncode != 0:
                    failures.append(
                        f'REGRESSION: {claim_id} — test {test} FAILED\n'
                        f'  stdout: {result.stdout.strip()[:200]}'
                    )
        
        elif status == 'removed':
            # Verify claim text is NOT in README
            if claim['readme_text'] in readme:
                failures.append(
                    f'OVERCLAIM: {claim_id} — removed text '
                    f'\'{claim["readme_text"]}\' still found in README'
                )
        
        elif status == 'locked':
            # Verify locked claim text is NOT in README
            if claim['readme_text'] in readme:
                failures.append(
                    f'PREMATURE: {claim_id} — locked text '
                    f'\'{claim["readme_text"]}\' found in README before tests pass'
                )
    
    if failures:
        print(f'\n=== CLAIM VERIFICATION FAILED ({len(failures)} issues) ===\n')
        for f in failures:
            print(f'  ✗ {f}')
        print()
        sys.exit(1)
    
    print(f'=== All {stats["total"]} claims verified ===')
    print(f'  Unlocked: {stats["unlocked"]} | Locked: {stats["locked"]} | Removed: {stats["removed"]}')


if __name__ == '__main__':
    # Output uses non-ASCII symbols; on a cp1252 stdout printing them
    # raised UnicodeEncodeError and the script exited 1 (BUG-038).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    main()
