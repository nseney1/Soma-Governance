# MCP Gateway & Dual-Plane Architecture

> Fast, secure, zero-dependency Model Context Protocol (MCP) server integration for AI coding assistants.

---

## 1. Overview

Soma provides a native MCP server (`soma-mcp`) allowing AI assistants (such as Claude Code, Antigravity, Gemini, and Cursor) to query governance rules, inspect verification verdicts, submit verification requests, and exchange typed artifacts with zero runtime dependencies.

Starting in `v0.122.0`, the MCP gateway is decomposed into a **Dual-Plane Architecture**:
- **Control Plane (`soma_mcp/registry.py`)**: Schema definitions, argument sanitization, workspace boundary confinement (`Workspace.confine`), and tier enforcement.
- **Execution Plane (`soma_mcp/handlers/`)**: Granular domain modules (<280 LOC each):
  - `governance.py`: Cell creation, listing, proposal, manifest generation, and skill handoffs.
  - `verification.py`: Verification runs, status polling, checkpointing, and receipt requests.
  - `audit.py`: Security audits, performance checks, and workspace scans.
  - `telemetry.py`: Outcome recording, insight capture, grading, coverage, and fitness signals.
- **Gateway Router (`soma_mcp/tools.py`)**: Ultra-thin dispatcher (<150 LOC) handling MCP protocol routing.

---

## 2. Tool Tiers & Security Policy

All 20 MCP tools are categorized into three capability tiers with a **Disabled-by-Default** security posture:

| Tier | Default State | Authorization | Tools |
| :--- | :---: | :---: | :--- |
| **Read** | Enabled | None | `soma_scan`, `soma_list_cells`, `soma_fitness`, `soma_coverage`, `soma_grade`, `soma_audit_security`, `soma_audit_performance` |
| **Write** | Enabled | Session Token / Receipt | `soma_create_cell`, `soma_propose_change`, `soma_generate_manifest`, `soma_report_outcome`, `soma_capture_insight`, `soma_request_receipt`, `soma_handoff` |
| **Execute** | Opt-In | Session Token & Explicit Flag | `soma_verify_changes`, `soma_poll_verification`, `soma_checkpoint` |

### Security Invariants
1. **Workspace Boundary Confinement**: Every tool path argument is confined within the canonical repository root via `Workspace.confine(path)`. Path traversal attempts (e.g. `../../etc/passwd`) raise `SecurityViolationError` immediately.
2. **Session HMAC Protection**: Verification receipts and turn-2 rebuttals are authenticated via HMAC-SHA256 signatures bound to `HEAD^{tree}`.
3. **Information Partitioning (SOMA-V01)**: Raw user prompts and plans are scrubbed before recording on disk; Defending agents inspect only abstract charges with capped lengths and XML sanitization.

---

## 3. Opt-In Response Projection

Clients can limit response token volume by providing the optional `view` or `fields` parameters:
- `view="full"` (default): Returns complete guidance and schema payloads.
- `view="summary"`: Returns high-level status and top findings.
- `view="ids"`: Returns only rule and cell identifier lists.
- `fields=["id", "enforcement", "fitness.score"]`: Pure dictionary key extraction without `eval()` or AST hazards.

---

## 4. Setup & Configuration

Add Soma to your agent's MCP configuration (e.g. `claude_desktop_config.json` or `.gemini/antigravity/mcp/soma.json`):

```json
{
  "mcpServers": {
    "soma": {
      "command": "soma-mcp",
      "args": ["--workspace", "/path/to/repo"]
    }
  }
}
```
