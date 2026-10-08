from __future__ import annotations

import importlib
import json
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from typing import Optional

from soma_core.cell_inventory import CellInventoryError, inventory_cells
from soma_core.workspace import resolve_workspace


# Ensure soma_sdk is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

yaml = None  # Backward-compatible sentinel: zero-dependency runtime

# Import JIT engine (stdlib only — parses frontmatter without pyyaml)
from soma_mcp.jit_engine import express as jit_express
from soma_mcp.jit_engine import parse_frontmatter, warn

# Import security utilities
from soma_mcp.security import Workspace, confine_workspace, confine_path, validate_cell_names
from soma_mcp.integrity import (
    load_manifest, verify_manifest, generate_manifest, save_manifest,
    generate_key, load_key,
)


def _get_workspace(args: dict | None = None) -> Workspace:
    """Resolve and confine the target workspace into a Workspace value object."""
    raw = (args.get("workspace") if args else None) or resolve_workspace(args)
    if isinstance(raw, Workspace):
        return raw
    return Workspace.confine(raw)

# Import TTC Verifier directly from soma_core
try:
    from soma_core.arbitration import soma_propose_change
except ImportError:
    soma_propose_change = None


# Try importing Governance SDK; its cell parser also has a stdlib fallback.
try:
    from soma_sdk.governance import Governance
    _HAS_SDK = True
except ImportError:
    _HAS_SDK = False


from soma_core.workspace import resolve_workspace as _core_resolve_workspace


def resolve_workspace(args=None):
    """Find the project root containing .soma/cells/."""
    # We do NOT trust args["workspace"] from client input unverified.
    # Write and Execute tools use args["workspace"] strictly because the MCP server safely injects _canonical_workspace over whatever the client provided.
    # Read tools and background execution must rely on SOMA_WORKSPACE to prevent cross-workspace reading attacks.
    return _core_resolve_workspace(strict_env=True)


# ── Checkpoint helpers (shared with soma_cli.checkpoint) ──────────────
# Imported from soma_core.verification.checkpoint_checks to avoid
# copy-paste divergence. See trap-recurring-finding-escape.md.

try:
    from soma_core.verification.checkpoint_checks import (
        run_all_checks as _run_checkpoint_checks,
        check_test_coverage as _checkpoint_test_coverage,
        check_hardcoded_paths as _checkpoint_hardcoded_paths,
        check_assertion_density as _checkpoint_assertion_density,
        check_cell_fitness as _checkpoint_cell_fitness,
        check_cell_conventions as _checkpoint_cell_conventions,
        check_arbitration_evidence as _checkpoint_arbitration_evidence,
        CHECK_NAMES as _CHECKPOINT_NAMES,
    )
except ImportError:
    _run_checkpoint_checks = None
    _checkpoint_test_coverage = None
    _checkpoint_hardcoded_paths = None
    _checkpoint_assertion_density = None
    _checkpoint_cell_fitness = None
    _checkpoint_cell_conventions = None
    _checkpoint_arbitration_evidence = None
    _CHECKPOINT_NAMES = []



def _parse_frontmatter(content):
    """Parse YAML frontmatter.

    Delegates to the shared implementation in jit_engine, which uses pyyaml when
    installed and a stdlib subset parser otherwise. Returns {} when there is no
    frontmatter and None when frontmatter is present but malformed.
    """
    return parse_frontmatter(content)


def _cell_diagnostic(relative_path, message):
    """Return a JSON-safe diagnostic without discarding the cell path."""
    return {
        '_name': os.path.splitext(os.path.basename(relative_path))[0],
        '_path': relative_path,
        '_error': message,
    }


_CANONICAL_TOOL_MAP = {
    "soma_create_rule": "soma_create_cell",
    "soma_list_rules": "soma_list_cells",
    "soma_rule_fitness": "soma_fitness",
}
_CANONICAL_ARG_MAP = {
    "rule_type": "cell_type",
    "rule_name": "cell_name",
    "rules": "cells_used",
    "rules_used": "cells_used",
}
_TYPE_TRANSLATION_MAP = {
    "safety-guard": "wall",
    "learned-trap": "vacuole",
    "agent-persona": "chloroplast",
    "escalation-boundary": "membrane",
    "contract-bridge": "plasmodesmata",
}


def normalize_tool_call(tool_name: str, arguments: dict) -> tuple[str, dict]:
    """Normalize porcelain aliases into canonical plumbing tool name and arguments."""
    canonical_name = _CANONICAL_TOOL_MAP.get(tool_name, tool_name)
    normalized_args = {}
    for k, v in (arguments or {}).items():
        canon_k = _CANONICAL_ARG_MAP.get(k, k)
        if canon_k == "cell_type" and isinstance(v, str):
            v = _TYPE_TRANSLATION_MAP.get(v, v)
        normalized_args[canon_k] = v
    if "cell_id" in (arguments or {}) and "cells_used" not in normalized_args:
        val = arguments["cell_id"]
        normalized_args["cells_used"] = [val] if isinstance(val, str) else list(val)
    if "rule_id" in (arguments or {}) and "cells_used" not in normalized_args:
        val = arguments["rule_id"]
        normalized_args["cells_used"] = [val] if isinstance(val, str) else list(val)
    return canonical_name, normalized_args


def _matches_cell_type_filter(rel: str, cell_type: Optional[str] = None) -> bool:
    if not cell_type:
        return True
    parent_name = os.path.basename(os.path.dirname(rel))
    return (
        parent_name in (cell_type, f"{cell_type}s")
        or f"/{cell_type}/" in rel
        or f"/{cell_type}s/" in rel
    )


def _list_cells_stdlib(workspace, cell_type=None):
    """List cells from one canonical byte snapshot using the shared parser."""
    if cell_type:
        cell_type = _TYPE_TRANSLATION_MAP.get(cell_type, cell_type)
    try:
        inventory = inventory_cells(workspace)
    except CellInventoryError as exc:
        return {'status': _STATUS_FAIL, 'error': str(exc)}

    cells = []
    for entry in inventory.entries:
        rel = entry.relative_path
        if os.path.basename(rel) == 'README.md':
            continue

        path_matches = _matches_cell_type_filter(rel, cell_type)

        try:
            content = entry.content.decode('utf-8')
        except UnicodeDecodeError as exc:
            if not path_matches:
                continue
            message = f'invalid UTF-8: {exc}'
            warn(f'skipped cell {rel}: {message}')
            cells.append(_cell_diagnostic(rel, message))
            continue

        fm = _parse_frontmatter(content)
        if fm is None:
            if not path_matches:
                continue
            message = 'malformed YAML frontmatter'
            warn(f'skipped cell {rel}: {message}')
            cells.append(_cell_diagnostic(rel, message))
            continue
        if not fm:
            if not path_matches:
                continue
            message = 'no frontmatter metadata'
            warn(f'skipped cell {rel}: {message}')
            cells.append(_cell_diagnostic(rel, message))
            continue

        if cell_type and not (fm.get('type') == cell_type or path_matches):
            continue

        fm['_name'] = os.path.splitext(os.path.basename(rel))[0]
        fm['_path'] = rel
        cells.append(fm)
    return cells


# Outcome vocabulary shared with the transport layer (see server._is_error_result).
_STATUS_PASS = "PASS"
_STATUS_FAIL = "FAIL"

# Mirrors the "outcome" enum advertised in TOOL_DEFINITIONS for soma_report_outcome.
_VALID_OUTCOMES = ("success", "partial", "failure", "tp", "fp", "pass", "fail")


_VERDICT_RE = re.compile(r'^\s*VERDICT:\s*([A-Z_]+)')
_PASSING_VERDICTS = ("APPROVED", "PASS", "SUCCESS", "OK")


def _classify_propose_result(result):
    """Classify a soma_propose_change return value as (status, verdict).

    enzymes.ttc_verifier returns a human-readable report whose first line is
    "VERDICT: <APPROVED|REJECTED|BLOCKED|ESCALATION_REQUIRED> ...". Only an
    approving verdict counts as a pass: a rejection, an inconclusive gate and an
    escalation hold all mean the change must not be treated as done.

    Passing outcomes are whitelisted rather than failures blacklisted, so an
    unrecognised report fails closed instead of telling the client that a
    blocked change went through.
    """
    verdict = None
    if isinstance(result, str):
        match = _VERDICT_RE.match(result)
        if match:
            verdict = match.group(1)
        elif result.lstrip().upper().startswith("SUCCESS"):
            verdict = "SUCCESS"
    elif isinstance(result, dict):
        if "error" in result:
            return _STATUS_FAIL, None
        verdict = str(result.get("status", "")).upper() or None
    if verdict is None:
        return _STATUS_FAIL, None
    return (_STATUS_PASS if verdict in _PASSING_VERDICTS else _STATUS_FAIL), verdict


def get_governance(args=None):
    if not _HAS_SDK:
        return None
    try:
        workspace = _get_workspace(args)
    except ValueError:
        return None
    return Governance(project_root=workspace)


def build_cell_create_prompt(description: str, domain_hint: str = None, cell_type: str = None, args=None) -> str:
    workspace = _get_workspace(args)
    
    examples = []
    inventory = inventory_cells(workspace)
    for entry in inventory.entries:
        rel = entry.relative_path
        if os.path.basename(rel) == 'README.md':
            continue
        try:
            content = entry.content.decode('utf-8')
        except UnicodeDecodeError as exc:
            warn(f'skipped cell example {rel}: invalid UTF-8: {exc}')
            continue
        if content.startswith('---'):
            examples.append(content[:500])
            
    example_text = '\n---\n'.join(examples[:3]) if examples else 'No existing cells found.'
    domain_context = f'\nDomain hint: {domain_hint}' if domain_hint else ''
    type_hint = f'\nPreferred cell type: {cell_type}' if cell_type else ''
    
    prompt = f"""You are a governance cell generator for Soma.

Given a natural language description of a concern, generate a governance cell in markdown with YAML frontmatter.

Cell types:
- wall: Non-negotiable invariant (hard safety gate). Use for things that must ALWAYS hold.
- vacuole: Learned anti-pattern trap. Use for known failure modes to watch for.
- membrane: Escalation gate. Use when sensitive areas need elevated review.
- chloroplast: Domain persona/accelerator. Use for idiomatic patterns to follow.
- plasmodesmata: Cross-service contract. Use for API/data shape agreements.

YAML fields required:
- type: (one of above)
- domain: (one of: efficiency, correctness, security, style, governance)
- enforcement: (gate for walls, advisory for vacuoles)
- hypothesis: (clear, testable statement)
- prediction: (what will happen if the hypothesis is violated)
- falsification: (how to prove this cell is no longer needed)
- target_paths: (list of file glob patterns this cell monitors)
- minimum_mode: (breeze | gale | trident | maelstrom | tempest)
- tags: (list of relevant tags)

Optionally include:
- fitness: (triggers: 0, true_positives: 0, false_positives: 0, score: null)

Existing cells in this project for reference:
{example_text}
{domain_context}{type_hint}

User description: "{description}"

Generate ONLY the complete markdown cell file content. Start with --- for the YAML frontmatter. After the closing ---, include a brief description paragraph explaining the cell's purpose. Do not include any other text."""

    return prompt

TOOL_DEFINITIONS = [
    {
        "name": "soma_request_receipt",
        "description": "Request an execution receipt for a privileged tool. Required before calling any write tools, or execution tools (if execution is enabled).",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
            "title": "Request Receipt"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "description": "The name of the execute tool you want to call."},
                "arguments": {"type": "object", "description": "The arguments you will pass to the execute tool."}
            },
            "required": ["operation", "arguments"]
        }
    },
    {
        "name": "soma_create_cell",
        "description": "Takes a natural language description and builds an advisory prompt proposal to create a governance cell (does not directly modify the filesystem).",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Create Cell"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Natural language description"},
                "cell_type": {"type": "string", "description": "Optional cell type hint"},
                "domain": {"type": "string", "description": "Optional domain hint"},
                "dry_run": {"type": "boolean", "description": "Optional dry run flag"},
                "receipt": {"type": "string", "description": "Execution receipt ID obtained from soma_request_receipt"}
            },
            "required": ["description", "receipt"]
        }
    },
    {
        "name": "soma_create_rule",
        "description": "Takes a natural language description and builds a prompt to create a governance rule.",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Create Rule"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Natural language description"},
                "rule_type": {"type": "string", "description": "Optional rule type hint (learned-trap, safety-guard, agent-persona)"},
                "domain": {"type": "string", "description": "Optional domain hint"},
                "dry_run": {"type": "boolean", "description": "Optional dry run flag"},
                "receipt": {"type": "string", "description": "Execution receipt ID obtained from soma_request_receipt"}
            },
            "required": ["description", "receipt"]
        }
    },
    {
        "name": "soma_scan",
        "description": (
            "CALL THIS BEFORE MAKING CHANGES. Returns governance guidance relevant to "
            "the specific files you are about to modify. Provides 2-3 focused rules "
            "based on your current git diff, ranked by proven effectiveness. "
            "Includes safety gates, known anti-patterns, and project-specific conventions."
        ),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Soma Scan"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of files being changed. Auto-detects from git diff if omitted."
                }
            }
        }
    },
    {
        "name": "soma_report_outcome",
        "description": (
            "Report the outcome of your work for fitness scoring. "
            "Call after completing a task to improve future governance guidance."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Report Outcome"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "cells_used": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of cells that influenced your work"
                },
                "outcome": {
                    "type": "string",
                    "enum": ["success", "partial", "failure", "tp", "fp", "pass", "fail"],
                    "description": "Overall outcome of the task"
                },
                "tests_passed": {"type": "boolean", "description": "Did tests pass?"},
                "rework_count": {"type": "integer", "description": "How many times you redid work"},
                "notes": {"type": "string", "description": "Optional notes on what helped or didn't"},
                "idempotency_key": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Caller-supplied key making the complete report retry-safe"
                },
                "receipt": {"type": "string", "description": "Execution receipt ID obtained from soma_request_receipt"}
            },
            "required": ["outcome", "idempotency_key", "receipt"]
        }
    },
    {
        "name": "soma_grade",
        "description": "Returns governance report card with fitness grades.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Soma Grade"
        },
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "soma_coverage",
        "description": "Returns cell coverage report showing which files are governed.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Soma Coverage"
        },
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "soma_fitness",
        "description": "Returns fitness landscape showing cell health and evolution.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Soma Fitness"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "bayesian": {"type": "boolean", "description": "Use Bayesian smoothing"}
            }
        }
    },
    {
        "name": "soma_list_cells",
        "description": "Lists all governance cells with their type, hypothesis, and fitness data.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "List Cells"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "cell_type": {"type": "string", "description": "Optional cell type filter (wall, vacuole, chloroplast, membrane, plasmodesmata)"}
            }
        }
    },
    {
        "name": "soma_list_rules",
        "description": "Lists all governance rules with their type, hypothesis, and fitness data.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "List Rules"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "rule_type": {"type": "string", "description": "Optional rule type filter"}
            }
        }
    },
    {
        "name": "soma_rule_fitness",
        "description": "Returns fitness landscape showing rule health and evolution.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Rule Fitness"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "bayesian": {"type": "boolean", "description": "Use Bayesian smoothing"}
            }
        }
    },
    {
        "name": "soma_propose_change",
        "description": "(PROTOTYPE - ADVISORY ONLY) The gateway MCP tool. Propose a change to a file. The system will verify the change against active JIT rules before writing to the file.",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
            "title": "Propose Change"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute or relative path to the file to change."},
                "proposed_content": {"type": "string", "description": "The complete proposed file content."},
                "receipt": {"type": "string", "description": "Execution receipt ID obtained from soma_request_receipt"}
            },
            "required": ["file_path", "proposed_content", "receipt"]
        }
    },
    {
        "name": "soma_audit_security",
        "description": "Run a basic Security prototype audit on a proposed diff.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Audit Security"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file being changed."},
                "proposed_content": {"type": "string", "description": "The complete proposed file content."}
            },
            "required": ["file_path", "proposed_content"]
        }
    },
    {
        "name": "soma_audit_performance",
        "description": "Run a basic Performance prototype audit on a proposed diff.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Audit Performance"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file being changed."},
                "proposed_content": {"type": "string", "description": "The complete proposed file content."}
            },
            "required": ["file_path", "proposed_content"]
        }
    },
    {
        "name": "soma_verify_changes",
        "description": "Verify proposed changes against Layer-1 governance checks.",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Verify Changes"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of changed files to verify."
                },
                "layer1_only": {"type": "boolean", "description": "Only run Layer-1 checks (default true)."},
                "async_mode": {"type": "boolean", "description": "Run verification asynchronously in background and return job_id for polling (default false)."},
                "task_plan": {"type": "string", "description": "Task plan or specification used for Layer-2 adversarial verification."},
                "rebuttal": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of defense rebuttal claims with evidence citations to rebut an in-band charge sheet."
                },
                "receipt": {"type": "string", "description": "Execution receipt ID obtained from soma_request_receipt"}
            },
            "required": ["receipt"]
        }
    },
    {
        "name": "soma_poll_verification",
        "description": "Poll the status and retrieve results of an asynchronous verification job.",
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Poll Verification Job"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Verification job ID returned by soma_verify_changes."
                }
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "soma_checkpoint",
        "description": "Run all checkpoint checks against the workspace.",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Soma Checkpoint"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "receipt": {"type": "string", "description": "Execution receipt ID obtained from soma_request_receipt"}
            },
            "required": ["receipt"]
        }
    },
    {
        "name": "soma_generate_manifest",
        "description": (
            "Generate and sign a cell integrity manifest for the workspace. "
            "Creates an HMAC-SHA256 key if none exists and generate_key is true."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
            "title": "Generate Manifest"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "generate_key": {
                    "type": "boolean",
                    "description": "Generate HMAC key if none exists (default false)."
                },
                "receipt": {"type": "string", "description": "Execution receipt ID obtained from soma_request_receipt"}
            },
            "required": ["receipt"]
        }
    },
    {
        "name": "soma_capture_insight",
        "description": (
            "Capture a human insight about the codebase. Records the insight, "
            "correlates it with governance cell coverage, and persists it to "
            ".soma/human_insights.jsonl for fitness scoring."
        ),
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
            "title": "Capture Insight"
        },
        "inputSchema": {
            "type": "object",
            "properties": {
                "insight": {
                    "type": "string",
                    "description": "Free-text description of the insight"
                },
                "context_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files the insight relates to (at least one required)"
                },
                "source_conversation": {
                    "type": "string",
                    "description": "Optional conversation/session identifier"
                },
                "category": {
                    "type": "string",
                    "description": "Optional category tag (e.g. contract_mismatch)"
                },
                "receipt": {"type": "string", "description": "Execution receipt ID obtained from soma_request_receipt"}
            },
            "required": ["insight", "context_files", "receipt"]
        }
    }
]

def _handle_create_cell(args: dict, gov) -> dict:
    try:
        prompt = build_cell_create_prompt(
            description=args.get("description"),
            domain_hint=args.get("domain"),
            cell_type=args.get("cell_type"),
            args=args,
        )
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    if args.get("dry_run"):
        return {
            "prompt": prompt,
            "dry_run": True,
            "instruction": "Dry run: showing prompt that would be used. No cell will be created.",
        }
    return {
        "prompt": prompt,
        "instruction": "Process this prompt and return the cell YAML. Then use a file-writing tool to save it to the appropriate .soma/cells/ directory.",
    }


def _handle_list_cells(args: dict, gov):
    cell_type = args.get("cell_type")
    if gov:
        try:
            return gov.list_cells(cell_type=cell_type)
        except RuntimeError as exc:
            return {"status": _STATUS_FAIL, "error": str(exc)}
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"status": _STATUS_FAIL, "error": str(exc)}
    return _list_cells_stdlib(workspace, cell_type=cell_type)


def _handle_propose_change(args: dict, gov) -> dict:
    if not soma_propose_change:
        return {"error": "soma_propose_change not available"}
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    file_path = args.get("file_path")
    if not file_path:
        return {"error": "file_path is required", "status": _STATUS_FAIL}
    try:
        _, rel_path = workspace.confine_path(file_path)
        file_path = str(rel_path)
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    proposed_content = args.get("proposed_content")

    # Express JIT rules for the given file to get active playbooks
    jit_result = jit_express(workspace, changed_files=[file_path])
    active_playbooks = jit_result.get("relevant_cells", [])

    result = soma_propose_change(file_path, proposed_content, active_playbooks, workspace=workspace)
    status, verdict = _classify_propose_result(result)
    payload = {"result": result, "status": status}
    if verdict:
        payload["verdict"] = verdict
    return payload


def _handle_audit_security(args: dict, gov) -> dict:
    content = args.get("proposed_content") or ""
    file_path = args.get("file_path") or ""
    if file_path:
        try:
            workspace = _get_workspace(args)
            _, rel_path = workspace.confine_path(file_path)
            file_path = rel_path
        except ValueError as exc:
            return {"error": str(exc), "status": _STATUS_FAIL}
    flags = []
    if "password=" in content.lower() or "secret=" in content.lower():
        flags.append(f"- Hardcoded secret or password detected in {file_path}.")
    if "eval(" in content:
        flags.append(f"- eval() detected in {file_path}. Potential injection vector.")
    if file_path:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ('.html', '.htm', '.js', '.jsx', '.ts', '.tsx'):
            if 'innerHTML' in content or 'document.write' in content:
                flags.append(f"- Potential XSS vector in {file_path}: innerHTML/document.write usage.")
        if ext == '.sql' or ('execute(' in content and '%s' not in content and '?' not in content):
            if 'f"' in content or "f'" in content or '% ' in content:
                flags.append(f"- Potential SQL injection in {file_path}: string formatting in query.")

    if flags:
        return {"status": "FAIL", "feedback": "\n".join(flags), "file_path": file_path, "instruction": "Fix these issues and resubmit."}
    return {"status": "PASS", "feedback": f"Security Audit passed for {file_path or 'input'}. No OWASP flaws or exposed secrets detected.", "file_path": file_path}


def _handle_audit_performance(args: dict, gov) -> dict:
    content = args.get("proposed_content") or ""
    file_path = args.get("file_path") or ""
    if file_path:
        try:
            workspace = _get_workspace(args)
            _, rel_path = workspace.confine_path(file_path)
            file_path = rel_path
        except ValueError as exc:
            return {"error": str(exc), "status": _STATUS_FAIL}
    flags = []
    if content.count("for ") > 2 and "in " in content:
        flags.append(f"- Potential O(N^2) or deeply nested loop detected in {file_path}.")
    if ".query(" in content and "SELECT *" in content:
        flags.append(f"- Inefficient DB query (SELECT *) detected in {file_path}. Select only needed columns.")
    if file_path:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.py':
            if 'import *' in content:
                flags.append(f"- Wildcard import in {file_path} may slow startup and increase memory.")

    if flags:
        return {"status": "FAIL", "feedback": "\n".join(flags), "file_path": file_path, "instruction": "Optimize the code and resubmit."}
    return {"status": "PASS", "feedback": f"Performance Audit passed for {file_path or 'input'}. No obvious bottlenecks detected.", "file_path": file_path}


def _handle_verify_changes(args: dict, gov) -> dict:
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    files = args.get('files') or []
    if not isinstance(files, (list, tuple)) or not all(isinstance(f, str) for f in files):
        return {"error": "'files' must be a list of file paths", "status": _STATUS_FAIL}
    if not files and not args.get('async_mode', False):
        return {"status": _STATUS_FAIL, "summary": "No files specified to verify.", "layer1_only": True, "evidence": []}
    try:
        files = [workspace.confine_path(f)[1] for f in files]
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    layer1_only = args.get('layer1_only', True)
    async_mode = args.get('async_mode', False)
    if async_mode:
        from soma_core.verification_jobs import submit_verification_job
        job = submit_verification_job(
            workspace=workspace,
            files=files,
            layer1_only=layer1_only,
            task_plan=args.get('task_plan', ''),
            receipt=args.get('receipt'),
        )
        return {
            "status": "QUEUED",
            "job_id": job.job_id,
            "message": "Verification job enqueued. Poll with soma_poll_verification.",
            "created_at": job.created_at,
        }

    try:
        from soma_core.verification import VerificationPipeline, runner
    except ImportError:
        return {"error": "soma_core.verification is not importable. Install soma package."}

    rebuttal = args.get('rebuttal')
    task_plan = args.get('task_plan', '')

    if not layer1_only:
        pipeline = VerificationPipeline()
        pipeline_res = pipeline.run(
            changed_files=files,
            workspace=workspace,
            task_plan=task_plan,
            in_band=True,
            rebuttal=rebuttal,
        )

        evidence = [
            {"tool": r.tool, "target": r.target, "verdict": r.verdict, "detail": r.detail}
            for r in pipeline_res.layer1_evidence
        ]
        try:
            from soma_core.outcomes import record_verification_telemetry
            record_verification_telemetry(
                workspace=workspace,
                target_files=files,
                passed=pipeline_res.passed,
                verdict=pipeline_res.verdict.name,
                layer1_evidence=evidence,
                source="mcp",
            )
        except Exception:
            pass

        if pipeline_res.charge_sheet:
            res_dict = pipeline_res.charge_sheet.to_dict()
            res_dict["layer1_passed"] = pipeline_res.layer1_passed
            res_dict["summary"] = pipeline_res.summary
            return res_dict

        resp = {
            "status": pipeline_res.verdict.name,
            "verdict": pipeline_res.verdict.name,
            "passed": pipeline_res.passed,
            "summary": pipeline_res.summary,
            "layer1_only": False,
            "evidence": evidence,
        }
        if pipeline_res.arbitration_result:
            if pipeline_res.evidence_path:
                resp["evidence_file"] = pipeline_res.evidence_path
                resp["cycle"] = getattr(pipeline_res, "cycle", None)
            resp["divergences"] = [
                {
                    "category": d.category.value,
                    "type": d.divergence_type,
                    "resolution": d.resolution,
                }
                for d in pipeline_res.arbitration_result.divergences
            ]
            resp["convergences"] = [c.value for c in pipeline_res.arbitration_result.convergences]
        return resp

    results = runner.run_layer1(changed_files=files, repo_root=workspace)
    verdict = runner.gate_verdict(results)
    summary = runner.format_summary(results)
    evidence = [
        {"tool": r.tool, "target": r.target, "verdict": r.verdict, "detail": r.detail}
        for r in results
    ]
    try:
        from soma_core.outcomes import record_verification_telemetry
        record_verification_telemetry(
            workspace=workspace,
            target_files=files,
            passed=bool(verdict),
            verdict="PASS" if verdict else "FAIL",
            layer1_evidence=evidence,
            source="mcp",
        )
    except Exception:
        pass
    return {
        "status": "PASS" if verdict else "FAIL",
        "summary": summary,
        "layer1_only": True,
        "evidence": evidence,
    }


def _handle_poll_verification(args: dict, gov) -> dict:
    job_id = args.get("job_id")
    if not job_id:
        return {"error": "Missing required argument 'job_id'", "status": _STATUS_FAIL}
    from soma_core.verification_jobs import get_job
    job = get_job(job_id)
    if job is None:
        return {"error": f"Verification job '{job_id}' not found or expired.", "status": _STATUS_FAIL}
    if job.status == "COMPLETED":
        return {
            "status": "COMPLETED",
            "job_id": job.job_id,
            "completed_at": job.completed_at,
            "result": job.result,
            "receipt": job.receipt,
        }
    elif job.status == "FAILED":
        return {
            "status": "FAILED",
            "job_id": job.job_id,
            "error": job.error,
            "completed_at": job.completed_at,
        }
    elif job.status == "RUNNING":
        return {
            "status": "RUNNING",
            "job_id": job.job_id,
            "started_at": job.started_at,
        }
    else:
        return {
            "status": job.status,
            "job_id": job.job_id,
            "created_at": job.created_at,
        }


def _handle_checkpoint(args: dict, gov) -> dict:
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    if _run_checkpoint_checks is None:
        return {"error": "checkpoint verification is not available", "status": _STATUS_FAIL}
    issues = _run_checkpoint_checks(workspace.root)
    return {
        "status": "PASS" if not issues else "FAIL",
        "checks": _CHECKPOINT_NAMES,
        "issue_count": len(issues),
        "issues": issues,
    }


def _handle_scan(args: dict, gov) -> dict:
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    files = args.get('files', None)
    if files is not None:
        if not isinstance(files, (list, tuple)) or not all(isinstance(f, str) for f in files):
            return {"error": "'files' must be a list of file paths", "status": _STATUS_FAIL}
        try:
            files = [str(workspace.confine_path(f)[1]) for f in files]
        except ValueError as exc:
            return {"error": str(exc), "status": _STATUS_FAIL}
    return jit_express(workspace, changed_files=files)


def _handle_report_outcome(args: dict, gov) -> dict:
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    raw_outcome = args.get('outcome')
    outcome_value = raw_outcome.strip().lower() if isinstance(raw_outcome, str) else None
    if outcome_value not in _VALID_OUTCOMES:
        return {
            "error": (
                f"Invalid 'outcome': {raw_outcome!r}. "
                f"Expected one of {list(_VALID_OUTCOMES)}."
            ),
            "status": _STATUS_FAIL,
        }
    idempotency_key = args.get('idempotency_key')
    if not isinstance(idempotency_key, str) or not idempotency_key:
        return {
            "error": "'idempotency_key' must be a nonempty string.",
            "status": _STATUS_FAIL,
        }
    raw_cells_used = args.get('cells_used')
    if raw_cells_used is None:
        if "cell_id" in args:
            val = args["cell_id"]
            raw_cells_used = [val] if isinstance(val, str) else val
        elif "rule_id" in args:
            val = args["rule_id"]
            raw_cells_used = [val] if isinstance(val, str) else val
    if raw_cells_used is not None:
        if not isinstance(raw_cells_used, (list, tuple)) or not all(isinstance(c, str) for c in raw_cells_used):
            return {
                "error": "'cells_used' must be a list of cell names.",
                "status": _STATUS_FAIL,
            }
        cells_used = list(raw_cells_used)
    else:
        cells_used = []

    if cells_used:
        invalid = workspace.validate_cell_names(cells_used)
        if invalid:
            return {
                "error": f"Unknown cell(s): {invalid}. Only existing cells can be reported.",
                "status": _STATUS_FAIL,
            }
    tests_passed = args.get('tests_passed')
    rework_count = args.get('rework_count', 0)
    notes = args.get('notes', '')
    signal_map = {'success': 'tp', 'tp': 'tp', 'failure': 'fp',
                  'fp': 'fp', 'partial': 'trigger', 'pass': 'tp', 'fail': 'fp'}
    metadata = {
        'notes': notes,
        'tests_passed': tests_passed,
        'rework_count': rework_count,
    }
    events = [
        {
            'cell_name': cell_id,
            'signal_type': signal_map.get(outcome_value, 'trigger'),
            'source': 'mcp',
            'metadata': metadata,
            'principal': 'mcp',
            'idempotency_scope': 'report_outcome',
            'idempotency_key': idempotency_key,
        }
        for cell_id in cells_used
    ]
    try:
        from soma_core.telemetry import append_signals, read_generation
        generation = read_generation(workspace)
        records = append_signals(
            workspace, events, expected_generation=generation)
    except Exception as exc:
        return {
            'status': _STATUS_FAIL,
            'error': f'Failed to record outcome: {exc}',
        }
    return {'status': 'recorded', 'records': records}


def _handle_capture_insight(args: dict, gov) -> dict:
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    try:
        from soma_core.insights import capture_insight
    except ImportError:
        return {"error": "soma_core.insights is not importable.", "status": _STATUS_FAIL}
    try:
        context_files_arg = args.get('context_files') or []
        if not isinstance(context_files_arg, (list, tuple)) or not all(isinstance(f, str) for f in context_files_arg):
            return {"error": "'context_files' must be a list of file paths", "status": _STATUS_FAIL}
        record = capture_insight(
            workspace=workspace,
            insight=args.get('insight', ''),
            context_files=[str(workspace.confine_path(f)[1]) for f in context_files_arg],
            source_conversation=args.get('source_conversation'),
            category=args.get('category'),
            scaffold_wall=bool(args.get('scaffold_wall', False)),
            wall_id=args.get('wall_id'),
        )
    except ValueError as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}
    return {
        'status': 'recorded',
        'insight': record,
    }


def _handle_generate_manifest(args: dict, gov) -> dict:
    try:
        workspace = _get_workspace(args)
    except ValueError as exc:
        return {"error": str(exc), "status": "FAIL"}
    cells_dir = str(workspace.cells_dir)

    key_created = False
    if args.get("generate_key") and load_key(workspace) is None:
        generate_key(workspace)
        key_created = True

    manifest = generate_manifest(cells_dir)
    save_manifest(workspace, manifest)

    return {
        "status": "OK",
        "cell_count": manifest["cell_count"],
        "signed": "signature" in manifest,
        "key_generated": key_created,
        "generated_at": manifest["generated_at"],
    }


def _handle_grade(args: dict, gov) -> dict:
    if gov:
        result = gov.grade()
    else:
        try:
            from soma_core.telemetry import calculate_immune_grade
            workspace = _get_workspace(args)
            result = calculate_immune_grade(workspace)
        except Exception as exc:
            return {"status": _STATUS_FAIL, "error": str(exc)}
    if result is None:
        return {
            "coverage": {"pct": 0.0, "grade": "F"},
            "avg_fitness": {"pct": 0.0, "grade": "F", "score": 0.0},
            "diversity": {"pct": 0.0, "grade": "F"},
            "staleness": {"pct": 0.0, "grade": "F"},
            "wall_integrity": {"pct": 0.0, "grade": "F"},
            "tiers": {},
            "overall": {"pct": 0.0, "grade": "F"},
            "status": "PASS",
            "note": "No cells found to grade",
        }
    if not isinstance(result, dict):
        return {"status": _STATUS_FAIL, "error": str(result)}
    return result


def _handle_coverage(args: dict, gov):
    if gov:
        result = gov.coverage_report()
    else:
        try:
            from soma_core.telemetry import calculate_coverage
            workspace = _get_workspace(args)
            result = calculate_coverage(workspace)
        except Exception as exc:
            return {"status": _STATUS_FAIL, "error": str(exc)}
    if not isinstance(result, dict):
        return {"status": _STATUS_FAIL, "error": str(result)}
    return result


def _handle_fitness(args: dict, gov):
    bayesian = args.get("bayesian", False)
    if gov:
        result = gov.fitness_landscape(bayesian=bayesian)
    else:
        try:
            from soma_core.lifecycle import compute_cells_fitness
            workspace = _get_workspace(args)
            result = compute_cells_fitness(workspace=workspace, bayesian=bayesian)
        except Exception as exc:
            return {"status": _STATUS_FAIL, "error": str(exc)}
    if isinstance(result, dict) and "error" in result:
        result["status"] = _STATUS_FAIL
    return result


def _handle_request_receipt(args: dict, gov) -> dict:
    operation = args.get("operation")
    if not operation:
        return {"error": "Missing required argument 'operation'", "status": _STATUS_FAIL}
    op_args = args.get("arguments", {})
    if not isinstance(op_args, dict):
        return {"error": "arguments must be an object", "status": _STATUS_FAIL}
    from soma_core.receipts import (
        issue_receipt,
        compute_file_digest,
        compute_cell_digest,
        target_paths,
        strip_server_owned,
    )
    workspace = (
        args.get("workspace")
        or (str(gov.repo_root) if (gov and hasattr(gov, "repo_root")) else resolve_workspace())
    )

    clean_args = strip_server_owned(op_args)
    session_id = args.get("session_id") or args.get("_sessionToken") or "local-session"
    try:
        file_digest = compute_file_digest(workspace, target_paths(clean_args))
        cell_digest = compute_cell_digest(workspace)
    except (ValueError, RuntimeError, OSError) as exc:
        return {"error": str(exc), "status": _STATUS_FAIL}

    receipt_id = issue_receipt(
        session_id=session_id,
        workspace=workspace,
        operation=operation,
        args=clean_args,
        file_digest=file_digest,
        cell_digest=cell_digest,
        ttl_seconds=300,
    )
    return {
        "receipt": receipt_id,
        "operation": operation,
        "status": "ISSUED",
    }


_TOOL_HANDLERS = {
    "soma_create_cell": _handle_create_cell,
    "soma_create_rule": _handle_create_cell,
    "soma_list_cells": _handle_list_cells,
    "soma_list_rules": _handle_list_cells,
    "soma_propose_change": _handle_propose_change,
    "soma_audit_security": _handle_audit_security,
    "soma_audit_performance": _handle_audit_performance,
    "soma_verify_changes": _handle_verify_changes,
    "soma_poll_verification": _handle_poll_verification,
    "soma_checkpoint": _handle_checkpoint,
    "soma_scan": _handle_scan,
    "soma_report_outcome": _handle_report_outcome,
    "soma_capture_insight": _handle_capture_insight,
    "soma_generate_manifest": _handle_generate_manifest,
    "soma_grade": _handle_grade,
    "soma_coverage": _handle_coverage,
    "soma_fitness": _handle_fitness,
    "soma_rule_fitness": _handle_fitness,
    "soma_request_receipt": _handle_request_receipt,
}


def execute_tool(name: str, args: dict):
    name, args = normalize_tool_call(name, args)
    gov = get_governance(args)
    handler = _TOOL_HANDLERS.get(name)
    if not handler:
        raise ValueError(f"Unknown tool: {name}")
    return handler(args, gov)

