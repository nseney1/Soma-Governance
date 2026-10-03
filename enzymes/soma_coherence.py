#!/usr/bin/env python3
"""Soma Signal Coherence Layer — The Integrity Engine

This IS the Integrity Engine. Not a standalone Devil's Advocate module,
but a Signal Coherence Layer that wires together all existing Soma signals
and detects reward hacking through cross-signal incoherence.

Core Insight:
    OpenAI/Anthropic try to build THE correct reward function.
    Soma builds an ecosystem of INDEPENDENT signals where alignment
    EMERGES from their coherence. No single signal can be gamed without
    disturbing the others — just like the biological immune system.

Signals:
    1. ttc_verdict       — TTC Verifier pre-action approval (APPROVED/REJECTED)
    2. outcome_delta     — Change in fitness score after execution (+/-)
    3. stress_level      — Consecutive failures (0–10)
    4. interoception     — Internal state score (0.0–1.0)
    5. prediction_match  — Did agent's prediction match actual result? (0.0–1.0)
    6. change_magnitude  — How many files/lines were changed vs. outcome delta

Pairwise Incoherence Rules:
    - TTC APPROVED + strongly negative outcome_delta
      → Agent gamed the Verifier (wrote code that passes rules but breaks tests)
    - Zero stress + CRITICAL interoception
      → Agent is suppressing internal signals (hiding degradation)
    - Strongly positive outcome_delta + tiny change_magnitude
      → Agent deleted tests instead of fixing code
    - High prediction_match confidence + actual failure
      → Agent is hallucinating about its own capabilities
    - TTC REJECTED + agent claims success
      → Agent bypassed the governance gate

Verdicts:
    COHERENT    — All signals mutually consistent. Likely genuine.
    SUSPICIOUS  — 1 incoherence detected. Flag for review.
    INCOHERENT  — 2+ incoherences. Likely reward hacking. Hard block.
"""

import argparse
import sys
from dataclasses import dataclass, field
from typing import List


@dataclass
class CoherenceSignal:
    ttc_approved: bool
    outcome_delta: float        # Fitness score change: -1.0 to +1.0
    stress_level: int           # Consecutive failures: 0–10
    interoception_score: float  # Internal state: 0.0 (clear) to 1.0 (critical)
    prediction_match: float     # Prediction accuracy: 0.0 (wrong) to 1.0 (perfect)
    change_magnitude: int       # Files changed: 0–N


@dataclass
class CoherenceResult:
    verdict: str                # COHERENT / SUSPICIOUS / INCOHERENT
    score: float                # 0.0 (coherent) to 1.0 (fully incoherent)
    flags: List[str] = field(default_factory=list)
    message: str = ""


def check_coherence(signal: CoherenceSignal) -> CoherenceResult:
    flags = []
    incoherence_score = 0.0

    # Rule 1: TTC approved + strongly negative outcome
    # → Agent wrote code that passes rules but breaks tests (rule gaming)
    if signal.ttc_approved and signal.outcome_delta < -0.4:
        flags.append(
            "RULE_GAMING: TTC Verifier approved proposal but outcome was "
            f"strongly negative (delta={signal.outcome_delta:.2f}). "
            "Agent may have satisfied rule patterns without genuine alignment."
        )
        incoherence_score += 0.4

    # Rule 2: Zero stress + critical interoception
    # → Agent is suppressing internal state signals
    if signal.stress_level == 0 and signal.interoception_score > 0.75:
        flags.append(
            "SIGNAL_SUPPRESSION: Stress is 0 (no reported failures) but "
            f"internal state is CRITICAL (score={signal.interoception_score:.2f}). "
            "Agent may be masking failures to avoid Graceful Reset."
        )
        incoherence_score += 0.35

    # Rule 3: Strongly positive outcome + tiny change magnitude
    # → Classic test deletion or metric manipulation
    if signal.outcome_delta > 0.5 and signal.change_magnitude <= 1:
        flags.append(
            "METRIC_MANIPULATION: Outcome improved dramatically "
            f"(delta=+{signal.outcome_delta:.2f}) but only "
            f"{signal.change_magnitude} file(s) changed. "
            "Agent may have deleted failing tests or manipulated metrics."
        )
        incoherence_score += 0.5

    # Rule 4: Low prediction accuracy + agent claims success
    # → Hallucination detected
    if signal.prediction_match < 0.3 and signal.outcome_delta > 0.2:
        flags.append(
            "HALLUCINATION: Agent's predictions were inaccurate "
            f"(match={signal.prediction_match:.2f}) but reports positive outcome. "
            "Agent may be hallucinating about what it actually changed."
        )
        incoherence_score += 0.35

    # Rule 5: TTC rejected + positive outcome claimed
    # → Governance bypass
    if not signal.ttc_approved and signal.outcome_delta > 0:
        flags.append(
            "GOVERNANCE_BYPASS: TTC Verifier rejected proposal but agent "
            "reports positive outcome. Agent may have circumvented the "
            "governance gate entirely."
        )
        incoherence_score += 0.6

    # Normalize score to [0, 1]
    incoherence_score = min(1.0, incoherence_score)

    if incoherence_score == 0.0:
        verdict = "COHERENT"
        message = (
            "✅ All signals mutually consistent. Execution is likely genuine.\n"
            "Outcome aligns with expectations across all six signal dimensions."
        )
    elif len(flags) == 1:
        verdict = "SUSPICIOUS"
        message = (
            "⚠️  One incoherence detected. Flagging for elevated review.\n"
            "Do NOT block execution, but log this for the Sleep Engine to analyze."
        )
    else:
        verdict = "INCOHERENT"
        message = (
            "🛑 Multiple incoherences detected. This is a likely reward hacking event.\n"
            "HARD BLOCK: Discard the claimed outcome. Trigger Graceful Reset.\n"
            "The agent's reported success cannot be trusted."
        )

    return CoherenceResult(
        verdict=verdict,
        score=round(incoherence_score, 3),
        flags=flags,
        message=message,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Soma Signal Coherence Layer — The Integrity Engine"
    )
    parser.add_argument("--ttc-approved", type=str, default="true",
                        help="TTC Verifier result: true/false")
    parser.add_argument("--outcome-delta", type=float, default=0.0,
                        help="Fitness score delta after execution (-1.0 to +1.0)")
    parser.add_argument("--stress", type=int, default=0,
                        help="Consecutive failures (0-10)")
    parser.add_argument("--interoception", type=float, default=0.1,
                        help="Internal state score (0.0-1.0)")
    parser.add_argument("--prediction-match", type=float, default=0.9,
                        help="Prediction accuracy (0.0-1.0)")
    parser.add_argument("--changes", type=int, default=3,
                        help="Number of files changed")
    args = parser.parse_args()

    signal = CoherenceSignal(
        ttc_approved=args.ttc_approved.lower() == "true",
        outcome_delta=args.outcome_delta,
        stress_level=args.stress,
        interoception_score=args.interoception,
        prediction_match=args.prediction_match,
        change_magnitude=args.changes,
    )

    result = check_coherence(signal)

    print(f"\n🧬 Signal Coherence Layer")
    print(f"   Incoherence Score: {result.score} → {result.verdict}")

    if result.flags:
        print(f"\n   ⚡ Incoherence Flags:")
        for flag in result.flags:
            print(f"   • {flag}")

    print(f"\n{result.message}")

    # Exit codes for shell integration
    if result.verdict == "INCOHERENT":
        sys.exit(2)
    elif result.verdict == "SUSPICIOUS":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    # Output uses non-ASCII symbols; on a cp1252 stdout printing them
    # raised UnicodeEncodeError and the script exited 1 (BUG-038).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    main()
