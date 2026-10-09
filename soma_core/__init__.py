"""soma_core package - foundational state and security primitives."""
from __future__ import annotations

import importlib
from typing import Any

__version__ = "1.4.0"

# Explicit mapping of exported symbol name -> (module_name, attribute_name)
_EXPORTS: dict[str, tuple[str, str | None]] = {
    # Submodules
    "arbitration": ("soma_core.arbitration", None),
    "cell_inventory": ("soma_core.cell_inventory", None),
    "command_safety": ("soma_core.command_safety", None),
    "defects": ("soma_core.defects", None),
    "enforcement": ("soma_core.enforcement", None),
    "errors": ("soma_core.errors", None),
    "evidence": ("soma_core.evidence", None),
    "evidence_collector": ("soma_core.evidence_collector", None),
    "homeostasis": ("soma_core.homeostasis", None),
    "inference_provider": ("soma_core.inference_provider", None),
    "insights": ("soma_core.insights", None),
    "lifecycle": ("soma_core.lifecycle", None),
    "locking": ("soma_core.locking", None),
    "metrics": ("soma_core.metrics", None),
    "outcomes": ("soma_core.outcomes", None),
    "quarantine": ("soma_core.quarantine", None),
    "receipts": ("soma_core.receipts", None),
    "scoring": ("soma_core.scoring", None),
    "sentinels": ("soma_core.sentinels", None),
    "skills": ("soma_core.skills", None),
    "somayaml": ("soma_core.somayaml", None),
    "storage": ("soma_core.storage", None),
    "sweep_session": ("soma_core.sweep_session", None),
    "sync": ("soma_core.sync", None),
    "telemetry": ("soma_core.telemetry", None),
    "verification": ("soma_core.verification", None),
    "workspace": ("soma_core.workspace", None),
    # Core types & functions
    "CommandAnalyzer": ("soma_core.command_safety", "CommandAnalyzer"),
    "SafetyEvaluation": ("soma_core.command_safety", "SafetyEvaluation"),
    "CellInventory": ("soma_core.cell_inventory", "CellInventory"),
    "CellInventoryEntry": ("soma_core.cell_inventory", "CellInventoryEntry"),
    "CellInventoryError": ("soma_core.cell_inventory", "CellInventoryError"),
    "inventory_cells": ("soma_core.cell_inventory", "inventory_cells"),
    "issue_receipt": ("soma_core.receipts", "issue_receipt"),
    "verify_receipt": ("soma_core.receipts", "verify_receipt"),
    "clear_receipts": ("soma_core.receipts", "clear_receipts"),
    "compute_cell_digest": ("soma_core.receipts", "compute_cell_digest"),
    "compute_file_digest": ("soma_core.receipts", "compute_file_digest"),
    "ReceiptExpiredError": ("soma_core.errors", "ReceiptExpiredError"),
    "resolve_workspace": ("soma_core.workspace", "resolve_workspace"),
    "workspace_lock": ("soma_core.locking", "workspace_lock"),
    "LockTimeoutError": ("soma_core.errors", "LockTimeoutError"),
    "laplace_score": ("soma_core.scoring", "laplace_score"),
    "wilson_lower_bound": ("soma_core.scoring", "wilson_lower_bound"),
    "calculate_fitness_status": ("soma_core.lifecycle", "calculate_fitness_status"),
    "STATUS_NEW": ("soma_core.lifecycle", "STATUS_NEW"),
    "STATUS_SURVIVE": ("soma_core.lifecycle", "STATUS_SURVIVE"),
    "STATUS_ADAPT": ("soma_core.lifecycle", "STATUS_ADAPT"),
    "STATUS_EXTINCT": ("soma_core.lifecycle", "STATUS_EXTINCT"),
    "STATUS_APOPTOSIS": ("soma_core.lifecycle", "STATUS_APOPTOSIS"),
    "STATUS_APOPTOSIS_WARNING": ("soma_core.lifecycle", "STATUS_APOPTOSIS_WARNING"),
    "STATUS_DORMANT": ("soma_core.lifecycle", "STATUS_DORMANT"),
    "parse_cell_frontmatter": ("soma_core.somayaml", "parse_cell_frontmatter"),
    "SomaYAML": ("soma_core.somayaml", "SomaYAML"),
    "SomaDocument": ("soma_core.somayaml", "SomaDocument"),
    "SomaYAMLError": ("soma_core.somayaml", "SomaYAMLError"),
    "append_signal": ("soma_core.telemetry", "append_signal"),
    "Workspace": ("soma_core.workspace", "Workspace"),
    "GitWorkspace": ("soma_core.workspace", "GitWorkspace"),
    "WorkspaceError": ("soma_core.errors", "WorkspaceError"),
    "WorkspaceNotFoundError": ("soma_core.errors", "WorkspaceNotFoundError"),
    "PathTraversalError": ("soma_core.errors", "PathTraversalError"),
    "SomaError": ("soma_core.errors", "SomaError"),
    "SomaValidationError": ("soma_core.errors", "SomaValidationError"),
    "CellCorruptError": ("soma_core.errors", "CellCorruptError"),
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        mod_name, attr_name = _EXPORTS[name]
        module = importlib.import_module(mod_name)
        val = module if attr_name is None else getattr(module, attr_name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + __all__)
