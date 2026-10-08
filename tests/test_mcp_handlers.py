"""Unit and contract tests for decomposed MCP handlers (audit, governance, telemetry, verification)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import pytest

from soma_mcp.handlers.audit import (
    _handle_audit_security,
    _handle_audit_performance,
    _handle_scan,
)
from soma_mcp.handlers.governance import (
    _handle_create_cell,
    _handle_list_cells,
    _handle_propose_change,
    _handle_generate_manifest,
    _handle_soma_handoff,
)
from soma_mcp.handlers.telemetry import (
    _handle_report_outcome,
    _handle_capture_insight,
    _handle_grade,
    _handle_coverage,
    _handle_fitness,
)
from soma_mcp.handlers.verification import (
    _handle_verify_changes,
    _handle_poll_verification,
    _handle_checkpoint,
    _handle_request_receipt,
)
from soma_core.somayaml import dump_frontmatter


@pytest.fixture
def mcp_workspace(tmp_path: Path) -> Path:
    cells_dir = tmp_path / ".soma" / "cells" / "vacuoles"
    cells_dir.mkdir(parents=True, exist_ok=True)
    cell_file = cells_dir / "sample-cell.md"
    fm = {
        "id": "sample-cell",
        "type": "vacuole",
        "target_paths": ["src/*.py"],
        "hypothesis": "Sample hypothesis",
        "fitness": {"score": 0.5, "triggers": 1, "true_positives": 1, "false_positives": 0},
    }
    cell_file.write_text(f"---\n{dump_frontmatter(fm)}---\n\n# Body\n", encoding="utf-8")
    (tmp_path / ".soma" / "evidence").mkdir(parents=True, exist_ok=True)
    (tmp_path / "genome").mkdir(parents=True, exist_ok=True)
    return tmp_path


# ── Audit Handlers ──────────────────────────────────────────────────────────

def test_audit_security(mcp_workspace: Path):
    ws = str(mcp_workspace)
    # Clean code pass
    res_pass = _handle_audit_security({"workspace": ws, "proposed_content": "def foo(): return 1"}, None)
    assert res_pass["status"] == "PASS"

    # Hardcoded secret fail
    res_secret = _handle_audit_security({"workspace": ws, "proposed_content": "password='secret'"}, None)
    assert res_secret["status"] == "FAIL"

    # Eval injection fail
    res_eval = _handle_audit_security({"workspace": ws, "proposed_content": "eval(x)"}, None)
    assert res_eval["status"] == "FAIL"

    # XSS fail
    res_xss = _handle_audit_security({"workspace": ws, "file_path": "index.html", "proposed_content": "element.innerHTML = x"}, None)
    assert res_xss["status"] == "FAIL"

    # SQL injection fail
    res_sql = _handle_audit_security({"workspace": ws, "file_path": "query.sql", "proposed_content": "f'SELECT * FROM users'"}, None)
    assert res_sql["status"] == "FAIL"


def test_audit_performance(mcp_workspace: Path):
    ws = str(mcp_workspace)
    res_pass = _handle_audit_performance({"workspace": ws, "proposed_content": "def foo(): return 1"}, None)
    assert res_pass["status"] == "PASS"

    # Nested loops
    nested = "for a in x:\n for b in y:\n  for c in z:\n   pass"
    res_loop = _handle_audit_performance({"workspace": ws, "proposed_content": nested}, None)
    assert res_loop["status"] == "FAIL"

    # Inefficient query
    res_q = _handle_audit_performance({"workspace": ws, "proposed_content": "db.query('SELECT *')"}, None)
    assert res_q["status"] == "FAIL"

    # Wildcard import
    res_wildcard = _handle_audit_performance({"workspace": ws, "file_path": "main.py", "proposed_content": "from os import *"}, None)
    assert res_wildcard["status"] == "FAIL"


def test_scan(mcp_workspace: Path):
    ws = str(mcp_workspace)
    res = _handle_scan({"workspace": ws, "files": ["src/main.py"]}, None)
    assert isinstance(res, dict)


# ── Governance Handlers ─────────────────────────────────────────────────────

def test_governance_create_and_list_cells(mcp_workspace: Path):
    ws = str(mcp_workspace)
    # Dry run create cell
    res_create = _handle_create_cell({
        "workspace": ws,
        "description": "Rule to test something",
        "domain": "testing",
        "cell_type": "vacuole",
        "dry_run": True,
    }, None)
    assert "prompt" in res_create
    assert res_create.get("dry_run") is True

    # List cells
    res_list = _handle_list_cells({"workspace": ws}, None)
    assert isinstance(res_list, list)
    assert len(res_list) >= 1
    assert res_list[0]["id"] == "sample-cell"


def test_governance_propose_change(mcp_workspace: Path):
    ws = str(mcp_workspace)
    res = _handle_propose_change({
        "workspace": ws,
        "cell_name": "sample-cell",
        "change_type": "update",
        "content": "test",
    }, None)
    assert isinstance(res, dict)


def test_governance_generate_manifest(mcp_workspace: Path):
    ws = str(mcp_workspace)
    res = _handle_generate_manifest({"workspace": ws}, None)
    assert isinstance(res, dict)


def test_governance_soma_handoff(mcp_workspace: Path):
    ws = str(mcp_workspace)
    res = _handle_soma_handoff({
        "workspace": ws,
        "from_skill": "sample-cell",
        "to_skill": "sample-cell",
        "artifact_type": "review_charge",
        "payload": {
            "charges": [
                {
                    "category": "architecture",
                    "risk": "leaky abstraction",
                    "mechanism": "direct coupling",
                }
            ]
        },
    }, None)
    assert isinstance(res, dict)


# ── Telemetry Handlers ──────────────────────────────────────────────────────

def test_telemetry_report_outcome(mcp_workspace: Path):
    ws = str(mcp_workspace)
    # Invalid outcome
    res_inv = _handle_report_outcome({"workspace": ws, "outcome": "invalid_val"}, None)
    assert "error" in res_inv

    # Valid outcome
    res_valid = _handle_report_outcome({
        "workspace": ws,
        "outcome": "success",
        "cell_id": "sample-cell",
        "idempotency_key": "test-key-1",
    }, None)
    assert res_valid["status"] == "recorded"


def test_telemetry_capture_insight(mcp_workspace: Path):
    ws = str(mcp_workspace)
    res = _handle_capture_insight({
        "workspace": ws,
        "insight": "Edge case discovered",
        "was_covered": False,
        "context_files": ["src/main.py"],
    }, None)
    assert res["status"] == "recorded"


def test_telemetry_grade_and_coverage_and_fitness(mcp_workspace: Path):
    ws = str(mcp_workspace)
    res_grade = _handle_grade({"workspace": ws}, None)
    assert isinstance(res_grade, dict)

    res_cov = _handle_coverage({"workspace": ws}, None)
    assert isinstance(res_cov, dict)

    res_fit = _handle_fitness({"workspace": ws, "cell_name": "sample-cell"}, None)
    assert isinstance(res_fit, (dict, list))


# ── Verification Handlers ───────────────────────────────────────────────────

def test_verification_handlers(mcp_workspace: Path):
    ws = str(mcp_workspace)
    # verify_changes
    res_verify = _handle_verify_changes({"workspace": ws, "files": ["src/main.py"]}, None)
    assert isinstance(res_verify, dict)

    # poll_verification
    res_poll = _handle_poll_verification({"workspace": ws, "run_id": "test-run"}, None)
    assert isinstance(res_poll, dict)

    # checkpoint
    res_cp = _handle_checkpoint({"workspace": ws}, None)
    assert isinstance(res_cp, dict)

    # request_receipt
    res_rr = _handle_request_receipt({"workspace": ws}, None)
    assert isinstance(res_rr, dict)
