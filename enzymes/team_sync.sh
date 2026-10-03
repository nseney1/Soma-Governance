#!/usr/bin/env bash
set -euo pipefail

# Symlink-safe resolution
PRG="${BASH_SOURCE[0]}"
while [ -h "$PRG" ]; do
  DIR="$(cd -P "$(dirname "$PRG")" && pwd)"
  PRG="$(readlink "$PRG")"
  [[ $PRG != /* ]] && PRG="$DIR/$PRG"
done
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
SCRIPTS_DIR="$REPO_DIR/enzymes"
# If scripts dir doesn't exist at resolved root, fall back to original script location
[ ! -d "$SCRIPTS_DIR" ] && SCRIPTS_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "$SCRIPTS_DIR/common.sh"
load_config "$REPO_DIR"

COMMAND="${1:-status}"

if [ -z "${TEAM_REPO:-}" ]; then
  echo "TEAM_REPO not configured."
  echo "Please set it in soma.conf (see soma.conf.example)."
  exit 0
fi

TEAM_MEMBER_ID="${TEAM_MEMBER_ID:-local_user}"
TEAM_REPO="${TEAM_REPO/#\~/$HOME}"
ORG_REPO="${ORG_REPO/#\~/$HOME}"
METRICS_REPO="${METRICS_REPO:-$REPO_DIR/docs/snapshots}"
METRICS_REPO="${METRICS_REPO/#\~/$HOME}"

case "$COMMAND" in
  push)
    echo "Syncing local promoted cells to team repo ($TEAM_REPO)..."
    mkdir -p "$TEAM_REPO/cells/promoted"
    mkdir -p "$TEAM_REPO/snapshots/$TEAM_MEMBER_ID"
    
    soma_python -c "
import json
import sys
import shutil
import os
import subprocess

repo_dir = sys.argv[1]
team_repo = sys.argv[2]
org_repo = sys.argv[3] if len(sys.argv) > 3 else ''
member_id = sys.argv[4]

cells_dir = os.path.join(repo_dir, '.soma', 'cells')
promoted_dir = os.path.join(team_repo, 'cells', 'promoted')

# 1. Cells
try:
    res = subprocess.run([sys.executable, os.path.join(repo_dir, 'enzymes', 'cell_fitness.py'), '--json'], capture_output=True, text=True)
    if res.returncode == 0:
        data = json.loads(res.stdout)
        for item in data:
            if item.get('score') is not None and item.get('score') > 0.85:
                cell_name = item['cell']
                src = os.path.join(cells_dir, cell_name)
                # Ensure we find the cell in subdirectories if needed
                if not os.path.exists(src):
                    for root, _, files in os.walk(cells_dir):
                        if cell_name in files:
                            src = os.path.join(root, cell_name)
                            break
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(promoted_dir, cell_name))
                    print(f'Promoted: {cell_name}')
                    if org_repo:
                        org_promoted_dir = os.path.join(org_repo, 'cells', 'promoted')
                        os.makedirs(org_promoted_dir, exist_ok=True)
                        shutil.copy2(src, os.path.join(org_promoted_dir, cell_name))
except Exception as e:
    print(f'Error syncing cells: {e}')

" "$REPO_DIR" "$TEAM_REPO" "${ORG_REPO:-}" "$TEAM_MEMBER_ID"

    # 2. Metrics snapshots
    echo "Syncing metrics snapshot..."
    bash "$SCRIPTS_DIR/metrics_snapshot.sh" > /dev/null 2>&1 || true
    # Find newest snapshot in the local metrics dir
    LATEST_SNAP=$(find "$METRICS_REPO" -maxdepth 1 -type f -name "*.json" | sort -r | head -n 1 || true)
    if [ -n "$LATEST_SNAP" ]; then
      cp "$LATEST_SNAP" "$TEAM_REPO/snapshots/$TEAM_MEMBER_ID/"
    fi
    
    # 3. Git push
    cd "$TEAM_REPO"
    if [ -d ".git" ]; then
      git add cells/promoted snapshots/"$TEAM_MEMBER_ID"
      git commit -m "chore(sync): update promoted cells and metrics for $TEAM_MEMBER_ID" || true
      git push || true
    fi
    
    if [ -n "${ORG_REPO:-}" ] && [ -d "$ORG_REPO/.git" ]; then
      cd "$ORG_REPO"
      git add cells/promoted
      git commit -m "chore(sync): update org promoted cells from $TEAM_MEMBER_ID" || true
      git push || true
    fi
    
    echo "Push complete."
    ;;
    
  pull)
    echo "Pulling cells from team repo ($TEAM_REPO)..."
    if [ -d "$TEAM_REPO/.git" ]; then
      cd "$TEAM_REPO"
      git pull || true
    fi
    
    if [ -n "${ORG_REPO:-}" ] && [ -d "$ORG_REPO/.git" ]; then
      cd "$ORG_REPO"
      git pull || true
    fi
    
    # Copy from TEAM_REPO and ORG_REPO to local
    soma_python -c "
import os
import sys
import shutil

repo_dir = sys.argv[1]
team_repo = sys.argv[2]
org_repo = sys.argv[3] if len(sys.argv) > 3 else ''

local_cells_dir = os.path.join(repo_dir, '.soma', 'cells')
os.makedirs(local_cells_dir, exist_ok=True)

existing_cells = set()
for root, _, files in os.walk(local_cells_dir):
    for f in files:
        existing_cells.add(f)

def pull_cells(src_dir, source_label):
    if not os.path.exists(src_dir):
        return
    for f in os.listdir(src_dir):
        if f.endswith('.md') and f not in existing_cells:
            src_path = os.path.join(src_dir, f)
            dest_path = os.path.join(local_cells_dir, f)
            
            # Read content and inject source frontmatter if not present
            with open(src_path, 'r') as file:
                content = file.read()
                
            if 'source:' not in content:
                content = content.replace('---\n', f'---\nsource: {source_label}\n', 1)
                
            with open(dest_path, 'w') as file:
                file.write(content)
            
            print(f'Pulled: {f} (from {source_label})')
            existing_cells.add(f)

pull_cells(os.path.join(team_repo, 'cells', 'promoted'), 'team')
if org_repo:
    pull_cells(os.path.join(org_repo, 'cells', 'promoted'), 'org')

" "$REPO_DIR" "$TEAM_REPO" "${ORG_REPO:-}"
    echo "Pull complete."
    ;;
    
  status)
    soma_python -c "
import os
import sys
import json
import subprocess

repo_dir = sys.argv[1]
team_repo = sys.argv[2]
org_repo = sys.argv[3] if len(sys.argv) > 3 else ''

local_cells = 0
local_cells_dir = os.path.join(repo_dir, '.soma', 'cells')
for root, _, files in os.walk(local_cells_dir):
    local_cells += sum(1 for f in files if f.endswith('.md'))

team_cells = 0
team_promoted = os.path.join(team_repo, 'cells', 'promoted')
if os.path.exists(team_promoted):
    team_cells = sum(1 for f in os.listdir(team_promoted) if f.endswith('.md'))

org_cells = 0
if org_repo:
    org_promoted = os.path.join(org_repo, 'cells', 'promoted')
    if os.path.exists(org_promoted):
        org_cells = sum(1 for f in os.listdir(org_promoted) if f.endswith('.md'))

print(f'Local cells: {local_cells}')
print(f'Team cells ({team_repo}): {team_cells}')
if org_repo:
    print(f'Org cells ({org_repo}): {org_cells}')

try:
    res = subprocess.run([sys.executable, os.path.join(repo_dir, 'enzymes', 'cell_fitness.py'), '--json'], capture_output=True, text=True)
    if res.returncode == 0:
        data = json.loads(res.stdout)
        eligible = [item['cell'] for item in data if item.get('score') is not None and item.get('score') > 0.85]
        print(f'Cells eligible for promotion: {len(eligible)}')
except Exception:
    pass
" "$REPO_DIR" "$TEAM_REPO" "${ORG_REPO:-}"
    ;;
    
  *)
    echo "Usage: bash enzymes/team_sync.sh [push|pull|status]"
    exit 1
    ;;
esac
