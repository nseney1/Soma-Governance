#!/usr/bin/env bash
# enzymes/liveness_sentinel.sh
# 
# Usage:
#   bash enzymes/liveness_sentinel.sh --check '{"agents": [{"name": "Canopy Scout", "dispatched": "2026-09-27T20:00:00Z", "timeout_seconds": 300}]}'
#
# Description:
#   Monitors subagent health during multi-agent orchestration.
#   Detects stalled or deadlocked subagents that fail to report back within expected timeframes.
#   Outputs a status report for each agent (HEALTHY / WARNING / STALLED).

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"  # soma_python (BUG-037); enables set -euo pipefail

if [[ "${1:-}" == "--help" || -z "${1:-}" ]]; then
  echo "Usage: $0 --check '{\"agents\": [...]}'"
  echo "Example:"
  echo "  $0 --check '{\"agents\": [{\"name\": \"Canopy Scout\", \"dispatched\": \"2026-09-27T20:00:00Z\", \"timeout_seconds\": 300}]}'"
  exit 0
fi

if [[ "$1" == "--check" && -n "${2:-}" ]]; then
  soma_python -c "
import json
import sys
from datetime import datetime, timezone

try:
    data = json.loads(sys.argv[1])
    now = datetime.now(timezone.utc)
    for agent in data.get('agents', []):
        name = agent.get('name', 'Unknown')
        dispatch_str = agent.get('dispatched', '')
        timeout = agent.get('timeout_seconds', 0)
        
        try:
            # Parse ISO datetime ending in Z or similar
            if dispatch_str.endswith('Z'):
                dispatch_str = dispatch_str[:-1] + '+00:00'
            dispatch_time = datetime.fromisoformat(dispatch_str)
        except ValueError:
            print(f'[{name}] INVALID_DATE: {dispatch_str}')
            continue
            
        elapsed = (now - dispatch_time).total_seconds()
        
        if elapsed > timeout:
            print(f'[{name}] STALLED (Elapsed: {elapsed:.1f}s, Timeout: {timeout}s) - Action suggested: kill or escalate')
        elif elapsed > timeout * 0.8:
            print(f'[{name}] WARNING (Elapsed: {elapsed:.1f}s, Timeout: {timeout}s) - Action suggested: nudge')
        else:
            print(f'[{name}] HEALTHY (Elapsed: {elapsed:.1f}s, Timeout: {timeout}s)')
            
except json.JSONDecodeError:
    print('Error: Invalid JSON provided.')
    sys.exit(1)
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)
" "$2"
fi
