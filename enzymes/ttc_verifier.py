#!/usr/bin/env python3
"""Soma Test-Time Compute (TTC) Verifier — ADVISORY ONLY.

Reviews a proposed file change against the currently active JIT playbooks and
the hidden TTC oracles, then returns a verdict plus a unified diff.

This module does NOT write to the filesystem. It used to, while being labelled
"ADVISORY ONLY" and while every gate in front of the write was either inert or
failed open. The agent now applies the change itself, with its own file tools,
after reading the verdict.

Ordering invariant: the containment / path-traversal check runs FIRST, before
any filesystem read and before any network egress, so a traversal path can
never be shipped to an external LLM.

Diagnostics go to stderr. Under the stdio MCP server stdout is the JSON-RPC
transport, and a stray print() there corrupts the framing.
"""

import difflib
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Protocols the escalation sentinel may legitimately return.
ESCALATION_PROTOCOLS = ("breeze", "gale", "trident", "maelstrom", "tempest")
# Protocols that require out-of-band review before a change lands.
ESCALATING_PROTOCOLS = ("trident", "maelstrom", "tempest")
# Sentinel value for "sensitivity could not be determined". Treated as
# escalating: undetermined is not the same as safe.
PROTOCOL_UNKNOWN = "unknown"

SENTINEL_TIMEOUT = int(os.environ.get("SOMA_SENTINEL_TIMEOUT", "30"))

# enzymes/ttc_oracle.py:74 returns "APPROVED: Oracle evaluation failed (...)"
# on ANY exception, and "APPROVED: No inference provider available ..." when it
# has no backend. Both are fail-open verdicts wearing an APPROVED label. That
# module is out of scope here, so recognise its sentinels and fail closed.
ORACLE_FAIL_OPEN_MARKERS = (
    "oracle evaluation failed",
    "no inference provider available",
)
# A genuine pass: there is nothing to check.
ORACLE_NO_RULES_MARKER = "no oracles defined"

VERDICT_APPROVED = "APPROVED"
VERDICT_REJECTED = "REJECTED"
VERDICT_BLOCKED = "BLOCKED"          # gate could not vouch for the change
VERDICT_ESCALATE = "ESCALATION_REQUIRED"


def _log(message: str) -> None:
    """Emit a diagnostic on stderr (stdout may be a JSON-RPC transport)."""
    print(message, file=sys.stderr)


class TTCVerifier:
    """Fast keyword heuristics standing in for a lightweight LLM reviewer.

    The previous implementation keyed off the literal strings "React" and
    "Testing" appearing in a playbook's `name`. jit_engine builds playbook
    names from FILE STEMS (e.g. "trap-magic-numbers", "wall-oracles"), so no
    real playbook could ever match and the gate never rejected anything. The
    heuristics below search the whole playbook — hypothesis, prediction,
    guidance, body — not just its name.
    """

    # (rule id, topic markers looked for in the playbook text,
    #  forbidden tokens looked for in the proposal, human reason)
    HEURISTICS = (
        (
            "no-class-components",
            ("react", "functional component", "class component", "jsx"),
            ("class ",),
            "class components are forbidden; use functional components",
        ),
        (
            "no-meaningless-assertions",
            ("assertion", "test", "pytest", "jest", "vitest"),
            ("assert True", "assert 1 == 1", "expect(true).toBe(true)"),
            "meaningless assertions detected",
        ),
        (
            "no-hardcoded-secrets",
            ("secret", "credential", "api key", "token", "password"),
            ("AWS_SECRET_ACCESS_KEY=", "api_key = \"sk-", "password = \""),
            "a literal credential appears in the proposal",
        ),
    )

    def __init__(self, active_playbooks: List[Dict]):
        self.active_playbooks = active_playbooks or []

    @staticmethod
    def _playbook_text(playbook: Dict) -> str:
        """Flatten a playbook into lowercase searchable text."""
        parts = []
        for key in ("name", "_name", "hypothesis", "prediction", "guidance",
                    "body", "_body", "content"):
            value = playbook.get(key)
            if isinstance(value, str):
                parts.append(value)
        return "\n".join(parts).lower()

    def verify_proposal(self, proposed_diff: str, file_path: str) -> Dict[str, object]:
        """Return {"status", "reason", "playbook"} for the proposal.

        Heuristic and deliberately cheap: it informs the advisory verdict, it
        does not gate a write (there is no write).
        """
        for playbook in self.active_playbooks:
            if not isinstance(playbook, dict):
                continue
            text = self._playbook_text(playbook)
            if not text:
                continue
            label = playbook.get("name") or playbook.get("_name") or "unnamed playbook"
            for rule_id, topic_markers, forbidden_tokens, reason in self.HEURISTICS:
                if not any(marker in text for marker in topic_markers):
                    continue
                for token in forbidden_tokens:
                    if token in proposed_diff:
                        return {
                            "status": VERDICT_REJECTED,
                            "reason": (f"Violation of '{label}' [{rule_id}]: {reason} "
                                       f"(matched {token!r})."),
                            "playbook": playbook,
                        }

        return {
            "status": VERDICT_APPROVED,
            "reason": (f"No playbook heuristic matched "
                       f"({len(self.active_playbooks)} playbook(s) checked)."),
            "playbook": None,
        }


def resolve_workspace(start: Optional[str] = None) -> str:
    """Walk up from `start` (default cwd) looking for a .soma directory."""
    workspace = os.path.abspath(start or os.getcwd())
    d = workspace
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, ".soma")):
            return d
        d = os.path.dirname(d)
    return workspace


def _contain_path(file_path: str, workspace: str):
    """Resolve `file_path` inside `workspace`. Returns (resolved, relative).

    Raises ValueError if the path escapes the workspace. Runs before any read,
    any subprocess and any network call.
    """
    if not file_path or not str(file_path).strip():
        raise ValueError("no file_path was supplied")

    workspace_root = Path(workspace).resolve()
    # os.path.join returns file_path unchanged when it is absolute, so an
    # absolute path outside the workspace still lands in the check below.
    candidate = Path(os.path.join(workspace, file_path)).resolve()

    if candidate == workspace_root:
        raise ValueError("refusing to treat the workspace root as a file")
    try:
        relative = candidate.relative_to(workspace_root)
    except ValueError:
        raise ValueError(
            f"path traversal blocked: {file_path!r} resolves to {candidate} "
            f"which is outside the workspace {workspace_root}"
        )
    return str(candidate), str(relative)


def get_escalation_protocol(file_path: str, workspace: str) -> str:
    """Ask the escalation sentinel which review protocol this file needs.

    Fails CLOSED. Previously a missing script, a raised exception or an
    unparseable line all yielded "breeze", so the single most common
    misconfiguration silently disabled the gate.
    """
    sentinel = os.path.join(workspace, "enzymes", "escalation_sentinel.sh")
    if not os.path.exists(sentinel):
        _log(f"[TTC] escalation sentinel missing at {sentinel}; failing closed.")
        return PROTOCOL_UNKNOWN

    try:
        # Invoked through bash: the exec bit does not survive every checkout.
        # check=False on purpose: the sentinel exits 1 when it sees no
        # changes, which is not an error for us — we read its stdout.
        result = subprocess.run(
            ["bash", sentinel, file_path],
            capture_output=True, text=True, check=False,
            timeout=SENTINEL_TIMEOUT, cwd=workspace,
        )
    except Exception as exc:                      # noqa: BLE001 - reported, not swallowed
        _log(f"[TTC] escalation sentinel failed ({exc!r}); failing closed.")
        return PROTOCOL_UNKNOWN

    for line in result.stdout.splitlines():
        if line.startswith("PROTOCOL="):
            # split("=", 1): split("=")[1] truncated any value containing "=".
            protocol = line.split("=", 1)[1].strip().lower()
            if protocol in ESCALATION_PROTOCOLS:
                return protocol
            _log(f"[TTC] sentinel returned unrecognised protocol {protocol!r}; "
                 "failing closed.")
            return PROTOCOL_UNKNOWN

    _log("[TTC] sentinel emitted no PROTOCOL= line; failing closed. "
         f"stderr={result.stderr.strip()[:200]!r}")
    return PROTOCOL_UNKNOWN


def _consult_oracle(workspace: str, file_path: str, proposed_content: str):
    """Run the TTC oracle. Returns (verdict, detail).

    verdict is one of VERDICT_APPROVED / VERDICT_REJECTED / VERDICT_BLOCKED.
    BLOCKED means the oracle could not render a judgement — fail closed.
    """
    try:
        try:
            from enzymes.ttc_oracle import evaluate_change
        except ImportError:
            from ttc_oracle import evaluate_change
    except Exception as exc:                      # noqa: BLE001
        return VERDICT_BLOCKED, f"oracle module unavailable ({exc!r})"

    try:
        raw = evaluate_change(workspace, file_path, proposed_content)
    except Exception as exc:                      # noqa: BLE001
        return VERDICT_BLOCKED, f"oracle raised ({exc!r})"

    raw = (raw or "").strip()
    lowered = raw.lower()

    if lowered.startswith("rejected"):
        return VERDICT_REJECTED, raw
    if any(marker in lowered for marker in ORACLE_FAIL_OPEN_MARKERS):
        # Labelled APPROVED by ttc_oracle, but it is really "I could not check".
        return VERDICT_BLOCKED, raw
    if ORACLE_NO_RULES_MARKER in lowered:
        return VERDICT_APPROVED, raw
    if lowered.startswith("approved"):
        return VERDICT_APPROVED, raw
    return VERDICT_BLOCKED, f"unrecognised oracle response: {raw[:200]!r}"


def _build_diff(resolved_path: str, relative_path: str, proposed_content: str) -> str:
    """Unified diff between the file on disk and the proposal. Read-only."""
    current = ""
    exists = os.path.isfile(resolved_path)
    if exists:
        try:
            with open(resolved_path, "r", encoding="utf-8") as f:
                current = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            return f"(could not read existing file for diff: {exc})"

    diff = "".join(difflib.unified_diff(
        current.splitlines(keepends=True),
        proposed_content.splitlines(keepends=True),
        fromfile=f"a/{relative_path}",
        tofile=f"b/{relative_path}",
        n=3,
    ))
    if not diff:
        return "(no change: the proposal is identical to the file on disk)"
    header = "" if exists else f"(new file: {relative_path} does not exist yet)\n"
    return header + diff


def _render(verdict: str, relative_path: str, protocol: str, lines: List[str],
            diff: Optional[str] = None) -> str:
    """Render the advisory report returned to the agent."""
    out = [
        f"VERDICT: {verdict} — ADVISORY ONLY, NO FILE WAS WRITTEN.",
        f"File: {relative_path}",
        f"Escalation protocol: {protocol}",
    ]
    out.extend(lines)
    if diff is not None:
        out.append("")
        out.append("--- proposed diff (not applied) ---")
        out.append(diff)
    return "\n".join(out)


def soma_propose_change(file_path: str, proposed_content: str,
                        active_playbooks: List[Dict]) -> str:
    """Review a proposed change and return a verdict plus a diff.

    ADVISORY ONLY: nothing is written to disk. The caller applies the change
    with its own file-editing tool after reading the verdict.
    """
    workspace = resolve_workspace()

    # ── Gate 0: containment. FIRST, before any read, subprocess or network
    # egress, so a traversal path is never handed to an external LLM.
    try:
        resolved_path, relative_path = _contain_path(file_path, workspace)
    except ValueError as exc:
        _log(f"[TTC] {exc}")
        return (f"VERDICT: {VERDICT_REJECTED} — ADVISORY ONLY, NO FILE WAS WRITTEN.\n"
                f"File: {file_path}\n"
                f"Reason: {exc}\n"
                "Nothing was inspected and nothing was sent anywhere. Supply a "
                "path inside the workspace.")

    if proposed_content is None:
        return _render(VERDICT_REJECTED, relative_path, "n/a",
                       ["Reason: no proposed_content was supplied."])

    # ── Gate 1: escalation protocol (fails closed).
    protocol = get_escalation_protocol(relative_path, workspace)
    if protocol in ESCALATING_PROTOCOLS or protocol == PROTOCOL_UNKNOWN:
        if protocol == PROTOCOL_UNKNOWN:
            why = ("Sensitivity could not be determined, so this is treated as "
                   "sensitive (the gate fails closed).")
        else:
            why = ("This file is highly sensitive (core infrastructure / auth).")
        return _render(
            VERDICT_ESCALATE, relative_path, protocol,
            [
                f"Reason: {why}",
                ("ACTION REQUIRED: dispatch the 'Security Audit Organ' and "
                 "'Performance Audit Organ' subagents to review this change "
                 "concurrently. Changes to this file require out-of-band "
                 "approval."),
                "The proposal was NOT sent to the oracle and NOT written.",
            ],
        )

    _log(f"[TTC] Reviewing proposed change to {relative_path} (protocol: {protocol}).")

    # ── Gate 2: playbook heuristics.
    playbook_result = TTCVerifier(active_playbooks).verify_proposal(
        proposed_content, relative_path)
    if playbook_result["status"] == VERDICT_REJECTED:
        return _render(
            VERDICT_REJECTED, relative_path, protocol,
            [f"Playbook check: REJECTED — {playbook_result['reason']}",
             "Revise the proposal so it no longer violates this playbook.",
             "The proposal was NOT sent to the oracle and NOT written."],
        )

    # ── Gate 3: TTC oracle (network egress happens here, after containment).
    oracle_verdict, oracle_detail = _consult_oracle(
        workspace, relative_path, proposed_content)
    diff = _build_diff(resolved_path, relative_path, proposed_content)

    if oracle_verdict == VERDICT_REJECTED:
        _log(f"[TTC Oracle] {oracle_detail}")
        return _render(
            VERDICT_REJECTED, relative_path, protocol,
            [f"Playbook check: PASSED — {playbook_result['reason']}",
             f"Oracle: REJECTED — {oracle_detail}",
             "Follow the architectural tenets and standards, then re-propose."],
            diff,
        )

    if oracle_verdict == VERDICT_BLOCKED:
        _log(f"[TTC Oracle] inconclusive: {oracle_detail}")
        return _render(
            VERDICT_BLOCKED, relative_path, protocol,
            [f"Playbook check: PASSED — {playbook_result['reason']}",
             f"Oracle: INCONCLUSIVE — {oracle_detail}",
             ("This is NOT a rule violation: the oracle could not render a "
              "judgement, so the gate fails closed rather than approving "
              "blind. Configure an inference provider (GEMINI_API_KEY / "
              "ANTHROPIC_API_KEY / OPENAI_API_KEY) or review the diff "
              "manually before applying it.")],
            diff,
        )

    return _render(
        VERDICT_APPROVED, relative_path, protocol,
        [f"Playbook check: PASSED — {playbook_result['reason']}",
         f"Oracle: APPROVED — {oracle_detail}",
         ("NEXT STEP: nothing was written. Apply the diff below with your own "
          "file-editing tool.")],
        diff,
    )


def _self_test() -> int:
    """Non-destructive self-test: asserts no file is created or modified."""
    # Make `from enzymes.ttc_oracle import ...` resolvable when run directly.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    # Detach stdin: with no inference provider configured the oracle falls back
    # to PromptOnlyProvider, which would legitimately wait for a human to paste
    # a verdict. A self-test must never block, so present a non-TTY stdin and
    # let the oracle gate report INCONCLUSIVE instead.
    import io
    sys.stdin = io.StringIO()

    mock_playbooks = [
        # Names are FILE STEMS, as jit_engine actually produces them — the old
        # name-only matcher could never fire on these.
        {"name": "chloroplast-react-idioms",
         "hypothesis": "React components must be functional components.",
         "body": "Never use class components."},
        {"name": "wall-test-assertions",
         "hypothesis": "Tests must carry meaningful assertions.",
         "body": "Meaningless assertions are forbidden in pytest suites."},
    ]

    target = "src/App.jsx"
    bad_proposal = ("class MyComponent extends React.Component {\n"
                    "  render() { return <div>Hi</div>; }\n}")
    good_proposal = "const MyComponent = () => <div>Hi</div>;\n"

    workspace = resolve_workspace()
    probe = os.path.join(workspace, target)
    existed_before = os.path.exists(probe)

    cases = [
        ("playbook rejection (class component)", target, bad_proposal),
        ("clean proposal", target, good_proposal),
        ("path traversal", "../../../../tmp/soma-ttc-escape.txt", good_proposal),
        ("absolute path outside workspace", "/tmp/soma-ttc-abs.txt", good_proposal),
    ]
    for label, path, content in cases:
        print(f"\n--- {label} ---")
        print(soma_propose_change(path, content, mock_playbooks))

    print("\n--- non-destructiveness assertions ---")
    failures = []
    if os.path.exists(probe) and not existed_before:
        failures.append(f"created {probe}")
    for escape in ("/tmp/soma-ttc-escape.txt", "/tmp/soma-ttc-abs.txt"):
        if os.path.exists(escape):
            failures.append(f"created {escape}")
    if failures:
        print("SELF-TEST FAIL: " + "; ".join(failures))
        return 1
    print(f"SELF-TEST PASS: no file created or modified "
          f"(checked {probe} and the traversal targets).")
    return 0


if __name__ == "__main__":
    # A cp1252 stdout can't encode this script's symbols (BUG-038).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    sys.exit(_self_test())
