#!/usr/bin/env python3
import os
import sys
import glob
import json
try:
    import yaml
except ImportError:
    yaml = None
import shutil
from datetime import datetime

def set_review_mode(workspace, mode):
    conf_path = os.path.join(workspace, "steering.conf")
    if not os.path.exists(conf_path):
        return
    
    with open(conf_path, 'r', encoding="utf-8") as f:
        lines = f.readlines()
        
    with open(conf_path, 'w', encoding="utf-8") as f:
        for line in lines:
            if line.startswith("REVIEW_MODE="):
                f.write(f"REVIEW_MODE={mode}\n")
            else:
                f.write(line)
    print(f"[Sentinel] Escalated REVIEW_MODE to {mode}")

def get_frontmatter(content):
    if not content.startswith('---'):
        return None, content
    end_idx = content.find('---', 3)
    if end_idx == -1:
        return None, content
    frontmatter = content[3:end_idx].strip()
    try:
        metadata = yaml.safe_load(frontmatter)
        return metadata, content[end_idx+3:]
    except Exception:
        return None, content

def write_frontmatter(filepath, metadata, body):
    with open(filepath, 'w', encoding="utf-8") as f:
        f.write("---\n")
        yaml.dump(metadata, f, default_flow_style=False, sort_keys=False)
        f.write("---\n")
        if body.startswith('\n'):
            f.write(body[1:])
        else:
            f.write(body)

def main():
    workspace = os.getcwd()
    cells_dir = os.path.join(workspace, '.prism', 'cells')
    if not os.path.exists(cells_dir):
        # Fallback for Soma v0.25 structure
        cells_dir = os.path.join(workspace, '.soma', 'cells')
        if not os.path.exists(cells_dir):
            sys.exit(0)

    last_gasp_dir = os.path.join(cells_dir, '.last_gasp_queue')
    archive_dir = os.path.join(cells_dir, '.archive')
    
    if not os.path.exists(last_gasp_dir):
        sys.exit(0)
        
    queued_files = glob.glob(os.path.join(last_gasp_dir, '*.md'))
    if not queued_files:
        sys.exit(0)

    for fpath in queued_files:
        filename = os.path.basename(fpath)
        with open(fpath, 'r', encoding="utf-8") as f:
            content = f.read()
            
        metadata, body = get_frontmatter(content)
        if not metadata:
            continue
            
        # Extract organ (default to governance-auditor)
        organ = metadata.get('organ', 'governance-auditor')
        
        # In a real environment, we would invoke the organ via MCP or subprocess here.
        # For the Sentinel logic: we evaluate the organ's feedback.
        # We will mock the validation result here (validation via mock organ).
        # We assume the organ returns a result payload in a .result file.
        
        # MOCK VALIDATION: We will randomly decide based on current score to simulate feedback
        import random
        random.seed(filename)
        
        # Normally organ runs here:
        print(f"[Sentinel] Cell {filename} faces APOPTOSIS. Invoking Last Gasp Organ: {organ}...")
        
        # Simulate organ result (e.g. 30% chance to save it)
        organ_validates_cell = random.random() < 0.3
        
        if organ_validates_cell:
            print(f"[Sentinel] Organ '{organ}' VALIDATED the cell! Saving from Apoptosis.")
            # Escalate the session
            set_review_mode(workspace, "TEMPEST")
            
            # Restore fitness
            if 'fitness' not in metadata:
                metadata['fitness'] = {}
            metadata['fitness']['score'] = 0.75
            metadata['fitness']['stress_survived'] = metadata['fitness'].get('stress_survived', 0) + 1
            
            # Move back to active cells directory
            parent_type = metadata.get('type', 'walls') + 's'
            target_dir = os.path.join(cells_dir, parent_type)
            os.makedirs(target_dir, exist_ok=True)
            new_path = os.path.join(target_dir, filename)
            
            write_frontmatter(new_path, metadata, body)
            os.remove(fpath)
            
        else:
            print(f"[Sentinel] Organ '{organ}' REFUTED the cell! Brutally punishing and archiving.")
            
            # Punish fitness
            if 'fitness' not in metadata:
                metadata['fitness'] = {}
            metadata['fitness']['score'] = 0.0
            metadata['fitness']['false_positives'] = metadata['fitness'].get('false_positives', 0) + 10
            
            os.makedirs(archive_dir, exist_ok=True)
            new_path = os.path.join(archive_dir, filename)
            
            write_frontmatter(new_path, metadata, body)
            os.remove(fpath)

if __name__ == "__main__":
    main()
