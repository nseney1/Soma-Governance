"""soma promote — evaluate and display cell promotion candidates."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


PROMOTION_PATH = {"vacuole": "wall", "wall": "genome"}
TYPE_TO_DIR = {"vacuole": "vacuoles", "wall": "walls"}


def _find_cell(cells_dir: Path, cell_id: str) -> tuple[Path | None, str | None]:
    """Find a cell file by ID across all type directories."""
    # Sanitize cell_id to prevent path traversal
    if not cell_id or "/" in cell_id or "\\" in cell_id or ".." in cell_id:
        return None, None
    for type_dir in ("vacuoles", "walls"):
        candidate = cells_dir / type_dir / f"{cell_id}.md"
        if candidate.is_file():
            return candidate, type_dir
    return None, None


def _force_promote(project_root: Path, cell_id: str, dry_run: bool, use_json: bool) -> int:
    """Force-promote a specific cell, bypassing evidence thresholds."""
    cells_dir = project_root / ".soma" / "cells"
    cell_path, current_dir = _find_cell(cells_dir, cell_id)

    if cell_path is None:
        msg = f"Cell '{cell_id}' not found in {cells_dir}"
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"  ❌ {msg}")
        return 1

    # Determine current type from directory
    current_type = current_dir.rstrip("s")  # vacuoles -> vacuole
    next_type = PROMOTION_PATH.get(current_type)

    if next_type is None:
        msg = f"Cell '{cell_id}' is already at '{current_type}' (max promotion level)"
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(f"  ⚠️  {msg}")
        return 1

    next_dir = TYPE_TO_DIR.get(next_type)
    if next_type == "genome":
        # Genome promotion goes to genome/ (core rules)
        target_path = project_root / "genome" / f"{cell_id}.md"
    else:
        target_path = cells_dir / next_dir / f"{cell_id}.md"

    if dry_run:
        if use_json:
            print(json.dumps({"action": "promote", "cell_id": cell_id,
                             "from": current_type, "to": next_type, "dry_run": True}))
        else:
            print(f"  🧬 Would promote: {cell_id}: {current_type} → {next_type}")
            print(f"     {cell_path} → {target_path}")
        return 0

    # Read content and update frontmatter type
    content = cell_path.read_text(encoding="utf-8")
    content = re.sub(
        r"^type:\s*\S+",
        f"type: {next_type}",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    # Update enforcement for walls
    if next_type == "wall":
        content = re.sub(
            r"^enforcement:\s*\S+",
            "enforcement: gate",
            content,
            count=1,
            flags=re.MULTILINE,
        )
        # Check frontmatter only, not body
        fm_end = content.find('---', 3)
        frontmatter = content[:fm_end] if fm_end > 0 else content
        if 'enforcement:' not in frontmatter:
            content = re.sub(
                r"^(type:\s*\S+)",
                r"\1\nenforcement: gate",
                content,
                count=1,
                flags=re.MULTILINE,
            )

    # Guard against silent overwrite
    if target_path.exists():
        msg = f"Target already exists: {target_path}"
        if use_json:
            print(json.dumps({"error": msg}))
        else:
            print(msg)
        return 1

    # Write to new location atomically and remove old
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(f"{target_path.name}.tmp.{os.getpid()}")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.replace(tmp_path, target_path)
        except OSError:
            import shutil
            shutil.move(str(tmp_path), str(target_path))
        cell_path.unlink()
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    if use_json:
        print(json.dumps({"action": "promote", "cell_id": cell_id,
                         "from": current_type, "to": next_type}))
    else:
        print(f"  ✅ Promoted: {cell_id}: {current_type} → {next_type}")
    return 0


def run_promote(args: argparse.Namespace) -> int:
    """Evaluate promotion candidates and display results.
    
    Returns 0 always (dry-run is advisory).
    """
    project_root = Path(getattr(args, "_project_root", Path.cwd()))
    use_json = getattr(args, "json", False)
    dry_run = getattr(args, "dry_run", False)
    force = getattr(args, "force", False)
    cell_id = getattr(args, "cell", None)

    if getattr(args, 'cell', None) and not getattr(args, 'force', False):
        print("Warning: --cell requires --force; running normal evaluation", file=sys.stderr)

    if force:
        if not cell_id:
            msg = "--force requires --cell <cell-id>"
            if use_json:
                print(json.dumps({"error": msg}))
            else:
                print(f"  ❌ {msg}")
            return 1
        return _force_promote(project_root, cell_id, dry_run, use_json)

    from immune_system.verification.lifecycle import evaluate_promotions

    candidates = evaluate_promotions(str(project_root))
    
    if use_json:
        print(json.dumps({"candidates": candidates}, indent=2, default=str))
    else:
        if not candidates:
            print("  No promotion candidates found.")
        else:
            print(f"  🧬 Promotion Candidates ({len(candidates)}):")
            print()
            for c in candidates:
                print(f"    {c['cell_id']}: {c['from_type']} → {c['to_type']}")
                print(f"      triggers={c['triggers']} tp_rate={c['tp_rate']:.0%} age={c['age_days']}d")
            print()
    
    return 0

