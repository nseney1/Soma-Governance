#!/usr/bin/env python3
import os
import sys
import argparse
import glob
try:
    import yaml
except ImportError:
    yaml = None
import random
from soma_resolve import resolve_workspace

def main():
    parser = argparse.ArgumentParser(description="Tournament selection for cell pruning decisions")
    parser.add_argument("--k", type=int, default=3, help="Tournament size")
    parser.add_argument("--count", type=int, default=5, help="Number of tournaments to run")
    args = parser.parse_args()

    workspace = resolve_workspace(__file__)
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    
    cell_files = glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True)
    
    valid_cells = []
    
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
            
        try:
            metadata = yaml.safe_load(content[3:end_idx].strip())
        except Exception:
            continue
            
        if not metadata or 'fitness' not in metadata:
            continue
            
        fitness = metadata['fitness']
        score = fitness.get('score')
        triggers = fitness.get('triggers', 0) if isinstance(fitness, dict) else 0
        
        valid_cells.append({
            'id': os.path.basename(file_path),
            'type': metadata.get('type', 'unknown'),
            'score': score if score is not None and triggers > 0 else -1.0 # Unobserved/null = worst
        })
        
    if not valid_cells:
        print("No valid cells with fitness scores found.")
        sys.exit(0)
        
    print(f"{'Winner Cell ID':<30} | {'Fitness Score':<15} | {'Type':<15}")
    print("-" * 65)
    
    for _ in range(args.count):
        # Handle case where fewer cells than k
        actual_k = min(args.k, len(valid_cells))
        if actual_k == 0:
            break
            
        tournament = random.sample(valid_cells, actual_k)
        winner = max(tournament, key=lambda x: x['score'])
        
        score_str = f"{winner['score']:.4f}" if winner['score'] >= 0 else "null"
        print(f"{winner['id']:<30} | {score_str:<15} | {winner['type']:<15}")

if __name__ == "__main__":
    main()
