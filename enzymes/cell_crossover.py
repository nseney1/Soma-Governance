#!/usr/bin/env python3
import os
import sys
import argparse
import glob
try:
    import yaml
except ImportError:
    yaml = None
import json
from datetime import datetime
from datetime import timezone
import re
from soma_resolve import resolve_workspace

def find_cell(workspace, cell_id):
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    if not os.path.exists(cells_dir):
        # Fallback to .gemini/cells if .soma/cells doesn't exist? The instructions specifically said .soma/cells/
        pass
    matches = glob.glob(os.path.join(cells_dir, '**', f'*{cell_id}*'), recursive=True)
    matches = [m for m in matches if os.path.isfile(m) and m.endswith('.md')]
    if not matches:
        return None
    return matches[0]

def parse_cell(file_path):
    with open(file_path, 'r', encoding="utf-8") as f:
        content = f.read()
    if not content.startswith('---'):
        return None, content
    end_idx = content.find('---', 3)
    if end_idx == -1:
        return None, content
    frontmatter = content[3:end_idx].strip()
    body = content[end_idx+3:].strip()
    try:
        metadata = yaml.safe_load(frontmatter)
        return metadata, body
    except Exception:
        return None, content

def get_type_plural(cell_type):
    cell_type = cell_type.lower()
    mapping = {
        'vacuole': 'vacuoles',
        'chloroplast': 'chloroplasts',
        'wall': 'walls',
        'membrane': 'membranes',
        'plasmodesmata': 'plasmodesmata'
    }
    return mapping.get(cell_type, 'vacuoles')

def main():
    parser = argparse.ArgumentParser(description="Merge complementary hypotheses from two high-fitness cells")
    parser.add_argument("cell_a_id", help="ID of the first parent cell")
    parser.add_argument("cell_b_id", help="ID of the second parent cell")
    args = parser.parse_args()

    workspace = resolve_workspace(__file__)
    
    cell_a_path = find_cell(workspace, args.cell_a_id)
    cell_b_path = find_cell(workspace, args.cell_b_id)

    if not cell_a_path:
        print(f"Error: Could not find cell matching {args.cell_a_id}")
        sys.exit(1)
    if not cell_b_path:
        print(f"Error: Could not find cell matching {args.cell_b_id}")
        sys.exit(1)

    meta_a, body_a = parse_cell(cell_a_path)
    meta_b, body_b = parse_cell(cell_b_path)

    if not meta_a or not meta_b:
        print("Error: One or both cells lack valid YAML frontmatter.")
        sys.exit(1)

    # Merge logic
    hyp_a = meta_a.get('hypothesis', '').strip()
    hyp_b = meta_b.get('hypothesis', '').strip()
    merged_hypothesis = f"{hyp_a}, prioritizing {hyp_b}"

    pred_a = meta_a.get('prediction', '').strip()
    pred_b = meta_b.get('prediction', '').strip()
    merged_prediction = f"{pred_a}\n\n{pred_b}".strip()

    weight_a = meta_a.get('impact_weight', 1.0)
    weight_b = meta_b.get('impact_weight', 1.0)
    merged_weight = max(weight_a, weight_b)

    type_a = meta_a.get('type', 'vacuole')
    type_b = meta_b.get('type', 'vacuole')
    if type_a == type_b:
        merged_type = type_a
    else:
        merged_type = 'vacuole'

    # Generate slug
    slug = re.sub(r'[^a-z0-9 ]', '', merged_hypothesis.lower())
    slug = re.sub(r'\s+', '-', slug)[:50].strip('-')

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    type_plural = get_type_plural(merged_type)
    out_dir = os.path.join(workspace, '.soma', 'cells', type_plural)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{slug}.md")

    falsification = "Falsification criteria combined or needs review."

    gen_a = meta_a.get('lineage', {}).get('generation', 0) if isinstance(meta_a.get('lineage'), dict) else 0
    gen_b = meta_b.get('lineage', {}).get('generation', 0) if isinstance(meta_b.get('lineage'), dict) else 0
    merged_generation = max(gen_a, gen_b) + 1

    new_meta = {
        'type': merged_type,
        'hypothesis': merged_hypothesis,
        'prediction': merged_prediction,
        'falsification': falsification,
        'expiry_sessions': 15,
        'expiry_days': 60,
        'created': date_str,
        'impact_weight': merged_weight,
        'tags': [],
        'lineage': {
            'parent_id': f"{args.cell_a_id} × {args.cell_b_id}",
            'created_by': "crossover",
            'generation': merged_generation,
            'siblings': []
        },
        'fitness': {
            'triggers': 0,
            'true_positives': 0,
            'false_positives': 0,
            'score': None
        }
    }

    # Write new cell
    with open(out_path, 'w', encoding="utf-8") as f:
        f.write("---\n")
        yaml.dump(new_meta, f, default_flow_style=False, sort_keys=False)
        f.write("---\n")
        f.write(f"## {merged_type.capitalize()}: {merged_hypothesis[:60]}{'...' if len(merged_hypothesis) > 60 else ''}\n\n")
        f.write(f"{merged_hypothesis}\n\n")
        f.write(f"### Prediction\n{merged_prediction}\n\n")
        f.write(f"### Falsification Criteria\n{falsification}\n")

    parent_a_name = os.path.basename(cell_a_path)
    parent_b_name = os.path.basename(cell_b_path)
    new_cell_name = os.path.basename(out_path)

    print(f"Crossover: {parent_a_name} × {parent_b_name} → {new_cell_name}")

    # Log to metrics
    metrics_dir = os.path.join(workspace, '.soma', 'metrics')
    os.makedirs(metrics_dir, exist_ok=True)
    metrics_file = os.path.join(metrics_dir, 'crossovers.jsonl')
    
    log_entry = {
        'timestamp': date_str,
        'parent_a': parent_a_name,
        'parent_b': parent_b_name,
        'new_cell': new_cell_name,
        'merged_type': merged_type
    }
    
    with open(metrics_file, 'a', encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + '\n')

if __name__ == "__main__":
    main()
