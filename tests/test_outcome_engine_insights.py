"""TDD tests for human insight signals in enzymes/outcome_engine.py.

Gate 1 of Core Change Protocol. Tests the integration of human insight
signals into the existing fitness scoring pipeline.
"""
import json
import os
import pytest


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
