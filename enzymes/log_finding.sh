#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/soma_python.sh"
soma_resolve_python || true

# log_finding.sh — Single entry point for governance finding logging.
# Replaces ad-hoc echo >> commands. Routes critical findings to pending_critical.md.
#
# Usage: log_finding.sh --severity <critical|warning|nit> --rule <rule> --change <change> --source <source>

SEVERITY=""
RULE=""
CHANGE=""
SOURCE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --severity) SEVERITY="$2"; shift 2 ;;
    --rule)     RULE="$2"; shift 2 ;;
    --change)   CHANGE="$2"; shift 2 ;;
    --source)   SOURCE="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$SEVERITY" || -z "$RULE" || -z "$CHANGE" || -z "$SOURCE" ]]; then
  echo "Usage: $0 --severity <critical|warning|nit> --rule <rule> --change <change> --source <source>" >&2
  exit 1
fi

SEVERITY=$(echo "$SEVERITY" | tr '[:upper:]' '[:lower:]')
LOGS_REPO="${HOME}/.gemini/antigravity/scratch/ai-conversation-logs"
AUTO_LOG="${LOGS_REPO}/governance/auto_applied_log.jsonl"
CRITICAL="${LOGS_REPO}/governance/pending_critical.md"
LOCK_FILE="${LOGS_REPO}/governance/.governance.lock"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

mkdir -p "${LOGS_REPO}/governance"

# Concurrency-safe write
(
  if command -v flock &>/dev/null; then
      flock -x 200
  else
      lock_dir="${LOCK_FILE}.d"
      retries=0
      while ! mkdir "$lock_dir" 2>/dev/null; do
          sleep 0.05; retries=$((retries + 1))
          [ "$retries" -ge 40 ] && { rm -rf "$lock_dir"; break; }
      done
      trap 'rm -rf "$lock_dir"' EXIT
  fi

  # 1. Append JSON record to audit log (safe serialization)
  if [ -n "${SOMA_PYTHON:-}" ]; then
    soma_py -c "
import json, sys
print(json.dumps({
    'timestamp': sys.argv[1],
    'severity': sys.argv[2],
    'rule': sys.argv[3],
    'change': sys.argv[4],
    'source': sys.argv[5]
}))" "$TIMESTAMP" "$SEVERITY" "$RULE" "$CHANGE" "$SOURCE" >> "$AUTO_LOG"
  else
    esc() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr '\n' ' '; }
    printf '{"timestamp":"%s","severity":"%s","rule":"%s","change":"%s","source":"%s"}\n' \
      "$(esc "$TIMESTAMP")" "$(esc "$SEVERITY")" "$(esc "$RULE")" "$(esc "$CHANGE")" "$(esc "$SOURCE")" >> "$AUTO_LOG"
  fi

  # 2. If critical, also append to pending_critical.md
  if [[ "$SEVERITY" == "critical" ]]; then
    printf '\n### 🔴 CRITICAL: %s (%s)\n- **Change**: %s\n- **Source**: %s\n' \
      "$RULE" "$TIMESTAMP" "$CHANGE" "$SOURCE" >> "$CRITICAL"
  fi
) 200>"$LOCK_FILE"

echo "✅ Logged $SEVERITY finding for $RULE"
