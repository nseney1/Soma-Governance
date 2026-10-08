"""Tests for soma_core.sentinels — Subagent liveness, deadlock detection, and escalation sentinels."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pytest

from soma_core.sentinels import (
    check_liveness,
    classify_file,
    is_test_file,
    set_review_mode,
    write_frontmatter,
    recommend_protocol,
)
from soma_core.somayaml import parse_frontmatter


def test_check_liveness_healthy_and_stalled() -> None:
    now = datetime.now(timezone.utc).isoformat()
    old = "2020-01-01T00:00:00Z"
    payload = {
        "agents": [
            {"name": "agent-healthy", "dispatched": now, "timeout_seconds": 600},
            {"name": "agent-stalled", "dispatched": old, "timeout_seconds": 10},
            {"name": "agent-bad-date", "dispatched": "invalid-date", "timeout_seconds": 10},
        ]
    }
    ret = check_liveness(json.dumps(payload))
    assert ret == 0


def test_check_liveness_invalid_json() -> None:
    ret = check_liveness("not-json")
    assert ret == 1


def test_classify_file_sensitivity() -> None:
    assert classify_file("Makefile") == "HIGH"
    assert classify_file("install.sh") == "HIGH"
    assert classify_file("soma_core/auth.py") == "HIGH"
    assert classify_file(".github/workflows/ci.yml") == "HIGH"
    assert classify_file("requirements.txt") == "HIGH"

    assert classify_file("docs/readme.md") == "LOW"
    assert classify_file("README.md") == "LOW"
    assert classify_file("LICENSE") == "LOW"
    assert classify_file("data.json") == "LOW"

    assert classify_file("soma_core/lifecycle.py") == "MEDIUM"
    assert classify_file("genome/testing.md") == "MEDIUM"


def test_is_test_file() -> None:
    assert is_test_file("tests/test_sentinels.py") is True
    assert is_test_file("src/foo_test.go") is True
    assert is_test_file("components/button.test.ts") is True
    assert is_test_file("src/app.py") is False


def test_set_review_mode(tmp_path: Path) -> None:
    conf = tmp_path / "steering.conf"
    conf.write_text("REVIEW_MODE=BREEZE\nOTHER=1\n", encoding="utf-8")
    set_review_mode(str(tmp_path), "TEMPEST")
    content = conf.read_text(encoding="utf-8")
    assert "REVIEW_MODE=TEMPEST\n" in content
    assert "OTHER=1\n" in content


def test_write_frontmatter(tmp_path: Path) -> None:
    target = tmp_path / "cell.md"
    metadata = {"id": "test-cell", "type": "wall"}
    body = "Body description\n"
    write_frontmatter(str(target), metadata, body)

    content = target.read_text(encoding="utf-8")
    fm = parse_frontmatter(content)
    assert fm["id"] == "test-cell"
    assert fm["type"] == "wall"
    assert "Body description" in content


def test_recommend_protocol_no_changes(tmp_path: Path) -> None:
    ret = recommend_protocol("--staged", [], tmp_path)
    assert ret == 1
