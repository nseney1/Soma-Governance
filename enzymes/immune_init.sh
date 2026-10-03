#!/usr/bin/env bash
set -euo pipefail

# Governance Init — PreInvocation hook
# Fires before every model call. On first invocation (and every 100th),
# checks for pending governance proposals.
#
# Alert routing:
#   🔴 Critical → LOUD alert, rotates pending_critical.md → last_critical.md
#   ℹ️  Non-critical → quiet alert ONLY if genuinely new findings exist (cursor-based)
#   ⚡ Preflight → coding project detected, prompt agent to run session-preflight
#   {} → silent if nothing new

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/common.sh"  # before the first Python call: soma_python (BUG-037)

INPUT=$(cat)
INVOCATION_NUM=$(echo "$INPUT" | soma_python -c "import sys,json; print(json.load(sys.stdin).get('invocationNum', 0))" 2>/dev/null || echo "0")

# Run on first invocation and every 100th invocation
if [ "$INVOCATION_NUM" != "1" ] && [ "$(( INVOCATION_NUM % 100 ))" != "0" ]; then
    echo '{}'
    exit 0
fi

RESOLVED_HOME=$(resolve_home)

SOMA_CONF="${SOMA_CONF:-$RESOLVED_HOME/.gemini/antigravity/scratch/soma/soma.conf}"
if [ -f "$SOMA_CONF" ]; then
    source "$SOMA_CONF"
fi

DEFAULT_REVIEW_MODE=${DEFAULT_REVIEW_MODE:-gale}
MINIMUM_REVIEW_MODE=${MINIMUM_REVIEW_MODE:-breeze}

LOGS_REPO="${SOMA_LOGS_DIR:-$RESOLVED_HOME/.gemini/antigravity/scratch/ai-conversation-logs}"
CRITICAL="$LOGS_REPO/governance/pending_critical.md"
LAST_CRITICAL="$LOGS_REPO/governance/last_critical.md"
AUTO_LOG="$LOGS_REPO/governance/auto_applied_log.jsonl"
CURSOR_FILE="$LOGS_REPO/governance/.last_seen_audit_lines"
LOCK_FILE="$LOGS_REPO/governance/.governance.lock"
SCRIPT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPORT_SCRIPT="$SCRIPT_DIR/export_logs.sh"

# Run log export async (non-blocking)
if [ -x "$EXPORT_SCRIPT" ]; then
    bash "$EXPORT_SCRIPT" > /dev/null 2>&1 &
fi

# ── Project Detection (Invocation 1 only, outside flock) ─────────────────
PREFLIGHT_STEPS="[]"
if [ "$INVOCATION_NUM" = "1" ]; then
    PREFLIGHT_STEPS=$(echo "$INPUT" | soma_python -c "
import json, os, sys

try:
    data = json.load(sys.stdin)
except Exception:
    print('[]')
    sys.exit(0)

ws_list = data.get('workspacePaths', [])
target = ws_list[0] if ws_list else ''
steps = []

# Skip governance repos and empty workspaces
if not target or any(k in target for k in ['soma', 'ai-conversation-logs']):
    print('[]')
    sys.exit(0)

# Detect coding project markers
is_python = any(os.path.exists(os.path.join(target, f)) for f in ['venv', '.venv', 'requirements.txt', 'pyproject.toml'])
is_node = os.path.exists(os.path.join(target, 'package.json'))
has_makefile = os.path.exists(os.path.join(target, 'Makefile'))
has_tests = os.path.exists(os.path.join(target, 'tests'))

markers = []
if is_python: markers.append('python')
if is_node: markers.append('node')
if has_makefile: markers.append('Makefile')
if has_tests: markers.append('tests/')

# E3: Auto-preflight for coding projects
if is_python or is_node:
    marker_str = ', '.join(markers)
    steps.append({
        'ephemeralMessage': f'⚡ PREFLIGHT: Coding project detected at {target} ({marker_str}). Per session-preflight skill, verify venv health, git status, and test suite before modifying files.'
    })

# E6: Domain researcher hint for game/automation projects
domain_hint = ''
target_lower = target.lower()
if any(k in target_lower for k in ['tab', 'billions']):
    domain_hint = 'They Are Billions'
elif any(k in target_lower for k in ['dwarf', 'fortress']):
    domain_hint = 'Dwarf Fortress'

# Deep probe: check requirements.txt for automation libs
if is_python and not domain_hint:
    req_path = os.path.join(target, 'requirements.txt')
    if os.path.exists(req_path):
        try:
            reqs = open(req_path).read().lower()
            if any(lib in reqs for lib in ['pyautogui', 'pynput', 'xdotool', 'pygame']):
                domain_hint = 'Game automation'
            elif any(lib in reqs for lib in ['torch', 'stable-baselines', 'gymnasium', 'ray']):
                domain_hint = 'RL/ML'
        except Exception:
            pass

if domain_hint:
    steps.append({
        'ephemeralMessage': f'⚡ DOMAIN: {domain_hint} project detected. Domain preset available in domain-researcher skill for verified external lookups.'
    })

# Component 1: Vacuoles
vacuoles_dir = os.path.join(target, '.soma/cells/vacuoles')
if os.path.exists(vacuoles_dir):
    vacuoles = []
    import glob, re
    for v in glob.glob(os.path.join(vacuoles_dir, '*.md')):
        try:
            with open(v) as f:
                content = f.read()
                m = re.search(r'^## Trap:\s*(.*)', content, re.MULTILINE)
                if m:
                    triggers = 0
                    tm = re.search(r'triggers:\s*(\d+)', content)
                    if tm:
                        triggers = int(tm.group(1))
                    vacuoles.append((triggers, m.group(1).strip()))
        except Exception:
            pass
    if vacuoles:
        vacuoles.sort(key=lambda x: x[0], reverse=True)
        trap_names = [v[1] for v in vacuoles[:5]]
        trap_str = ", ".join(f"[{t}]" for t in trap_names)
        steps.append({
            'ephemeralMessage': f'⚠️ KNOWN TRAPS: {trap_str}'
        })

print(json.dumps(steps))
" 2>/dev/null || echo "[]")
fi

# ── Governance Alert Checks (under flock) ────────────────────────────────
GOV_STEPS="[]"
if [ -d "$LOGS_REPO/governance" ]; then
    GOV_STEPS=$(
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

        # 1. Check for critical findings
        if [ -f "$CRITICAL" ] && [ -s "$CRITICAL" ]; then
            FINDING_COUNT=$(grep -c "🔴" "$CRITICAL" 2>/dev/null || echo "1")

            # Rotate: pending → last (user can cat last_critical.md)
            cp -f "$CRITICAL" "$LAST_CRITICAL"
            : > "$CRITICAL"

            # Update cursor so we don't double-alert non-critical
            if [ -f "$AUTO_LOG" ]; then
                wc -l < "$AUTO_LOG" > "$CURSOR_FILE"
            fi

            echo "[{\"ephemeralMessage\": \"🔴 GOVERNANCE: $FINDING_COUNT critical change(s) were AUTO-APPLIED to your steering rules. Review: cat $LAST_CRITICAL\"}]"
        else
            # 2. Check for genuinely new non-critical findings (cursor-based)
            NEW_FINDINGS=0
            if [ -f "$AUTO_LOG" ]; then
                TOTAL_LINES=$(wc -l < "$AUTO_LOG")
                LAST_SEEN=0
                if [ -f "$CURSOR_FILE" ]; then
                    LAST_SEEN=$(cat "$CURSOR_FILE" 2>/dev/null || echo "0")
                fi
                NEW_FINDINGS=$((TOTAL_LINES - LAST_SEEN))
            fi

            if [ "$NEW_FINDINGS" -gt 0 ]; then
                # Update cursor
                echo "$TOTAL_LINES" > "$CURSOR_FILE"
                echo "[{\"ephemeralMessage\": \"ℹ️ Governance: $NEW_FINDINGS non-critical finding(s) auto-applied since last session. Audit: tail -$NEW_FINDINGS $AUTO_LOG\"}]"
            else
                echo "[]"
            fi
        fi
    ) 200>"$LOCK_FILE"
else
    GOV_STEPS="[]"
fi

# ── Merge all steps into single response ─────────────────────────────────
MERGED=$(soma_python -c "
import json, sys
preflight = json.loads(sys.argv[1])
gov = json.loads(sys.argv[2])
all_steps = preflight + gov
if all_steps:
    print(json.dumps({'injectSteps': all_steps}))
else:
    print('{}')
" "$PREFLIGHT_STEPS" "$GOV_STEPS" 2>/dev/null || echo "{}")

echo "$MERGED"

# === Homeostatic Governance ===
# Read recent waste rate and adjust review intensity suggestion
if [ -d "$RESOLVED_HOME/.gemini/antigravity/scratch/ai-conversation-logs/governance" ]; then
  RECENT_WASTE=$(soma_python -c "
import os, json, glob
gov_dir = os.path.expanduser('$RESOLVED_HOME/.gemini/antigravity/scratch/ai-conversation-logs/governance')
sweeps = sorted(glob.glob(os.path.join(gov_dir, '*.json')))[-5:]  # last 5 sessions
if not sweeps:
    print('unknown')
else:
    rates = []
    for f in sweeps:
        try:
            with open(f) as fh:
                data = json.load(fh)
                rate = data.get('waste_rate', data.get('waste_pct'))
                if rate is not None:
                    rates.append(float(rate))
        except Exception: pass
    if rates:
        avg = sum(rates) / len(rates)
        if avg < 5:
            print('low')     # Can relax governance
        elif avg > 15:
            print('high')    # Should tighten governance
        else:
            print('normal')
    else:
        print('unknown')
" 2>/dev/null || echo 'unknown')

  case "$RECENT_WASTE" in
    low)
      echo "  📊 Homeostasis: Recent waste rate <5%. Consider Breeze/Gale for routine changes." >&2
      ;;
    high)
      echo "  ⚠️ Homeostasis: Recent waste rate >15%. Recommend Trident+ for all changes." >&2
      ;;
    normal)
      echo "  📊 Homeostasis: Waste rate nominal (5-15%). Standard review protocol." >&2
      ;;
  esac
fi

# === Escalation Sentinel ===
if [ -f "$SCRIPT_DIR/escalation_sentinel.sh" ]; then
  SENTINEL_RESULT=$(bash "$SCRIPT_DIR/escalation_sentinel.sh" 2>/dev/null || echo '')
  RECOMMENDED_MODE=$(echo "$SENTINEL_RESULT" | soma_python -c "
import sys
result = {}
for line in sys.stdin:
    line = line.strip()
    if '=' in line:
        key, _, val = line.partition('=')
        result[key.strip()] = val.strip()
print(result.get('PROTOCOL', result.get('recommended_mode', 'gale')))
" 2>/dev/null || echo 'gale')
  echo "  Escalation sentinel recommends: $RECOMMENDED_MODE" >&2
fi
