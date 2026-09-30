#!/usr/bin/env python3
# cell_metamorphose.py: Transforms cells between types based on maturity criteria.
# Usage: python3 enzymes/cell_metamorphose.py <cell_id>

import os
import sys
import argparse
import glob
import json
try:
    import yaml
except ImportError:
    yaml = None
import shutil
from datetime import datetime
from datetime import timezone
from soma_resolve import resolve_workspace

METAMORPHOSIS_PATHS = {
    "vacuole": [
        {"target": "wall", "min_fitness": 0.8, "min_sessions": 20},
        {"target": "membrane", "min_fitness": 0.7, "min_sessions": 15},
    ],
    "chloroplast": [
        {"target": "rule", "min_fitness": 0.9, "min_sessions": 30},
    ],
    "wall": [
        {"target": "rule", "min_fitness": 0.85, "min_sessions": 25},
    ],
}

def main():
    parser = argparse.ArgumentParser(description="Transforms cells between types based on maturity criteria.")
    parser.add_argument("cell_id", help="The ID of the cell to metamorphose (filename or partial match)")
    args = parser.parse_args()

    workspace = resolve_workspace(__file__)
    cells_dir = os.path.join(workspace, ".soma", "cells")
    
    matches = glob.glob(os.path.join(cells_dir, "**", f"*{args.cell_id}*.md"), recursive=True)
    if not matches:
        print(f"Error: Cell '{args.cell_id}' not found in {cells_dir}")
        sys.exit(1)
    if len(matches) > 1:
        print(f"Error: Multiple cells match '{args.cell_id}': {', '.join([os.path.basename(m) for m in matches])}")
        sys.exit(1)
        
    cell_path = matches[0]
    cell_filename = os.path.basename(cell_path)
    
    try:
        with open(cell_path, 'r', encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading cell {cell_filename}: {e}")
        sys.exit(1)
        
    if not content.startswith('---'):
        print(f"Error: Cell {cell_filename} does not have YAML frontmatter.")
        sys.exit(1)
        
    end_idx = content.find('---', 3)
    if end_idx == -1:
        print(f"Error: Cell {cell_filename} has malformed YAML frontmatter.")
        sys.exit(1)
        
    frontmatter_str = content[3:end_idx].strip()
    body_str = content[end_idx+3:]
    
    try:
        metadata = yaml.safe_load(frontmatter_str) or {}
    except Exception as e:
        print(f"Error parsing YAML for {cell_filename}: {e}")
        sys.exit(1)
        
    current_type = metadata.get('type')
    if not current_type:
        print(f"Error: Cell {cell_filename} does not have a 'type' field in frontmatter.")
        sys.exit(1)
        
    if current_type not in METAMORPHOSIS_PATHS:
        print(f"Cell type '{current_type}' has no valid metamorphosis paths.")
        sys.exit(0)
        
    fitness = metadata.get('fitness', {})
    triggers = fitness.get('triggers', 0)
    score = fitness.get('score')
    
    if score is None:
        if triggers == 0:
            score = 0
        else:
            tp = fitness.get('true_positives', 0)
            impact = metadata.get('impact_weight', 1.0)
            score = (tp / triggers) * impact
            
    paths = METAMORPHOSIS_PATHS[current_type]
    
    best_path = None
    for path in paths:
        if score >= path['min_fitness'] and triggers >= path['min_sessions']:
            best_path = path
            break
            
    if not best_path:
        # Find nearest threshold
        nearest = None
        closest_distance = 1e9  # sentinel for min-distance search (never serialized)
        for path in paths:
            fitness_dist = max(0, path['min_fitness'] - score)
            session_dist = max(0, path['min_sessions'] - triggers)
            # Normalizing distance roughly
            dist = fitness_dist * 100 + session_dist
            if dist < closest_distance:
                closest_distance = dist
                nearest = path
                
        if nearest:
            print(f"Not yet mature. Nearest path: {current_type} -> {nearest['target']} (need fitness {nearest['min_fitness']:.2f}, have {score:.2f}; need {nearest['min_sessions']} triggers, have {triggers})")
        else:
            print(f"Not yet mature for metamorphosis.")
        sys.exit(0)
        
    # Metamorphose
    new_type = best_path['target']
    metadata['type'] = new_type
    metadata['metamorphosed_from'] = current_type
    metadata['metamorphosis_date'] = datetime.now(timezone.utc).isoformat() + "Z"
    
    gen = metadata.get('lineage', {}).get('generation', 0) if isinstance(metadata.get('lineage'), dict) else 0
    metadata['lineage'] = {
        'parent_id': os.path.splitext(cell_filename)[0],
        'created_by': "metamorphosis",
        'generation': gen + 1,
        'siblings': []
    }
    
    if new_type == 'rule':
        target_dir = os.path.join(workspace, "genome")
        os.makedirs(target_dir, exist_ok=True)
        # Assuming rule files are prefixed with rule-
        target_path = os.path.join(target_dir, f"rule-{cell_filename}")
        if 'trigger' not in metadata:
            metadata['trigger'] = 'manual'
    else:
        plural_type = f"{new_type}s"
        target_dir = os.path.join(workspace, ".soma", "cells", plural_type)
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, cell_filename)
        
    try:
        with open(target_path, 'w', encoding="utf-8") as f:
            f.write("---\n")
            yaml.dump(metadata, f, default_flow_style=False, sort_keys=False)
            f.write("---\n")
            if body_str.startswith('\n'):
                f.write(body_str[1:])
            else:
                f.write(body_str)
                
        os.remove(cell_path)
    except Exception as e:
        print(f"Error during metamorphosis: {e}")
        sys.exit(1)
        
    # Log metamorphosis
    metrics_dir = os.path.join(workspace, ".soma", "metrics")
    os.makedirs(metrics_dir, exist_ok=True)
    meta_log = os.path.join(metrics_dir, "metamorphosis.jsonl")
    
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "cell": cell_filename,
        "old_type": current_type,
        "new_type": new_type,
        "fitness_score": score,
        "triggers": triggers
    }
    
    try:
        with open(meta_log, 'a', encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"Warning: Failed to log metamorphosis to {meta_log}: {e}")
        
    # Metamorphosis: {cell_id} ({old_type} → {new_type}) [fitness: {score}, triggers: {n}]
    print(f"Metamorphosis: {cell_filename} ({current_type} -> {new_type}) [fitness: {score:.2f}, triggers: {triggers}]")

if __name__ == "__main__":
    main()
