#!/usr/bin/env bash
set -euo pipefail

# Session Close — Stop hook
# Exports conversation logs and syncs both repos when session ends.

# Symlink-safe resolution (Thorns fix #3). Must run before common.sh is
# sourced: a lexical dirname of a symlinked hook names the link's directory.
PRG="${BASH_SOURCE[0]}"
while [ -h "$PRG" ]; do
  DIR="$(cd -P "$(dirname "$PRG")" && pwd)"
  PRG="$(readlink "$PRG")"
  [[ $PRG != /* ]] && PRG="$DIR/$PRG"
done
SCRIPT_DIR="$(cd -P "$(dirname "$PRG")" && pwd)"
source "$SCRIPT_DIR/common.sh"
RESOLVED_HOME=$(resolve_home)

# Resolve repo root relative to this script (enzymes/ -> repo root)
STEERING_REPO="$(cd -P "$SCRIPT_DIR/.." && pwd)"
# Inline snippets run without the CWD on sys.path (BUG-044), so soma_core is
# imported from the steering repo explicitly, not from whatever the CWD is.
export SOMA_STEERING_REPO="$STEERING_REPO"
LOGS_REPO="$RESOLVED_HOME/.gemini/antigravity/scratch/ai-conversation-logs"
EXPORT_SCRIPT="$STEERING_REPO/enzymes/export_logs.sh"

# Clean stale git locks (only if no process is actively using them)
for repo in "$STEERING_REPO" "$LOGS_REPO"; do
    lock="$repo/.git/index.lock"
    if [ -f "$lock" ]; then
        if command -v fuser > /dev/null 2>&1; then
            if ! fuser "$lock" > /dev/null 2>&1; then
                rm -f -- "$lock"
            fi
        elif command -v lsof > /dev/null 2>&1; then
            if ! lsof "$lock" > /dev/null 2>&1; then
                rm -f -- "$lock"
            fi
        fi
    fi
done

# Export logs
if [ -x "$EXPORT_SCRIPT" ]; then
    bash "$EXPORT_SCRIPT" > /dev/null 2>&1 || true
fi

# Push steering repo if dirty (catches any rule edits made during session)
if [ -d "$STEERING_REPO/.git" ]; then
    cd "$STEERING_REPO"
    # Safe branch detection (Thorns fix #10): skip push if detached HEAD
    CURRENT_BRANCH=$(git symbolic-ref --short -q HEAD 2>/dev/null || true)
    if [ -n "$CURRENT_BRANCH" ] && [ -n "$(git status --porcelain 2>/dev/null)" ]; then
        git add . && git commit -m "chore(sync): auto-sync on session close: $(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date +"%Y-%m-%dT%H:%M:%S")" && git push origin "$CURRENT_BRANCH" 2>/dev/null || true
    fi
fi

echo '{}'


# === Automated Outcome Feedback ===
echo "Running outcome engine..."
SCRIPTS_DIR="$SCRIPT_DIR"
soma_py "$SCRIPTS_DIR/outcome_engine.py" 2>/dev/null || true

# === Automated Cell Evolution ===
echo "Running cell evolution..."

# 1. Evaluate fitness with telomere shortening decay
soma_py "$SCRIPTS_DIR/cell_fitness.py" 2>/dev/null || true

# 2. Run selection pressure (archive extinct cells)
bash "$SCRIPTS_DIR/cell_selection.sh" --execute 2>/dev/null || true

# 3. Probabilistic crossover: if >5 cells with fitness >0.5, attempt one crossover
CROSSOVER_CANDIDATES=$(soma_py -c "
import os, glob, sys
sys.path.insert(0, os.environ['SOMA_STEERING_REPO'])
import yaml
from soma_core.evidence import aggregate_signals

cells = glob.glob(os.path.join(os.getcwd(), '.soma', 'cells', '**', '*.md'), recursive=True)
high_fitness = []
evidence_dir = os.path.join(os.getcwd(), '.soma', 'evidence')
# Canonical aggregation reads signals.jsonl; only its trigger dimension applies here.
signal_counts = aggregate_signals(evidence_dir).counts
cell_triggers = {
    cell_id: counts['triggers']
    for cell_id, counts in signal_counts.items()
    if counts['has_triggers']
}
for cid, count in cell_triggers.items():
    if count >= 5:
        high_fitness.append(cid)
if len(high_fitness) >= 2:
    import random
    pair = random.sample(high_fitness, 2)
    print(f'{pair[0]} {pair[1]}')
else:
    print('')
" 2>/dev/null || echo '')

if [ -n "$CROSSOVER_CANDIDATES" ]; then
  read -r CELL_A CELL_B <<< "$CROSSOVER_CANDIDATES"
  echo "  Attempting crossover: $CELL_A × $CELL_B"
  soma_py "$SCRIPTS_DIR/cell_crossover.py" "$CELL_A" "$CELL_B" 2>/dev/null || true
fi

# 4. Check for metamorphosis candidates
soma_py -c "
import os, glob, sys
sys.path.insert(0, os.environ['SOMA_STEERING_REPO'])
import yaml
from soma_core.evidence import aggregate_signals

cells = glob.glob(os.path.join(os.getcwd(), '.soma', 'cells', '**', '*.md'), recursive=True)
evidence_dir = os.path.join(os.getcwd(), '.soma', 'evidence')
# Canonical aggregation reads signals.jsonl; only its trigger dimension applies here.
signal_counts = aggregate_signals(evidence_dir).counts
cell_triggers = {
    cell_id: counts['triggers']
    for cell_id, counts in signal_counts.items()
    if counts['has_triggers']
}
for f in cells:
    if os.path.basename(f) == 'README.md': continue
    try:
        with open(f) as fh: content = fh.read()
        if not content.startswith('---'): continue
        fm = yaml.safe_load(content[3:content.find('---',3)])
        ctype = fm.get('type', '')
        name = os.path.splitext(os.path.basename(f))[0]
        triggers = cell_triggers.get(fm.get('id', name), 0)
        if ctype == 'vacuole' and triggers >= 20:
            print(f'  Metamorphosis candidate: {name} (vacuole→wall, triggers={triggers})')
        elif ctype == 'wall' and triggers >= 25:
            print(f'  Metamorphosis candidate: {name} (wall→rule, triggers={triggers})')
    except Exception: pass
" 2>/dev/null || true

# === Stochastic Genesis (Diversity Injection) ===
soma_py "$SCRIPTS_DIR/cell_genesis_stochastic.py" 2>/dev/null || true

# === Mulch → Cell Pipeline ===
MULCH_QUEUE="$(pwd)/.soma/governance/mulch_queue.jsonl"
if [ -f "$MULCH_QUEUE" ] && [ -s "$MULCH_QUEUE" ]; then
    echo "  Processing mulch queue..."
    MULCH_COUNT=0
    while IFS= read -r line; do
        NAME=$(echo "$line" | soma_py -c "import sys,json; print(json.load(sys.stdin).get('name','mulch-cell'))" 2>/dev/null || echo 'mulch-cell')
        HYPO=$(echo "$line" | soma_py -c "import sys,json; print(json.load(sys.stdin).get('hypothesis',''))" 2>/dev/null || echo '')
        PRED=$(echo "$line" | soma_py -c "import sys,json; print(json.load(sys.stdin).get('prediction','Mulch hypothesis will reduce defect recurrence'))" 2>/dev/null || echo 'Mulch hypothesis will reduce defect recurrence')
        FALS=$(echo "$line" | soma_py -c "import sys,json; print(json.load(sys.stdin).get('falsification','Defect pattern recurs with equal frequency'))" 2>/dev/null || echo 'Defect pattern recurs with equal frequency')
        if [ -n "$HYPO" ]; then
            bash "$SCRIPTS_DIR/cell_create.sh" --id "$NAME" --type vacuole --hypothesis "$HYPO" --prediction "$PRED" --falsification "$FALS" 2>/dev/null && MULCH_COUNT=$((MULCH_COUNT + 1)) || true
        fi
    done < "$MULCH_QUEUE"
    mv "$MULCH_QUEUE" "$MULCH_QUEUE.processed"
    echo "  Created $MULCH_COUNT cells from mulch findings."
fi

# === Session Dashboard ===
soma_py -c "
import os, glob, sys
sys.path.insert(0, os.environ['SOMA_STEERING_REPO'])
import yaml
from soma_core.evidence import aggregate_signals

cells_dir = os.path.join(os.getcwd(), '.soma', 'cells')
if not os.path.isdir(cells_dir):
    exit(0)

evidence_dir = os.path.join(os.getcwd(), '.soma', 'evidence')
# Canonical aggregation reads signals.jsonl; only its trigger dimension applies here.
signal_counts = aggregate_signals(evidence_dir).counts
cell_triggers = {
    cell_id: counts['triggers']
    for cell_id, counts in signal_counts.items()
    if counts['has_triggers']
}

cells = glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True)
active = extinct = 0
for f in cells:
    if os.path.basename(f) == 'README.md': continue
    try:
        with open(f) as fh: content = fh.read()
        if not content.startswith('---'): continue
        fm = yaml.safe_load(content[3:content.find('---',3)])
        name = fm.get('id', os.path.splitext(os.path.basename(f))[0])
        triggers = cell_triggers.get(name, 0)
        if triggers > 0:
            active += 1
        else:
            extinct += 1
    except Exception: pass

print()
print('\u2554' + '\u2550'*50 + '\u2557')
print('\u2551  \U0001f4ca Governance Session Summary' + ' '*21 + '\u2551')
print('\u2560' + '\u2550'*50 + '\u2563')
print(f'\u2551  Active Cells:     {active:<30}\u2551')
print(f'\u2551  Extinct Cells:    {extinct:<30}\u2551')
print(f'\u2551  Total Population:  {active+extinct:<29}\u2551')
print('\u255a' + '\u2550'*50 + '\u255d')
" 2>/dev/null || true

echo "Cell evolution complete."
