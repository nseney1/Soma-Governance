#!/usr/bin/env python3
import argparse
import glob
import json
import os
from datetime import datetime
from datetime import timezone

try:
    import yaml
except ImportError:
    yaml = None
from bayesian_score import bayesian_score
from soma_resolve import resolve_workspace


def bayesian_fitness(tp, fp, confidence=0.90):
    """Beta-Binomial posterior with Jeffrey's prior."""
    a = tp + 0.5
    b = fp + 0.5
    mean = a / (a + b)
    import math
    std = math.sqrt((a * b) / ((a + b) ** 2 * (a + b + 1)))
    z = 1.645
    lower = max(0, mean - z * std)
    upper = min(1, mean + z * std)
    certainty = 'low' if (tp + fp) < 5 else 'medium' if (tp + fp) < 20 else 'high'
    return {
        'mean': round(mean, 4),
        'lower_90': round(lower, 4),
        'upper_90': round(upper, 4),
        'certainty': certainty
    }

def antifragile_bonus(metadata):
    """Cells gain +5% fitness per survived high-intensity review."""
    stress_events = metadata.get('fitness', {}).get('stress_survived', 0)
    return 1.0 + (0.05 * min(stress_events, 10))

def format_snr(value):
    """Render an SNR value for human-readable table output.

    `snr_db` is None in the JSON payload when SNR is infinite (true positives
    with zero false positives) because RFC 8259 has no `Infinity` literal.
    Only the table output renders the infinity symbol.
    """
    if value is None:
        return '\u221e'
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return str(value)


def decayed_fitness(raw_score, last_trigger_date, telomere_days=30):
    if last_trigger_date is None or raw_score is None:
        return raw_score
    days_since = (datetime.now() - last_trigger_date).days
    decay_factor = 0.5 ** (days_since / telomere_days)
    return round(raw_score * decay_factor, 4)

def main():
    parser = argparse.ArgumentParser(description="Compute fitness of immune cells")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--prune", action="store_true", help="List cells recommended for removal")
    parser.add_argument("--promote", action="store_true", help="List cells ready for cross-repo promotion")
    parser.add_argument("--cross-repo", action="store_true", help="Aggregate fitness across multiple repos in METRICS_REPO")
    parser.add_argument("--bayesian", action="store_true", help="Output bayesian estimates")
    args = parser.parse_args()


    workspace = resolve_workspace(__file__)
    total_sessions = 30
    conf_path = os.path.join(workspace, "soma.conf")
    if os.path.exists(conf_path):
        with open(conf_path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("TOTAL_SESSIONS="):
                    try:
                        total_sessions = int(line.strip().split("=", 1)[1])
                    except Exception:
                        pass

    cells_dir = os.path.join(workspace, '.soma', 'cells')
    cell_files = glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True)

    results = []

    for file_path in cell_files:
        if os.path.basename(file_path) == 'README.md':
            continue
        
        with open(file_path, 'r', encoding='utf-8') as f:
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
        
        cell_name = os.path.basename(file_path)
        cell_type = metadata.get('type', 'unknown')
        fitness = metadata.get('fitness', {})
        if isinstance(fitness, (int, float)):
            fitness = {'score': float(fitness)}
            metadata['fitness'] = fitness
        triggers = fitness.get('triggers', 0)
        tp = fitness.get('true_positives', 0)
        fp = fitness.get('false_positives', 0)
        impact_weight = metadata.get('impact_weight', 1.0)
        

        if triggers == 0:
            # Bayesian posterior mean: Beta(1,1) → 0.5 (maximally uncertain)
            score = bayesian_score(0, 0, impact_weight)
            snr_db = 0.0
            is_unobserved = True
        else:
            # Bayesian posterior mean: Beta(tp+1, fp+1) / Laplace smoothing
            # Converges to raw tp/triggers as triggers increase
            score = bayesian_score(tp, triggers, impact_weight)
            is_unobserved = False
            
            trigger_rate = triggers / max(total_sessions, 1)
            specificity_penalty = 1.0 - min(trigger_rate, 1.0)
            if trigger_rate > 0.8:
                score = score * specificity_penalty
                
            score = score * antifragile_bonus(metadata)
            
            import math
            if tp > 0 and fp > 0:
                snr_db = round(10 * math.log10(tp / fp), 1)
            elif tp > 0:
                # tp > 0 and fp == 0 -> SNR is mathematically infinite.
                # float('inf') would make json.dumps emit a bare `Infinity`,
                # which RFC 8259 forbids; strict non-Python MCP clients reject
                # the frame. None is the JSON-safe encoding of "infinite";
                # format_snr() renders it as the infinity symbol for humans.
                snr_db = None
            else:
                snr_db = 0.0

            
        last_trigger_date_str = fitness.get('last_trigger_date')
        last_trigger_date = None
        if last_trigger_date_str:
            try:
                # Handle ISO format strings
                last_trigger_date = datetime.fromisoformat(last_trigger_date_str.replace('Z', '+00:00')).replace(tzinfo=None)
            except Exception:
                pass
                
        type_upper = cell_type.upper()
        hl_val = os.environ.get(f'CELL_TELOMERE_{type_upper}')
        if hl_val is None:
            hl_val = os.environ.get('CELL_TELOMERE_DAYS', '30')
            
        if hl_val == 'null':
            dec_score = score
        else:
            telomere_days = int(hl_val)
            dec_score = decayed_fitness(score, last_trigger_date, telomere_days)
            
        expiry_days = metadata.get('expiry_days')
        created_str = metadata.get('created')
        status = "NEW"
        

        # Apoptosis: immediate eviction if false positives dominate
        if fp > 0 and tp > 0 and fp > 2 * tp:
            if cell_type == 'wall':
                status = "APOPTOSIS_WARNING"
            else:
                status = "APOPTOSIS"

        elif not is_unobserved and dec_score is not None:
            if dec_score > 0.7:
                status = "SURVIVE"
            elif 0.3 <= dec_score <= 0.7:
                status = "ADAPT"
            else:
                status = "EXTINCT"
        else:
            if expiry_days and created_str:
                try:
                    fmt = "%Y-%m-%dT%H:%M:%SZ" if 'T' in created_str else "%Y-%m-%d"
                    created_date = datetime.strptime(created_str, fmt)
                    current_date = datetime.now()
                    days_since_created = (current_date - created_date).days
                    if days_since_created > expiry_days:
                        status = "DORMANT"
                    else:
                        status = "NEW"
                except Exception:
                    status = "NEW"

        decay_to = metadata.get('decay_to')
        if status in ("EXTINCT", "DORMANT") and decay_to:
            new_type = decay_to.get('type', 'membrane')
            metadata['type'] = new_type
            metadata['impact_weight'] = decay_to.get('impact_weight', 1.0)
            metadata['minimum_mode'] = decay_to.get('minimum_mode', 'trident')
            if 'response_type' in decay_to:
                metadata['response_type'] = decay_to['response_type']
            if 'activation' in decay_to:
                metadata['activation'] = decay_to['activation']
            del metadata['decay_to']
            
            if 'fitness' not in metadata:
                metadata['fitness'] = {}
            metadata['fitness']['score'] = 0.5
            metadata['fitness']['triggers'] = 0
            metadata['fitness']['true_positives'] = 0
            metadata['fitness']['false_positives'] = 0
            
            status = "DECAYING"
            
            metrics_dir = os.path.join(workspace, '.soma', 'metrics')
            os.makedirs(metrics_dir, exist_ok=True)
            with open(os.path.join(metrics_dir, 'decay_transitions.jsonl'), 'a', encoding='utf-8') as mf:
                mf.write(json.dumps({
                    'timestamp': datetime.now(timezone.utc).isoformat() + "Z",
                    'cell_id': cell_name,
                    'from_type': cell_type,
                    'to_type': new_type
                }) + '\n')

        # Enhanced fitness with independent outcome signal
        enforcement = metadata.get('enforcement', 'advisory')
        tier_weights = {'advisory': 1.0, 'mechanical': 1.2, 'gate': 1.5}
        tier_weight = tier_weights.get(enforcement, 1.0)
        
        # Load escaped defect rate
        escaped_defects_log = os.path.join(workspace, '.soma', 'metrics', 'escaped_defects.jsonl')
        escaped_count = 0
        if os.path.exists(escaped_defects_log):
            with open(escaped_defects_log, encoding='utf-8') as edf:
                for eline in edf:
                    try:
                        eentry = json.loads(eline.strip())
                        if eentry.get('cell') == os.path.splitext(cell_name)[0]:
                            escaped_count += 1
                    except Exception:
                        continue
        
        edr = escaped_count / (escaped_count + tp) if (escaped_count + tp) > 0 else 0.0
        enhanced_score = round(score * (1 - edr) * tier_weight, 4) if score is not None else None

        res = {
            "cell": cell_name,
            "type": cell_type,
            "hypothesis": metadata.get('hypothesis', ''),
            "triggers": triggers,
            "tp": tp,
            "fp": fp,
            "score": score,
            "decayed_score": dec_score,
            "status": status,
            "snr_db": snr_db,
            "enforcement": enforcement,
            "escaped_defects": escaped_count,
            "escaped_defect_rate": edr,
            "enhanced_fitness": enhanced_score
        }
        if args.bayesian:
            res['bayesian'] = bayesian_fitness(tp, fp)
        results.append(res)

    if args.prune:
        results = [r for r in results if r['status'] in ("EXTINCT", "DORMANT")]
    elif args.promote:
        results = [r for r in results if r['score'] is not None and r['score'] > 0.7 and r.get('triggers', 0) > 0]

    if args.cross_repo:
        def resolve_metrics_dir(workspace):
            team_repo = os.environ.get("TEAM_REPO")
            team_member = os.environ.get("TEAM_MEMBER_ID", "local_user")
            metrics_repo = os.environ.get("METRICS_REPO")
            if not team_repo or not metrics_repo:
                conf_path = os.path.join(workspace, "soma.conf")
                if os.path.exists(conf_path):
                    with open(conf_path, encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("TEAM_REPO=") and not line.startswith("#"):
                                team_repo = line.split("=", 1)[1].strip().strip('"').strip("'")
                            elif line.startswith("TEAM_MEMBER_ID=") and not line.startswith("#"):
                                team_member = line.split("=", 1)[1].strip().strip('"').strip("'")
                            elif line.startswith("METRICS_REPO=") and not line.startswith("#"):
                                metrics_repo = line.split("=", 1)[1].strip().strip('"').strip("'")
            if team_repo:
                # We return the root of snapshots so we can scan */*
                path = os.path.join(os.path.expanduser(team_repo), "snapshots")
                return path
            if metrics_repo:
                return os.path.expanduser(metrics_repo)
            return os.path.join(workspace, "docs", "snapshots")
            
    
        workspace = resolve_workspace(__file__)
        total_sessions = 30
        conf_path = os.path.join(workspace, "soma.conf")
        if os.path.exists(conf_path):
            with open(conf_path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("TOTAL_SESSIONS="):
                        try:
                            total_sessions = int(line.strip().split("=", 1)[1])
                        except Exception:
                            pass

            metrics_dir = resolve_metrics_dir(workspace)
        
            # Look for JSON files in metrics_dir that might be cell fitness snapshots
            # A cell fitness snapshot is assumed to contain a list of objects with 'hypothesis', 'score', and 'repo'
            # or we infer repo from filename if 'repo' is missing.
            snapshots = glob.glob(os.path.join(metrics_dir, '**', '*.json'), recursive=True)
        
            # Group by hypothesis
            hypothesis_stats = {}
            for snap in snapshots:
                try:
                    with open(snap, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if not isinstance(data, list):
                        continue
                    
                    # Infer repo from filename if not in data: e.g. "repoA-fitness.json"
                    filename = os.path.basename(snap)
                    inferred_repo = filename.split('-')[0] if '-' in filename else filename.split('.')[0]
                
                    for item in data:
                        if 'hypothesis' in item and 'score' in item and item['score'] is not None:
                            hyp = item['hypothesis']
                            repo = item.get('repo', inferred_repo)
                            if hyp not in hypothesis_stats:
                                hypothesis_stats[hyp] = {'repos': set(), 'scores': []}
                            hypothesis_stats[hyp]['repos'].add(repo)
                            hypothesis_stats[hyp]['scores'].append(item['score'])
                except Exception:
                    continue
                
            cross_repo_results = []
            for hyp, stats in hypothesis_stats.items():
                avg_score = sum(stats['scores']) / len(stats['scores']) if stats['scores'] else 0
                repos_count = len(stats['repos'])
                candidate = "Yes" if avg_score > 0.7 and repos_count >= 3 else "No"
                cross_repo_results.append({
                    "hypothesis": hyp,
                    "repos": repos_count,
                    "avg_fitness": avg_score,
                    "candidate": candidate
                })
            
            if args.json:
                print(json.dumps(cross_repo_results, indent=2))
            else:
                print(f"{'Cell Hypothesis':<50} | {'Repos':<5} | {'Avg Fitness':<11} | {'Candidate?':<10}")
                print("-" * 85)
                for r in cross_repo_results:
                    hyp = r['hypothesis']
                    if len(hyp) > 47:
                        hyp = hyp[:44] + "..."
                    print(f"{hyp:<50} | {r['repos']:<5} | {r['avg_fitness']:<11.2f} | {r['candidate']:<10}")
        return


    if args.json:
        print(json.dumps(results, indent=2))
    else:
        if args.bayesian:
            print(f"{'Cell':<20} | {'Type':<12} | {'Tier':<10} | {'Triggers':<8} | {'TP':<4} | {'FP':<4} | {'Esc':<3} | {'EnhFit':<6} | {'Raw':<6} | {'Status':<10} | {'Bayesian Mean':<13} | {'SNR':<5}")
            print("-" * 130)
            for r in results:
                score_str = f"{r['score']:.2f}" if r['score'] is not None else "null"
                enh_str = f"{r['enhanced_fitness']:.2f}" if r['enhanced_fitness'] is not None else "null"
                bayes_mean = f"{r['bayesian']['mean']:.2f} ({r['bayesian']['certainty']})" if 'bayesian' in r else ""
                snr_str = format_snr(r.get('snr_db', 0.0))
                print(f"{r['cell']:<20} | {r['type']:<12} | {r.get('enforcement', 'advisory'):<10} | {r['triggers']:<8} | {r['tp']:<4} | {r['fp']:<4} | {r.get('escaped_defects', 0):<3} | {enh_str:<6} | {score_str:<6} | {r['status']:<10} | {bayes_mean:<13} | {snr_str:<5}")
        else:
            print(f"{'Cell':<20} | {'Type':<12} | {'Tier':<10} | {'Triggers':<8} | {'TP':<4} | {'FP':<4} | {'Esc':<3} | {'EnhFit':<6} | {'Raw':<6} | {'Status':<10} | {'SNR':<5}")
            print("-" * 110)
            for r in results:
                score_str = f"{r['score']:.2f}" if r['score'] is not None else "null"
                enh_str = f"{r['enhanced_fitness']:.2f}" if r['enhanced_fitness'] is not None else "null"
                snr_str = format_snr(r.get('snr_db', 0.0))
                print(f"{r['cell']:<20} | {r['type']:<12} | {r.get('enforcement', 'advisory'):<10} | {r['triggers']:<8} | {r['tp']:<4} | {r['fp']:<4} | {r.get('escaped_defects', 0):<3} | {enh_str:<6} | {score_str:<6} | {r['status']:<10} | {snr_str:<5}")


if __name__ == "__main__":
    main()
