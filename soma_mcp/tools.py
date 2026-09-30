import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

# pyyaml is an OPTIONAL dependency of soma_mcp. The server must start on a bare
# interpreter (see .soma/cells/walls/wall-mcp-zero-deps.md), so we only use
# pyyaml when it happens to be installed.
try:
    import yaml
except ImportError:
    yaml = None

# Ensure soma_sdk is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import JIT engine (stdlib only — parses frontmatter without pyyaml)
from soma_mcp.jit_engine import express as jit_express
from soma_mcp.jit_engine import parse_frontmatter, warn

# Import TTC Verifier
try:
    from enzymes.ttc_verifier import soma_propose_change
except ImportError:
    soma_propose_change = None

# Try importing Governance SDK (requires pyyaml); fall back to stdlib-only impl
try:
    from soma_sdk.governance import Governance
    _HAS_SDK = True
except ImportError:
    _HAS_SDK = False


def resolve_workspace():
    """Find the project root containing .soma/cells/."""
    soma_root = os.environ.get("SOMA_ROOT")
    if soma_root:
        if os.path.isdir(os.path.join(soma_root, ".soma", "cells")):
            return os.path.abspath(soma_root)
        else:
            raise ValueError(f"SOMA_ROOT is set to {soma_root} but no .soma/cells found there.")

    cwd = os.getcwd()
    if os.path.isdir(os.path.join(cwd, ".soma", "cells")):
        return cwd

    d = cwd
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, ".soma", "cells")):
            return d
        d = os.path.dirname(d)
        
    return cwd


def _parse_frontmatter(content):
    """Parse YAML frontmatter.

    Delegates to the shared implementation in jit_engine, which uses pyyaml when
    installed and a stdlib subset parser otherwise. Returns {} when there is no
    frontmatter and None when frontmatter is present but malformed.
    """
    return parse_frontmatter(content)


def _list_cells_stdlib(workspace):
    """List cells using only stdlib (no pyyaml)."""
    cells = []
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    if not os.path.isdir(cells_dir):
        return cells
    for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
        if os.path.basename(cell_file) == 'README.md':
            continue
        rel = os.path.relpath(cell_file, workspace)
        try:
            with open(cell_file, encoding="utf-8") as f:
                content = f.read()
            fm = _parse_frontmatter(content)
            if fm is None:
                warn(f'skipped cell {rel}: malformed YAML frontmatter')
                continue
            if not fm:
                warn(f'skipped cell {rel}: no frontmatter metadata')
                continue
            fm['_name'] = os.path.splitext(os.path.basename(cell_file))[0]
            fm['_path'] = rel
            cells.append(fm)
        except Exception as e:
            warn(f'skipped cell {rel}: {e.__class__.__name__}: {e}')
    return cells


# Outcome vocabulary shared with the transport layer (see server._is_error_result).
_STATUS_PASS = "PASS"
_STATUS_FAIL = "FAIL"

# Mirrors the "outcome" enum advertised in TOOL_DEFINITIONS for soma_report_outcome.
_VALID_OUTCOMES = ("success", "partial", "failure")


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


def get_governance():
    if not _HAS_SDK:
        return None
    workspace = resolve_workspace()
    return Governance(project_root=workspace)


def build_cell_create_prompt(description: str, domain_hint: str = None, cell_type: str = None) -> str:
    workspace = resolve_workspace()
    
    examples = []
    cells_dir = os.path.join(workspace, '.soma', 'cells')
    if os.path.isdir(cells_dir):
        for cell_file in glob.glob(os.path.join(cells_dir, '**', '*.md'), recursive=True):
            if os.path.basename(cell_file) == 'README.md': continue
            try:
                with open(cell_file, encoding="utf-8") as f:
                    content = f.read()
                if content.startswith('---'):
                    examples.append(content[:500])
            except Exception: pass
            
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
        "name": "soma_create_cell",
        "description": "Takes a natural language description and builds a prompt to create a governance cell.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Natural language description"},
                "cell_type": {"type": "string", "description": "Optional cell type hint"},
                "domain": {"type": "string", "description": "Optional domain hint"},
                "dry_run": {"type": "boolean", "description": "Optional dry run flag"}
            },
            "required": ["description"]
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
                    "enum": ["success", "partial", "failure"],
                    "description": "Overall outcome of the task"
                },
                "tests_passed": {"type": "boolean", "description": "Did tests pass?"},
                "rework_count": {"type": "integer", "description": "How many times you redid work"},
                "notes": {"type": "string", "description": "Optional notes on what helped or didn't"}
            },
            "required": ["outcome"]
        }
    },
    {
        "name": "soma_grade",
        "description": "Returns governance report card with fitness grades.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "soma_coverage",
        "description": "Returns cell coverage report showing which files are governed.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "soma_fitness",
        "description": "Returns fitness landscape showing cell health and evolution.",
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
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "soma_propose_change",
        "description": "(PROTOTYPE - ADVISORY ONLY) The gateway MCP tool. Propose a change to a file. The system will verify the change against active JIT rules before writing to the file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute or relative path to the file to change."},
                "proposed_content": {"type": "string", "description": "The complete proposed file content."}
            },
            "required": ["file_path", "proposed_content"]
        }
    },
    {
        "name": "soma_audit_security",
        "description": "Run a basic Security prototype audit on a proposed diff.",
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
        "name": "soma_capture_insight",
        "description": (
            "Capture a human insight about the codebase. Records the insight, "
            "correlates it with governance cell coverage, and persists it to "
            ".soma/human_insights.jsonl for fitness scoring."
        ),
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
                }
            },
            "required": ["insight", "context_files"]
        }
    }
]

def execute_tool(name: str, args: dict):
    gov = get_governance()
    
    if name == "soma_create_cell":
        prompt = build_cell_create_prompt(
            description=args.get("description"),
            domain_hint=args.get("domain"),
            cell_type=args.get("cell_type")
        )
        return {"prompt": prompt, "instruction": "Process this prompt and return the cell YAML. Then use a file-writing tool to save it to the appropriate .soma/cells/ directory."}
    
    elif name == "soma_list_cells":
        # list_cells works without pyyaml via stdlib fallback
        if gov:
            return gov.list_cells()
        return _list_cells_stdlib(resolve_workspace())

    elif name == "soma_propose_change":
        if not soma_propose_change:
            return {"error": "soma_propose_change not available"}
        workspace = resolve_workspace()
        file_path = args.get('file_path')
        proposed_content = args.get('proposed_content')
        
        # Express JIT rules for the given file to get active playbooks
        jit_result = jit_express(workspace, changed_files=[file_path])
        active_playbooks = jit_result.get('relevant_cells', [])
        
        result = soma_propose_change(file_path, proposed_content, active_playbooks)
        status, verdict = _classify_propose_result(result)
        # Explicit status so the transport does not have to sniff the message text.
        payload = {"result": result, "status": status}
        if verdict:
            payload["verdict"] = verdict
        return payload
        
    elif name == "soma_audit_security":
        content = args.get("proposed_content", "")
        # Prototype: Basic keyword scanning for secrets and OWASP basics
        flags = []
        if "password=" in content.lower() or "secret=" in content.lower():
            flags.append("- Hardcoded secret or password detected.")
        if "eval(" in content:
            flags.append("- eval() detected. Potential injection vector.")
            
        if flags:
            return {"status": "FAIL", "feedback": "\n".join(flags), "instruction": "Fix these issues and resubmit."}
        return {"status": "PASS", "feedback": "Security Audit passed. No OWASP flaws or exposed secrets detected."}
        
    elif name == "soma_audit_performance":
        content = args.get("proposed_content", "")
        # Prototype: Basic keyword scanning for hot-paths and inefficiencies
        flags = []
        if content.count("for ") > 2 and "in " in content:
            # Very naive nested loop check
            flags.append("- Potential O(N^2) or deeply nested loop detected in hot path.")
        if ".query(" in content and "SELECT *" in content:
            flags.append("- Inefficient DB query (SELECT *) detected. Select only needed columns.")
            
        if flags:
            return {"status": "FAIL", "feedback": "\n".join(flags), "instruction": "Optimize the code and resubmit."}
        return {"status": "PASS", "feedback": "Performance Audit passed. No obvious bottlenecks detected."}

    if name == "soma_scan":
        # v0.23: JIT expression — returns only relevant cells, not everything
        workspace = resolve_workspace()
        files = args.get('files', None)
        return jit_express(workspace, changed_files=files)

    elif name == "soma_report_outcome":
        # v0.23: Agent reports execution outcome for fitness scoring
        workspace = resolve_workspace()
        # Enforce the advertised enum here: persisting 'unknown' would silently
        # poison fitness scoring with un-gradeable rows.
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
        outcome = {
            'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'cells_used': args.get('cells_used', []),
            'outcome': outcome_value,
            'tests_passed': args.get('tests_passed'),
            'rework_count': args.get('rework_count', 0),
            'notes': args.get('notes', '')
        }
        outcomes_file = os.path.join(workspace, '.soma', 'outcomes.jsonl')
        os.makedirs(os.path.dirname(outcomes_file), exist_ok=True)
        with open(outcomes_file, 'a', encoding="utf-8") as f:
            f.write(json.dumps(outcome) + '\n')
        return {'status': 'recorded', 'outcome': outcome}

    elif name == "soma_capture_insight":
        workspace = resolve_workspace()
        try:
            from enzymes.insight_capture import capture_insight
        except ImportError:
            return {"error": "enzymes.insight_capture is not importable."}
        try:
            record = capture_insight(
                workspace=workspace,
                insight=args.get('insight', ''),
                context_files=args.get('context_files', []),
                source_conversation=args.get('source_conversation'),
                category=args.get('category'),
            )
        except ValueError as exc:
            return {"error": str(exc), "status": _STATUS_FAIL}
        return {
            'status': 'recorded',
            'insight': record,
        }

    # All other tools require the full SDK (pyyaml)
    if not gov:
        if yaml is None:
            return {"error": "soma_sdk requires pyyaml. Install with: pip install pyyaml"}
        return {"error": "soma_sdk is not importable from this workspace; soma_grade, soma_coverage and soma_fitness are unavailable."}

    if name == "soma_grade":
        return gov.grade()
        
    elif name == "soma_coverage":
        return gov.coverage_report()
        
    elif name == "soma_fitness":
        return gov.fitness_landscape(bayesian=args.get("bayesian", False))
        
    else:
        raise ValueError(f"Unknown tool: {name}")
