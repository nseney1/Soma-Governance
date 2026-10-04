#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/common.sh"
RESOLVED_HOME=$(resolve_home)

# Safety Gate — PreToolUse hook
# Gates destructive run_command operations. Returns force_ask for dangerous patterns.
# Output contract: {"decision": "allow"} or {"decision": "force_ask", "reason": "..."}
# Latency target: <100ms (pure bash, no subshells in hot path)

# Emergency bypass: operator can disable the gate entirely
if [ "${STEERING_SAFETY_GATE:-}" = "disabled" ]; then
    echo '{"decision": "allow"}'
    exit 0
fi

INPUT=$(cat)
CMD=$(echo "$INPUT" | soma_py -c "
import sys, json
data = json.load(sys.stdin)
tc = data.get('toolCall', {})
args = tc.get('args', {})
print(args.get('CommandLine', ''))
" 2>/dev/null || echo "")

# Fail-closed: if we can't parse the command or it's empty, force ask
if [ -z "$CMD" ]; then
    cat <<'RESPONSE'
{
  "decision": "force_ask",
  "reason": "🛡️ Safety Gate: Unable to parse command — requesting confirmation"
}
RESPONSE
    exit 0
fi

# Destructive patterns
BLOCKED=false
REASON=""

# --- File system destruction ---

# rm: catch -rf, -r -f, -fr, --recursive, and rmdir with ignore flag
if echo "$CMD" | grep -qE 'rm[[:space:]]+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|-r[[:space:]]+-f|-f[[:space:]]+-r|--recursive)[[:space:]]+(/|~|/home|\$HOME)'; then
    BLOCKED=true
    REASON="Recursive delete targeting home/root directory"
fi

if echo "$CMD" | grep -qE 'rmdir[[:space:]]+--ignore-fail-on-non-empty'; then
    BLOCKED=true
    REASON="rmdir with --ignore-fail-on-non-empty — bypasses safety check"
fi

# mkfs — formatting a filesystem
if echo "$CMD" | grep -qE '(^|[^[:alnum:]_])mkfs([^[:alnum:]_]|$)'; then
    BLOCKED=true
    REASON="Filesystem format (mkfs) detected — destructive operation"
fi

# dd if= — raw disk write
if echo "$CMD" | grep -qE '(^|[^[:alnum:]_])dd[[:space:]]+.*if='; then
    BLOCKED=true
    REASON="Raw disk write (dd) detected — destructive operation"
fi

# chmod 777 — overly permissive
if echo "$CMD" | grep -qE 'chmod[[:space:]]+777'; then
    BLOCKED=true
    REASON="chmod 777 — overly permissive, potential security risk"
fi

# kill -9 -1 — kill all processes
if echo "$CMD" | grep -qE 'kill[[:space:]]+-9[[:space:]]+-1'; then
    BLOCKED=true
    REASON="kill -9 -1 — would kill all user processes"
fi

# --- Privilege escalation ---

# sudo — any sudo invocation
if echo "$CMD" | grep -qE '(^|[^[:alnum:]_])sudo([^[:alnum:]_]|$)'; then
    BLOCKED=true
    REASON="sudo detected — elevated privileges require confirmation"
fi

# --- Remote code execution ---

# curl|sh, wget|sh patterns
if echo "$CMD" | grep -qE 'curl[[:space:]].*\|.*sh|wget[[:space:]].*\|.*sh'; then
    BLOCKED=true
    REASON="Piping remote content to shell — potential code execution risk"
fi

# --- Git destructive operations ---

# Force push: --force, -f flag, or +refspec
if echo "$CMD" | grep -qE 'git[[:space:]]+push[[:space:]]+.*(-f|--force|--force-with-lease)'; then
    BLOCKED=true
    REASON="Force push detected — destructive-ops mandate requires confirmation"
fi

if echo "$CMD" | grep -qE 'git[[:space:]]+push[[:space:]]+[^[:space:]]+[[:space:]]+\+'; then
    BLOCKED=true
    REASON="Force push via +refspec detected — destructive-ops mandate requires confirmation"
fi

# Git reset --hard
if echo "$CMD" | grep -qE 'git[[:space:]]+reset[[:space:]]+--hard'; then
    BLOCKED=true
    REASON="Hard reset — will discard uncommitted changes"
fi

# Git checkout -f (force checkout, discards local changes)
if echo "$CMD" | grep -qE 'git[[:space:]]+checkout[[:space:]]+-f'; then
    BLOCKED=true
    REASON="Force checkout — will discard uncommitted changes"
fi

# Git clean -fdx (removes untracked files and directories)
if echo "$CMD" | grep -qE 'git[[:space:]]+clean[[:space:]]+.*-[a-zA-Z]*f'; then
    BLOCKED=true
    REASON="git clean -f — will permanently remove untracked files"
fi

# Bulk git staging without dry-run: git add -A, git add ., git add --all, git add *
if echo "$CMD" | grep -qE 'git[[:space:]]+add[[:space:]]+(-A|\.|\./?|\*|--all)([[:space:]]|$|[;&|>)])'; then
    BLOCKED=true
    REASON="Bulk staging (git add -A/./*/--all) — run git status first to verify file count"
fi

# --- Database destructive operations ---

if echo "$CMD" | grep -qiE '(DROP[[:space:]]+(TABLE|DATABASE)|DELETE[[:space:]]+FROM[[:space:]]+[[:alnum:]_]+[[:space:]]*|TRUNCATE[[:space:]]+TABLE)'; then
    BLOCKED=true
    REASON="Destructive database operation without WHERE clause"
fi

# --- Logging ---

GATE_LOG="${SOMA_LOGS_DIR:-$RESOLVED_HOME/.gemini/antigravity/scratch/ai-conversation-logs}/governance/gate_events.jsonl"
GATE_LOG_DIR="$(dirname "$GATE_LOG")"

# Create log directory if missing (graceful)
if [ ! -d "$GATE_LOG_DIR" ]; then
    mkdir -p "$GATE_LOG_DIR" 2>/dev/null || true
fi

# Safe JSON logger — prevents command injection via python3 json.dumps
log_gate_event() {
  local decision="$1" reason="${2:-}" cmd_snippet redacted_cmd
  redacted_cmd=$(echo "$CMD" | sed \
    -e 's/AKIA[0-9A-Z]\{16\}/AKIA_REDACTED/g' \
    -e 's/ghp_[a-zA-Z0-9]\{36\}/ghp_REDACTED/g' \
    -e 's/github_pat_[a-zA-Z0-9_]\{20,\}/github_pat_REDACTED/g' \
    -e 's/sk-[a-zA-Z0-9]\{20,\}/sk-REDACTED/g' \
    -e 's/AIzaSy[a-zA-Z0-9_-]\{33\}/AIzaSy_REDACTED/g' \
    -e 's/Bearer [a-zA-Z0-9._-]\{20,\}/Bearer REDACTED/g' \
    -e 's/GEMINI_API_KEY=[^ ]*/GEMINI_API_KEY=REDACTED/g')
  cmd_snippet="$(echo "$redacted_cmd" | head -c 200)"
  if [ -n "${SOMA_PYTHON:-}" ]; then
    soma_py -c "
import json, sys
obj = {'timestamp': sys.argv[1], 'command': sys.argv[2], 'decision': sys.argv[3]}
if sys.argv[4]: obj['reason'] = sys.argv[4]
print(json.dumps(obj))
" "$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date +"%Y-%m-%dT%H:%M:%S")" "$cmd_snippet" "$decision" "$reason" >> "$GATE_LOG" 2>/dev/null || true
  else
    # Fallback: escape double quotes manually
    cmd_snippet="$(echo "$cmd_snippet" | sed 's/"/\\"/g')"
    local ts
    ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date +"%Y-%m-%dT%H:%M:%S")"
    echo "{\"timestamp\":\"$ts\",\"command\":\"$cmd_snippet\",\"decision\":\"$decision\",\"reason\":\"${reason:-}\"}" >> "$GATE_LOG" 2>/dev/null || true
  fi
}

if [ "$BLOCKED" = true ]; then
    log_gate_event "BLOCKED" "$REASON"
    cat <<RESPONSE
{
  "decision": "force_ask",
  "reason": "🛡️ Safety Gate: $REASON"
}
RESPONSE
else
    log_gate_event "ALLOWED" ""
    echo '{"decision": "allow"}'
fi
