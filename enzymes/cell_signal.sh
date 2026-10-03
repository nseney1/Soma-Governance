#!/usr/bin/env bash
# Soma - External Fitness Signal API
# Allows external systems to feed fitness signals back to cells.
# Usage:
#   bash enzymes/cell_signal.sh <cell_id> tp [--metric key=value]
#   bash enzymes/cell_signal.sh <cell_id> fp
#   bash enzymes/cell_signal.sh <cell_id> fn

set -euo pipefail

# Symlink-safe pattern to resolve repository directory
# Walk up from CWD to find project root with .soma/cells/
if [ -n "${SOMA_ROOT:-}" ] && [ -d "$SOMA_ROOT" ]; then
  REPO_DIR="$SOMA_ROOT"
else
  _d="$(pwd)"
  REPO_DIR="$_d"
  while [ "$_d" != "/" ]; do
    if [[ "$_d" == */vendor/* ]] || [[ "$_d" == */vendor ]]; then
      _d="$(dirname "$_d")"
      continue
    fi
    if [ -d "$_d/.soma/cells" ]; then
      REPO_DIR="$_d"
      break
    fi
    _d="$(dirname "$_d")"
  done
fi
# Source common utilities from this script's directory (soma_python, BUG-037).
# Follow symlinks first: a dirname of the link would miss enzymes/common.sh.
PRG="${BASH_SOURCE[0]}"
while [ -h "$PRG" ]; do
  DIR="$(cd -P "$(dirname "$PRG")" && pwd)"
  PRG="$(readlink "$PRG")"
  [[ $PRG != /* ]] && PRG="$DIR/$PRG"
done
source "$(cd -P "$(dirname "$PRG")" && pwd)/common.sh"

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 <cell_id> <tp|fp|fn> [--metric key=value] [--stress]"
  exit 2
fi

CELL_ID="$1"
OUTCOME="$2"
shift 2

METRIC_KEY=""
METRIC_VAL=""
STRESS="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --metric)
      if [ "$#" -ge 2 ]; then
        METRIC_KEY="${2%%=*}"
        METRIC_VAL="${2#*=}"
        shift 2
      else
        shift
      fi
      ;;
    --stress)
      STRESS="true"
      shift
      ;;
    *)
      shift
      ;;
  esac
done

if [[ "$OUTCOME" != "tp" && "$OUTCOME" != "fp" && "$OUTCOME" != "fn" ]]; then
  echo "Error: Outcome must be tp, fp, or fn."
  exit 2
fi

CELLS_DIR="$REPO_DIR/.soma/cells"
if [ ! -d "$CELLS_DIR" ]; then
  echo "Error: Directory $CELLS_DIR not found."
  exit 1
fi

# Find cell matches
MATCHES=()
while IFS= read -r line; do
  [ -n "$line" ] && MATCHES+=("$line")
done <<< "$(find "$CELLS_DIR" -type f -name "*${CELL_ID}*")"
if [ ${#MATCHES[@]} -eq 0 ]; then
  echo "Error: No cells found matching '$CELL_ID' in $CELLS_DIR."
  exit 1
elif [ ${#MATCHES[@]} -gt 1 ]; then
  echo "Error: Multiple cells matched '$CELL_ID':"
  for m in "${MATCHES[@]}"; do
    echo "  - $(basename "$m")"
  done
  exit 1
fi

TARGET_CELL="${MATCHES[0]}"
# Use the actual cell ID (basename without extension) for the metrics file
CELL_BASENAME="$(basename "$TARGET_CELL" .md)"
METRICS_FILE="$REPO_DIR/.soma/metrics/${CELL_BASENAME}.jsonl"

PYTHON_HELPER=$(cat << 'EOF'
import sys
import json
import yaml
from datetime import datetime
from datetime import timezone
import os

file_path = sys.argv[1]
outcome = sys.argv[2]
metric_key = sys.argv[3]
metric_val = sys.argv[4]
metrics_file = sys.argv[5]
stress = True if sys.argv[6] == 'true' else False

try:
    with open(file_path, 'r') as f:
        content = f.read()
except Exception as e:
    print(f"Error reading {file_path}: {e}")
    sys.exit(1)

if not content.startswith('---'):
    print(f"Error: {file_path} lacks YAML frontmatter")
    sys.exit(1)

end_idx = content.find('---', 3)
if end_idx == -1:
    print(f"Error: {file_path} has malformed YAML frontmatter")
    sys.exit(1)

frontmatter_str = content[3:end_idx].strip()
body_str = content[end_idx+3:]

try:
    metadata = yaml.safe_load(frontmatter_str) or {}
except Exception as e:
    print(f"Error parsing YAML: {e}")
    sys.exit(1)

if 'fitness' not in metadata:
    metadata['fitness'] = {}

fitness = metadata['fitness']
triggers = fitness.get('triggers', 0)
tp = fitness.get('true_positives', 0)
fp = fitness.get('false_positives', 0)

old_score = (tp / triggers) if triggers > 0 else 0.0

if outcome == 'tp':
    triggers += 1
    tp += 1
elif outcome == 'fp':
    triggers += 1
    fp += 1
elif outcome == 'fn':
    triggers += 1

new_score = (tp / triggers) if triggers > 0 else 0.0
fitness['triggers'] = triggers
fitness['true_positives'] = tp
fitness['false_positives'] = fp
fitness['score'] = new_score
fitness['last_trigger_date'] = datetime.now(timezone.utc).isoformat() + "Z"

if stress:
    fitness['stress_survived'] = fitness.get('stress_survived', 0) + 1

metadata['fitness'] = fitness

try:
    with open(file_path, 'w') as f:
        f.write("---\n")
        yaml.dump(metadata, f, default_flow_style=False, sort_keys=False)
        f.write("---\n")
        # To avoid duplicating newlines if body_str already starts with one
        if body_str.startswith('\n'):
            f.write(body_str[1:])
        else:
            f.write(body_str)
except Exception as e:
    print(f"Error writing to {file_path}: {e}")
    sys.exit(1)

cell_name = os.path.basename(file_path)
# Output summary as requested
print(f"Cell {cell_name}: {outcome} recorded. Score: {old_score:.2f} -> {new_score:.2f} (triggers: {triggers})")

if metric_key:
    try:
        os.makedirs(os.path.dirname(metrics_file), exist_ok=True)
        metric_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "outcome": outcome,
            metric_key: metric_val
        }
        with open(metrics_file, 'a') as mf:
            mf.write(json.dumps(metric_entry) + "\n")
    except Exception as e:
        print(f"Warning: Failed to write to metrics file {metrics_file}: {e}")
EOF
)

soma_python -c "$PYTHON_HELPER" "$TARGET_CELL" "$OUTCOME" "$METRIC_KEY" "$METRIC_VAL" "$METRICS_FILE" "$STRESS"
