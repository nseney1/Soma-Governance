#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# Governance Sweep — Periodic lower-priority governance check
#
# Checks:
#   1. Unreviewed sessions (>100 steps, no metrics)
#   2. Warning-level finding trends
#   3. Metrics recomputation
#   4. Active session monitoring (>50 steps, modified recently)
#   5. Gate event summary
#
# Outputs:
#   - New session_metrics/*.json files for unreviewed sessions
#   - Updated pending_proposals.md if actionable items found
#   - Appends to sweep_log.jsonl
#
# Usage:
#   bash enzymes/immune_sweep.sh                    # Full sweep
#   bash enzymes/immune_sweep.sh --active-only      # Only check active sessions
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"
RESOLVED_HOME=$(resolve_home)

# Configurable data directory — defaults to Antigravity location
SOMA_DATA_DIR="${SOMA_DATA_DIR:-$RESOLVED_HOME/.gemini/antigravity}"
GOVERNANCE_DIR="$SOMA_DATA_DIR/scratch/ai-conversation-logs/governance"
BRAIN_DIR="$SOMA_DATA_DIR/brain"
METRICS_DIR="$GOVERNANCE_DIR/session_metrics"
SWEEP_LOG="$GOVERNANCE_DIR/sweep_log.jsonl"
PROPOSALS="$GOVERNANCE_DIR/pending_proposals.md"
TAXONOMY="$GOVERNANCE_DIR/taxonomy.json"
SWEEP_SCANNER="$SCRIPT_DIR/sweep_session.py"
# The sweep log and proposals are appended to and session_metrics/ is written
# to; on a fresh home neither directory exists yet. (METRICS_DIR is inside
# GOVERNANCE_DIR, so this creates both.)
mkdir -p "$METRICS_DIR"

ACTIVE_ONLY="${1:-}"
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# Counters
sessions_scanned=0
metrics_generated=0
warnings_tallied=0
active_flagged=0

echo "🔄 Governance Sweep — $TIMESTAMP"
echo ""

# ── Check 1: Unreviewed Sessions ──────────────────────────────────────────

if [ "$ACTIVE_ONLY" != "--active-only" ]; then
  echo "📋 Check 1: Scanning for unreviewed sessions (>100 steps)..."

  for brain_dir in "$BRAIN_DIR"/*/; do
    [ ! -d "$brain_dir" ] && continue

    session_id="$(basename "$brain_dir")"
    short_id="${session_id:0:8}"
    transcript="$brain_dir/.system_generated/logs/transcript.jsonl"
    metrics_file="$METRICS_DIR/${short_id}.json"

    # Skip if no transcript
    [ ! -f "$transcript" ] && continue

    # Skip if metrics already exist
    [ -f "$metrics_file" ] && continue

    # Count steps
    step_count="$(wc -l < "$transcript" 2>/dev/null | tr -d ' ' || echo 0)"

    # Only process sessions with >100 steps
    if [ "$step_count" -gt 100 ]; then
      echo "  🔍 $short_id ($step_count steps) — generating metrics..."
      if soma_py "$SWEEP_SCANNER" "$transcript" > "$metrics_file" 2>/dev/null; then
        metrics_generated=$((metrics_generated + 1))
        echo "  ✅ $short_id: metrics generated"
      else
        echo "  ⚠️  $short_id: scan failed"
        rm -f "$metrics_file"
      fi
      sessions_scanned=$((sessions_scanned + 1))
    fi
  done

  echo "  Done: $sessions_scanned scanned, $metrics_generated metrics generated"
  echo ""
fi

# ── Check 2: Warning Trends ──────────────────────────────────────────────

echo "📋 Check 2: Tallying warning-level findings..."

AUDIT_LOG="$GOVERNANCE_DIR/auto_applied_log.jsonl"
warning_report=""

if [ -f "$AUDIT_LOG" ] && [ -s "$AUDIT_LOG" ]; then
  # Count warnings by rule
  warning_tally="$(soma_py -c "
import json, sys
from collections import Counter

counts = Counter()
with open(sys.argv[1]) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if entry.get('severity') == 'warning':
                counts[entry.get('rule', 'unknown')] += 1
        except json.JSONDecodeError:
            continue

for rule, count in counts.most_common():
    flag = '⚠️  CONSIDER HARDENING' if count >= 3 else ''
    print(f'  {count}x {rule} {flag}')
    sys.stdout.flush()
" "$AUDIT_LOG" 2>/dev/null || echo "  (parse error)")"

  warnings_tallied="$(echo "$warning_tally" | wc -l)"
  echo "$warning_tally"

  # Check for rules with 3+ warnings
  hardening_candidates="$(echo "$warning_tally" | grep "CONSIDER HARDENING" || true)"
  if [ -n "$hardening_candidates" ]; then
    warning_report="$hardening_candidates"
  fi
else
  echo "  (no audit log entries)"
fi
echo ""

# ── Check 3: Metrics Recomputation ───────────────────────────────────────

echo "📋 Check 3: Recomputing aggregate metrics..."

metrics_summary="$(soma_py -c "
import json, os, sys, glob

metrics_dir = sys.argv[1]
total_steps = 0
total_waste = 0
session_count = 0
deep_sessions = 0
sweep_sessions = 0

for f in sorted(glob.glob(os.path.join(metrics_dir, '*.json'))):
    try:
        with open(f) as fh:
            m = json.load(fh)
        if 'total_steps' not in m:
            continue  # Skip non-session files (backups, schemas)
        steps = int(m.get('total_steps', 0))
        # Polymorphic extraction: prefer nested dict, fallback to flat
        flat_waste = m.get('wasted_steps')
        nested_waste = None
        if isinstance(m.get('waste'), dict):
            nested_waste = m['waste'].get('total_wasted_steps')
        # Use nested if flat is missing or zero-but-nested-is-nonzero
        if nested_waste is not None and (flat_waste is None or flat_waste == 0):
            waste = int(nested_waste)
        elif flat_waste is not None:
            waste = int(flat_waste)
        else:
            waste = 0
        
        is_sweep = m.get('scan_type') == 'lightweight_sweep' or m.get('review_tier') == 'heuristic_sweep'
        if is_sweep:
            sweep_sessions += 1
        else:
            deep_sessions += 1
            
        total_steps += steps
        total_waste += waste
        session_count += 1
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        continue

rate = round(total_waste / total_steps * 100, 1) if total_steps > 0 else 0
print(f'  Sessions: {session_count} (deep: {deep_sessions}, sweep: {sweep_sessions})')
print(f'  Total steps: {total_steps:,}')
print(f'  Total waste: {total_waste:,} ({rate}%)')
" "$METRICS_DIR" 2>/dev/null || echo "  (computation error)")"

echo "$metrics_summary"
echo ""

# ── Check 4: Active Session Monitoring ───────────────────────────────────

echo "📋 Check 4: Checking active sessions (modified in last 2 hours)..."

active_report=""
# NUL-delimited, read on fd 3 via process substitution: `for t in $(find ...)`
# split paths on spaces, a `find | while` pipeline would lose active_flagged /
# active_report in a subshell, and fd 3 keeps the list away from the loop
# body's stdin. (bash 3.2 compatible.)
while IFS= read -r -d '' transcript <&3; do
  step_count="$(wc -l < "$transcript" 2>/dev/null | tr -d ' ' || echo 0)"
  if [ "$step_count" -gt 50 ]; then
    rel="${transcript#"$BRAIN_DIR"/}"
    session_id="${rel%%/*}"
    short_id="${session_id:0:8}"

    summary="$(soma_py "$SWEEP_SCANNER" "$transcript" --summary-only 2>/dev/null || echo "{}")"
    waste_rate="$(echo "$summary" | soma_py -c "import json,sys; print(json.load(sys.stdin).get('waste_rate',0))" 2>/dev/null || echo "0")"
    top_pattern="$(echo "$summary" | soma_py -c "import json,sys; print(json.load(sys.stdin).get('top_pattern','unknown'))" 2>/dev/null || echo "unknown")"

    # Convert to percentage for comparison
    waste_pct="$(soma_py -c "import sys; print(int(float(sys.argv[1]) * 100))" "$waste_rate" 2>/dev/null || echo "0")"

    if [ "$waste_pct" -gt 15 ]; then
      echo "  ⚠️  $short_id: ${step_count} steps, ~${waste_pct}% waste, top: $top_pattern"
      active_flagged=$((active_flagged + 1))
      active_report="${active_report}\n  ⚠️  $short_id: ${waste_pct}% waste ($top_pattern)"
    else
      echo "  ✅ $short_id: ${step_count} steps, ~${waste_pct}% waste"
    fi
  fi
done 3< <(find "$BRAIN_DIR" -name "transcript.jsonl" -mmin -120 -print0 2>/dev/null)

[ "$active_flagged" -eq 0 ] && echo "  All active sessions clean."
echo ""

# ── Check 5: Gate Event Summary ──────────────────────────────────────────

GATE_LOG="$GOVERNANCE_DIR/gate_events.jsonl"
if [ -f "$GATE_LOG" ] && [ "$ACTIVE_ONLY" != "--active-only" ]; then
  echo "📋 Check 5: Gate event summary..."
  gate_count="$(wc -l < "$GATE_LOG" | tr -d ' ')"
  blocked="$(grep -c '"BLOCKED"' "$GATE_LOG" 2>/dev/null || echo 0)"
  echo "  Total events: $gate_count"
  echo "  Blocked: $blocked"
  echo ""
fi

# ── Generate Sweep Report ────────────────────────────────────────────────

has_actionable=false

if [ "$metrics_generated" -gt 0 ] || [ -n "$warning_report" ] || [ "$active_flagged" -gt 0 ]; then
  has_actionable=true

  # Append to pending_proposals.md
  {
    echo ""
    echo "## Governance Sweep — $TIMESTAMP"
    echo ""

    if [ "$metrics_generated" -gt 0 ]; then
      echo "### New Session Metrics ($metrics_generated generated)"
      echo "Run \`staff-review\` post-mortem for deep analysis on high-waste sessions."
      echo ""
    fi

    if [ -n "$warning_report" ]; then
      echo "### Warning Trends — Hardening Candidates"
      echo "$warning_report"
      echo ""
    fi

    if [ "$active_flagged" -gt 0 ]; then
      echo "### Active Session Alerts"
      echo -e "$active_report"
      echo ""
    fi
  } >> "$PROPOSALS"

  echo "📝 Sweep report appended to pending_proposals.md"
fi

# ── Log Sweep ────────────────────────────────────────────────────────────

echo "{\"timestamp\":\"$TIMESTAMP\",\"sessions_scanned\":$sessions_scanned,\"metrics_generated\":$metrics_generated,\"warnings_tallied\":$warnings_tallied,\"active_flagged\":$active_flagged,\"has_actionable\":$has_actionable}" >> "$SWEEP_LOG"

echo ""
echo "✅ Governance sweep complete."
echo "   Scanned: $sessions_scanned | Generated: $metrics_generated | Warnings: $warnings_tallied | Active flags: $active_flagged"
