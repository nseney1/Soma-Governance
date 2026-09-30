#!/usr/bin/env python3
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

def main():
    parser = argparse.ArgumentParser(description="Adapt immune cells based on fitness.")
    parser.add_argument("--generate", action="store_true", help="Generate v2 cells for adaptation candidates")
    args = parser.parse_args()

    workspace_dir = resolve_workspace(__file__)
    cells_dir = os.path.join(workspace_dir, '.soma', 'cells')
    cell_files = glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True)

    metrics_repo = os.environ.get("METRICS_REPO")
    if not metrics_repo:
        conf_path = os.path.join(workspace_dir, "soma.conf")
        if os.path.exists(conf_path):
            with open(conf_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("METRICS_REPO=") and not line.startswith("#"):
                        metrics_repo = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    if metrics_repo:
        metrics_repo = os.path.expanduser(metrics_repo)
    else:
        metrics_repo = os.path.join(workspace_dir, "docs", "snapshots")
    
    os.makedirs(metrics_repo, exist_ok=True)
    fitness_log_path = os.path.join(metrics_repo, "fitness.jsonl")

    adaptations = []

    print(f"{'Cell':<30} | {'Score':<5} | {'TP/FP':<7} | {'Suggestion'}")
    print("-" * 80)

    for file_path in cell_files:
        if os.path.basename(file_path) == 'README.md':
            continue
        
        with open(file_path, 'r', encoding="utf-8") as f:
            content = f.read()
        
        if not content.startswith('---'):
            continue
        
        end_idx = content.find('---', 3)
        if end_idx == -1:
            continue
        
        frontmatter = content[3:end_idx].strip()
        try:
            metadata = yaml.safe_load(frontmatter)
        except Exception:
            continue
            
        fitness = metadata.get('fitness', {})
        triggers = fitness.get('triggers', 0)
        tp = fitness.get('true_positives', 0)
        fp = fitness.get('false_positives', 0)
        impact_weight = metadata.get('impact_weight', 1.0)
        
        if triggers == 0:
            continue
            
        score = (tp / triggers) * impact_weight
        
        if 0.3 <= score <= 0.7:
            cell_name = os.path.basename(file_path)
            
            suggestion = ""
            if fp > tp * 1.5:
                suggestion = "narrowing the hypothesis scope"
            elif triggers < 5:
                suggestion = "broadening the trigger conditions"
            else:
                suggestion = "splitting into two more specific cells"
                
            print(f"{cell_name:<30} | {score:<5.2f} | {tp}/{fp:<4} | Suggest {suggestion}")
            
            if args.generate:
                name_parts = os.path.splitext(cell_name)
                v2_name = f"{name_parts[0]}_v2{name_parts[1]}"
                v2_path = os.path.join(os.path.dirname(file_path), v2_name)
                
                # Create v2 cell
                new_metadata = dict(metadata)
                new_metadata['hypothesis'] = new_metadata.get('hypothesis', '') + " (Refined)"
                new_metadata['fitness'] = {
                    'triggers': 0,
                    'true_positives': 0,
                    'false_positives': 0,
                    'score': None
                }
                new_metadata['lineage'] = [cell_name]
                new_metadata['created'] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                
                # Dump new frontmatter
                new_frontmatter = yaml.dump(new_metadata, sort_keys=False, default_flow_style=False)
                new_content = f"---\n{new_frontmatter}---\n{content[end_idx+3:]}"
                
                with open(v2_path, 'w', encoding="utf-8") as f:
                    f.write(new_content)
                    
                print(f"  -> Generated {v2_name}")
                
                adaptations.append({
                    "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                    "type": "adaptation",
                    "original_cell": cell_name,
                    "new_cell": v2_name,
                    "score": score,
                    "suggestion": suggestion
                })

    if args.generate and adaptations:
        with open(fitness_log_path, 'a', encoding="utf-8") as f:
            for adapt in adaptations:
                f.write(json.dumps(adapt) + "\n")

if __name__ == "__main__":
    main()
