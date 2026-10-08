# Horizontal Skill Graph & Agent Handoffs

> Modular capability graph and token-efficient agent-to-agent operational handoffs.

---

## 1. Overview

While **Cells** represent biological, evolutionary rules that adapt and decay, **Skills** represent deterministic, static agent capabilities and verification lenses.

The **Horizontal Skill Graph** provides:
- Decoupled, reusable capabilities across repositories.
- Zero-token bloat operational handoffs between collaborating subagents.
- Fail-closed typed artifact contracts.

---

## 2. Operational Handoff Primitives

Agents exchange work products using the `soma_handoff` primitive:

- **MCP Tool**: `soma_handoff(target_skill, artifact_type, payload)` in `soma_mcp/handlers/governance.py`
- **CLI Porcelain**: `soma handoff --from <skill> --to <skill> --artifact <path>`

### File-Buffered Tickets (< 150 Tokens)
Rather than dumping multi-thousand-token payloads into conversational context windows, `soma_handoff`:
1. Writes the full typed artifact to `.soma/swarm/handoffs/{cycle_id}_{artifact_type}.json`.
2. Delivers an ultra-compact receipt reference (<150 tokens) to the recipient agent.
3. The recipient agent reads the disk artifact on-demand when executing its task.

---

## 3. Schema Contracts & Production Matrix

All handoff payloads conform to registered dataclass schemas in `soma_core/schemas/artifacts.py`:
- `ChargeSheet`: Abstract violation charges with length caps and XML escaping.
- `InspectionReceipt`: Deterministic code inspection results.
- `DiffProposal`: Isolated unified diff with target file boundaries.
- `TestVerdict`: Machine-parseable test outcome report.

Handoff envelopes are signed with HMAC tokens and cryptographically bound to the current repository state (`HEAD^{tree}`).
