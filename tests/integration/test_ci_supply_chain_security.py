"""Supply Chain & CI Hardening Tests (Phase 4).

Verifies pyproject.toml optional dependencies and publish.yml release asset uploads.
"""
import os
import pytest
from pathlib import Path
from conftest import REPO_ROOT


def test_pyproject_optional_dependencies_contains_keyring():
    """pyproject.toml must declare keyring under optional-dependencies."""
    pyproject_path = Path(REPO_ROOT) / "pyproject.toml"
    content = pyproject_path.read_text(encoding="utf-8")
    assert "keyring =" in content or "keyring = [" in content


def test_publish_yml_contains_release_asset_upload():
    """publish.yml must grant contents: write and upload release assets."""
    publish_yml = Path(REPO_ROOT) / ".github" / "workflows" / "publish.yml"
    content = publish_yml.read_text(encoding="utf-8")
    assert "contents: write" in content
    assert "gh release upload" in content
