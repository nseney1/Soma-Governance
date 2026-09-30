---
name: TDD Protocol
description: Enforces test-driven development with sequential phase gates. No implementation begins until tests exist and fail for the right reasons.
trigger: model_decision
---

# TDD Protocol

**Role**: Workflow enforcement rule that mandates test-first development with sequential hard gates. Advisory testing guidance lives in `.oracles/testing.md`; this rule defines the **process** that wraps it.

## Protocol Gates

| Gate | Name | Must Pass Before |
|:-----|:-----|:-----------------|
| 1 | Test Suite Written | Any implementation begins |
| 2 | Red Phase | Tests fail for the right reasons |
| 3 | Implementation | Only after Gate 2 |
| 4 | Green Phase | All tests pass, full regression clean |
| 5 | Tempest Review | Adversarial subagents audit the diff |
| 6 | Commit | Only after Gate 5 verdict is SHIP |

Gates are **sequential and non-negotiable**. Skipping a gate or reordering requires explicit user override with documented rationale.

---

## Gate 1: Test Suite Written

Before writing any production code for a feature or fix:

1. **Identify behaviors** — List the observable behaviors the change must produce. Frame as "when X, then Y" assertions.
2. **Write tests first** — Create test functions/methods that assert on expected outcomes. Tests must cover:
   - At least one happy path per behavior
   - At least one sad path or edge case per behavior
   - Boundary conditions where applicable
3. **No stubs allowed** — Tests must import real modules and call real entry points. Placeholder `pass` bodies or `@skip` decorators do not satisfy this gate.
4. **Gate check** — Run the test suite. It should either fail to import (module doesn't exist yet) or fail assertions. If tests pass at this stage, they are not testing new behavior.

**Output**: Test file(s) committed or staged. Agent must cite the test file paths and the behaviors they cover.

---

## Gate 2: Red Phase

Verify that the tests fail **for the right reasons**:

1. **Run tests** — Execute the test suite and capture output.
2. **Classify failures** — Each failure must be one of:
   - `ImportError` / `ModuleNotFoundError` — Module not yet created *(acceptable)*
   - `AttributeError` / `NameError` — Function/class not yet defined *(acceptable)*
   - `AssertionError` — Logic not yet implemented *(acceptable)*
3. **Reject wrong failures** — The following failure types indicate bad tests, not missing implementation:
   - `SyntaxError` — Fix the test
   - `TypeError` (wrong arg count) — Fix the test's call signature
   - `FileNotFoundError` for test fixtures — Create the fixture first
   - Timeout / hang — Fix the test
4. **Gate check** — Agent must explicitly state: *"Red phase verified: N tests fail with [failure types]. No wrong-reason failures detected."*

**Output**: Test run log showing expected failures. Agent cites failure count and types.

---

## Gate 3: Implementation

Only begins after Gate 2 passes:

1. **Write minimal production code** to make the failing tests pass.
2. **No gold-plating** — Do not add behaviors that aren't covered by existing tests. If new behavior is needed, return to Gate 1.
3. **Incremental runs** — Run the specific test file after each logical unit of implementation. Do not batch all testing to the end.
4. **Checkpoint discipline** — If modifying 3+ files, run relevant tests between each file change (per `.oracles/testing.md` §Checkpoint Testing).

**Output**: Production code changes. Agent tracks which tests have turned green.

---

## Gate 4: Green Phase

All tests must pass with clean regression:

1. **Full suite** — Run the **complete** test suite, not just the new tests.
2. **Zero failures** — Any failure blocks the gate. Fix before proceeding.
3. **No test modifications** — If a pre-existing test broke, the implementation caused a regression. Fix the implementation, not the test (unless the test was genuinely wrong, which must be documented).
4. **Gate check** — Agent must state: *"Green phase verified: N/N tests passing. Full regression clean."*

**Output**: Clean test run output. Agent cites total pass count.

---

## Gate 5: Tempest Review

Adversarial review of the complete diff:

1. **Trigger** — Dispatch Tempest review per the project's review protocol (Spores triage → escalation).
2. **Scope** — Review covers all changes since the last clean commit: production code, tests, and configuration.
3. **Minimum bar** — At least one review prong must examine:
   - Correctness (do the tests actually prove the claimed behavior?)
   - Regression risk (could this break existing functionality?)
4. **Verdict** — Review must produce an explicit verdict: **SHIP**, **HOLD**, or **REJECT**.
   - **SHIP** — Proceed to Gate 6
   - **HOLD** — Address findings, return to Gate 3 or Gate 1 depending on severity
   - **REJECT** — Fundamental approach is wrong; return to planning

**Output**: Review verdict with cited findings. Agent must not self-review.

---

## Gate 6: Commit

Only after Gate 5 verdict is SHIP:

1. **Atomic commit** — All related changes (tests + implementation) in a single commit or PR.
2. **Commit message** — Must reference the TDD protocol: tests written first, red/green verified.
3. **No post-commit fixups** — If issues are found after commit, open a new TDD cycle (Gate 1) for the fix.

---

## Exceptions & Overrides

- **Trivial changes** (typos, comment-only, formatting): Gates 1-2 may be skipped with explicit `[TDD-SKIP: trivial]` in commit message.
- **Emergency hotfixes**: User may override to Gate 3 → Gate 4 → Gate 6 with documented rationale. Gate 5 must be performed post-commit as a follow-up.
- **Spike/exploration**: Throwaway code in scratch directories is exempt. Production code is never exempt.

---

## Metrics

- **Gate Violation Rate**: Percentage of commits that skip gates without override. Target: **0%**.
- **Red-to-Green Ratio**: Average number of implementation iterations between Gate 2 and Gate 4. Target: **≤3** (indicates well-scoped tests).
- **Regression Introduction Rate**: Percentage of Gate 4 runs that catch pre-existing test breakage. Track to identify fragile areas.
