#!/usr/bin/env python3
import os
import sys
import argparse
import glob
try:
    import yaml
except ImportError:
    yaml = None
import csv
from datetime import datetime
from soma_resolve import resolve_workspace

def decayed_fitness(raw_score, last_trigger_date, telomere_days=30):
    if last_trigger_date is None or raw_score is None:
        return raw_score
    days_since = (datetime.now() - last_trigger_date).days
    decay_factor = 0.5 ** (days_since / telomere_days)
    return round(raw_score * decay_factor, 4)

def main():
    parser = argparse.ArgumentParser(description="ASCII visualization of governance effectiveness")
    parser.add_argument("--format", choices=["ascii", "csv"], default="ascii", help="Output format")
    args = parser.parse_args()

    workspace = resolve_workspace(__file__)
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    
    cell_files = glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True)
    
    cells_data = []
    
    telomere_days = int(os.environ.get('CELL_TELOMERE_DAYS', 30))
    
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
            
        if not metadata:
            continue
            
        # `fitness` is a bare scalar in real cells (`fitness: 1.0`), not always a
        # mapping. Calling .get() on it raised
        #   AttributeError: 'float' object has no attribute 'get'
        # and aborted the whole run. cell_fitness.py, outcome_engine.py,
        # cell_promote.py and jit_engine all normalize this the same way.
        fitness = metadata.get('fitness', {})
        if not isinstance(fitness, dict):
            if isinstance(fitness, bool) or fitness is None:
                fitness = {}
            elif isinstance(fitness, (int, float)):
                fitness = {'score': float(fitness)}
            elif isinstance(fitness, str):
                try:
                    fitness = {'score': float(fitness)}
                except ValueError:
                    fitness = {}
            else:
                fitness = {}
        triggers = fitness.get('triggers', 0)
        raw_score = fitness.get('score')
        
        last_trigger_date_str = fitness.get('last_trigger_date')
        last_trigger_date = None
        if last_trigger_date_str:
            try:
                last_trigger_date = datetime.fromisoformat(last_trigger_date_str.replace('Z', '+00:00')).replace(tzinfo=None)
            except Exception:
                pass
                
        dec_score = decayed_fitness(raw_score, last_trigger_date, telomere_days)
        
        # Determine status (HEALTHY / WARNING / EXTINCT)
        if dec_score is None or dec_score <= 0.3:
            status = "EXTINCT"
        elif dec_score <= 0.7:
            status = "WARNING"
        else:
            status = "HEALTHY"
            
        cells_data.append({
            'name': os.path.basename(file_path),
            'type': metadata.get('type', 'unknown'),
            'raw_score': raw_score,
            'dec_score': dec_score,
            'triggers': triggers,
            'status': status
        })

    # Sort by decayed fitness descending (handling nulls)
    def get_sort_key(c):
        return c['dec_score'] if c['dec_score'] is not None else -1.0
        
    cells_data.sort(key=get_sort_key, reverse=True)
    
    active_count = sum(1 for c in cells_data if c['dec_score'] is not None and c['dec_score'] > 0.3)
    extinct_count = sum(1 for c in cells_data if c['dec_score'] is None or c['dec_score'] <= 0.3)
    
    valid_scores = [c['dec_score'] for c in cells_data if c['dec_score'] is not None]
    avg_fitness = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0
    min_fitness = min(valid_scores) if valid_scores else 0.0
    max_fitness = max(valid_scores) if valid_scores else 0.0

    if args.format == "csv":
        writer = csv.writer(sys.stdout)
        writer.writerow(["Name", "Type", "Raw Score", "Decayed Score", "Triggers", "Status"])
        for c in cells_data:
            writer.writerow([
                c['name'],
                c['type'],
                c['raw_score'] if c['raw_score'] is not None else "",
                c['dec_score'] if c['dec_score'] is not None else "",
                c['triggers'],
                c['status']
            ])
    else:
        print("=== Governance Fitness Landscape ===")
        print(f"Active Cells:  {active_count}")
        print(f"Extinct Cells: {extinct_count}")
        print(f"Avg Fitness:   {avg_fitness:.4f}")
        print(f"Min Fitness:   {min_fitness:.4f}")
        print(f"Max Fitness:   {max_fitness:.4f}")
        print("\n" + "="*85)
        print(f"{'Cell Name':<30} | {'Type':<12} | {'Raw':<6} | {'Decayed':<7} | {'Triggers':<8} | {'Status':<10}")
        print("-" * 85)
        
        for c in cells_data:
            r_str = f"{c['raw_score']:.2f}" if c['raw_score'] is not None else "null"
            d_str = f"{c['dec_score']:.2f}" if c['dec_score'] is not None else "null"
            print(f"{c['name']:<30} | {c['type']:<12} | {r_str:<6} | {d_str:<7} | {c['triggers']:<8} | {c['status']:<10}")

if __name__ == "__main__":
    main()
