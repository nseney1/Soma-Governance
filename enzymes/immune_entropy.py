#!/usr/bin/env python3
"""Governance entropy rate: measure information production in the governance system."""
import os, sys, argparse, glob, json, math
try:
    import yaml
except ImportError:
    yaml = None
from datetime import datetime, timedelta
from soma_resolve import resolve_workspace


def main():
    parser = argparse.ArgumentParser(description='Governance entropy rate: detect fossilization vs adaptation')
    parser.add_argument('--json', action='store_true', help='JSON output')
    args = parser.parse_args()
    
    workspace = resolve_workspace(__file__)
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    metrics_dir = os.path.join(workspace, '.soma', 'metrics')
    
    # Load all cells and their trigger counts
    cells = []
    for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
        if os.path.basename(cell_file) == 'README.md': continue
        try:
            with open(cell_file, encoding="utf-8") as f: content = f.read()
            if not content.startswith('---'): continue
            fm = yaml.safe_load(content[3:content.find('---', 3)])
            cells.append({
                'name': os.path.splitext(os.path.basename(cell_file))[0],
                'type': fm.get('type', ''),
                'triggers': (fm.get('fitness') or {}).get('triggers', 0),
                'tp': (fm.get('fitness') or {}).get('true_positives', 0),
                'fp': (fm.get('fitness') or {}).get('false_positives', 0),
            })
        except Exception: pass
    
    if not cells:
        print('No cells found.')
        return
    
    # Trigger distribution entropy
    total_triggers = sum(c['triggers'] for c in cells)
    if total_triggers > 0:
        trigger_probs = [c['triggers'] / total_triggers for c in cells if c['triggers'] > 0]
        trigger_entropy = -sum(p * math.log2(p) for p in trigger_probs if p > 0)
        max_trigger_entropy = math.log2(len(cells)) if len(cells) > 1 else 1
        trigger_evenness = trigger_entropy / max_trigger_entropy if max_trigger_entropy > 0 else 0
    else:
        trigger_entropy = 0.0
        trigger_evenness = 0.0
    
    # Type distribution entropy
    type_counts = {}
    for c in cells:
        ct = c.get('type', 'unknown')
        type_counts[ct] = type_counts.get(ct, 0) + 1
    total_cells = len(cells)
    if len(type_counts) > 1:
        type_probs = [n / total_cells for n in type_counts.values()]
        type_entropy = -sum(p * math.log2(p) for p in type_probs if p > 0)
        max_type_entropy = math.log2(len(type_counts))
        type_evenness = type_entropy / max_type_entropy if max_type_entropy > 0 else 0
    else:
        type_entropy = 0.0
        type_evenness = 0.0
    
    # Activity analysis
    active_cells = sum(1 for c in cells if c['triggers'] > 0)
    dormant_cells = sum(1 for c in cells if c['triggers'] == 0)
    
    # Signal quality
    total_tp = sum(c['tp'] for c in cells)
    total_fp = sum(c['fp'] for c in cells)
    if total_tp + total_fp > 0:
        system_precision = total_tp / (total_tp + total_fp)
    else:
        system_precision = 0.0
    
    if total_tp > 0 and total_fp > 0:
        system_snr = 10 * math.log10(total_tp / total_fp)
    elif total_tp > 0:
        # None is the JSON-safe encoding of "infinite" (RFC 8259 forbids bare
        # Infinity); format_snr() in cell_fitness.py renders it as ∞ for humans.
        system_snr = None
    else:
        system_snr = 0.0
    
    # Diagnosis
    if trigger_evenness > 0.7:
        trigger_diagnosis = 'HEALTHY — triggers distributed across cells'
    elif trigger_evenness > 0.4:
        trigger_diagnosis = 'CONCENTRATING — a few cells dominate triggers'
    else:
        trigger_diagnosis = 'FOSSILIZING — triggers concentrated in 1-2 cells'
    
    if type_evenness > 0.7:
        type_diagnosis = 'DIVERSE — healthy mix of cell types'
    elif type_evenness > 0.4:
        type_diagnosis = 'IMBALANCED — some cell types underrepresented'
    else:
        type_diagnosis = 'MONOCULTURE — dangerous lack of type diversity'
    
    if dormant_cells > active_cells:
        activity_diagnosis = 'STAGNANT — more dormant than active cells'
    elif dormant_cells > active_cells * 0.5:
        activity_diagnosis = 'MIXED — significant dormant population'
    else:
        activity_diagnosis = 'ACTIVE — most cells are contributing'
    
    results = {
        'population': {'total': len(cells), 'active': active_cells, 'dormant': dormant_cells},
        'trigger_entropy': {
            'value': round(trigger_entropy, 4),
            'max_possible': round(max_trigger_entropy if total_triggers > 0 else 0, 4),
            'evenness': round(trigger_evenness, 4),
            'diagnosis': trigger_diagnosis
        },
        'type_entropy': {
            'value': round(type_entropy, 4),
            'evenness': round(type_evenness, 4),
            'distribution': type_counts,
            'diagnosis': type_diagnosis
        },
        'signal_quality': {
            'precision': round(system_precision, 4),
            'snr_db': round(system_snr, 1) if system_snr is not None else None,
            'total_tp': total_tp,
            'total_fp': total_fp
        },
        'activity_diagnosis': activity_diagnosis
    }
    
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f'\n\U0001f30d Governance Entropy Analysis\n')
        print(f'Population: {len(cells)} cells ({active_cells} active, {dormant_cells} dormant)')
        print(f'\nTrigger Entropy: {trigger_entropy:.3f} / {max_trigger_entropy if total_triggers > 0 else 0:.3f} bits (evenness: {trigger_evenness:.2f})')
        print(f'  {trigger_diagnosis}')
        print(f'\nType Entropy: {type_entropy:.3f} bits (evenness: {type_evenness:.2f})')
        for ct, count in sorted(type_counts.items()):
            bar = '\u2588' * count
            print(f'  {ct:<15} {bar} ({count})')
        print(f'  {type_diagnosis}')
        print(f'\nSignal Quality:')
        print(f'  Precision: {system_precision:.1%} ({total_tp} TP / {total_fp} FP)')
        snr_str = f'{system_snr:.1f} dB' if system_snr is not None else '\u221e dB (perfect)'
        print(f'  System SNR: {snr_str}')
        print(f'\nOverall: {activity_diagnosis}')


if __name__ == '__main__':
    main()
