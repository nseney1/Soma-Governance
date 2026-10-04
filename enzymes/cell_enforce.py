#!/usr/bin/env python3
"""Auto-generate enforcement artifacts for promoted cells.

When a cell reaches 'mechanical' tier, generates pre-commit hook checks.
When a cell reaches 'gate' tier, generates runtime assertions.

Usage:
    python cell_enforce.py                    # Generate all pending artifacts
    python cell_enforce.py --cell <name>      # Generate for specific cell
    python cell_enforce.py --dry-run          # Preview without writing
    python cell_enforce.py --list             # List all enforcement artifacts
"""
import os, sys, argparse, glob, json, re, shlex
from datetime import datetime
from datetime import timezone
from pathlib import Path
from soma_resolve import resolve_workspace

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
from soma_sdk.cells import parse_cell_file


def load_cells(cells_dir):
    cells = []
    for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
        if os.path.basename(cell_file) == 'README.md': continue
        try:
            fm, body = parse_cell_file(cell_file)
            fm['_path'] = cell_file
            fm['_name'] = os.path.splitext(os.path.basename(cell_file))[0]
            fm['_body'] = body.strip()
            cells.append(fm)
        except Exception: pass
    return cells


def generate_precommit_check(cell, workspace):
    """Generate a pre-commit check script for a 'mechanical' cell."""
    name = cell['_name']
    cell_type = cell.get('type', 'vacuole')
    hypothesis = cell.get('hypothesis', '')
    target_paths = cell.get('target_paths', [])
    
    quoted_name = shlex.quote(name)
    quoted_hyp = shlex.quote(hypothesis[:80])
    quoted_patterns = ' '.join(shlex.quote(p) for p in target_paths)
    
    # Generate different checks based on cell type
    if cell_type == 'wall':
        # Walls generate strict pattern checks
        check = f'''#!/bin/bash
# Auto-generated enforcement artifact for: {name}
# Type: {cell_type} | Tier: mechanical
# Hypothesis: {hypothesis}
# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
#
# This check runs as part of the pre-commit hook.
# To disable: remove this file or demote the cell to advisory.

set -uo pipefail

CHANGED_FILES=$(git diff --cached --name-only 2>/dev/null)
if [ -z "$CHANGED_FILES" ]; then exit 0; fi

TARGET_PATTERNS=({quoted_patterns})
MATCHED=0

while IFS= read -r file; do
    for pattern in "${{TARGET_PATTERNS[@]}}"; do
        case "$file" in
            $pattern) MATCHED=1; break 2 ;;
        esac
    done
done <<< "$CHANGED_FILES"

if [ "$MATCHED" -eq 1 ]; then
    echo -n "🛡️  ["
    echo -n {quoted_name}
    echo "] Cell triggered (mechanical enforcement)"
    echo -n "   Hypothesis: "
    echo {quoted_hyp}
    echo "   Files: $CHANGED_FILES"
    # Signal the cell
    SCRIPT_DIR="$(dirname "$0")/../../scripts"
    [ -f "$SCRIPT_DIR/cell_signal.sh" ] && bash "$SCRIPT_DIR/cell_signal.sh" {quoted_name} tp 2>/dev/null
    exit 1  # Mechanical: block commit
fi

exit 0  # No match: allow commit
'''
    elif cell_type == 'membrane':
        check = f'''#!/bin/bash
# Auto-generated enforcement artifact for: {name}
# Type: {cell_type} | Tier: mechanical
# Hypothesis: {hypothesis}
# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}

set -uo pipefail

CHANGED_FILES=$(git diff --cached --name-only 2>/dev/null)
if [ -z "$CHANGED_FILES" ]; then exit 0; fi

TARGET_PATTERNS=({quoted_patterns})
MATCHED=0

while IFS= read -r file; do
    for pattern in "${{TARGET_PATTERNS[@]}}"; do
        case "$file" in
            $pattern) MATCHED=1; break 2 ;;
        esac
    done
done <<< "$CHANGED_FILES"

if [ "$MATCHED" -eq 1 ]; then
    echo -n "⚠️  ["
    echo -n {quoted_name}
    echo "] Membrane escalation triggered (mechanical enforcement)"
    echo -n "   Hypothesis: "
    echo {quoted_hyp}
    echo "   Recommend elevated review before merging."
    exit 1  # Mechanical: block commit
fi

exit 0  # No match: allow commit
'''
    else:  # vacuole, chloroplast, etc.
        check = f'''#!/bin/bash
# Auto-generated enforcement artifact for: {name}
# Type: {cell_type} | Tier: mechanical
# Hypothesis: {hypothesis}
# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}

set -uo pipefail

CHANGED_FILES=$(git diff --cached --name-only 2>/dev/null)
if [ -z "$CHANGED_FILES" ]; then exit 0; fi

TARGET_PATTERNS=({quoted_patterns})
MATCHED=0

while IFS= read -r file; do
    for pattern in "${{TARGET_PATTERNS[@]}}"; do
        case "$file" in
            $pattern) MATCHED=1; break 2 ;;
        esac
    done
done <<< "$CHANGED_FILES"

if [ "$MATCHED" -eq 1 ]; then
    echo -n "🔍  ["
    echo -n {quoted_name}
    echo "] Trap check triggered (mechanical enforcement)"
    echo -n "   Hypothesis: "
    echo {quoted_hyp}
    exit 1  # Mechanical: block commit
fi

exit 0  # No match: allow commit
'''
    return check


def generate_gate_assertion(cell, workspace):
    """Generate a runtime assertion for a 'gate' cell."""
    name = cell['_name']
    cell_type = cell.get('type', 'vacuole')
    hypothesis = cell.get('hypothesis', '')
    target_paths = cell.get('target_paths', [])
    
    class_suffix = re.sub(r"[^a-zA-Z0-9]", "_", name)
    json_name = json.dumps(name)
    json_hyp = json.dumps(hypothesis)
    json_targets = json.dumps(target_paths)
    
    assertion = f'''# Auto-generated gate assertion for: {name}
# Type: {cell_type} | Tier: gate
# Hypothesis: {hypothesis}
# Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
#
# This assertion is a deterministic gate that cannot be bypassed
# without modifying this file. It was auto-generated when the cell
# was promoted to gate tier based on demonstrated effectiveness.
#
# To disable: demote the cell to mechanical or advisory tier.

import os
import subprocess
import sys


class Gate_{class_suffix}:
    """Runtime gate for: {hypothesis[:100]}"""
    
    CELL_NAME = {json_name}
    HYPOTHESIS = {json_hyp}
    TARGET_PATHS = {json_targets}
    
    @classmethod
    def check(cls, context=None):
        """Run the gate check. Raises RuntimeError on violation."""
        # Override this method with domain-specific logic.
        # The default implementation logs the check.
        signal_script = os.path.join(
            os.path.dirname(__file__), '..', '..', 'vendor', 'soma',
            'enzymes', 'cell_signal.sh'
        )
        if not os.path.exists(signal_script):
            signal_script = os.path.join(
                os.path.dirname(__file__), '..', '..', 'enzymes', 'cell_signal.sh'
            )
        if os.path.exists(signal_script):
            subprocess.run(
                ['bash', signal_script, cls.CELL_NAME, 'tp'],
                capture_output=True, cwd=os.path.dirname(signal_script)
            )
    
    @classmethod
    def enforce(cls, condition, message=None):
        """Assert a condition. Halt on failure."""
        if not condition:
            msg = message or f"Gate violation: {{cls.HYPOTHESIS}}"
            # Record escaped defect
            escaped_script = os.path.join(
                os.path.dirname(__file__), '..', '..', 'vendor', 'soma',
                'enzymes', 'cell_escaped_defects.py'
            )
            if os.path.exists(escaped_script) and cls.TARGET_PATHS:
                subprocess.run(
                    [sys.executable, escaped_script, '--event', 'crash',
                     '--files'] + cls.TARGET_PATHS + ['--severity', 'critical'],
                    capture_output=True
                )
            raise RuntimeError(f"\U0001f6d1 GATE VIOLATION [{{cls.CELL_NAME}}]: {{msg}}")
'''
    return assertion


def update_cell_enforcement_artifact(cell, artifact_path, workspace):
    """Add enforcement_artifact field to cell YAML."""
    cell_path = cell['_path']
    with open(cell_path, encoding="utf-8") as f:
        content = f.read()
    
    if 'enforcement_artifact:' in content:
        return  # Already has artifact link
    
    rel_path = os.path.relpath(artifact_path, workspace)
    
    # Parse the YAML frontmatter properly
    if not content.startswith('---'):
        return
    end_idx = content.find('---', 3)
    if end_idx == -1:
        return
    
    yaml_block = content[3:end_idx]
    body = content[end_idx:]  # includes closing ---
    
    # Insert enforcement_artifact after enforcement line
    lines = yaml_block.split('\n')
    new_lines = []
    inserted = False
    for line in lines:
        new_lines.append(line)
        if line.strip().startswith('enforcement:') and not inserted:
            new_lines.append(f'enforcement_artifact: {rel_path}')
            inserted = True
    
    if not inserted:
        # Just append before the end
        new_lines.append(f'enforcement_artifact: {rel_path}')
    
    new_content = '---' + '\n'.join(new_lines) + body
    with open(cell_path, 'w', encoding="utf-8") as f:
        f.write(new_content)


def main():
    parser = argparse.ArgumentParser(
        description='Auto-generate enforcement artifacts for promoted cells'
    )
    parser.add_argument('--cell', help='Generate for specific cell name')
    parser.add_argument('--dry-run', action='store_true', help='Preview without writing files')
    parser.add_argument('--list', action='store_true', help='List all enforcement artifacts')
    parser.add_argument('--json', action='store_true', help='JSON output')
    args = parser.parse_args()
    
    workspace = resolve_workspace(__file__)
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    cells = load_cells(cells_dir)
    
    if not cells:
        print('No cells found.')
        return
    
    artifacts_dir = os.path.join(workspace, '.soma', 'enforcement')
    
    if args.list:
        if not os.path.exists(artifacts_dir):
            print('No enforcement artifacts generated yet.')
            return
        artifacts = []
        for f in os.listdir(artifacts_dir):
            artifacts.append({
                'file': f,
                'path': os.path.join(artifacts_dir, f)
            })
        if args.json:
            print(json.dumps(artifacts, indent=2))
        else:
            print(f'\\n\U0001f512 Enforcement Artifacts ({len(artifacts)})\\n')
            for a in artifacts:
                print(f'  {a["file"]}')
        return
    
    # Filter cells that need enforcement artifacts
    target_cells = []
    for cell in cells:
        enforcement = cell.get('enforcement', 'advisory')
        if enforcement in ('mechanical', 'gate'):
            if args.cell and cell['_name'] != args.cell:
                continue
            # Check if artifact already exists
            existing = cell.get('enforcement_artifact', '')
            if existing and os.path.exists(os.path.join(workspace, existing)):
                continue  # Already generated
            target_cells.append(cell)
    
    if not target_cells:
        print('No cells pending enforcement artifact generation.')
        print('Cells must be promoted to mechanical or gate tier first.')
        print('Run: python3 enzymes/cell_promote.py --tier-check')
        return
    
    os.makedirs(artifacts_dir, exist_ok=True)
    generated = []
    
    for cell in target_cells:
        enforcement = cell.get('enforcement', 'advisory')
        name = cell['_name']
        
        if enforcement == 'mechanical':
            content = generate_precommit_check(cell, workspace)
            filename = f'check-{name}.sh'
            artifact_path = os.path.join(artifacts_dir, filename)
        elif enforcement == 'gate':
            content = generate_gate_assertion(cell, workspace)
            filename = f'gate-{name}.py'
            artifact_path = os.path.join(artifacts_dir, filename)
        else:
            continue
        
        if args.dry_run:
            print(f'\\n{"=" * 60}')
            print(f'Would generate: {filename} ({enforcement})')
            print(f'Cell: {name} ({cell.get("type", "")})')
            print(f'{"=" * 60}')
            print(content[:500])
            if len(content) > 500:
                print(f'... ({len(content)} chars total)')
            generated.append({'cell': name, 'artifact': filename, 'tier': enforcement})
            continue
        
        with open(artifact_path, 'w', encoding="utf-8") as f:
            f.write(content)
        os.chmod(artifact_path, 0o755)
        
        # Update cell with artifact link
        update_cell_enforcement_artifact(cell, artifact_path, workspace)
        
        generated.append({'cell': name, 'artifact': filename, 'tier': enforcement})
        print(f'\u2705 Generated: {filename} ({enforcement} enforcement for {name})')
    
    if args.json:
        print(json.dumps(generated, indent=2))
    elif generated and not args.dry_run:
        print(f'\\nGenerated {len(generated)} enforcement artifact(s) in .soma/enforcement/')


if __name__ == '__main__':
    # A cp1252 stdout can't encode this script's symbols (BUG-038).
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    main()
