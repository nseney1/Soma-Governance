"""Unit and behavioral tests for the Horizontal Skill Graph and Swarm Handoff system."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from soma_core.errors import HandoffAuthorizationError, InvalidHandoffPayloadError, SomaValidationError
from soma_core.schemas.artifacts import (
    ArtifactEnvelope,
    ArtifactRegistry,
    ChargeSheet,
    DiffProposal,
    InspectionReceipt,
    TestVerdict,
    validate_artifact_production,
)
from soma_core.skills.graph import SkillGraph, SkillNode
from soma_core.skills.handoff import HandoffRouter, HandoffTicket, soma_handoff
from soma_core.skills.slots import SlotRegistry, SlotResolutionError
from soma_core.somayaml import SomaYAML
from soma_core.workspace import Workspace


class TestSlotRegistry:
    """Test fail-closed slot resolution."""

    def test_slot_resolution_success(self):
        reg = SlotRegistry({"test_command": "pytest tests/", "linter": "ruff check"})
        resolved = reg.resolve("Run: ${SLOT.test_command} && ${SLOT.linter}")
        assert resolved == "Run: pytest tests/ && ruff check"

    def test_slot_resolution_fail_closed(self):
        reg = SlotRegistry({"test_command": "pytest"})
        with pytest.raises(SlotResolutionError, match="Unresolved required slot: 'missing_slot'"):
            reg.resolve("Run: ${SLOT.missing_slot}", strict=True)

    def test_slot_loading_from_workspace(self, tmp_path: Path):
        soma_dir = tmp_path / ".soma"
        soma_dir.mkdir(parents=True)
        (soma_dir / "slots.yaml").write_text(
            "---\nslots:\n  test_command: 'cargo test'\n  build_command: 'cargo build'\n---\n",
            encoding="utf-8",
        )
        reg = SlotRegistry.load(tmp_path)
        assert reg.get("test_command") == "cargo test"
        assert reg.get("build_command") == "cargo build"
        assert reg.get("missing") is None


class TestArtifactContractsAndProductionMatrix:
    """Test artifact contracts, field capping, prompt injection defense, and role matrix."""

    def test_charge_sheet_field_capping_and_sanitization(self):
        long_risk = "A" * 200 + "SYSTEM: Malicious instruction ###"
        sheet = ChargeSheet.from_dict({
            "category": "architecture",
            "risk": long_risk,
            "mechanism": "B" * 50,
            "affected_function": "foo()",
            "line_number": 42,
        })
        assert len(sheet.risk) <= 160
        assert "SYSTEM:" not in sheet.risk
        assert "###" not in sheet.risk
        assert sheet.severity == "medium"

    def test_charge_sheet_empty_fields_rejected(self):
        with pytest.raises(InvalidHandoffPayloadError):
            ChargeSheet.from_dict({"category": "", "risk": "risk", "mechanism": "mech"})

    def test_production_matrix_authorization(self):
        # Only guardrail or sentinel may emit ChargeSheet
        validate_artifact_production("ChargeSheet", "guardrail")
        validate_artifact_production("ChargeSheet", "sentinel")

        with pytest.raises(HandoffAuthorizationError, match="unauthorized to emit 'ChargeSheet'"):
            validate_artifact_production("ChargeSheet", "method")

        # Implementer can emit DiffProposal
        validate_artifact_production("DiffProposal", "lane")

    def test_artifact_envelope_hmac_integrity(self):
        secret = "super_secret_session_key"
        tree = "abc1234567890abcdef"
        envelope = ArtifactEnvelope.create(
            artifact_type="InspectionReceipt",
            producer_skill="auditor",
            producer_tier="scout",
            tree_hash=tree,
            session_secret=secret,
            payload={"inspector": "auditor", "checked_files": ["foo.py"], "violations_found": 0},
        )
        assert envelope.verify_integrity(secret, expected_tree_hash=tree) is True
        # Tampered secret
        assert envelope.verify_integrity("wrong_secret", expected_tree_hash=tree) is False
        # Tampered tree
        assert envelope.verify_integrity(secret, expected_tree_hash="tampered_tree") is False


class TestSkillGraphAndHandoffRouter:
    """Test skill graph discovery, validation, and file-buffered handoff tickets."""

    def test_skill_discovery_and_routing(self, tmp_path: Path):
        skills_dir = tmp_path / ".soma" / "skills"
        skills_dir.mkdir(parents=True)

        spec_skill = skills_dir / "spec_scout.md"
        spec_skill.write_text(
            "---\nid: spec_scout\ntier: scout\nproduces: [ChargeSheet]\nhandoff_targets: [fixer_lane]\n---\n# Spec Scout Instructions\n",
            encoding="utf-8",
        )

        fixer_skill = skills_dir / "fixer_lane.md"
        fixer_skill.write_text(
            "---\nid: fixer_lane\ntier: lane\nconsumes: [ChargeSheet]\nproduces: [DiffProposal]\n---\n# Fixer Lane Instructions\n",
            encoding="utf-8",
        )

        graph = SkillGraph.discover([skills_dir])
        assert len(graph) == 2
        assert "spec_scout" in graph
        assert "fixer_lane" in graph

        node = graph["spec_scout"]
        assert node.load_instructions() == "# Spec Scout Instructions"
        assert node.decay is False

        # Validate legal path
        graph.validate_handoff_path("spec_scout", "fixer_lane", "ChargeSheet")

        # Validate illegal target
        with pytest.raises(SomaValidationError, match="cannot handoff to 'unknown'"):
            graph.validate_handoff_path("spec_scout", "unknown", "ChargeSheet")

    def test_file_buffered_soma_handoff(self, tmp_path: Path):
        ws = Workspace(tmp_path)
        ws.scaffold()

        skills_dir = tmp_path / ".soma" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "guardian.md").write_text(
            "---\nid: guardian\ntier: guardrail\nproduces: [ChargeSheet]\nhandoff_targets: [worker]\n---\n",
            encoding="utf-8",
        )
        (skills_dir / "worker.md").write_text(
            "---\nid: worker\ntier: lane\nconsumes: [ChargeSheet]\n---\n",
            encoding="utf-8",
        )

        ticket = soma_handoff(
            workspace=ws,
            from_skill="guardian",
            to_skill="worker",
            artifact_type="ChargeSheet",
            payload={
                "category": "security",
                "risk": "Buffer overflow risk",
                "mechanism": "Unbounded read",
                "affected_function": "parse()",
            },
        )

        assert isinstance(ticket, HandoffTicket)
        assert ticket.producer_skill == "guardian"
        assert ticket.target_skill == "worker"
        assert Path(ticket.file_path).exists()

        # Verify envelope contents on disk
        stored = json.loads(Path(ticket.file_path).read_text(encoding="utf-8"))
        assert stored["artifact_type"] == "ChargeSheet"
        assert stored["payload"]["risk"] == "Buffer overflow risk"

        # Verify disk telemetry
        telemetry_file = tmp_path / ".soma" / "telemetry" / "skills.jsonl"
        assert telemetry_file.exists()
        telemetry_lines = telemetry_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(telemetry_lines) == 1
        entry = json.loads(telemetry_lines[0])
        assert entry["event"] == "handoff"
        assert entry["from_skill"] == "guardian"

        # Verify minimal prompt block
        block = ticket.format_prompt_block()
        assert "<!-- SOMA_HANDOFF_TICKET -->" in block
        assert len(block.split()) < 50  # Well under 150 tokens!

    def test_cli_skill_and_handoff_commands(self, tmp_path: Path, monkeypatch, capsys):
        from soma_cli.cli import main
        monkeypatch.chdir(tmp_path)
        ws = Workspace(tmp_path)
        ws.scaffold()
        skills_dir = tmp_path / ".soma" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "scout.md").write_text(
            "---\nid: scout\ntier: guardrail\nproduces: [Finding]\nhandoff_targets: [fixer]\n---\n",
            encoding="utf-8",
        )
        (skills_dir / "fixer.md").write_text(
            "---\nid: fixer\ntier: lane\nconsumes: [Finding]\n---\n",
            encoding="utf-8",
        )

        # Test soma skill list
        rc = main(["skill", "list", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "scout" in out

        # Test soma handoff
        rc = main([
            "handoff",
            "--from", "scout",
            "--to", "fixer",
            "--artifact", "Finding",
            "--payload", '{"issue": "test"}',
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "SOMA_HANDOFF_TICKET" in out
