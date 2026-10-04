#!/usr/bin/env bash
# Post-session hook: update cell fitness data from a session transcript.
#
# Usage:
#   bash enzymes/post_session_hook.sh <transcript_path>
#
# This is the v1 integration point. The Oracle Checkpoint (Phase 4) will
# provide mid-session feedback; when it ships, this hook becomes its
# post-session cleanup step.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/soma_python.sh"
soma_resolve_python || true

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <transcript_path>" >&2
    exit 1
fi

TRANSCRIPT="$1"

if [[ ! -f "$TRANSCRIPT" ]]; then
    echo "Error: transcript not found: $TRANSCRIPT" >&2
    exit 1
fi

soma_py "${SCRIPT_DIR}/fitness_updater.py" "$TRANSCRIPT"

# === Evidence enrichment: correlate rule compliance patterns ===
# evidence_collector.py is a library — invoke via one-liner
soma_py -c "
import sys, json, os
sys.path.insert(0, '${SCRIPT_DIR}')
from evidence_collector import check_compliance, build_observation, aggregate_evidence
from pathlib import Path

transcript = Path('$TRANSCRIPT')
if not transcript.exists():
    sys.exit(0)

# Check compliance for known governance rules
rules = ['read-before-write', 'test-before-implementation', 'no-hardcoded-paths']
observations = []
for rule_id in rules:
    result = check_compliance(transcript, rule_id)
    obs = build_observation(result, transcript, rule_id)
    if obs is not None:
        observations.append(obs)

if observations:
    summary = aggregate_evidence(observations)
    evidence_dir = os.path.join(os.getcwd(), '.soma', 'evidence')
    os.makedirs(evidence_dir, exist_ok=True)
    outfile = os.path.join(evidence_dir, 'compliance.jsonl')
    with open(outfile, 'a') as f:
        f.write(json.dumps(summary) + '\n')
"

