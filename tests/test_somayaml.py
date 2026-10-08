"""Tests for soma_core.somayaml — Pure-Python SomaYAML engine & unified domain model."""
from __future__ import annotations

import os
from pathlib import Path
import pytest

from soma_core.somayaml import (
    SomaYAML,
    SomaDocument,
    SomaYAMLError,
    FrontmatterError,
    dump_frontmatter,
    parse_frontmatter,
    parse_cell_frontmatter,
    parse_yaml_subset,
    _get_body,
    MAX_DOC_BYTES,
    MAX_SCALAR_CHARS,
    MAX_LINES,
    MAX_DEPTH,
)
from soma_core.workspace import Workspace


class TestSomaYAMLCoreParsing:
    """Test standard YAML subset parsing capabilities."""

    def test_flat_scalars(self):
        text = """
id: cell-123
name: 'Special Cell'
count: 42
pi: 3.14159
is_active: true
is_dormant: false
extra: null
"""
        data = parse_yaml_subset(text)
        assert data["id"] == "cell-123"
        assert data["name"] == "Special Cell"
        assert data["count"] == 42
        assert data["pi"] == 3.14159
        assert data["is_active"] is True
        assert data["is_dormant"] is False
        assert data["extra"] is None

    def test_wrapped_plain_scalars(self):
        text = """
hypothesis: A persona specialized in bash scripting improves the quality of shell-based
  automation.
prediction: Deploying this persona will increase the robustness of install and safety
  scripts.
falsification: Shell scripts are deprecated and no longer used.
"""
        data = parse_yaml_subset(text)
        assert data["hypothesis"] == (
            "A persona specialized in bash scripting improves the quality of shell-based "
            "automation."
        )
        assert data["prediction"] == (
            "Deploying this persona will increase the robustness of install and safety "
            "scripts."
        )

    def test_block_scalars_literal_and_folded(self):
        text = """
literal: |
  line 1
  line 2
folded: >
  line 1
  line 2
"""
        data = parse_yaml_subset(text)
        assert data["literal"] == "line 1\nline 2\n"
        assert data["folded"] == "line 1 line 2\n"

    def test_nested_mappings_and_sequences(self):
        text = """
id: rule-complex
target_paths:
  - "soma_core/*.py"
  - "soma_cli/*.py"
fitness:
  triggers: 10
  score: 0.95
tags: [security, gates, v1]
"""
        data = parse_yaml_subset(text)
        assert data["target_paths"] == ["soma_core/*.py", "soma_cli/*.py"]
        assert data["fitness"]["triggers"] == 10
        assert data["fitness"]["score"] == 0.95
        assert data["tags"] == ["security", "gates", "v1"]

    def test_unquoted_apostrophes_and_ratios(self):
        text = """
desc: organism's DNA
ratio: 1:1
"""
        data = parse_yaml_subset(text)
        assert data["desc"] == "organism's DNA"
        assert data["ratio"] == "1:1"


class TestSomaYAMLSafetyAndDoSGuards:
    """Security, anti-poisoning, and denial-of-service controls."""

    def test_max_doc_bytes_limit(self):
        oversized = "a: " + ("x" * (MAX_DOC_BYTES + 10))
        with pytest.raises(SomaYAMLError, match="exceeds maximum allowed size"):
            SomaYAML.parse_text(oversized)

    def test_max_lines_limit(self):
        too_many_lines = "\n".join(f"k{i}: v" for i in range(MAX_LINES + 5))
        with pytest.raises(SomaYAMLError, match="exceeds maximum line limit"):
            SomaYAML.parse_text(too_many_lines)

    def test_max_scalar_chars_limit(self):
        long_scalar = "key: " + ("A" * (MAX_SCALAR_CHARS + 1))
        with pytest.raises(SomaYAMLError, match=r"Scalar length \(\d+\) exceeds maximum limit"):
            SomaYAML.parse_text(long_scalar)

    def test_max_depth_block_limit(self):
        nested = ""
        for i in range(MAX_DEPTH + 2):
            nested += f"{'  ' * i}nest_{i}:\n"
        nested += f"{'  ' * (MAX_DEPTH + 2)}val: leaf\n"
        with pytest.raises(SomaYAMLError, match="Maximum YAML nesting depth exceeded"):
            SomaYAML.parse_text(nested)

    def test_max_depth_flow_limit(self):
        nested_flow = "a: " + ("[" * (MAX_DEPTH + 2)) + ("0" * 1) + ("]" * (MAX_DEPTH + 2))
        with pytest.raises(SomaYAMLError, match="Maximum YAML nesting depth exceeded"):
            SomaYAML.parse_text(nested_flow)

    def test_duplicate_key_prohibition_block(self):
        text = """
id: wall-1
enforcement: advisory
enforcement: gate
"""
        with pytest.raises(SomaYAMLError, match="Duplicate key 'enforcement' detected"):
            SomaYAML.parse_text(text)

    def test_duplicate_key_prohibition_flow(self):
        text = "map: {key: 1, key: 2}"
        with pytest.raises(SomaYAMLError, match="Duplicate key 'key' detected"):
            SomaYAML.parse_text(text)

    def test_zero_width_sanitization(self):
        # Hidden zero-width characters in key or value
        text = "\ufeffid:\u200b cell-sanitized\n\u200ctier: \u200dmethod"
        doc = SomaYAML.parse_text(text)
        assert doc["id"] == "cell-sanitized"
        assert doc["tier"] == "method"

    def test_control_character_rejection(self):
        text = "key: bad\x07bell"
        with pytest.raises(SomaYAMLError, match="Control character"):
            SomaYAML.parse_text(text)

    def test_null_byte_escape_rejection(self):
        text = 'key: "null\\0byte"'
        with pytest.raises(SomaYAMLError, match="Escape sequence \\\\0 is not permitted"):
            SomaYAML.parse_text(text)


class TestSomaDocumentAndDomainModel:
    """Test polymorphic document models, schema inference, and mapping interface."""

    def test_rule_kind_auto_inference(self):
        text = """---
id: wall-symlink
type: wall
enforcement: gate
---
# Wall Symlink
"""
        doc = SomaYAML.parse_text(text)
        assert isinstance(doc, SomaDocument)
        assert doc.kind == "rule"
        assert doc.id == "wall-symlink"
        assert doc.enforcement == "gate"
        assert doc.type == "wall"
        assert doc.decay is True
        assert doc.target_paths == []
        assert doc["id"] == "wall-symlink"
        assert "Wall Symlink" in doc.body

    def test_skill_kind_auto_inference(self):
        text = """---
id: tdd-cycle
tier: method
consumes: [FeatureSpec]
produces: [VerifiedPatch]
---
# TDD Cycle
"""
        doc = SomaYAML.parse_text(text)
        assert doc.kind == "skill"
        assert doc.id == "tdd-cycle"
        assert doc.tier == "method"
        assert doc.consumes == ["FeatureSpec"]
        assert doc.produces == ["VerifiedPatch"]
        assert doc.decay is False
        assert doc.handoff_targets == []

    def test_mapping_interface(self):
        doc = SomaDocument(metadata={"id": "test", "num": 42}, body="# Body", kind="generic")
        assert len(doc) == 2
        assert "id" in doc
        assert "missing" not in doc
        assert doc["id"] == "test"
        assert doc.get("num") == 42
        assert doc.get("missing", "default") == "default"
        assert list(doc.keys()) == ["id", "num"]
        assert list(doc.values()) == ["test", 42]
        assert list(doc.items()) == [("id", "test"), ("num", 42)]
        assert doc.metadata == {"id": "test", "num": 42}
        assert doc.body == "# Body"

    def test_parse_file_confined_workspace(self, tmp_path: Path):
        ws = Workspace(tmp_path)
        rule_file = tmp_path / "cell.md"
        rule_file.write_text("---\nid: local-cell\n---\n# Body\n", encoding="utf-8")

        doc = SomaYAML.parse_file("cell.md", ws)
        assert doc.id == "local-cell"

    def test_parse_file_rejects_symlinks(self, tmp_path: Path):
        ws = Workspace(tmp_path)
        real_file = tmp_path / "real.md"
        real_file.write_text("---\nid: real\n---\n", encoding="utf-8")

        symlink_file = tmp_path / "symlink.md"
        try:
            symlink_file.symlink_to(real_file)
        except OSError:
            pytest.skip("Symlinks not supported on this platform")

        with pytest.raises(SomaYAMLError, match="Symlink parsing prohibited"):
            SomaYAML.parse_file("symlink.md", ws)


class TestBackwardCompatibilityParity:
    """Ensure exact drop-in parity with legacy frontmatter API."""

    def test_parse_frontmatter_and_get_body(self):
        text = "---\nid: legacy-cell\nversion: 1.0\n---\n# Cell Content\nLine 2"
        meta = parse_frontmatter(text)
        assert meta["id"] == "legacy-cell"
        assert meta["version"] == 1.0
        assert _get_body(text) == "# Cell Content\nLine 2"

    def test_parse_cell_frontmatter_file_and_str(self, tmp_path: Path):
        f = tmp_path / "rule.md"
        f.write_text("---\nid: from-file\n---\n# Body from file", encoding="utf-8")

        meta1, body1 = parse_cell_frontmatter(str(f))
        assert meta1["id"] == "from-file"
        assert body1 == "# Body from file"

        meta2, body2 = parse_cell_frontmatter("---\nid: from-str\n---\n# Body from str")
        assert meta2["id"] == "from-str"
        assert body2 == "# Body from str"

    def test_dump_frontmatter_roundtrip(self):
        data = {
            "id": "roundtrip-cell",
            "active": True,
            "score": 0.88,
            "tags": ["alpha", "beta"],
            "nested": {"key": "val"},
        }
        body = "# Header\nBody text"
        dumped = dump_frontmatter(data, body=body)
        meta, parsed_body = parse_cell_frontmatter(dumped)
        assert meta == data
        assert parsed_body == body
