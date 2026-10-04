#!/usr/bin/env python3
import os
import sys
import glob
import json
import yaml
import shutil
from datetime import datetime
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
from soma_sdk.cells import parse_cell_file

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

def get_frontmatter(filepath):
    try:
        metadata, body = parse_cell_file(filepath)
        return metadata, body
    except Exception:
        return None, None

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
        metadata, body = get_frontmatter(fpath)
        if not metadata:
            continue
            
        # Extract organ (default to governance-auditor)
        organ = metadata.get('organ', 'governance-auditor')
        
        # TODO: Invoke the organ via MCP or subprocess to validate the cell.
        # For now, check for a pre-computed .result file written by the organ.
        print(f"[Sentinel] Cell {filename} faces APOPTOSIS. Invoking Last Gasp Organ: {organ}...")
        
        result_file = os.path.join(last_gasp_dir, filename.replace('.md', '.result'))
        organ_validates_cell = os.path.exists(result_file)
        
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
            raw_type = str(metadata.get('type', 'wall')).rstrip('s')
            allowed_types = {'wall', 'membrane', 'vacuole', 'chloroplast', 'ribosome', 'nucleus'}
            cell_type = raw_type if raw_type in allowed_types else 'wall'
            parent_type = cell_type + 's'
            target_dir = os.path.abspath(os.path.join(cells_dir, parent_type))
            abs_cells_dir = os.path.abspath(cells_dir)
            if not target_dir.startswith(abs_cells_dir) or os.path.commonpath([abs_cells_dir, target_dir]) != abs_cells_dir:
                target_dir = os.path.join(abs_cells_dir, 'walls')
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
