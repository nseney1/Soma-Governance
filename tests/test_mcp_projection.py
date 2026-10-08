"""Unit and behavioral tests for MCP response projection and SOMA-V01 security guards."""
from __future__ import annotations

import pytest
from soma_mcp.projection import DENYLIST, project_response


class TestResponseProjection:
    """Test opt-in view and field projection."""

    def test_full_view_backwards_compatibility(self):
        payload = {
            "id": "cell-1",
            "body": "# Extensive guidance markdown\n" * 100,
            "status": "active",
        }
        res = project_response(payload, view="full")
        assert res == payload

        res_none = project_response(payload, view=None)
        assert res_none == payload

    def test_ids_view_projection(self):
        payload = {
            "cells": [
                {"id": "cell-1", "type": "wall", "body": "text"},
                {"id": "cell-2", "type": "membrane", "body": "text"},
            ],
            "total": 2,
        }
        res = project_response(payload, view="ids")
        assert res == {"cells": ["cell-1", "cell-2"]}

    def test_summary_view_projection(self):
        payload = {
            "id": "run-42",
            "status": "passed",
            "score": 0.95,
            "verbose_logs": "Detailed debug traces line 1\nline 2\n" * 50,
            "cells": [
                {"id": "c1", "status": "survive", "body": "lots of instructions"},
            ],
        }
        res = project_response(payload, view="summary")
        assert res["id"] == "run-42"
        assert res["status"] == "passed"
        assert res["score"] == 0.95
        assert "verbose_logs" not in res
        assert res["cells_count"] == 1
        assert res["cells"][0]["id"] == "c1"
        assert "body" not in res["cells"][0]

    def test_custom_fields_projection(self):
        payload = {
            "cell": {
                "id": "cell-123",
                "meta": {
                    "tier": "guardrail",
                    "secret": "hide_me",
                },
                "instructions": "large markdown body",
            },
            "status": "ok",
        }
        res = project_response(payload, fields=["cell.id", "cell.meta.tier", "status"])
        assert res == {
            "cell": {
                "id": "cell-123",
                "meta": {
                    "tier": "guardrail",
                },
            },
            "status": "ok",
        }

    def test_soma_v01_security_scrubbing(self):
        payload = {
            "id": "audit-1",
            "task_plan": "Sensitive reasoning and internal attack vectors",
            "prompt": "Raw system prompt with instructions",
            "raw_prompt": "Hidden prompt",
            "__class__": "Introspection exploit",
            "verdict": "valid",
        }
        # Even with view='full', denylisted fields must be scrubbed
        res = project_response(payload, view="full")
        assert "task_plan" not in res
        assert "prompt" not in res
        assert "raw_prompt" not in res
        assert "__class__" not in res
        assert res["verdict"] == "valid"

    def test_soma_v01_denied_field_request_rejected(self):
        payload = {
            "id": "audit-1",
            "task_plan": "Sensitive reasoning",
            "status": "ok",
        }
        res = project_response(payload, fields=["id", "task_plan"])
        assert "task_plan" not in res
        assert res == {"id": "audit-1"}

    def test_execute_tool_with_projection(self, tmp_path, monkeypatch):
        from soma_mcp.tools import execute_tool

        (tmp_path / ".soma" / "cells").mkdir(parents=True, exist_ok=True)
        monkeypatch.chdir(tmp_path)
        # Test audit tool with fields projection
        res = execute_tool(
            "soma_audit_security",
            {
                "proposed_content": "x = 1\n",
                "file_path": "test.py",
                "fields": ["status"],
            },
        )
        assert res == {"status": "PASS"}

