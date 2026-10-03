#!/usr/bin/env python3
"""Soma Sleep Engine — Memory Consolidation

Runs at session close (triggered by session_close.sh).
Performs offline consolidation in three phases:

  Phase 1: Experience Replay (REM)
    Recalculates Bayesian fitness with recency bias — what worked TODAY 
    matters more than what worked 30 days ago.

  Phase 2: Structural Pruning (Deep Sleep)
    Aggressive offline pruning of cells that weren't triggered this session
    AND have low fitness. Safe to do offline (no risk of removing a cell mid-task).

  Phase 3: Dream Compression
    Compresses key lessons into .soma/dreams/YYYY-MM-DD.md
    On next session start, the agent reads this instead of the full genome.
"""

import os
import sys
import glob
import json
import re
from datetime import datetime, timezone
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
from soma_sdk.cells import parse_cell_file

PRUNE_SCORE_THRESHOLD = 0.4
RECENCY_WEIGHT = 2.0  # Today's outcomes count double


def resolve_workspace():
    """Find the nearest .soma directory walking up from cwd."""
    path = os.getcwd()
    while path != os.path.dirname(path):
        if os.path.isdir(os.path.join(path, ".soma")):
            return path
        path = os.path.dirname(path)
    return os.getcwd()


def load_cells(workspace):
    cells_dir = os.path.join(workspace, ".soma", "cells")
    cells = []
    for f in glob.glob(os.path.join(cells_dir, "**", "*.md"), recursive=True):
        try:
            metadata, body = parse_cell_file(f)
            metadata["_path"] = f
            metadata["_body"] = body
            cells.append(metadata)
        except Exception:
            continue
    return cells


def load_session_outcomes(workspace):
    """Load today's outcome signals from the immune log."""
    outcomes_path = os.path.join(workspace, ".soma", "metrics", "outcomes.jsonl")
    if not os.path.exists(outcomes_path):
        return []
    today = datetime.now(timezone.utc).date().isoformat()
    outcomes = []
    try:
        with open(outcomes_path, encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line.strip())
                if entry.get("timestamp", "").startswith(today):
                    outcomes.append(entry)
    except Exception:
        pass
    return outcomes


def phase1_experience_replay(cells, session_outcomes):
    """Apply recency-weighted fitness update."""
    print("\n🌙 Phase 1: Experience Replay (REM)")
    triggered_today = {o.get("cell_id") for o in session_outcomes}
    updates = 0
    for cell in cells:
        cell_id = os.path.splitext(os.path.basename(cell["_path"]))[0]
        if cell_id not in triggered_today:
            continue
        fitness = cell.get("fitness", {})
        if not isinstance(fitness, dict):
            fitness = {}
        # Apply recency boost: today's outcomes count RECENCY_WEIGHT times
        tp = fitness.get("true_positives", 0)
        triggers = fitness.get("triggers", 0)
        today_tp = sum(1 for o in session_outcomes
                       if o.get("cell_id") == cell_id and o.get("outcome") == "pass")
        today_fp = sum(1 for o in session_outcomes
                       if o.get("cell_id") == cell_id and o.get("outcome") == "fail")
        fitness["true_positives"] = tp + int(today_tp * RECENCY_WEIGHT)
        fitness["triggers"] = triggers + int((today_tp + today_fp) * RECENCY_WEIGHT)
        cell["fitness"] = fitness
        updates += 1
    print(f"   Recency-weighted {updates} cells touched this session.")
    return cells


def phase2_structural_pruning(cells, session_outcomes):
    """Aggressively prune cells not triggered today with low fitness."""
    print("\n💤 Phase 2: Structural Pruning (Deep Sleep)")
    triggered_today = {o.get("cell_id") for o in session_outcomes}
    pruned = []
    survivors = []
    for cell in cells:
        cell_id = os.path.splitext(os.path.basename(cell["_path"]))[0]
        fitness = cell.get("fitness", {})
        if not isinstance(fitness, dict):
            fitness = {}
        tp = fitness.get("true_positives", 0)
        triggers = fitness.get("triggers", 1)
        score = tp / triggers if triggers > 0 else 0.0
        cell_type = cell.get("type", "vacuole")
        # Walls are immortal — never pruned
        if cell_type == "wall":
            survivors.append(cell)
            continue
        # Prune: not triggered today AND low fitness
        if cell_id not in triggered_today and score < PRUNE_SCORE_THRESHOLD:
            pruned.append(cell)
            try:
                os.remove(cell["_path"])
            except Exception:
                pass
        else:
            survivors.append(cell)
    print(f"   Pruned {len(pruned)} low-fitness cells. {len(survivors)} survivors.")
    return survivors


def phase3_dream_compression(cells, session_outcomes, workspace):
    """Write a compressed Dream Log for the next session."""
    print("\n🌛 Phase 3: Dream Compression")
    # Rank cells by fitness score
    ranked = []
    for cell in cells:
        fitness = cell.get("fitness", {})
        if not isinstance(fitness, dict):
            fitness = {}
        tp = fitness.get("true_positives", 0)
        triggers = fitness.get("triggers", 1)
        score = tp / triggers if triggers > 0 else 0.0
        ranked.append((score, cell))
    ranked.sort(key=lambda x: x[0], reverse=True)

    top_3 = ranked[:3]
    bottom_3 = [c for c in ranked[-3:] if c[0] < PRUNE_SCORE_THRESHOLD]

    today = datetime.now(timezone.utc).date().isoformat()
    dreams_dir = os.path.join(workspace, ".soma", "dreams")
    os.makedirs(dreams_dir, exist_ok=True)
    dream_path = os.path.join(dreams_dir, f"{today}.md")

    with open(dream_path, "w", encoding="utf-8") as f:
        f.write(f"# Dream Log — {today}\n\n")
        f.write("*Read this at session start instead of the full genome.*\n\n")
        f.write("## 🏆 Top Performers (reinforce these)\n")
        for score, cell in top_3:
            name = cell.get("name", os.path.basename(cell["_path"]))
            hypothesis = cell.get("hypothesis", "No hypothesis recorded.")
            f.write(f"- **{name}** (fitness: {score:.2f}) — {hypothesis}\n")
        if bottom_3:
            f.write("\n## ⚠️ Weak Signals (verify these are still valid)\n")
            for score, cell in bottom_3:
                name = cell.get("name", os.path.basename(cell["_path"]))
                f.write(f"- **{name}** (fitness: {score:.2f}) — Low signal. Consider apoptosis.\n")
        f.write(f"\n*Session outcomes logged: {len(session_outcomes)} signals.*\n")

    print(f"   Dream Log written: {dream_path}")
    return dream_path


def main():
    workspace = resolve_workspace()
    print(f"🧬 Soma Sleep Engine starting. Workspace: {workspace}")
    cells = load_cells(workspace)
    session_outcomes = load_session_outcomes(workspace)
    print(f"   Loaded {len(cells)} cells. {len(session_outcomes)} session outcomes found.")

    cells = phase1_experience_replay(cells, session_outcomes)
    cells = phase2_structural_pruning(cells, session_outcomes)
    dream_path = phase3_dream_compression(cells, session_outcomes, workspace)

    print(f"\n✅ Sleep complete. Dream Log: {dream_path}")


if __name__ == "__main__":
    # Output uses non-ASCII symbols; on a cp1252 stdout printing them
    # raised UnicodeEncodeError and the script exited 1 (BUG-038).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    main()
