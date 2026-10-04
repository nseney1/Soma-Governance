"""TDD tests for human insight signals in enzymes/outcome_engine.py.

Gate 1 of Core Change Protocol. Tests the integration of human insight
signals into the existing fitness scoring pipeline.
"""
import json
import os
import sys
import pytest

# outcome_engine does `from soma_resolve import ...`; make enzymes/ importable
# so this module does not depend on another test file having run first.
_ENZYMES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "enzymes")
if _ENZYMES not in sys.path:
    sys.path.insert(0, _ENZYMES)


def _write_insights(workspace, insights):
    """Helper: write insight records to .soma/human_insights.jsonl."""
    jsonl_path = os.path.join(workspace, ".soma", "human_insights.jsonl")
    os.makedirs(os.path.dirname(jsonl_path), exist_ok=True)
    with open(jsonl_path, "w") as f:
        for record in insights:
            f.write(json.dumps(record) + "\n")


def _write_cell(workspace, name, target_paths):
    """Helper: create a minimal cell file."""
    cells_dir = os.path.join(workspace, ".soma", "cells", "vacuoles")
    os.makedirs(cells_dir, exist_ok=True)
    content = f"""---
type: vacuole
enforcement: advisory
hypothesis: "Test cell"
target_paths:
{chr(10).join(f'  - "{p}"' for p in target_paths)}
fitness:
  triggers: 5
  true_positives: 3
  false_positives: 1
---
Test cell body.
"""
    with open(os.path.join(cells_dir, f"{name}.md"), "w") as f:
        f.write(content)


class TestCaptureHumanInsightSignals:
    """Tests for capture_human_insight_signals()."""

    def test_returns_signals_for_matching_cells(self, tmp_path):
        """Insights matching cell target_paths produce fitness signals."""
        from enzymes.outcome_engine import capture_human_insight_signals

        workspace = str(tmp_path)
        _write_cell(workspace, "vacuole-api-check", ["api/*.py"])
        _write_insights(workspace, [
            {"insight": "API needs validation", "context_files": ["api/handler.py"],
             "category": "validation", "timestamp": "2026-09-29T10:00:00Z",
             "was_covered": True, "covering_cells": ["vacuole-api-check"]},
        ])

        signals = capture_human_insight_signals(workspace)
        assert len(signals) >= 1
        matching = [s for s in signals if s["cell"] == "vacuole-api-check"]
        assert len(matching) == 1
        # Verify update_cell_fitness compatible schema
        assert os.path.isfile(matching[0]["_path"])
        assert matching[0]["signal"] == pytest.approx(0.5)
        assert matching[0]["verified"] is True

    def test_signal_weight_is_configurable(self, tmp_path):
        """Human insight signal weight reads from .soma/config if present."""
        from enzymes.outcome_engine import capture_human_insight_signals

        workspace = str(tmp_path)
        _write_cell(workspace, "vacuole-test", ["src/*.py"])
        _write_insights(workspace, [
            {"insight": "Check this", "context_files": ["src/main.py"],
             "category": "attention", "timestamp": "2026-09-29T10:00:00Z",
             "was_covered": True, "covering_cells": ["vacuole-test"]},
        ])

        # Default weight should be 0.5 (no config file)
        signals = capture_human_insight_signals(workspace)
        matching = [s for s in signals if s["cell"] == "vacuole-test"]
        assert len(matching) == 1
        assert matching[0]["weight"] == pytest.approx(0.5, abs=0.01)

        # With config file: weight should be overridden (requires pyyaml)
        try:
            import yaml as _yaml
        except ImportError:
            _yaml = None

        if _yaml is not None:
            config_path = os.path.join(workspace, ".soma", "config.yaml")
            with open(config_path, "w") as f:
                f.write("insight_signal_weight: 0.8\n")

            # Reset cursor so insights are re-read with new config
            cursor_path = os.path.join(workspace, ".soma", "insight_cursor")
            if os.path.isfile(cursor_path):
                os.remove(cursor_path)

            signals = capture_human_insight_signals(workspace)
            matching = [s for s in signals if s["cell"] == "vacuole-test"]
            assert len(matching) == 1
            assert matching[0]["weight"] == pytest.approx(0.8, abs=0.01)

    def test_no_insights_no_signals(self, tmp_path):
        """When .soma/human_insights.jsonl doesn't exist, return empty list."""
        from enzymes.outcome_engine import capture_human_insight_signals

        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, ".soma"), exist_ok=True)

        signals = capture_human_insight_signals(workspace)
        assert signals == []

    def test_uncovered_insights_flagged(self, tmp_path):
        """Insights with was_covered=False produce a 'blind_spot' signal."""
        from enzymes.outcome_engine import capture_human_insight_signals

        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, ".soma"), exist_ok=True)
        _write_insights(workspace, [
            {"insight": "Nobody watches this", "context_files": ["orphan/file.py"],
             "category": "attention", "timestamp": "2026-09-29T10:00:00Z",
             "was_covered": False, "covering_cells": []},
        ])

        signals = capture_human_insight_signals(workspace)
        blind_spots = [s for s in signals if s.get("signal_type") == "blind_spot"]
        assert len(blind_spots) >= 1
        assert "orphan/file.py" in blind_spots[0]["files"]


# ── Durable insight cursor ─────────────────────────────────────────────

def _covered(cell, text="Needs attention"):
    return {"insight": text, "context_files": ["api/handler.py"], "category": "validation",
            "timestamp": "2026-09-29T10:00:00Z", "was_covered": True, "covering_cells": [cell]}


def _cursor_path(workspace):
    return os.path.join(workspace, ".soma", "insight_cursor")


def _signals_log(workspace):
    path = os.path.join(workspace, ".soma", "evidence", "signals.jsonl")
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


class TestInsightCursorDurability:

    def test_read_never_writes_cursor(self, tmp_path):
        from enzymes.outcome_engine import read_human_insight_signals
        ws = str(tmp_path)
        _write_cell(ws, "vacuole-api-check", ["api/*.py"])
        _write_insights(ws, [_covered("vacuole-api-check")])

        signals, offset = read_human_insight_signals(ws)
        assert len(signals) == 1
        assert offset == os.path.getsize(os.path.join(ws, ".soma", "human_insights.jsonl"))
        assert not os.path.exists(_cursor_path(ws))
        # Re-reading without commit yields the same insight again
        again, _ = read_human_insight_signals(ws)
        assert len(again) == 1

    def test_commit_cursor_is_atomic_and_advances(self, tmp_path, monkeypatch):
        import enzymes.outcome_engine as oe
        ws = str(tmp_path)
        _write_cell(ws, "vacuole-api-check", ["api/*.py"])
        _write_insights(ws, [_covered("vacuole-api-check")])
        signals, offset = oe.read_human_insight_signals(ws)

        replaced = []
        real_replace = os.replace

        def spy(src, dst):
            replaced.append((src, dst))
            return real_replace(src, dst)

        monkeypatch.setattr(oe.os, "replace", spy)
        assert oe.commit_insight_cursor(ws, offset) is True
        assert replaced and replaced[-1][1] == _cursor_path(ws)
        with open(_cursor_path(ws)) as f:
            assert int(f.read().strip()) == offset
        leftovers = [n for n in os.listdir(os.path.join(ws, ".soma")) if n.endswith(".tmp")]
        assert leftovers == []
        assert oe.read_human_insight_signals(ws)[0] == []

    def test_partial_trailing_line_is_reread(self, tmp_path):
        from enzymes.outcome_engine import read_human_insight_signals, commit_insight_cursor
        ws = str(tmp_path)
        _write_cell(ws, "vacuole-a", ["api/*.py"])
        _write_cell(ws, "vacuole-b", ["api/*.py"])
        path = os.path.join(ws, ".soma", "human_insights.jsonl")
        first = json.dumps(_covered("vacuole-a")) + "\n"
        second = json.dumps(_covered("vacuole-b"))
        # newline="\n": the offset is in bytes, and Windows text mode writes CRLF.
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(first + second[:20])  # writer crashed / still mid-append

        signals, offset = read_human_insight_signals(ws)
        assert [s["cell"] for s in signals] == ["vacuole-a"]
        assert offset == len(first.encode("utf-8"))
        commit_insight_cursor(ws, offset)

        with open(path, "a", encoding="utf-8") as f:
            f.write(second[20:] + "\n")
        signals, offset = read_human_insight_signals(ws)
        assert [s["cell"] for s in signals] == ["vacuole-b"]
        assert offset == os.path.getsize(path)

    def test_capture_wrapper_still_commits(self, tmp_path):
        from enzymes.outcome_engine import capture_human_insight_signals
        ws = str(tmp_path)
        _write_cell(ws, "vacuole-api-check", ["api/*.py"])
        _write_insights(ws, [_covered("vacuole-api-check")])
        assert len(capture_human_insight_signals(ws)) == 1
        assert capture_human_insight_signals(ws) == []


class TestAppendFitnessLogResult:

    def _sig(self, tmp_path):
        return [{"cell": "vacuole-x", "_path": str(tmp_path / "x.md"), "signal": 0.5,
                 "verified": True, "reasons": []}]

    def test_true_when_all_appends_succeed(self, tmp_path):
        from enzymes.outcome_engine import append_fitness_log
        assert append_fitness_log(str(tmp_path), self._sig(tmp_path), {}) is True
        assert len(_signals_log(str(tmp_path))) == 1

    def test_true_for_empty_signal_list(self, tmp_path):
        from enzymes.outcome_engine import append_fitness_log
        assert append_fitness_log(str(tmp_path), [], {}) is True

    def test_false_when_any_append_fails(self, tmp_path, monkeypatch):
        import soma_sdk.telemetry as telemetry
        from enzymes.outcome_engine import append_fitness_log

        def boom(*args, **kwargs):
            raise RuntimeError("migration in progress")

        monkeypatch.setattr(telemetry, "append_signals", boom)
        assert append_fitness_log(str(tmp_path), self._sig(tmp_path), {}) is False


def _stub_main(monkeypatch, ws):
    import enzymes.outcome_engine as oe
    monkeypatch.setattr(oe, "resolve_workspace", lambda *a, **k: ws)
    monkeypatch.setattr(oe, "capture_test_outcome", lambda w: {"verified": False, "reason": "stub"})
    monkeypatch.setattr(oe, "capture_build_outcome", lambda w: {"verified": False})
    monkeypatch.setattr(oe, "capture_git_signals", lambda w: {"reverts": 0, "rework_files": []})
    monkeypatch.setattr(oe, "capture_mcp_outcomes", lambda w: [])
    monkeypatch.setattr(oe, "_get_changed_files", lambda w: [])
    monkeypatch.setattr(oe, "match_cells_to_changes", lambda w, files: [])
    return oe


class TestMainCursorCommitOrdering:

    def _setup(self, tmp_path):
        ws = str(tmp_path)
        _write_cell(ws, "vacuole-api-check", ["api/*.py"])
        _write_insights(ws, [_covered("vacuole-api-check")])
        return ws

    def test_crash_in_append_leaves_cursor_and_insight_is_reread(self, tmp_path, monkeypatch):
        ws = self._setup(tmp_path)
        oe = _stub_main(monkeypatch, ws)
        real_append = oe.append_fitness_log

        def crash(*args, **kwargs):
            raise KeyboardInterrupt("simulated crash before evidence persisted")

        monkeypatch.setattr(oe, "append_fitness_log", crash)
        with pytest.raises(KeyboardInterrupt):
            oe.main()
        assert not os.path.exists(_cursor_path(ws))

        monkeypatch.setattr(oe, "append_fitness_log", real_append)
        oe.main()
        rows = _signals_log(ws)
        assert [r["cell"] for r in rows] == ["vacuole-api-check"]
        with open(_cursor_path(ws)) as f:
            assert int(f.read()) == os.path.getsize(os.path.join(ws, ".soma", "human_insights.jsonl"))

    def test_failed_append_does_not_commit_cursor(self, tmp_path, monkeypatch):
        import soma_sdk.telemetry as telemetry
        ws = self._setup(tmp_path)
        oe = _stub_main(monkeypatch, ws)

        def boom(*args, **kwargs):
            raise RuntimeError("migration in progress")

        monkeypatch.setattr(telemetry, "append_signals", boom)
        oe.main()  # must not raise
        assert not os.path.exists(_cursor_path(ws))
        signals, _ = oe.read_human_insight_signals(ws)
        assert len(signals) == 1  # still pending

    def test_blind_spots_only_commit_cursor(self, tmp_path, monkeypatch):
        ws = str(tmp_path)
        os.makedirs(os.path.join(ws, ".soma", "cells"), exist_ok=True)
        _write_insights(ws, [{"insight": "Nobody watches this", "context_files": ["orphan.py"],
                              "category": "attention", "timestamp": "2026-09-29T10:00:00Z",
                              "was_covered": False, "covering_cells": []}])
        oe = _stub_main(monkeypatch, ws)
        oe.main()
        with open(_cursor_path(ws)) as f:
            assert int(f.read()) == os.path.getsize(os.path.join(ws, ".soma", "human_insights.jsonl"))
