#!/usr/bin/env bash
set -euo pipefail

EXECUTE=false
if [[ "${1:-}" == "--execute" ]]; then
  EXECUTE="--execute"
fi

SCRIPT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/soma_python.sh"
soma_resolve_python || true
PYTHON_SCRIPT="$SCRIPT_DIR/cell_fitness.py"

# Wraps cell_fitness.py. If it doesn't exist yet, we parse it ourselves.
soma_py - "$EXECUTE" "$SCRIPT_DIR" << 'PYEOF'
import os, sys, re, json, datetime, shutil

execute_mode = len(sys.argv) > 1 and sys.argv[1] == '--execute'
script_dir = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()

# Walk up from CWD to find project root with .soma/cells/
def resolve_workspace():
    if os.environ.get("SOMA_ROOT") and os.path.isdir(os.environ.get("SOMA_ROOT")):
        return os.environ.get("SOMA_ROOT")
    d = os.getcwd()
    while d != os.path.dirname(d):
        if "/vendor/" in d or d.endswith("/vendor"):
            d = os.path.dirname(d)
            continue
        if os.path.isdir(os.path.join(d, ".soma", "cells")):
            return d
        d = os.path.dirname(d)
    return os.getcwd()

repo_root = resolve_workspace()

cells_dir = os.path.join(repo_root, ".soma", "cells")
archive_dir = os.path.join(cells_dir, ".archive")
evidence_dir = os.path.join(repo_root, ".soma", "evidence")
os.makedirs(evidence_dir, exist_ok=True)
fitness_log = os.path.join(evidence_dir, "lifecycle.jsonl")

if not os.path.exists(cells_dir):
    print("No cells directory found.")
    sys.exit(0)

print(f"Running cell selection (execute={execute_mode})...")

if execute_mode:
    os.makedirs(archive_dir, exist_ok=True)

for root, dirs, files in os.walk(cells_dir):
    if ".archive" in root: continue
    for f in files:
        if not f.endswith(".md") or f == "README.md": continue
        fpath = os.path.join(root, f)
        
        with open(fpath, 'r') as file:
            content = file.read()
            
        fm_match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL)
        if not fm_match: continue
        fm = fm_match.group(1)
        
        def get_val(key, default=0):
            m = re.search(fr'{key}:\s*(\S+)', fm)
            if m and m.group(1) != 'null': return float(m.group(1))
            return default
            
        triggers = get_val('triggers', 0)
        tp = get_val('true_positives', 0)
        fp = get_val('false_positives', 0)
        type_match = re.search(r'type:\s*([^\s\n]+)', fm)
        cell_type = type_match.group(1) if type_match else ''
        dormant = ('dormant_since' in fm)
        
        if triggers == 0:
            category = "DORMANT"
            score = 0.0
        else:
            score = tp / triggers
            if fp > 0 and tp > 0 and fp > 2 * tp:
                if cell_type == 'wall':
                    category = "APOPTOSIS_WARNING"
                else:
                    category = "APOPTOSIS"
            elif score > 0.7: category = "SURVIVE"
            elif score >= 0.3: category = "ADAPT"
            else: category = "EXTINCT"
            
        print(f"[{category}] {f} (Score: {score:.2f})")
        
        if execute_mode:
            action = None
            if category in ("EXTINCT", "APOPTOSIS"):
                if category == "APOPTOSIS":
                    last_gasp_dir = os.path.join(cells_dir, ".last_gasp_queue")
                    os.makedirs(last_gasp_dir, exist_ok=True)
                    dest = os.path.join(last_gasp_dir, f)
                    shutil.move(fpath, dest)
                    action = "last_gasp_requested"
                else:
                    dest = os.path.join(archive_dir, f)
                    shutil.move(fpath, dest)
                    action = "moved_to_archive"
                
                if action == "moved_to_archive":
                    # Save dormant spore
                    spores_file = os.path.join(cells_dir, ".spores.jsonl")
                    
                    def get_str(key):
                        m = re.search(fr"{key}:\s*(.+?)$", fm, re.MULTILINE)
                        return m.group(1).strip().strip("\"'") if m else ""
                    
                    name_val = get_str("name") or f.replace(".md", "")
                    type_val = get_str("type")
                    hypo_val = get_str("hypothesis")
                    
                    tp_list = []
                    tp_m = re.search(r"target_paths:\s*\[(.*?)\]", fm, re.DOTALL)
                    if tp_m:
                        tp_list = [p.strip().strip("\"'") for p in tp_m.group(1).split(",") if p.strip()]
                    
                    spore = {
                        "name": name_val,
                        "type": type_val,
                        "hypothesis": hypo_val,
                        "target_paths": tp_list,
                        "peak_fitness": score,
                        "extinction_date": datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "reactivation_patterns": tp_list
                    }
                    with open(spores_file, "a") as sf:
                        sf.write(json.dumps(spore) + "\n")
            elif category == "DORMANT" and not dormant:
                timestamp = datetime.datetime.now(timezone.utc).isoformat() + "Z"
                new_content = content.replace("fitness:", f"dormant_since: {timestamp}\nfitness:")
                with open(fpath, 'w') as file:
                    file.write(new_content)
                action = "marked_dormant"
                
            if action:
                with open(fitness_log, 'a') as log:
                    log.write(json.dumps({"timestamp": datetime.datetime.now(timezone.utc).isoformat() + "Z", "cell": f, "action": action}) + "\n")
PYEOF
