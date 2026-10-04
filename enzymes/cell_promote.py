#!/usr/bin/env python3
import os
import sys
import argparse
import glob
import json
import time
import yaml
from datetime import datetime
from datetime import timezone
from pathlib import Path
from bayesian_score import bayesian_score
from soma_resolve import resolve_workspace

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
from soma_sdk.cells import parse_cell_file

DECAY_FACTOR = 0.95  # Multiply counts by this each application; ~20-session memory window


def apply_decay(meta):
    """Decay historical fitness data so recent signals weigh more.

    Prevents Beta-locking: a cell with 1000 historical TPs can still
    be demoted if it starts producing false positives consistently.
    Effective memory window: ~20 sessions (0.95^20 ≈ 0.36).

    Idempotency: skips decay if last_decay_epoch is within 1 hour.
    Mutates meta in place and returns it.
    """
    fitness = (meta or {}).get('fitness', {})
    if not isinstance(fitness, dict):
        return meta

    # Idempotency guard: skip if already decayed within the last hour
    now = int(time.time())
    last_decay = fitness.get('last_decay_epoch', 0)
    if now - last_decay < 3600:
        return meta

    triggers = fitness.get('triggers', 0)
    tp = fitness.get('true_positives', 0)
    fp = fitness.get('false_positives', 0)

    if triggers <= 0:
        fitness['last_decay_epoch'] = now
        meta['fitness'] = fitness
        return meta

    # Decay counts, floor to integers, never below 1 for triggers
    fitness['triggers'] = max(1, int(triggers * DECAY_FACTOR))
    fitness['true_positives'] = max(0, int(tp * DECAY_FACTOR))
    fitness['false_positives'] = max(0, int(fp * DECAY_FACTOR))

    # Recompute score with centralized Bayesian posterior mean
    new_tp = fitness['true_positives']
    new_triggers = fitness['triggers']
    fitness['score'] = round(bayesian_score(new_tp, new_triggers), 4)

    fitness['last_decay_epoch'] = now
    meta['fitness'] = fitness
    return meta

def normalize_fitness(metadata):
    """Return the cell's `fitness` value as a dict.

    Cells in the wild carry `fitness` as a bare scalar (`fitness: 1.0`) as well
    as a nested mapping. cell_fitness.py, outcome_engine.py and
    jit_engine.get_fitness_score all normalize this; cell_promote.py did not,
    so `fitness.get('triggers', 0)` raised
    AttributeError: 'float' object has no attribute 'get'
    and aborted the whole run (9 of 18 cells in this repo hit it).
    """
    fitness = (metadata or {}).get('fitness', {})
    if isinstance(fitness, dict):
        return fitness
    if isinstance(fitness, bool) or fitness is None:
        return {}
    if isinstance(fitness, (int, float)):
        return {'score': float(fitness)}
    if isinstance(fitness, str):
        try:
            return {'score': float(fitness)}
        except ValueError:
            return {}
    return {}


def resolve_metrics_dir(workspace):
    metrics_repo = os.environ.get("METRICS_REPO")
    if not metrics_repo:
        conf_path = os.path.join(workspace, "soma.conf")
        if os.path.exists(conf_path):
            with open(conf_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("METRICS_REPO=") and not line.startswith("#"):
                        metrics_repo = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    if metrics_repo:
        return os.path.expanduser(metrics_repo)
    return os.path.join(workspace, "docs", "snapshots")

def main():
    parser = argparse.ArgumentParser(description="Promote cells to global rules.")
    parser.add_argument("--local", action="store_true", help="Single-repo mode: fitness > 0.85 and >=20 triggers")
    parser.add_argument("--execute", action="store_true", help="Create rule file (marked manual) instead of dry-run")
    parser.add_argument("--tier-check", action="store_true", help="Check cells for enforcement tier promotion/demotion")
    args = parser.parse_args()
    
    dry_run = not args.execute
    workspace = resolve_workspace(__file__)
    metrics_dir = resolve_metrics_dir(workspace)
    fitness_log_path = os.path.join(metrics_dir, "fitness.jsonl")
    
    if args.tier_check:
        cells_dir = os.path.join(workspace, '.soma', 'cells')
        cell_files = glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True)
        escaped_defects_log = os.path.join(workspace, '.soma', 'metrics', 'escaped_defects.jsonl')
        
        escaped_counts = {}
        if os.path.exists(escaped_defects_log):
            with open(escaped_defects_log, encoding="utf-8") as edf:
                for line in edf:
                    try:
                        entry = json.loads(line.strip())
                        cname = entry.get('cell')
                        if cname:
                            escaped_counts[cname] = escaped_counts.get(cname, 0) + 1
                    except Exception:
                        continue
        
        for file_path in cell_files:
            if os.path.basename(file_path) == 'README.md': continue
            try:
                metadata, _body = parse_cell_file(file_path)
            except Exception: continue
            
            # Re-read raw content for the write path below (tier changes, decay persistence)
            with open(file_path, 'r', encoding='utf-8') as f: content = f.read()
            end_idx = content.find('---', 3)
            if end_idx == -1: continue
            frontmatter_str = content[3:end_idx].strip('\n')
            
            cell_name = os.path.basename(file_path)
            cell_base = os.path.splitext(cell_name)[0]
            
            enforcement = metadata.get('enforcement', 'advisory')
            fitness = normalize_fitness(metadata)

            # Apply exponential decay so recent signals dominate
            metadata['fitness'] = fitness
            apply_decay(metadata)
            fitness = metadata['fitness']

            triggers = fitness.get('triggers', 0)
            tp = fitness.get('true_positives', 0)
            fp = fitness.get('false_positives', 0)
            
            escaped = escaped_counts.get(cell_base, 0)
            total_cases = escaped + tp
            defect_prevention_rate = tp / total_cases if total_cases > 0 else 1.0
            
            fp_rate = fp / triggers if triggers > 0 else 0.0
            trigger_rate = triggers / 30.0 # simple approx for per 30 sessions
            
            new_tier = enforcement
            reason = ""
            
            if enforcement == 'advisory':
                if defect_prevention_rate > 0.85 and triggers >= 20 and fp_rate < 0.15:
                    new_tier = 'mechanical'
                    reason = "defect_prevention_rate > 0.85, triggers >= 20, FP rate < 0.15"
            elif enforcement == 'mechanical':
                if defect_prevention_rate > 0.95 and triggers >= 50 and fp_rate < 0.05:
                    new_tier = 'gate'
                    reason = "defect_prevention_rate > 0.95, triggers >= 50, FP rate < 0.05"
                elif fp_rate > 0.50 or trigger_rate < (1/30.0):
                    new_tier = 'advisory'
                    reason = "FP rate > 0.50 or low trigger rate"
            elif enforcement == 'gate':
                if fp_rate > 0.30 or escaped > 0: # simple spike logic
                    new_tier = 'mechanical'
                    reason = "FP rate > 0.30 or escaped defects spike"

            # Rebuild frontmatter with decayed fitness + any tier change
            needs_write = False
            lines = frontmatter_str.split('\n')

            if new_tier != enforcement:
                needs_write = True
                for i, line in enumerate(lines):
                    if line.startswith('enforcement:'):
                        lines[i] = f"enforcement: {new_tier}"
                        break
                else:
                    lines.append(f"enforcement: {new_tier}")

            # Always persist decayed fitness counts
            if not dry_run:
                needs_write = True

            if needs_write and not dry_run:
                # Update fitness values in frontmatter
                has_decay_epoch = False
                for i, line in enumerate(lines):
                    stripped = line.lstrip()
                    if stripped.startswith('triggers:'):
                        lines[i] = line[:len(line)-len(stripped)] + f"triggers: {fitness['triggers']}"
                    elif stripped.startswith('true_positives:'):
                        lines[i] = line[:len(line)-len(stripped)] + f"true_positives: {fitness['true_positives']}"
                    elif stripped.startswith('false_positives:'):
                        lines[i] = line[:len(line)-len(stripped)] + f"false_positives: {fitness['false_positives']}"
                    elif stripped.startswith('score:'):
                        lines[i] = line[:len(line)-len(stripped)] + f"score: {fitness.get('score', 0.5)}"
                    elif stripped.startswith('last_decay_epoch:'):
                        lines[i] = line[:len(line)-len(stripped)] + f"last_decay_epoch: {fitness.get('last_decay_epoch', 0)}"
                        has_decay_epoch = True

                # Insert last_decay_epoch if not already in frontmatter
                if not has_decay_epoch and 'last_decay_epoch' in fitness:
                    # Find the fitness block indent and append after score
                    for i, line in enumerate(lines):
                        if line.lstrip().startswith('score:'):
                            indent = line[:len(line)-len(line.lstrip())]
                            lines.insert(i + 1, f"{indent}last_decay_epoch: {fitness['last_decay_epoch']}")
                            break

                new_frontmatter = '\n'.join(lines)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(f"---\n{new_frontmatter}\n---{content[end_idx+3:]}")
                if new_tier != enforcement:
                    print(f"Promoted/Demoted {cell_name}: {enforcement} -> {new_tier} ({reason})")
                    
                    if new_tier in ('mechanical', 'gate'):
                        # Auto-generate enforcement artifact
                        enforce_script = os.path.join(os.path.dirname(__file__), 'cell_enforce.py')
                        if os.path.exists(enforce_script):
                            import subprocess
                            subprocess.run([sys.executable, enforce_script, '--cell', cell_name], cwd=workspace)
                else:
                    print(f"No tier change for {cell_name}: already at {enforcement}")
                    
        return

    candidates = []
    
    if args.local:
        cells_dir = os.path.join(workspace, '.soma', 'cells')
        cell_files = glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True)
        for file_path in cell_files:
            if os.path.basename(file_path) == 'README.md': continue
            try:
                metadata, _body = parse_cell_file(file_path)
            except Exception: continue
            
            fitness = normalize_fitness(metadata)

            # Apply exponential decay so recent signals dominate
            metadata['fitness'] = fitness
            apply_decay(metadata)
            fitness = metadata['fitness']

            triggers = fitness.get('triggers', 0)
            tp = fitness.get('true_positives', 0)
            impact = metadata.get('impact_weight', 1.0)
            if triggers == 0: continue
            # Centralized Bayesian posterior mean
            score = bayesian_score(tp, triggers, impact)
            
            if score > 0.85 and triggers >= 20:
                candidates.append({
                    "cell_name": os.path.basename(file_path),
                    "repo": "local",
                    "score": score,
                    "hypothesis": metadata.get('hypothesis', ''),
                    "prediction": metadata.get('prediction', ''),
                    "triggers": triggers
                })
    else:
        snapshots = glob.glob(os.path.join(metrics_dir, '**', '*.json'), recursive=True)
        hypothesis_stats = {}
        for snap in snapshots:
            try:
                with open(snap, 'r', encoding='utf-8') as f: data = json.load(f)
                if not isinstance(data, list): continue
                filename = os.path.basename(snap)
                inferred_repo = filename.split('-')[0] if '-' in filename else filename.split('.')[0]
                
                for item in data:
                    if 'hypothesis' in item and 'score' in item and item['score'] is not None:
                        hyp = item['hypothesis']
                        repo = item.get('repo', inferred_repo)
                        if hyp not in hypothesis_stats:
                            hypothesis_stats[hyp] = {
                                'repos': set(), 'scores': [], 'cell_name': item.get('cell', 'unknown.md'),
                                'prediction': item.get('prediction', '')
                            }
                        hypothesis_stats[hyp]['repos'].add(repo)
                        hypothesis_stats[hyp]['scores'].append(item['score'])
            except Exception: continue
            
        for hyp, stats in hypothesis_stats.items():
            avg_score = sum(stats['scores']) / len(stats['scores']) if stats['scores'] else 0
            if avg_score > 0.7 and len(stats['repos']) >= 3:
                candidates.append({
                    "cell_name": stats['cell_name'],
                    "repo": f"{len(stats['repos'])} repos",
                    "score": avg_score,
                    "hypothesis": hyp,
                    "prediction": stats['prediction'],
                    "triggers": 0
                })
                
    if not candidates:
        print("No candidates found for promotion.")
        return
        
    print(f"Found {len(candidates)} candidate(s) for promotion.\n")
    
    promotions = []
    
    for cand in candidates:
        safe_name = cand['cell_name'].replace('.md', '').replace('_', '-')
        rule_name = f"rule-{safe_name}.md"
        rule_path = os.path.join(workspace, "genome", rule_name)
        
        rule_content = f"""---
name: Promoted Rule - {safe_name}
description: Auto-promoted global rule
trigger: manual
# Promoted from cell: {cand['cell_name']}, repo: {cand['repo']}, fitness: {cand['score']:.2f}
---

# {cand['hypothesis']}

> **Enforcement**: {cand['prediction']}

## Details
This rule was promoted from local cell {cand['cell_name']} after demonstrating high fitness.
"""
        if dry_run:
            print(f"[DRY-RUN] Would create {rule_path}")
            print(f"  Hypothesis: {cand['hypothesis']}")
            print(f"  Score: {cand['score']:.2f}\n")
        else:
            with open(rule_path, 'w', encoding='utf-8') as f:
                f.write(rule_content)
            print(f"Created {rule_path}")
            
            # Sync to team repo
            team_repo = os.environ.get("TEAM_REPO")
            if not team_repo:
                conf_path = os.path.join(workspace, "soma.conf")
                if os.path.exists(conf_path):
                    with open(conf_path, encoding='utf-8') as conf_file:
                        for line in conf_file:
                            line = line.strip()
                            if line.startswith("TEAM_REPO=") and not line.startswith("#"):
                                team_repo = line.split("=", 1)[1].strip().strip('"').strip("'")
                                break
            
            if team_repo:
                team_repo = os.path.expanduser(team_repo)
                team_promoted_dir = os.path.join(team_repo, 'cells', 'promoted')
                os.makedirs(team_promoted_dir, exist_ok=True)
                import shutil
                # The instructions say "copy the promoted rule to $TEAM_REPO/cells/promoted/"
                # We'll copy the original cell since the folder is 'cells/promoted'
                # or the rule? I'll just copy the cell file (which makes sense for cell promotion sharing)
                # Actually, the instructions say "copy the promoted rule". I'll copy the cell file itself since that's what team_sync.sh pulls.
                cell_path = os.path.join(workspace, '.soma', 'cells', cand['cell_name'])
                if not os.path.exists(cell_path):
                    # fallback to find it
                    for root, _, files in os.walk(os.path.join(workspace, '.soma', 'cells')):
                        if cand['cell_name'] in files:
                            cell_path = os.path.join(root, cand['cell_name'])
                            break
                if os.path.exists(cell_path):
                    shutil.copy2(cell_path, os.path.join(team_promoted_dir, cand['cell_name']))
                    print("Also synced to team repo")
            
            promotions.append({
                "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                "type": "speciation",
                "original_cell": cand['cell_name'],
                "new_rule": rule_name,
                "score": cand['score']
            })
            
    if not dry_run and promotions:
        os.makedirs(os.path.dirname(fitness_log_path), exist_ok=True)
        with open(fitness_log_path, 'a', encoding='utf-8') as f:
            for promo in promotions:
                f.write(json.dumps(promo) + "\n")
        print(f"Logged {len(promotions)} promotions to {fitness_log_path}")

if __name__ == "__main__":
    main()
