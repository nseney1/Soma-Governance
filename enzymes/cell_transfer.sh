#!/usr/bin/env bash
# cell_transfer.sh: Copies a cell to another project with fitness reset.
# Usage: bash enzymes/cell_transfer.sh <cell_id> --to /path/to/target/project

if [[ -f "enzymes/common.sh" ]]; then
  source "enzymes/common.sh"
fi

CELL_ID=""
TARGET_DIR=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --to)
      TARGET_DIR="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: bash enzymes/cell_transfer.sh <cell_id> --to /path/to/target/project"
      exit 0
      ;;
    *)
      if [[ -z "$CELL_ID" ]]; then
        CELL_ID="$1"
        shift
      else
        echo "Unknown option: $1"
        exit 1
      fi
      ;;
  esac
done

if [[ -z "$CELL_ID" || -z "$TARGET_DIR" ]]; then
  echo "Error: Missing cell_id or --to directory"
  echo "Usage: bash enzymes/cell_transfer.sh <cell_id> --to /path/to/target/project"
  exit 1
fi

SOURCE_CELL=$(find "$REPO_DIR/.soma/cells" -type f -name "*${CELL_ID}*.md" | head -n 1)

if [[ -z "$SOURCE_CELL" ]]; then
  echo "Error: Cell matching '${CELL_ID}' not found in $REPO_DIR/.soma/cells/"
  exit 1
fi

if [[ ! -d "$TARGET_DIR/.soma" ]] && [[ ! -d "$TARGET_DIR/.prism" ]]; then
  echo "Error: Target directory does not have a .soma/ directory."
  echo "Suggest running 'install --local' in the target directory first."
  exit 1
fi

FILENAME=$(basename "$SOURCE_CELL")
TARGET_BASENAME=$(basename "$TARGET_DIR")
SOURCE_BASENAME=$(basename "$PWD")

python3 -c "
try:
    import yaml
except ImportError:
    yaml = None
import sys
import os
import json
from datetime import datetime
from datetime import timezone

source_file = sys.argv[1]
target_dir = sys.argv[2]
source_basename = sys.argv[3]
target_basename = sys.argv[4]
filename = os.path.basename(source_file)

with open(source_file, 'r') as f:
    content = f.read()
    
if not content.startswith('---'):
    print('Error: Cell does not have YAML frontmatter.')
    sys.exit(1)
    
end_idx = content.find('---', 3)
frontmatter_str = content[3:end_idx].strip()
body_str = content[end_idx+3:]

metadata = yaml.safe_load(frontmatter_str) or {}
cell_type = metadata.get('type')
if not cell_type:
    # infer from path
    if 'vacuoles' in source_file: cell_type = 'vacuole'
    elif 'chloroplasts' in source_file: cell_type = 'chloroplast'
    elif 'walls' in source_file: cell_type = 'wall'
    elif 'membranes' in source_file: cell_type = 'membrane'
    elif 'plasmodesmata' in source_file: cell_type = 'plasmodesmata'
    else: cell_type = 'vacuole'

# pluralize
plural_type = f'{cell_type}s'
target_path = os.path.join(target_dir, '.soma', 'cells', plural_type)
os.makedirs(target_path, exist_ok=True)
dest_file = os.path.join(target_path, filename)

# Reset fitness and add transfer metadata
if 'fitness' not in metadata:
    metadata['fitness'] = {}
metadata['fitness']['triggers'] = 0
metadata['fitness']['true_positives'] = 0
metadata['fitness']['false_positives'] = 0
metadata['fitness']['score'] = None
metadata['expiry_sessions'] = 5

metadata['transferred_from'] = source_basename
metadata['transfer_date'] = datetime.now(timezone.utc).isoformat() + 'Z'

gen = metadata.get('lineage', {}).get('generation', 0) if isinstance(metadata.get('lineage'), dict) else 0
metadata['lineage'] = {
    'parent_id': os.path.splitext(filename)[0],
    'created_by': 'transfer',
    'generation': gen + 1,
    'siblings': []
}

with open(dest_file, 'w') as f:
    f.write('---\n')
    yaml.dump(metadata, f, default_flow_style=False, sort_keys=False)
    f.write('---\n')
    if body_str.startswith('\n'):
        f.write(body_str[1:])
    else:
        f.write(body_str)

# Log to metrics (in source project)
metrics_dir = '.soma/metrics'
os.makedirs(metrics_dir, exist_ok=True)
transfers_log = os.path.join(metrics_dir, 'transfers.jsonl')

log_entry = {
    'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
    'cell': filename,
    'target_project': target_basename
}

with open(transfers_log, 'a') as f:
    f.write(json.dumps(log_entry) + '\n')
" "$SOURCE_CELL" "$TARGET_DIR" "$SOURCE_BASENAME" "$TARGET_BASENAME"

echo "Transferred: $CELL_ID -> $TARGET_BASENAME (fitness reset, 5-session probation)"
exit 0
