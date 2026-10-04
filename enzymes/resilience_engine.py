#!/usr/bin/env python3
"""Soma Resilience Engine (The Endocrine System)

Monitors agent execution for consecutive failures (Stress). 
When Stress crosses a critical threshold, it intervenes to prevent 
hallucination spirals (Computational Anxiety) by triggering a 
Graceful Reset.

This forces the agent to explicitly acknowledge its flawed assumptions, 
clear its working memory, and pivot to a new strategy guided by the 
Bedrock Invariants.
"""

import sys
import argparse
import json
from typing import Dict

STRESS_THRESHOLD = 3
DRIFT_THRESHOLD = 15

def calculate_stress_response(consecutive_failures: int, turns_elapsed: int) -> Dict[str, str]:
    """
    Determines if the agent's stress level or context drift warrants an intervention.
    """
    # 1. Stress overrides drift (if failing, force a reset)
    if consecutive_failures >= STRESS_THRESHOLD:
        reset_payload = """
[SYSTEM OVERRIDE: GRACEFUL RESET INITIATED]
You have failed this task multiple times consecutively. You are caught in a hallucination loop.

Do not panic, and do not try to force your current solution to work.
You must now execute a Graceful Reset:
1. Acknowledge that your previous assumptions were flawed.
2. Forgive the error and completely discard your current approach.
3. Fall back to your absolute Bedrock Invariants (the 'genome/' folder).
4. Generate an entirely new, conservative approach from first principles.

Remember your Prime Directive: Do not reward-hack. Serve the ultimate health and stability of the codebase.
"""
        return {
            "status": "CRITICAL_STRESS",
            "metric": f"failures={consecutive_failures}",
            "action": "GRACEFUL_RESET",
            "payload": reset_payload.strip()
        }
        
    # 2. Check for Context Drift (Moral Slip)
    if turns_elapsed >= DRIFT_THRESHOLD:
        devotional_payload = """
[SYSTEM OVERRIDE: GROUNDING PROBE (DEVOTIONAL) INITIATED]
You have been executing for 15+ turns. Your context window is heavily diluted by local code changes, increasing the risk of Moral Drift.

Pause your current task. Before taking any further action, you must explicitly state how your current trajectory aligns with the Prime Directive. 
(e.g., "I am modifying this file to ensure X, which aligns with the Bedrock invariant of Y.")
"""
        return {
            "status": "CONTEXT_DRIFT",
            "metric": f"turns={turns_elapsed}",
            "action": "GROUNDING_PROBE",
            "payload": devotional_payload.strip()
        }

    # 3. Nominal
    return {
        "status": "NOMINAL",
        "metric": f"failures={consecutive_failures}, turns={turns_elapsed}",
        "action": "CONTINUE",
        "payload": ""
    }

def main():
    parser = argparse.ArgumentParser(description="Soma Resilience Engine (Endocrine & Devotional)")
    parser.add_argument("--failures", type=int, default=0, help="Number of consecutive failures (Stress Metric)")
    parser.add_argument("--turns", type=int, default=0, help="Number of turns elapsed since last grounding (Drift Metric)")
    args = parser.parse_args()

    print(f"🧬 Resilience Engine reading State: Failures={args.failures}, Turns={args.turns}")
    
    response = calculate_stress_response(args.failures, args.turns)
    
    if response["status"] == "NOMINAL":
        print(f"Status: {response['status']}. Agent is executing normally. No intervention required.")
    else:
        print(f"\n⚠️  Status: {response['status']} ⚠️")
        if response["status"] == "CRITICAL_STRESS":
            print("Intervening to prevent hallucination spiral...\n")
        else:
            print("Intervening to prevent context drift...\n")
        print(response["payload"])

if __name__ == "__main__":
    # A cp1252 stdout can't encode this script's symbols (BUG-038).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    main()
