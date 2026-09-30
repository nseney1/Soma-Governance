#!/usr/bin/env python3
# Soma - Cell Demotion
# Demotes a global rule back to a local cell when it causes issues in new contexts.
# Usage: python3 enzymes/cell_demote.py <rule-name> --reason "False positives in Go codebases"

import os
import sys
import argparse
import glob
import json
try:
    import yaml
except ImportError:
    yaml = None
from datetime import datetime
from datetime import timezone
from soma_resolve import resolve_workspace

# The 11 built-in core rules that must not be demoted
PROTECTED_RULES = {
    "providence", "cost-optimization", "subagent-delegation", "architectural-tenets",
    "polyglot-standards", "feature-specs", "testing", "documentation",
    "destructive-ops", "git-workflow", "desktop-automation"
}

def main():
    parser = argparse.ArgumentParser(description="Demote a global rule back to a local cell.")
    parser.add_argument("rule_name", help="The name of the rule to demote (e.g. rule-trap-walls)")
    parser.add_argument("--reason", required=True, help="Reason for demotion")
    args = parser.parse_args()

    workspace = resolve_workspace(__file__)
    
    rule_name = args.rule_name
    if rule_name.endswith('.md'):
        rule_name = rule_name[:-3]
        
    rule_base = rule_name
    if rule_base.startswith('rule-'):
        rule_base = rule_base[5:]

    if rule_base in PROTECTED_RULES or rule_name in PROTECTED_RULES:
        print(f"Cannot demote core rule: {rule_name}. Only promoted cells can be demoted.")
        sys.exit(1)
        
    rules_dir = os.path.join(workspace, "genome")
    
    # Try finding the rule by exact or partial match
    rule_path = os.path.join(rules_dir, f"{rule_name}.md")
    if not os.path.exists(rule_path):
        matches = glob.glob(os.path.join(rules_dir, f"*{rule_name}*.md"))
        if not matches:
            print(f"Error: Rule '{rule_name}' not found in {rules_dir}")
            sys.exit(1)
        if len(matches) > 1:
            print(f"Error: Multiple rules match '{rule_name}': {', '.join([os.path.basename(m) for m in matches])}")
            sys.exit(1)
        rule_path = matches[0]
        
    actual_rule_name = os.path.basename(rule_path)[:-3]

    try:
        with open(rule_path, 'r', encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading rule {actual_rule_name}: {e}")
        sys.exit(1)
        
    if not content.startswith('---'):
        print(f"Error: Rule {actual_rule_name} does not have YAML frontmatter.")
        sys.exit(1)
        
    end_idx = content.find('---', 3)
    if end_idx == -1:
        print(f"Error: Rule {actual_rule_name} has malformed YAML frontmatter.")
        sys.exit(1)
        
    frontmatter_str = content[3:end_idx].strip()
    body_str = content[end_idx+3:]
    
    try:
        metadata = yaml.safe_load(frontmatter_str) or {}
    except Exception as e:
        print(f"Error parsing YAML for {actual_rule_name}: {e}")
        sys.exit(1)

    # Modify the frontmatter for demotion
    if 'fitness' not in metadata:
        metadata['fitness'] = {}
        
    # Reset fitness score to 0.5 (neutral)
    metadata['fitness']['score'] = 0.5
    
    demotion_entry = {
        "reason": args.reason,
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
    }
    
    if 'demoted_contexts' not in metadata:
        metadata['demoted_contexts'] = []
    metadata['demoted_contexts'].append(demotion_entry)
    
    if 'demotion_history' not in metadata:
        metadata['demotion_history'] = []
    metadata['demotion_history'].append(demotion_entry)

    # Determine destination cell path
    cells_dir = os.path.join(workspace, ".soma", "cells", "vacuoles")
    os.makedirs(cells_dir, exist_ok=True)
    
    # Restore original cell name if it was prefixed with 'rule-'
    cell_name = actual_rule_name
    if cell_name.startswith('rule-'):
        cell_name = cell_name[5:]
        
    target_path = os.path.join(cells_dir, f"{cell_name}.md")
    
    try:
        with open(target_path, 'w', encoding="utf-8") as f:
            f.write("---\n")
            yaml.dump(metadata, f, default_flow_style=False, sort_keys=False)
            f.write("---\n")
            if body_str.startswith('\n'):
                f.write(body_str[1:])
            else:
                f.write(body_str)
                
        # Remove the rule file from genome/
        os.remove(rule_path)
    except Exception as e:
        print(f"Error moving rule to cell: {e}")
        sys.exit(1)
        
    # Log demotion to metrics
    metrics_dir = os.path.join(workspace, ".soma", "metrics")
    os.makedirs(metrics_dir, exist_ok=True)
    demotions_log = os.path.join(metrics_dir, "demotions.jsonl")
    
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "rule": actual_rule_name,
        "cell": cell_name,
        "reason": args.reason
    }
    
    try:
        with open(demotions_log, 'a', encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"Warning: Failed to log demotion to {demotions_log}: {e}")
        
    print(f"Demoted: {actual_rule_name} -> .soma/cells/vacuoles/{cell_name}.md (reason: {args.reason})")

if __name__ == "__main__":
    main()
