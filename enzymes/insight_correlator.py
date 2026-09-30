#!/usr/bin/env python3
"""Insight Correlator — clusters human insights into governance cell candidates.

Reads `.soma/human_insights.jsonl`, groups by category within a rolling window,
and produces cell candidates when a cluster reaches the minimum size threshold.
"""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone


def _parse_timestamp(ts_str: str) -> datetime:
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime."""
    # Handle trailing 'Z' (common in JSON)
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    return datetime.fromisoformat(ts_str)


def cluster_insights(
    workspace: str,
    min_cluster_size: int = 3,
    window_days: int = 30,
) -> list:
    """Read human insights and cluster by category.

    Parameters
    ----------
    workspace : str
        Root of the Soma workspace (contains ``.soma/``).
    min_cluster_size : int
        Minimum number of insights required to form a cluster.
    window_days : int
        Only consider insights within this many days from *now*.

    Returns
    -------
    list[dict]
        A list of cluster dicts, each containing:
        ``pattern_id``, ``insight_count``, ``common_files``,
        ``common_category``, and ``confidence``.
    """
    jsonl_path = os.path.join(workspace, ".soma", "human_insights.jsonl")
    if not os.path.isfile(jsonl_path):
        return []

    # Read all records
    records: list[dict] = []
    with open(jsonl_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not records:
        return []

    # Filter by window_days
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    recent: list[dict] = []
    for rec in records:
        ts_str = rec.get("timestamp")
        if not ts_str:
            continue
        try:
            ts = _parse_timestamp(ts_str)
        except (ValueError, TypeError):
            continue
        if ts >= cutoff:
            recent.append(rec)

    if not recent:
        return []

    # Group by category
    groups: dict[str, list[dict]] = {}
    for rec in recent:
        cat = rec.get("category") or "uncategorized"
        groups.setdefault(cat, []).append(rec)

    # Build clusters for groups that meet the threshold
    clusters: list[dict] = []
    for category, group in sorted(groups.items()):
        if len(group) < min_cluster_size:
            continue

        # Union of all context_files across the group
        common_files: list[str] = []
        seen_files: set[str] = set()
        for rec in group:
            for f in rec.get("context_files", []):
                if f not in seen_files:
                    seen_files.add(f)
                    common_files.append(f)

        insight_count = len(group)
        # Simple Bayesian confidence estimate
        confidence = round(insight_count / (insight_count + 2), 4)

        # Deterministic pattern_id from category
        slug = category.replace(" ", "-").lower()
        file_hash = hashlib.sha256(
            "-".join(sorted(seen_files)).encode()
        ).hexdigest()[:8]
        pattern_id = f"{slug}-{file_hash}"

        clusters.append(
            {
                "pattern_id": pattern_id,
                "insight_count": insight_count,
                "common_files": common_files,
                "common_category": category,
                "confidence": confidence,
            }
        )

    return clusters


def generate_cell_candidates(
    clusters: list,
    workspace: str,
) -> list:
    """Produce governance-cell candidate dicts from insight clusters.

    Parameters
    ----------
    clusters : list[dict]
        Output of :func:`cluster_insights`.
    workspace : str
        Root of the Soma workspace.

    Returns
    -------
    list[dict]
        One candidate per cluster with keys:
        ``hypothesis``, ``target_paths``, ``origin``, ``type``,
        ``enforcement``.
    """
    if not clusters:
        return []

    candidates: list[dict] = []
    for cluster in clusters:
        category = cluster.get("common_category", "unknown")
        files = cluster.get("common_files", [])
        files_str = ", ".join(files) if files else "project-wide"

        hypothesis = (
            f"Human attention pattern detected: {category} in {files_str}"
        )

        candidates.append(
            {
                "hypothesis": hypothesis,
                "target_paths": list(files),
                "origin": "human_insight",
                "type": "vacuole",
                "enforcement": "advisory",
            }
        )

    return candidates
