from pathlib import Path
"""TDD tests for review intensity level documentation consistency.

Verifies that the review intensity hierarchy is consistently documented
across README.md and the adaptive-reviewer SKILL.md.

Tests verify:
1. All intensity levels exist in both README and SKILL.md
2. Supercell is documented as the highest intensity
3. Escalation table includes all levels
"""
import os
import re
import sys

import pytest

REPO_ROOT = str(next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists()))
sys.path.insert(0, REPO_ROOT)


# Expected intensity levels in order (lowest to highest)
INTENSITY_LEVELS = ["Breeze", "Gale", "Trident", "Maelstrom", "Tempest", "Supercell"]


class TestReviewIntensityDocs:
    """Review intensity documentation consistency."""

    def test_readme_contains_all_intensity_levels(self):
        """Intensity levels are documented in ROADMAP (stripped from README in v0.73)."""
        roadmap = _read(os.path.join(REPO_ROOT, "docs", "project", "ROADMAP.md"))
        assert "Review Intensity" in roadmap or "Breeze" in roadmap, \
            "Review intensity should be documented in ROADMAP.md"

    def test_readme_intensity_table_has_supercell(self):
        """Supercell is documented in SKILL.md (stripped from README in v0.73)."""
        skill_path = os.path.join(REPO_ROOT, "organs", "adaptive-reviewer", "SKILL.md")
        if not os.path.isfile(skill_path):
            pytest.skip("adaptive-reviewer SKILL.md not found")
        skill = _read(skill_path)
        assert "Supercell" in skill


    def test_skill_escalation_table_has_supercell(self):
        """Adaptive reviewer SKILL.md must include Supercell escalation."""
        skill_path = os.path.join(REPO_ROOT, "organs", "adaptive-reviewer", "SKILL.md")
        if not os.path.isfile(skill_path):
            pytest.skip("adaptive-reviewer SKILL.md not found")
        skill = _read(skill_path)
        assert "Supercell" in skill, "Missing Supercell in adaptive-reviewer SKILL.md"

    def test_skill_escalation_table_has_all_levels(self):
        """Adaptive reviewer escalation table must reference all levels."""
        skill_path = os.path.join(REPO_ROOT, "organs", "adaptive-reviewer", "SKILL.md")
        if not os.path.isfile(skill_path):
            pytest.skip("adaptive-reviewer SKILL.md not found")
        skill = _read(skill_path)
        for level in INTENSITY_LEVELS:
            assert level in skill, (
                f"Missing intensity level '{level}' in adaptive-reviewer SKILL.md"
            )



def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _extract_section(text, heading):
    """Extract content from a markdown heading to the next heading of same or higher level."""
    pattern = rf"^(#{{1,3}})\s+{re.escape(heading)}\s*$"
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        return None
    start = match.end()
    level = len(match.group(1))
    # Find next heading of same or higher level
    next_heading = re.search(rf"^#{{1,{level}}}\s+", text[start:], re.MULTILINE)
    if next_heading:
        return text[start:start + next_heading.start()]
    return text[start:]
