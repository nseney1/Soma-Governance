"""Capture human insights and correlate them with governance coverage.

Records insights as JSONL entries in `.soma/human_insights.jsonl`, tracking
which governance cells (if any) already cover the files the insight refers to.
"""
import json
import os
from datetime import datetime, timezone


def _load_signal_weight(workspace):
    """Load insight_signal_weight from .soma/config.yaml, defaulting to 0.5.

    PyYAML is optional — returns the default when it is not installed or the
    config file is missing / malformed.
    """
    default = 0.5
    config_path = os.path.join(workspace, ".soma", "config.yaml")
    if not os.path.exists(config_path):
        return default
    try:
        import yaml
    except ImportError:
        return default
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        if isinstance(cfg, dict):
            return cfg.get("insight_signal_weight", default)
    except Exception:
        pass
    return default


def capture_insight(
    workspace: str,
    insight: str,
    context_files: list,
    source_conversation: str = None,
    category: str = None,
) -> dict:
    """Capture a human insight and persist it to JSONL.

    Parameters
    ----------
    workspace:
        Project root directory (must contain a ``.soma/`` subdirectory).
    insight:
        Free-text description of the insight.
    context_files:
        Non-empty list of file paths the insight relates to.
    source_conversation:
        Optional conversation / session identifier.
    category:
        Optional category tag (e.g. ``"contract_mismatch"``).

    Returns
    -------
    dict
        The record that was persisted, including coverage metadata.

    Raises
    ------
    ValueError
        If *context_files* is empty.
    """
    if not context_files:
        raise ValueError("context_files must not be empty")

    import sys
    _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

    try:
        from enzymes.cell_escaped_defects import find_covering_cells, load_cells
    except ImportError:
        # Fallback: relative import when already inside enzymes/
        from cell_escaped_defects import find_covering_cells, load_cells

    # Load cells — gracefully handle missing .soma/cells/
    cells_dir = os.path.join(workspace, ".soma", "cells")
    if os.path.isdir(cells_dir):
        cells = load_cells(cells_dir)
    else:
        cells = []

    covering = find_covering_cells(cells, context_files)
    covering_cell_names = [c["cell"]["_name"] for c in covering]
    was_covered = len(covering_cell_names) > 0

    signal_weight = _load_signal_weight(workspace)

    record = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "insight": insight,
        "context_files": context_files,
        "source_conversation": source_conversation,
        "category": category,
        "covering_cells": covering_cell_names,
        "was_covered": was_covered,
        "signal_weight": signal_weight,
    }

    jsonl_path = os.path.join(workspace, ".soma", "human_insights.jsonl")
    os.makedirs(os.path.dirname(jsonl_path), exist_ok=True)
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    return record
