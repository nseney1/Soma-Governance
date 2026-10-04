"""Unified scoring module for soma-governance.

Single source of truth for all fitness scoring functions.
All enzyme files should import from here instead of inline scoring.

Phase 2.2: Consolidates bayesian_score.py + cells.py scoring into one module.
Uses Wilson score interval (correct for small n) instead of Wald approximation.
"""
from __future__ import annotations

import math
from typing import Dict, Tuple, Union


def _wilson_interval(tp: int, total: int, z: float = 1.645) -> Tuple[float, float]:
    """Wilson score interval — correct for small n, no scipy needed.

    Args:
        tp: Number of successes (true positives).
        total: Total number of observations (tp + fp).
        z: Z-score for confidence level (1.645=90%, 1.96=95%, 2.576=99%).

    Returns:
        Tuple of (lower_bound, upper_bound).
    """
    if total == 0:
        return 0.0, 1.0
    p = tp / total
    denom = 1 + z ** 2 / total
    center = (p + z ** 2 / (2 * total)) / denom
    spread = z * math.sqrt((p * (1 - p) + z ** 2 / (4 * total)) / total) / denom
    return max(0.0, center - spread), min(1.0, center + spread)


def _to_num(val, default=0.0):
    if val is None or isinstance(val, bool):
        return default
    if isinstance(val, (int, float)):
        return max(0.0, float(val)) if math.isfinite(val) else default
    if isinstance(val, str):
        val = val.strip()
        if '/' in val:
            try:
                from fractions import Fraction
                f = float(Fraction(val))
                return max(0.0, f) if math.isfinite(f) else default
            except Exception:
                return default
        try:
            f = float(val)
            return max(0.0, f) if math.isfinite(f) else default
        except Exception:
            return default
    return default


def bayesian_posterior(
    tp: int,
    fp: int,
    confidence: float = 0.90,
) -> Dict[str, Union[float, str, int]]:
    """Wilson-bounded fitness scoring with Jeffrey's prior.

    Uses the Wilson score interval for lower/upper bounds (correct for small n)
    and Jeffrey's Beta(0.5, 0.5) prior for the posterior mean.

    Args:
        tp: True positives.
        fp: False positives.
        confidence: Confidence level (0.90, 0.95, or 0.99).

    Returns:
        Dict with keys: mean, lower, lower_90, upper, upper_90, certainty, n.
    """
    tp = _to_num(tp)
    fp = _to_num(fp)
    a = tp + 0.5
    b = fp + 0.5
    mean = a / (a + b)
    z = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}.get(confidence, 1.645)
    total = tp + fp
    lower, upper = _wilson_interval(tp, total, z)
    lower = round(lower, 4)
    upper = round(upper, 4)
    return {
        'mean': round(mean, 4),
        'lower': lower,
        'lower_90': lower,    # Backward compat alias
        'upper': upper,
        'upper_90': upper,    # Backward compat alias
        'certainty': 'low' if total < 5 else 'medium' if total < 20 else 'high',
        'n': total,
    }


def laplace_score(
    tp: int,
    triggers: int,
    impact_weight: float = 1.0,
) -> float:
    """Laplace-smoothed point estimate: (tp+1)/(triggers+2) × impact.

    Legacy scoring function retained for backward compatibility.
    New code should use bayesian_posterior() instead.

    Args:
        tp: True positives.
        triggers: Total trigger count.
        impact_weight: Multiplicative weight for impact scoring.

    Returns:
        Smoothed score in [0, 1] × impact_weight.
    """
    weight = float(_to_num(impact_weight, default=1.0))
    return ((_to_num(tp) + 1.0) / (_to_num(triggers) + 2.0)) * weight


# Deprecated alias — external scripts importing bayesian_score won't break
def bayesian_score(
    tp: int,
    triggers: int,
    impact_weight: float = 1.0,
) -> float:
    """DEPRECATED: Use bayesian_posterior() for new code.

    Legacy Laplace-smoothed point estimate.
    """
    return laplace_score(tp, triggers, impact_weight)
