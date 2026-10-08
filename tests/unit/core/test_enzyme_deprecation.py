"""Tests verifying deprecation or removal of legacy enzymes package."""
import importlib
import os
import pytest
from conftest import REPO_ROOT


def test_enzymes_package_deprecation_or_removal():
    """Importing legacy enzymes package must raise ModuleNotFoundError."""
    with pytest.raises(ModuleNotFoundError):
        import enzymes
