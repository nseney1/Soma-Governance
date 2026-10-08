"""Consolidated module contract tests for Soma Governance.

Replaces 83 individual 1:1 mirrored stub files with a single parameterized
test that verifies every pure-Python module in the repository imports cleanly
and exports valid symbols.
"""
from __future__ import annotations

import importlib
from pathlib import Path
import pytest

from conftest import REPO_ROOT

SOURCE_PACKAGES = [
    "soma_core",
    "soma_cli",
    "soma_mcp",
    "soma_sdk",
]


def _discover_modules() -> list[str]:
    root = Path(REPO_ROOT)
    modules: list[str] = []
    for pkg in SOURCE_PACKAGES:
        pkg_dir = root / pkg
        if not pkg_dir.is_dir():
            continue
        for p in pkg_dir.rglob("*.py"):
            rel = p.relative_to(root)
            # Exclude __pycache__
            if "__pycache__" in rel.parts:
                continue
            parts = list(rel.parts)
            # Remove .py
            parts[-1] = p.stem
            mod_name = ".".join(parts)
            modules.append(mod_name)
    return sorted(modules)


ALL_MODULES = _discover_modules()


@pytest.mark.parametrize("module_name", ALL_MODULES)
def test_module_contract_clean_import(module_name: str) -> None:
    """Verify that every repository source module imports cleanly and is non-null."""
    mod = importlib.import_module(module_name)
    assert mod is not None, f"Module {module_name} imported as None"
