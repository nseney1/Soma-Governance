"""Regression tests for the second-pass review of the v0.89 audit fixes.

* A failed evidence append followed by a retry must not duplicate insight
  events in signals.jsonl or apply the same insight boost to a cell twice.
* Evidence appends from the outcome engine are fenced on the epoch
  generation the run observed.
* MCP report_outcome writes only canonical, idempotent signals in one batch.
* Stow-style symlinked config dirs that stay inside HOME uninstall normally.
"""
import json
import os

import pytest

from conftest import REPO_ROOT, require_bash, run, symlink_or_skip
from test_outcome_engine_insights import (
    _covered, _cursor_path, _signals_log, _stub_main, _write_cell, _write_insights,
)


def _fitness(ws, name):
    from soma_sdk.cells import parse_cell_file
    fm, _ = parse_cell_file(os.path.join(ws, ".soma", "cells", "vacuoles", f"{name}.md"))
    return fm["fitness"]


# ── Insight retry: no duplicate evidence, no double boost ───────────────

def test_retry_after_partial_append_neither_duplicates_nor_reinflates(tmp_path, monkeypatch):
    import soma_sdk.telemetry as telemetry
    ws = str(tmp_path)
    _write_cell(ws, "vacuole-a", ["a/*.py"])
    _write_cell(ws, "vacuole-b", ["b/*.py"])
    _write_insights(ws, [_covered("vacuole-a"), _covered("vacuole-b")])
    oe = _stub_main(monkeypatch, ws)
    before_a, before_b = _fitness(ws, "vacuole-a"), _fitness(ws, "vacuole-b")

    real_append = telemetry.append_signals
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk full")
        return real_append(*args, **kwargs)

    monkeypatch.setattr(telemetry, "append_signals", flaky)
    oe.main()  # atomic batch fails before any signal lands
    assert not os.path.exists(_cursor_path(ws)), "cursor advanced past unpersisted insight"
    assert _signals_log(ws) == [], "failed batch persisted partial evidence"
    oe.main()  # retry
    rows = _signals_log(ws)
    assert sorted(r["cell"] for r in rows) == ["vacuole-a", "vacuole-b"], (
        "retry duplicated an already-logged insight event"
    )
    after_a, after_b = _fitness(ws, "vacuole-a"), _fitness(ws, "vacuole-b")
    assert after_a["true_positives"] == before_a["true_positives"] + 1
    assert after_b["true_positives"] == before_b["true_positives"] + 1

    oe.main()  # nothing new: cursor committed, no further change
    assert len(_signals_log(ws)) == 2
    assert _fitness(ws, "vacuole-a")["true_positives"] == after_a["true_positives"]


def test_outcome_engine_appends_are_generation_fenced(tmp_path):
    from enzymes.outcome_engine import append_fitness_log
    ws = str(tmp_path)
    os.makedirs(os.path.join(ws, ".soma"), exist_ok=True)
    with open(os.path.join(ws, ".soma", "epoch_generation"), "w", encoding="utf-8") as f:
        f.write("2\n")
    sig = [{"cell": "c", "_path": "x", "signal": 0.5, "verified": True, "reasons": []}]
    assert append_fitness_log(ws, sig, {}, expected_generation=1) is False
    assert not os.path.exists(os.path.join(ws, ".soma", "evidence", "signals.jsonl"))
    assert append_fitness_log(ws, sig, {}, expected_generation=2) is True


# ── MCP outcome ↔ signal linkage ─────────────────────────────────────────

def _workspace_with_cell(tmp_path, cell="trap-x"):
    cells = tmp_path / ".soma" / "cells" / "vacuoles"
    cells.mkdir(parents=True)
    (cells / f"{cell}.md").write_text(
        f"---\nid: {cell}\ntype: vacuole\nhypothesis: h\nprediction: p\n---\n# x\n",
        encoding="utf-8")
    return tmp_path


def _jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_report_outcome_writes_only_canonical_signal(tmp_path, monkeypatch):
    from soma_mcp.tools import execute_tool
    ws = _workspace_with_cell(tmp_path)
    monkeypatch.setenv("SOMA_WORKSPACE", str(ws))
    result = execute_tool(
        "soma_report_outcome",
        {"outcome": "success", "cells_used": ["trap-x"],
         "workspace": str(ws), "idempotency_key": "report-1"},
    )
    assert result["status"] == "recorded"
    ev = ws / ".soma" / "evidence"
    signal, = _jsonl(ev / "signals.jsonl")
    assert signal["cell"] == "trap-x"
    assert signal["signal"] == "tp"
    assert signal["event_id"], "MCP outcome signal is not idempotent"
    assert not (ev / "outcomes.jsonl").exists()


def test_migration_dedupes_linked_twin_even_when_timestamps_differ(tmp_path):
    from soma_cli.migration import run_epoch_migration
    ev = tmp_path / ".soma" / "evidence"
    ev.mkdir(parents=True)
    with open(ev / "outcomes.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"cell_id": "cell-m", "outcome": "success",
                            "timestamp": "2026-02-01T10:00:00Z", "outcome_id": "oid-1"}) + "\n")
    with open(ev / "signals.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": "2026-02-01T10:00:01Z", "cell": "cell-m",
                            "signal": "tp", "source": "mcp",
                            "metadata": {"outcome_id": "oid-1"}}) + "\n")
    assert run_epoch_migration(str(tmp_path)) is True
    rows = _jsonl(ev / "signals.jsonl")
    assert sum(1 for r in rows if r["cell"] == "cell-m" and r["signal"] == "tp") == 1


# ── Uninstall: in-root symlinked config dirs ─────────────────────────────

UNINSTALL_SH = os.path.join(REPO_ROOT, "install", "uninstall.sh")


def test_stow_style_symlinked_config_dir_inside_home_uninstalls(tmp_path):
    home, project = tmp_path / "home", tmp_path / "project"
    project.mkdir()
    real_kiro = home / "dotfiles" / ".kiro"
    (real_kiro / "steering").mkdir(parents=True)
    rule = real_kiro / "steering" / "soma-rule.md"
    rule.write_text("rule\n", encoding="utf-8")
    symlink_or_skip(real_kiro, home / ".kiro")
    manifest = home / ".soma" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({
        "platform": "kiro", "scope": "global", "backup_dir": None,
        "files": [str(home / ".kiro" / "steering" / "soma-rule.md")],
        "organs": [], "hooks": [],
    }), encoding="utf-8")
    proc = run([require_bash(), UNINSTALL_SH, "kiro", "--force", "--no-restore", "--keep-config"],
               cwd=str(project), env={"HOME": str(home), "USERPROFILE": str(home)})
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    assert not rule.exists()
    assert (home / ".kiro").is_symlink(), "the user's symlink itself must be left alone"
