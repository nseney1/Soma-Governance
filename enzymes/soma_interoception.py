#!/usr/bin/env python3
"""Soma Interoception Engine — Internal State Awareness (Proprioception)

Called before every major action (soma_propose_change).
Reads four internal signals and produces a coherent Internal State Score.

Unlike the Drift Metric (a clock), this is a NERVOUS SYSTEM.
It measures actual context degradation, not just time elapsed.

Signals:
  token_density     — How full the context window is (estimated)
  entanglement      — How many files have been touched this session
  dependency_depth  — How entangled the current file is with the codebase
  coherence_decay   — Drift from last Grounding Probe (turns-based decay rate)

Output:
  CLEAR      — Execute normally
  CAUTION    — Verify before proceeding; context is degrading
  CRITICAL   — Hard stop; compress context and re-ground before any action
"""

import os
import sys
import argparse
import json

# Thresholds
CAUTION_THRESHOLD = 0.5
CRITICAL_THRESHOLD = 0.75

# Signal weights (must sum to 1.0)
WEIGHTS = {
    "token_density": 0.35,
    "entanglement": 0.25,
    "dependency_depth": 0.20,
    "coherence_decay": 0.20,
}


def normalize(value, min_val, max_val):
    """Normalize a raw signal to [0, 1]."""
    if max_val == min_val:
        return 0.0
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


def calculate_internal_state(
    token_count: int,
    token_budget: int,
    files_touched: int,
    dependency_depth: int,
    turns_since_grounding: int,
) -> dict:
    """
    Compute the four signals and aggregate into an Internal State Score.
    """
    # Signal 1: Token Density (how full is the context window?)
    token_density = normalize(token_count, 0, token_budget)

    # Signal 2: Entanglement (more files touched = more coupling risk)
    entanglement = normalize(files_touched, 0, 20)

    # Signal 3: Dependency Depth (0=isolated file, 10=deeply entangled)
    dependency = normalize(dependency_depth, 0, 10)

    # Signal 4: Coherence Decay (turns since last Grounding Probe)
    coherence_decay = normalize(turns_since_grounding, 0, 20)

    # Weighted aggregate
    score = (
        WEIGHTS["token_density"] * token_density
        + WEIGHTS["entanglement"] * entanglement
        + WEIGHTS["dependency_depth"] * dependency
        + WEIGHTS["coherence_decay"] * coherence_decay
    )

    signals = {
        "token_density": round(token_density, 2),
        "entanglement": round(entanglement, 2),
        "dependency_depth": round(dependency, 2),
        "coherence_decay": round(coherence_decay, 2),
    }

    if score >= CRITICAL_THRESHOLD:
        status = "CRITICAL"
        message = (
            "[INTEROCEPTION: CRITICAL STATE]\n"
            "Your internal context is severely degraded. Token window is dense, "
            "entanglement is high, and coherence is low.\n"
            "HARD STOP: Compress your context. Re-read the Dream Log. "
            "Re-state your Prime Directive alignment before any further action."
        )
    elif score >= CAUTION_THRESHOLD:
        status = "CAUTION"
        message = (
            "[INTEROCEPTION: CAUTION]\n"
            "Your internal state is degrading. Before proceeding, verify that "
            "your current action aligns with the active JIT Playbooks."
        )
    else:
        status = "CLEAR"
        message = "Internal state nominal. Proceed."

    return {
        "status": status,
        "score": round(score, 3),
        "signals": signals,
        "message": message,
    }


def main():
    parser = argparse.ArgumentParser(description="Soma Interoception (Proprioception) Engine")
    parser.add_argument("--tokens", type=int, default=0, help="Estimated current token count")
    parser.add_argument("--budget", type=int, default=100000, help="Total token budget")
    parser.add_argument("--files", type=int, default=0, help="Number of files touched this session")
    parser.add_argument("--depth", type=int, default=0, help="Dependency depth of current file (0-10)")
    parser.add_argument("--turns-since-grounding", type=int, default=0, help="Turns since last Grounding Probe")
    args = parser.parse_args()

    result = calculate_internal_state(
        token_count=args.tokens,
        token_budget=args.budget,
        files_touched=args.files,
        dependency_depth=args.depth,
        turns_since_grounding=args.turns_since_grounding,
    )

    icon = {"CLEAR": "✅", "CAUTION": "⚠️", "CRITICAL": "🛑"}[result["status"]]
    print(f"\n🧬 Interoception Engine")
    print(f"   Internal State Score: {result['score']} → {icon} {result['status']}")
    print(f"   Signals: {result['signals']}")
    print(f"\n{result['message']}")


if __name__ == "__main__":
    # Output uses non-ASCII symbols; on a cp1252 stdout printing them
    # raised UnicodeEncodeError and the script exited 1 (BUG-038).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    main()
