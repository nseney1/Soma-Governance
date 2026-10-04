# Changelog

All notable changes to Soma are documented here.
This project uses [Semantic Versioning](https://semver.org/).

## [0.90.0] — 2026-10-03 — "Security & Hardening"

### Added
- **`soma completion {bash,zsh,fish}`**: prints a shell completion script for every subcommand, option and choice value (for example `init --platform`). `soma_cli/completion.py` generates it at runtime from the argparse parser, so it can't drift from the CLI. Soma never edits dotfiles; `QUICKSTART.md` ("Shell completion") gives the line to add, such as `eval "$(soma completion zsh)"`. Tests: `tests/test_completion.py`, which also syntax-checks the output with `bash -n` and `zsh -n` when those shells are installed.
- **`soma doctor --fix-path [--yes]`**: the opt-in alternative to copying the BUG-041 PATH line by hand. It appends that line, marked `# added by soma doctor --fix-path`, to `~/.zshrc` (honours `ZDOTDIR`), `~/.bashrc` (macOS: `~/.bash_profile`) or fish's `config.fish` (honours `XDG_CONFIG_HOME`, uses `fish_add_path`). It is a dry run unless you confirm at the prompt or pass `--yes`, and without a terminal it only prints the file and line. It is idempotent, refuses an rc file that resolves outside your home directory (including through a symlink), writes atomically and keeps the file mode, and never edits a PowerShell `$PROFILE` (it prints the command instead). The installers still never edit dotfiles. Each added line is recorded under `path_lines` in `~/.soma/manifest.json`; `install/uninstall.sh` and `install/uninstall.ps1` list it as `[MOD] <rc> (remove soma PATH line)` and remove exactly that line, restoring the file byte for byte (a file doctor created is deleted again if nothing else is in it). An edited line is left alone with a warning. `install.sh` carries `path_lines` over when it rewrites the manifest. Tests: `tests/test_doctor_fix_path.py`.
- **`soma doctor` MCP launcher check**: MCP configs start the server with `python3 -m soma_mcp`. Doctor now resolves `python3` from `PATH` the way the MCP host does and reports whether it works, is missing, is the Windows Store App Installer stub (exit 49, or a Store message and no output), or runs but cannot import `soma_mcp`, with the fix for each. The check is advisory and doesn't change doctor's exit code. Tests: `tests/test_doctor_mcp_launcher.py`.
- **Open bugs BUG-033 and BUG-034** in the Bug Registry: `soma status` miscounts installed core rules (#55), and `mutation_tester` fails open when tests cannot run (#54). Both were reproduced on v0.89.0.
- **Open bugs BUG-036, BUG-037 and BUG-038**: `uninstall.sh` under Git Bash rejects every path (#62), the Git Bash `python3` Store stub (#64, split out of BUG-010), and enzyme scripts crashing on a cp1252 stdout (#65).
- **`SECURITY.md`**: supported versions (current minor line only), private reporting through GitHub private vulnerability reporting, response goals, scope and out-of-scope, and a summary of the security model (MCP receipts and workspace confinement, evidence integrity, installer confinement, release digests). Linked from the README documentation table. Test: `tests/test_security_policy.py`.
- **Open bug BUG-040**: recording an outcome leaves `.soma/evidence/.signals.lock` as an untracked file, because no ignore rule covers it (#70).
- **Windows pytest job in CI** (B3): `validate.yml` gains `test-windows`, which runs the full suite on `windows-latest` (Python 3.9 and 3.12) under Git Bash against the validated wheel. `HOME` and `USERPROFILE` point under `runner.temp` (BUG-010), and `PYTHONUTF8=0` keeps the cp1252 defaults. Failures fail the job. Regression tests: the `test_windows_test_job_*` tests in `tests/test_ci_workflows.py`.

### Changed
- **BUG-013 root cause** recorded in the Bug Registry and `docs/KNOWN_ISSUES_WINDOWS.md`: generated verification tests embed unescaped Windows paths and fail with a `unicodeescape` `SyntaxError`.
- **BUG-015** now links to #57, and **BUG-014** to its own issue #59 (split from #48, which the v0.89.0 BOM fix closed). **BUG-032** is listed in `docs/KNOWN_ISSUES_WINDOWS.md`.

### Fixed
- **`soma status` miscounted core rules for installer-based Claude setups** (BUG-033, #55): the installers merge rules into `~/.claude/CLAUDE.md`, but status only counted loose `*.md` files and, finding none, reported the package's own `genome/` count (a 1-rule `CLAUDE.md` showed "19 active"). Status now counts the Soma sections in `CLAUDE.md`, in both the installer format and the `soma init` marker format, plus loose files, without counting a rule twice, and never falls back to `genome/` when `CLAUDE.md` has Soma content. Regression tests: `tests/test_status_claude_md.py`, including one that runs `install/install.sh claude` under an isolated `HOME`.
- **`soma completion zsh` colons and BOM-prefixed rule files**: `:` in option help (e.g. `--rules` "(default: standard)") is now escaped as `\:` so zsh `_arguments` descriptions aren't cut short; `soma status` and `soma_sdk.cells.parse_cell_file` read rule/cell files as `utf-8-sig`, so BOM-prefixed files from PowerShell 5.1 `Set-Content -Encoding UTF8` keep their frontmatter `id` and aren't double-counted against `CLAUDE.md`. Tests: `tests/test_completion.py`, `tests/test_status_claude_md.py`, `tests/test_cells_bom.py`.
- **Windows: cell inventory rejected any cell edited after creation** (BUG-035, #61): `soma_core/cell_inventory.py` compared `os.stat` and `os.fstat` signatures that included `st_ctime_ns`, which Windows reports as creation time from one and change time from the other. `soma_scan` and `soma_list_cells` failed, and `soma_request_receipt` returned `Internal error`, so no write or execute MCP tool could run on Windows. `st_ctime_ns` is now left out of the signature on Windows, and cells are opened with `O_BINARY` so the snapshot holds the exact on-disk bytes. Regression tests: `test_receipt_flow_works_after_cell_edited_since_creation`, `test_cell_edited_after_creation_is_inventoried`. The `O_BINARY` change also fixes `test_inventory_is_stable_and_captures_exact_bytes` on Windows. The stale-receipt tests now match the exact verifier message, because their `"receipt"` substring check also accepted unrelated errors such as the missing-receipt error.
- **Windows: installer tests wrote to the real user profile** (BUG-010, #47): under Git Bash `resolve_home()` prefers `USERPROFILE`, and six `tests/test_install_lifecycle.py` calls overrode only `HOME`. The shared `run()` helper in `tests/conftest.py` now sets `USERPROFILE` to `HOME` when a test overrides `HOME` alone. Regression test: `tests/test_home_isolation.py`.
- **Windows: `soma status` crashed on a cp1252 stdout** (BUG-012, #49): printing an emoji raised `UnicodeEncodeError` and the command exited 1. `soma` and `enzymes/verify_bug_registry.py` now reconfigure stdout with `errors="replace"`; standalone enzyme scripts are still affected (open BUG-038). `tests/test_rule_metadata.py` reads rule files as UTF-8. Regression tests: `tests/test_cli.py::TestNonUtf8Console`, `tests/test_bug_registry.py::test_error_report_survives_cp1252_stdout`.
- **Windows-only test failures** (BUG-013, #50): generated tests now escape `tmp_path` (`{str(tmp_path)!r}`); path assertions compare `Path.parts` or normalized paths; byte-sensitive files are written as UTF-8 with LF; `tests/conftest.py` gains `require_bash()` (replacing hard-coded `/bin/bash`) and `symlink_or_skip()`; the execute-bit test skips on Windows. On Windows the suite goes from 49 to 12 failures (BUG-036, BUG-038).
- **`mutation_tester` failed open when tests couldn't run** (BUG-034, #54): `check()` counted any test failure as a killed mutant, so a test file with a syntax error, import error or wrong assertion reported `verdict=True`. It now runs the tests against the unmutated source first and returns `verdict=False` (`lines=[-1]`) when that baseline fails. Regression tests: `tests/test_verification/test_mutation_tester.py::TestMutationTesterFailsClosed`.
- **`mutation_tester` skipped most mutation kinds** (BUG-039, #66): comparison, `and`/`or`, statement-deletion and return-value mutations were counted but never applied, so a test that never checked a comparison reported `verdict=True`. Every collected mutation is now applied; docstring deletion and `return None` are no longer generated, since they are equivalent mutants no test can kill. Regression tests: `tests/test_verification/test_mutation_tester.py::TestMutationTesterAppliesEveryCollectedMutation`.
- **Recording an outcome left `.soma/evidence/.signals.lock` untracked** (BUG-040, #70): `evidence_lock()` keeps its lock file, and no ignore rule covered it, so `git add -A` would commit it. `.soma/evidence/.gitignore` now lists it. Regression tests: `tests/test_telemetry.py::TestEvidenceLockIgnoredByGit`, which also checks that the committed evidence files are still not ignored.
- **Windows: `uninstall.sh` under Git Bash refused every path** (BUG-036, #62): MSYS paths (`/c/...`, `/tmp/...`) reached the confinement check in native Windows Python unconverted, so `os.path.isabs()` rejected them and nothing was removed. The check now maps them with `cygpath`, resolved from `PATH` by the shell, since a bare name in Windows Python also searches the current directory. Three defects behind it are fixed too: `read_manifest_field` wrote CRLF in the console code page, so every entry but the last, and non-ASCII names, silently dropped out of the plan; an entry it couldn't encode (a lone surrogate) ended the list early, and uninstall then exited 0 and deleted the manifest; and a refusal could crash while printing its own path. Hardening: on Windows the check also refuses path segments that end in a space or a dot, and `:` stream syntax, which Win32 would resolve to a different name than the one checked. Regression tests: the Git Bash path-form, Win32-normalisation and manifest-reader tests in `tests/test_uninstall_confinement.py`.
- **Windows: enzyme scripts crashed on a cp1252 stdout** (BUG-038, #65): standalone scripts under `enzymes/` and `immune_system/verification/` printed emoji or other non-ASCII and exited 1 with `UnicodeEncodeError` when output was redirected or captured, including hook runs. All 29 entry points with non-ASCII output now reconfigure stdout with `errors="replace"` at the start of their `__main__` block, the same guard as BUG-012. `tests/test_enzyme_console_encoding.py` covers it, and the 3 Windows failures in `tests/test_crossover_structured.py` are fixed.
- **`soma` was "command not found" under zsh after `pip install --user`, with no guidance** (BUG-041): zsh doesn't read `~/.profile`, where `~/.local/bin` is added to `PATH`. The new `soma_cli/pathcheck.py` finds where pip put the script, checks exact `PATH` entries, and prints the line to add for zsh, bash, fish or PowerShell and the file it belongs in; it never edits dotfiles. `soma doctor`, `install/install.sh` and `install/install.ps1` print it. The Makefile now installs with the resolved interpreter's pip (`"$(SOMA_PYTHON_BIN)" -m pip`, BUG-037) and shows pip's errors when every attempt fails, instead of discarding them. Added `python3 -m soma_cli` and `soma --version`, and a troubleshooting section in `QUICKSTART.md`. Regression tests: `tests/test_pathcheck.py`, `tests/test_doctor.py::test_cli_check_prints_zsh_remedy_when_unresolvable`.
- **Git Bash: the Windows Store `python3` stub broke hooks and shell enzymes** (BUG-037, #64): `command -v python3` succeeds for the App Installer stub, which exits 49 when run. `enzymes/soma_python.sh` resolves the first of `python3`, `python` and `py -3` that actually runs Python 3 (`SOMA_PYTHON` overrides it), and all calls go through `soma_py`.
- **`immune_sweep.sh` aborted unless `SOMA_DATA_DIR` was exported** (BUG-042): it read `$RESOLVED_HOME`, which nothing set, under `set -u`. It now uses `resolve_home`, and creates its governance directory on a fresh home. Regression test: `tests/test_v090_hardening.py::test_immune_sweep_runs_without_soma_data_dir`.
- **`uninstall.sh` without Python 3 used a lexical confinement check** (BUG-043): see Security. Regression test: `tests/test_v090_hardening.py::test_manifestless_uninstall_without_python_removes_nothing`.
- **Inline Python in enzymes no longer imports CWD modules** (BUG-044): `soma_py` strips CWD entry from `sys.path[0]` for inline code while preserving user site-packages. Regression test: `tests/test_redteam_followups.py`.
- **`uninstall.sh` Claude `settings.json` cleanup is confined and previewed** (BUG-045): settings files holding `hooks.soma` are previewed as `[MOD]`, checked against `ALLOWED_ROOTS`, and rewritten atomically preserving mode. Regression test: `tests/test_redteam_followups.py`.
- **`verify_bug_registry.py` timed out on clean Windows installation** (BUG-046, #80): dynamic timeout budget based on test count and pytest summary ID matching.
- **The `soma init` pre-commit hook aborted commits with only `soma: not found`** (BUG-047): it ran a bare `soma checkpoint`, which doesn't resolve when `soma` isn't on the hook's `PATH` (zsh and other non-login shells after `pip install --user`, GUI git clients, IDEs). The hook now falls back to the interpreter that ran `soma init`, and with neither it fails with a message that names `soma doctor` and the `PATH` fix. Re-running `soma init` refreshes an existing hook block in place and keeps your own lines; `soma doctor` reports an old block. Regression tests: `tests/test_precommit_hook_fallback.py`.

### Security
- **PyPI Trusted Publishing (OIDC)**: `publish.yml` no longer uses a long-lived `PYPI_API_TOKEN` or `twine`. The publish job runs in the `pypi` environment with `id-token: write` and uploads through `pypa/gh-action-pypi-publish`. It uploads only the files `verify_dist.py verify` printed, copied into `publish-dist/`, because `dist/` also holds `SHA256SUMS`. The build-once, digest-verified, no-rebuild chain is unchanged.
- **Least-privilege tokens**: both workflows set top-level `permissions: contents: read`; only `build-wheel` (attestations) and `publish` (OIDC) are granted more, at job level.
- **SHA-pinned actions**: every third-party action is pinned to a full commit SHA with a `# vX.Y.Z` comment; `.github/dependabot.yml` updates `github-actions` and `pip` weekly.
- **Dependency audit**: a new `dependency-audit` job in `validate.yml` runs `pip-audit --strict .` on the runtime dependencies in `pyproject.toml` and fails on any finding. `pip-audit` is installed in CI only.
- **Build provenance**: `build-wheel` signs SLSA provenance for the wheel and sdist with `actions/attest-build-provenance` on push and release builds. It is skipped on pull requests, because fork PRs get no OIDC token. The publish action also uploads PEP 740 attestations to PyPI.
- Regression tests: `tests/test_ci_workflows.py`.

## [0.89.0] — 2026-10-02 — "MCP Execution Security"

### Added
- **Opaque, stateful, session-bound receipts for MCP execution** (Fixes BUG-009): The server now requires single-use cryptographic receipts for all write and execute tools, fetched via `soma_request_receipt`. This ensures only trusted MCP connections can mutate workspace state, mitigating cross-workspace CSRF attacks.
- **Strict workspace injection boundaries** in the MCP dispatcher. The server forcibly injects the operator-configured `_canonical_workspace` into write and execute tools, ignoring client-provided `workspace` arguments, preventing path traversal via rogue arguments.
- **Open-bug tracking in the Bug Registry**: entries take `status: open|fixed` (default `fixed` for existing entries). `enzymes/verify_bug_registry.py` requires only the core fields for open bugs, rejects open bugs that set fix fields, and skips regression-test collection for them.
- **`platform_compat` root-cause category** and open bugs BUG-008–BUG-014 (Windows and MCP issues; GitHub issues #45–#50) and BUG-015 (`soma checkpoint`/`soma sync` wipe cell fitness on a fresh clone).
- **`docs/KNOWN_ISSUES_WINDOWS.md`**: open Windows issues, workarounds, and impact.

### Changed
- **README**: known-issue notes for the MCP server and Windows; the Windows rows of the platform table are now ⚠️ where open bugs apply.
- **`soma_request_receipt` classification**: Reclassified from `_WRITE_TOOLS` to `_READ_TOOLS` so it remains discoverable in `tools/list` when execution mode is disabled.

### Fixed
- **MCP write/execute tools unusable from MCP hosts** (BUG-009, #46): Handshake designed for direct clients replaced with session-bound receipt architecture. Regression test: `test_mcp_dispatch.py`.
- **`install.ps1` failed to parse under Windows PowerShell 5.1** (BUG-011, #48): the installers were UTF-8 without a BOM, so PS 5.1 read them as cp1252. They are now saved with a UTF-8 BOM. Regression test: `test_powershell_scripts_with_non_ascii_have_utf8_bom`. CI: new Windows PowerShell 5.1 dry-run step in `validate.yml`.
- **MCP server crashed on Windows at startup** (BUG-008, #45): `soma_mcp/tools.py` and `soma_sdk/telemetry.py` imported `fcntl` unconditionally. Both now fall back to unlocked appends when `fcntl` is unavailable, matching `enzymes/fitness_updater.py`. Regression tests: `tests/test_fcntl_optional.py`.
- `tests/test_diagnose_hot_zones.py`: the "Insufficient data" snapshot test assumed fewer than 10 registry entries; it now asserts the warning tracks the registry size.

### Fixed (pre-release review)
- **Canonical workspace was never injected** (BUG-016): the assignment sat after an unconditional `return`, so write/execute tools honoured a client-supplied `workspace`. The dispatcher now strips server-owned keys (`workspace`, `receipt`, `_sessionToken`) from every call, read tools included, and injects the operator-configured workspace after receipt verification. Privileged calls fail closed when no canonical workspace is configured. Tests: `tests/test_mcp_receipt_binding.py`.
- **Receipts bound to empty digests** (BUG-017): receipts now bind sha256 digests of the target files named in the arguments (`file_path`, `files`, `context_files`) and of every cell under `.soma/cells`, recomputed at redemption. Paths outside the workspace are rejected at issuance. Note: any cell edit (including an outcome-engine fitness update) inside the 300 s receipt window makes outstanding receipts stale; request a new one.
- **Telemetry `event_id` was not enforced** (BUG-018): `append_signal` now holds a cross-process evidence lock (`.soma/evidence/.signals.lock`; `fcntl`, `msvcrt` or thread-lock fallback), treats an identical replay as a no-op, raises `EventConflictError` for a changed payload, returns the persisted record, and stamps every record with the epoch `generation`.
- **Epoch migration was a placeholder** (BUG-019): `run_epoch_migration` now holds the evidence lock for the whole cutover, snapshots every ledger into `snapshot/gen-<n>/` with `SHA256SUMS`, converts legacy `fitness.jsonl`/`outcomes.jsonl` rows with deterministic event ids, skips MCP twins and already-migrated rows, aborts unchanged on a reconciliation mismatch, writes atomically, and fences writers via `append_signal(expected_generation=...)` / `StaleGenerationError`.
- **Human-insight cursor advanced before persistence** (BUG-020): reading no longer writes the cursor. `main()` appends evidence first; insight events carry a stable id, so a retry after a partial failure dedupes instead of duplicating. The cursor is then committed atomically, and cell frontmatter is updated only after that, so a retry never applies a boost twice. Appends are fenced on the generation the run observed. Partial trailing lines are re-read.
- **MCP outcomes could be double counted by migration**: `soma_report_outcome` now writes one `outcome_id` into both the legacy `outcomes.jsonl` row and its idempotent `signals.jsonl` twin, and migration dedupes on that id. Rows without an id fall back to timestamp matching.
- **Uninstall path confinement was lexical** (BUG-021): `uninstall.sh` and `uninstall.ps1` validate every manifest field and the full removal plan against canonical allowed roots before any mutation, fail closed, and re-check each path at the sink. Symlinked or junctioned ancestors are accepted only when their target stays inside the allowed root (stow-style `~/.kiro -> ~/dotfiles/.kiro` works; a link out of `$HOME` is refused). OneDrive placeholders, which carry the ReparsePoint attribute without being links, are not treated as redirections.
- **`quality_gate` crashed on Python 3.14** (BUG-022): dropped the removed `ast.Str` alias.
- **Release could ship untested bytes** (BUG-023): one build records `SHA256SUMS`; the sdist and the matrix-installed wheel are smoke-tested outside the checkout (`python -I`, `PYTHONPATH` unset, module origins asserted under site-packages) by `.github/scripts/wheel_smoke.py`; `publish.yml` verifies the digests and uploads only the verified files.
- **BUG-009 registry entry** used a non-schema `resolved_in` field and lacked `changelog_ref`, so the registry failed its own verifier and broke CI.

---

## [0.88.2] — 2026-10-01 — "Documentation Updates"

### Documentation
- Removed deprecated API Key fields from `README.md` configuration table.

---

## [0.88.1] — 2026-10-01 — "Credential Hardening"

### Security
- **Deprecated Plaintext API Keys**: Removed `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, and `OPENAI_API_KEY` from configuration files (`soma.conf`, `.soma/credentials.conf`).
- **Enforced Secure Storage**: `inference_provider.py` now exclusively resolves credentials via environment variables or the system `keyring`, mitigating the risk of accidentally committing secrets.

---

## [0.88.0] — 2026-10-01 — "Key Management"

### Added
- **HMAC-SHA256 key management** (`soma_mcp/integrity.py`): 256-bit key generation, storage in `.soma/keys/manifest.key` with `0o600` permissions, key rotation with `.bak` backup.
- **Manifest signing**: `save_manifest()` auto-signs when key exists; `verify_signature()` uses constant-time `hmac.compare_digest`.
- **`soma_generate_manifest` MCP tool**: Generates and signs cell integrity manifests, with optional key creation. Added to `_EXECUTE_TOOLS` tier (requires session auth).
- **Signature verification in cell cache**: `cell_cache.py` logs HMAC verification status during refresh.
- **10 new security test cases**: Key CRUD, signing determinism, tamper detection, auto-sign on save, graceful unsigned fallback.

### Technical
- Stdlib only (`hmac` + `secrets`), no new dependencies.
- Signs only the `cells` dict (not metadata) for canonical determinism.

---

## [0.87.0] — 2026-10-01 — "Content Cleanup"

### Removed
- **Deleted `soma_run.py`** (221 lines): Legacy master orchestrator, fully replaced by MCP server (`soma_mcp/`) and CLI (`soma_cli/`). Zero importers found in codebase.

### Changed
- **`docs/architecture/scripts.md`**: Marked "Master Pipeline Orchestrator" section as removed, pointing to `soma_mcp/`.
- **`soma_sdk_js/README.md`**: Replaced `soma_run.py` reference with MCP server.

---

## [0.86.0] — 2026-10-01 — "Security Hardening"

### Added
- **Path confinement** (`soma_mcp/security.py` — NEW): `confine_workspace()` rejects workspaces without `.soma/cells/`; `confine_path()` blocks path traversal and symlink escape; `validate_cell_names()` rejects fabricated cell names.
- **Enzyme import allowlist** (`soma_mcp/tools.py`): Frozen allowlist + `_safe_import_enzyme()` prevents rogue `.py` files in `enzymes/` from being loaded.
- **SHA-256 cell integrity manifests** (`soma_mcp/integrity.py` — NEW): Manifest generation and verification during cell cache refresh with graceful degradation.
- **Session token auth** (`soma_mcp/server.py`): Token generated on `initialize`, required for write/execute tools, read tools remain open.
- **Per-tool rate limiting** (`soma_mcp/server.py`): Sliding window rate limits on execution-heavy tools.
- **Permission tiers**: All tools classified into `_READ_TOOLS`, `_WRITE_TOOLS`, `_EXECUTE_TOOLS` frozensets.
- **31 new security test cases** (`tests/test_security.py` — NEW): Path confinement, cell validation, integrity manifests, enzyme allowlist, auth tiers, rate limiting.

### Fixed
- **`tests/test_mcp_verify.py`**: Updated 8 test fixtures to create valid `.soma/cells/` workspaces (required by new confinement checks).

---

## [0.85.1] — 2026-10-01

### Fixed
- **Python 3.9 compatibility** (`enzymes/diagnose_hot_zones.py`): Added `from __future__ import annotations` — `dict | None` union syntax (PEP 604) requires 3.10+ at runtime. (BUG-006)

---

## [0.85.0] — 2026-10-01 — "Antifragile"

### Added
- **Hot Zone Engine** (`soma_sdk/hot_zones.py`): Pure-function module computing file heat and pattern heat from the bug registry. Cells covering historically-buggy files or recurring root cause categories receive a fitness score boost.
- **Configurable thresholds** in `BUG_REGISTRY.json`: `file_heat_threshold` (default 2), `pattern_heat_threshold` (default 3), `max_file_boost` (0.5), `max_pattern_boost` (0.3), `min_outcomes_for_boost` (3).
- 17 new tests in `tests/test_hot_zones.py` — threshold activation, cap enforcement, tag-to-category mapping, workspace integration.

### Changed
- `soma_mcp/jit_engine.py`: `express()` now applies hot zone boost after initial fitness scoring. Multiplicative formula ensures zero-scored cells stay at zero.

### Design
The antifragile loop: Bugs → Registry → Hot zones → Cell boost → Better governance → Fewer bugs → ♻️

---

## [0.84.0] — 2026-10-01 — "Bug Ledger"

### Added
- **Bug Registry** (`docs/project/BUG_REGISTRY.json`): Machine-parseable registry with root cause taxonomy (`path_error`, `schema_drift`, `silent_failure`, `mapping_error`, `dead_code`), severity levels, regression test links, and pattern descriptions. Backfilled with Bugs 1–5.
- **Verification enzyme** (`enzymes/verify_bug_registry.py`): Validates schema, ID uniqueness, root cause categories, and regression test existence.
- **Governance cell**: `trap-unregistered-bug-fix` — gate enforcement requiring BUG_REGISTRY.json entries alongside bug fixes.
- 9 new tests in `tests/test_bug_registry.py` — schema validation, uniqueness, and integration with the real registry.

---

## [0.83.0] — 2026-10-01 — "Fast Path"

### Added
- **JIT Cell Cache** (`soma_mcp/cell_cache.py`): mtime-based in-memory cache eliminates redundant disk I/O when the MCP server calls `express()`. Cells are re-parsed only when files in `.soma/cells/` change.
- 9 new tests in `tests/test_cell_cache.py` — cache hits, invalidation on add/modify/delete, expired cell skipping, schema compatibility.

### Changed
- `soma_mcp/jit_engine.py`: `express()` now uses module-level `CellCache` singleton instead of `load_all_cells()` per invocation.

---

## [0.82.0] — 2026-10-01 — "Consolidation"

### Fixed
- **Bug 4**: `sync.py` no longer clobbers cell scores to 0.0 when a cell has triggers but no tp/fp outcomes. Score is preserved until actual outcome data arrives.
- **Bug 5**: `outcome_engine.py::append_fitness_log()` no longer writes to dead-end `.soma/cells/fitness.jsonl`. Now routes through unified `soma_sdk.telemetry.append_signal()` to `.soma/evidence/signals.jsonl`.
- **Bug 5b**: `cell_selection.sh` lifecycle actions redirected from `.soma/cells/fitness.jsonl` to `.soma/evidence/lifecycle.jsonl`.

### Changed
- **Writer migration**: `fitness_updater.py`, `soma_mcp/tools.py` (soma_report_outcome), and `outcome_engine.py` now write through `soma_sdk.telemetry.append_signal()`.
- **CLI wrapper**: `python3 -m soma_sdk.telemetry` enables bash scripts to write signals through the unified path.
- **ROADMAP.md**: Phase 4 → ✅ Shipped, Phase 4.5 → ✅ Shipped, Phase 4.6 added.
- **README.md**: CI outcome reporter moved from "Planned" to shipped.

### Added
- **Governance cell**: `trap-roadmap-status-drift` — gate enforcement requiring ROADMAP.md updates alongside releases.

---

## [0.81.0] — 2026-10-01 — "Smoke Detector"

### Added
- **CI Outcome Reporter** (Phase 4.5b): `enzymes/ci_outcome_reporter.py` — report-only advisory that matches cells to changed files via `target_paths` globs, computes per-file credit weights (conserved 1/N), and proposes signals (pass→`trigger`, fail→`fp`). Integrated into CI as a GitHub Actions step summary.
- **Unified telemetry writer** (Phase 4.5a): `soma_sdk/telemetry.py` — `append_signal()` with file-locked concurrent writes, schema validation, and canonical evidence log at `.soma/evidence/signals.jsonl`.
- **Governance cell**: `trap-bugfix-without-regression-test` — mechanical enforcement requiring regression tests for every bug fix.
- **TDD test suite**: 4 new test files — `test_telemetry.py` (8), `test_ci_outcome_reporter.py` (10), `test_telemetry_bugfixes.py` (8). Total: 1,518 passed.

### Fixed
- **Bug 1**: `outcome_engine.py` read from wrong path (`.soma/outcomes.jsonl` → `.soma/evidence/outcomes.jsonl`).
- **Bug 2**: `outcome_engine.py` expected wrong schema key (`cells_used` list → also accepts `cell_id` string).
- **Bug 3**: `sync.py` silently ignored agent outcomes (`success`/`failure` now mapped to tp/fp).

---

## [0.80.0] — 2026-10-01 — "Consensus"

### Added
- **Quorum sensing** (Phase 4.1): `evaluate_quorum()` detects when ≥N cells trigger simultaneously on the same changed files, escalates to the highest `minimum_mode`, and logs events to JSONL. Extracted from CLI `main()` for testability.
- **Gate enforcement DSL** (Phase 4.2): `soma_sdk/invariants.py` with `check_import_banned()` (AST-based), `check_file_must_exist()`, `check_invariants()` aggregate, and `evaluate_enforcement()` three-tier ladder.
- **Enforcement ladder**: `advisory` (warn, exit 0) → `mechanical` (block, exit 1) → `gate` (block, exit 1). Unknown tiers default to advisory.
- **TDD test suite**: 3 new test files — `test_quorum.py` (11), `test_gate_invariant_dsl.py` (9), `test_enforcement_ladder.py` (7). Total: 1,492 passed, 7 skipped.

### Fixed
- **Documentation cleanup**: 9 doc files updated — stale version refs, broken post-restructure links, removed claim terminology, outdated phase statuses.
- **Stale release branches**: Deleted 10 local release branches (`release/v0.60` through `release/v0.75`).

### Claims Unlocked
- `claim_quorum_sensing` — Multi-rule consensus for high-confidence decisions
- `claim_gate_enforcement` — Invariant DSL-based gate enforcement in CI

---

## [0.75.0] — 2026-10-01 — "Credit Where Due"

### Added
- **Credit assignment** (Phase 3.1): `prob_round()` probabilistic rounding, `compute_credit_weights()` per-file scope narrowing with credit conservation. Signal provenance tracked in JSONL via `credit_weight` and `signal_method` fields.
- **Mutation operators** (Phase 3.2): Comparison swap (`<`↔`>`, `<=`↔`>=`, `==`↔`!=`), boolean swap (`and`↔`or`), statement deletion (stmt→pass), return value mutation (`return X`→`return None`).
- **TDD test suite**: 8 new behavioral test files — `test_credit_assignment.py` (14), `test_outcome_engine.py` (18), `test_jit_engine_behavioral.py` (22), `test_error_handling.py` (13), `test_mcp_tools_contract.py` (12), `test_tournament_integration.py` (8), `test_crossover_structured.py` (12), `test_mutation_tester_upgraded.py` (10).

### Fixed
- **Crossover target_paths** (Phase 3.6): `cell_crossover.py` now merges `target_paths` as deduplicated union of both parents. Previously omitted entirely, making child cells unable to match any files.
- **Crossover tags**: Tags now merged as union instead of reset to empty list.

### Changed
- `compute_fitness_signals()` accepts optional `changed_files` kwarg for credit weighting.
- `update_cell_fitness()` uses `prob_round(credit_weight)` for tp/fp counter updates.
- `append_fitness_log()` includes `credit_weight` and `signal_method` provenance.
- Claim registry: `claim_credit_assignment`, `claim_structured_crossover`, `claim_tournament_selection` unlocked.

### Metrics
- Test suite: **1465 passed**, 7 skipped, 0 failed (up from 1359 in v0.74)

---

## [0.71.0] — 2026-10-01 — "Branch Sync"

### Fixed
- **Gitflow step 7**: Release checklist now merges **main** back to develop (not the release branch). Previous workflow skipped main's PR merge commit, causing main and develop to diverge over 5 releases.

---

## [0.74.0] — 2026-10-01 — "Foundation"

### Added
- `soma_sdk/errors.py`: Complete error hierarchy (SomaError → CellParseError, CellNotFoundError, CellPathTraversalError, FitnessError)
- `soma_sdk/scoring.py`: Wilson-bounded fitness scoring (bayesian_posterior, laplace_score, _wilson_interval)
- `soma_sdk/cells.py`: Canonical cell parser (parse_cell_file, write_cell_frontmatter, load_cell, _sanitize_cell_id)
- `tests/test_bayesian_correctness.py`: 17 mathematical ground truth tests
- `tests/test_sdk_behavioral.py`: 21 SDK public API tests
- `tests/test_escaped_defects.py`: 12 antifragile behavior tests
- `tests/test_cell_deps_behavioral.py`: 5 co-trigger detection tests
- `tests/test_integration_lifecycle.py`: 8 end-to-end lifecycle tests
- `tests/test_threshold_recalibration.py`: 12 boundary value tests

### Changed
- Migrated 27 enzyme/CLI files from inline YAML parsing to canonical `parse_cell_file()`
- `CellFitness.bayesian()` upgraded from Wald approximation to Wilson score interval
- `Cell.is_extinct` / `Cell.is_promotable` now use `laplace_score()` import
- `enzymes/bayesian_score.py` converted to thin wrapper re-exporting from `soma_sdk.scoring`
- `enzymes/cell_deps.py` added `--workspace` argument for testability

### Metrics
- Suite: 1359 passed, 5 skipped, 0 failed
- Claims: 8 unlocked, 5 locked, 7 removed (20/20 verified)
- Net code change: +1606/-353 lines across 41 files

---

## [0.73.0] — 2026-10-01 — "Stop the Bleeding"

### Added
- `docs/CLAIM_REGISTRY.json`: Machine-readable claim tracking (locked/unlocked/removed)
- `enzymes/verify_readme_claims.py`: CI gate verifying README claims against tests
- `tests/test_static_invariants.py::test_version_is_single_sourced`: Version sync invariant
- `docs/ROADMAP.md`: Future features moved from README
- `docs/RELEASE_WORKFLOW.md`: Codified gitflow release procedure

### Changed
- README stripped to earned claims only — removed 7 unverified claims
- Fixed `exit 1` bug in pre-commit hook generation (cell_enforce.py)
- Version synced across pyproject.toml and VERSION file

### Removed
- Unearned README claims: evolutionary computation, gate enforcement, < 1.0% waste rate, deterministic verification, inflated test count

---

## [0.70.0] — 2026-10-01 — "Genesis"

### Added
- **`soma genesis` command**: Scans codebase architecture with 8 language-agnostic detectors and generates governance cell candidates.
  - Detectors: module boundaries, config stores, shared state, API surfaces, data pipelines, state machines, test boundaries, dependency walls
  - All generated cells start as vacuoles with `proposed_type` frontmatter
  - Generates `docs/organelles.md` architecture map
  - Flags: `--dry-run`, `--json`, `--force`, `--yes`

### Security
- Path traversal fix: import regex rejects relative imports; `is_relative_to()` containment check
- Memory exhaustion fix: streaming `read(limit)` replaces `read_text()[:limit]`
- Symlink guard: `is_symlink()` check before all file writes

### Fixed
- Dry-run no longer creates `.soma/cells/vacuoles/` directory
- `docs/organelles.md` respects `--dry-run`, `--force`, and symlink guards
- `input()` wrapped in `try/except` for headless environments
- `rglob` replaced with filtered `_iter_source_files` (no `.git`/`.venv` traversal)
- Frontmatter/markdown sanitization prevents injection via crafted identifiers
- 80% I/O reduction via single-pass source cache across 5 detectors

---

## [0.62.2] — 2026-10-01 — "Documentation Sweep"

### Fixed
- **README.md**: Version badge 0.60.0 → 0.62.2, test badge 1162 → 1228, script count 58 → 57. Added `soma sync` to CLI table. Added PyPI install to Quick Start. Added Python 3.9+ label.
- **QUICKSTART.md**: Added all CLI commands (sync, checkpoint, oracle, promote, demote, doctor, verify). Fixed repo URL. Updated PyPI status from "coming soon" to available. Added PEP 668 hint. Added Kiro platform.
- **SCRIPTS.md**: Full recount and rewrite — 39 → 57 scripts cataloged.
- **CONTRIBUTING.md**: Added Python 3.9 compat requirement, CI matrix info, test command, `from __future__ import annotations` requirement.
- **pyproject.toml**: Added Python 3.9/3.10/3.11/3.12 classifiers.

---

## [0.62.1] — 2026-10-01 — Patch

### Fixed
- **`make install`**: Handle PEP 668 externally-managed Python environments (`--user --break-system-packages` fallback chain).
- **`make install`**: Print PATH hint when `~/.local/bin` is not on PATH.
- **`install.sh`**: Fix skill install crash when a previously-installed file/symlink is being replaced by a directory (`cp: cannot overwrite non-directory`).

---

## [0.62.0] — 2026-10-01 — "Evidence Pipeline"

### Added
- **`soma sync` command**: Reconciles `.soma/evidence/fitness.jsonl` and `outcomes.jsonl` with cell frontmatter. Supports `--dry-run` and `--json` flags.

### Fixed
- **Fitness pipeline disconnect**: `fitness_updater.py` wrote trigger events to JSONL but never updated cell frontmatter, causing `immune_grade.py` and `cell_fitness.py` to report zero fitness despite evidence existing.
- **`soma checkpoint`** now auto-syncs evidence → frontmatter before running quality checks, so the report card is always fresh.
- **`fitness_updater.py`** now auto-syncs frontmatter after writing JSONL, closing the pipeline gap.

### Changed
- Bootstrapped fitness evidence from two Supercell session transcripts (170+ trigger events, 42 cells scored).

---

## [0.61.0] — 2026-10-01 — "Python 3.9 Compatibility"

### Fixed
- **Python 3.9 runtime crash**: 6 files in `immune_system/verification/` used PEP 604 union syntax (`X | None`) in function signatures without `from __future__ import annotations`, causing `TypeError: unsupported operand type(s) for |` on Python 3.9. Added the future import to all affected files.

### Changed
- **CI matrix**: Added Python 3.9 to test matrix (Ubuntu, macOS, Windows).
- **CI publish**: Auto-publish to PyPI on GitHub release creation via `PYPI_API_TOKEN` secret.

---

## [0.60.0] — 2026-09-30 — "Two-Layer Verification & Cell Lifecycle"

### Added
- **Two-Layer Verification System** (`immune_system/verification/`):
  - **Layer 1 (Deterministic AST Tools)**: Objective, ungameable evidence collection via `persistence_checker`, `call_graph`, `mutation_tester`, `branch_coverage`, and `import_guard`. Orchestrated via `runner.py` producing boolean `ToolEvidence`.
  - **Layer 2 (Adversarial Information-Partitioned Agents)**: Multi-agent verification leveraging information asymmetry between Spec Agent (sees task specification) and Code Agent (sees implementation/tests).
  - **Deterministic Arbiter**: Set-algebra adjudication over a fixed 14-category risk taxonomy, issuing `SHIP`, `BLOCK`, or `REVISE` verdicts with zero LLM in the loop.
  - **Transcript Verifier**: Post-hoc validation of self-reported agent claims against JSONL session logs.
- **Unified CLI Suite** (`soma`): 9 subcommands — `init`, `status`, `report`, `doctor`, `verify`, `checkpoint`, `oracle`, `promote`, `demote`.
  - `soma verify`: Full two-layer verification with `--layer1-only` support.
  - `soma checkpoint`: Fast deterministic quality gate with `--pre-commit` hook integration.
  - `soma oracle`: Cell health classification (healthy, noisy, expired, unobserved).
  - `soma promote` / `soma demote`: Automated lifecycle evaluation with `--dry-run` and `--json`.
  - `soma init`: Enhanced with `--rules {minimal|standard|full}`, MCP config, and pre-commit hook.
- **Cell Lifecycle Engine** (`immune_system/verification/lifecycle.py`):
  - Deterministic state machine: Vacuole → Wall → Genome (and demotions).
  - Grounded in JSONL evidence ledgers, not YAML frontmatter.
  - Promotion: triggers ≥ 20, tp_rate > 0.85, age > 30 days.
  - Demotion: fp_rate > 0.5 or dormancy ≥ 90 days.
- **MCP Tools**: Added `soma_verify_changes` and `soma_checkpoint` for zero-API-key in-agent verification.
- **Supercell Review Intensity**: New highest review tier (above Tempest) — adversarial Prosecutor/Defender pairs per prong, iterative fix-revalidate with no deferrals until clean ship.
- **Quality Gate Checks**: Assertion density, bare `pass` detection, import verification, test sanity.
- **Doc Consistency Tests**: 6 tests verifying README ↔ SKILL.md intensity level consistency.
- **Test Suite**: 1184 tests with shared fixtures (`tests/helpers_cell.py`).
- **Governance Cells**: 44 total — 20 walls, 2 plasmodesmata, 3 membranes, 3 chloroplasts, 16 vacuoles.
  - NEW: `trap-stdout-protocol-corruption` (wall) — hooks emitting to stdout after JSON.
  - NEW: `trap-tautological-test` (wall) — tests that verify nothing.
  - NEW: `contract-sdk-feature-parity` (plasmodesmata) — Python/JS SDK method parity.
- **SDK Parity**: Added `entropy()` and `adversarial()` to Python SDK (matching JS SDK).

### Changed
- Package discovery updated to include `immune_system*`.
- Pre-commit hook auto-installed by `soma init`.
- Architecture diagram widened for Supercell intensity level.
- **SDK `is_extinct`/`is_promotable`**: Now use Bayesian scoring aligned with `cell_promote.py` standards (score > 0.85, triggers ≥ 20) instead of legacy `raw_score`.
- **DRY**: `outcome_engine.py` imports canonical `resolve_workspace()` from `soma_resolve.py`. Intentional duplication in `soma_mcp/` documented (zero-dep wall).
- **Type Annotations**: Added to all public APIs in `governance.py`, `cells.py`, `jit_engine.py`, `bayesian_score.py`.
- **Test Fixtures**: Deduplicated `soma_workspace`, `_write_cell`, `_make_cell` into shared `helpers_cell.py`.
- **Hardcoded Paths**: `safety_gate.sh` and `immune_init.sh` now use `${SOMA_LOGS_DIR}` / `${SOMA_CONF}` env vars with fallbacks.
- **Makefile validate**: Now covers `soma_cli/` and `immune_system/` in addition to `enzymes/`, `soma_mcp/`, `soma_sdk/`.
- **Docs**: Fixed ABSTRACT contribution count (3→4), step count (12,000→11,900), removed duplicate PHYLOGENY section, added Phase 16/18/19/20/21 stubs.

### Fixed
- **Evidence Pipeline**: 4 critical bugs fixed (schema mismatch, dead detectors, missing FPSR extraction).
- 2 new evidence detectors: `test-before-implementation`, `no-hardcoded-paths`.
- **Security (Supercell S1)**: Code injection via `.format()` in `branch_coverage.py` — paths now escaped with `repr()`.
- **Security (Supercell S2)**: Path traversal via `--files` — containment check added to `verify.py`.
- **Correctness (Supercell C1)**: Outcomes path/schema desync between MCP and lifecycle engine.
- **Correctness (Supercell C2)**: JSONL crash on non-dict lines in lifecycle evidence loading.
- **Correctness (Supercell C3)**: Lifecycle threshold bugs (boundary values, min sample size, dormancy).
- **Bug**: 5 pre-existing `test_status.py` failures from real filesystem leak through platform auto-detection.
- **Robustness (Phase 2)**: 9 fixes across verification tools:
  - `branch_coverage.py`: Parse `missing_branches`, add subprocess timeout (120s), UTF-8 encoding.
  - `transcript_verifier.py`: FileNotFoundError guard, tool_calls-based write detection (no more content-string false positives), collection error sentinel `(-1,-1)`, multi-run false positive fix.
  - `immune_init.sh`: JSON protocol corruption — 4 echo statements redirected to stderr.
  - `escalation_sentinel.sh`: Frontmatter `target_paths` parsing replaces fragile hypothesis regex.
- **Layer 2 Fail-Open (Phase 3)**: Empty spec agent predictions now produce `Verdict.BLOCK` instead of silently passing through to `SHIP`.

---

## [0.60.0-rc] — 2026-09-30 — "Wire Verification & Cell Lifecycle RC"

### Added
- **Gitflow**: Standardized branch lifecycle with session pattern rules.
- **Content Coherence Tests**: Automated doc ↔ code consistency validation.
- **MCP Self-Install**: `soma init` auto-configures MCP server in agent config.
- `soma init --rules {minimal|standard|full}`: Tiered rule installation.
- **Wire Verification System (Phase 2)**: End-to-end evidence pipeline validation.
- **Pre-Commit Hook**: Deterministic quality gate via `soma checkpoint --pre-commit`.
- **Cell Lifecycle Engine**: Oracle, promote, and demote commands with deterministic state machine.
- **Supercell Review Process**: Highest review tier — adversarial Prosecutor/Defender pairs per prong.
- **Checkpoint Extraction**: Deterministic quality gate checks (assertion density, bare `pass`, imports).
- **Evidence Pipeline Fix**: 4 critical bugs (schema mismatch, dead detectors, missing FPSR extraction).

### Changed
- 5 review cycles completed during RC hardening.

---

## [0.52.0] — 2026-09-30 — "Gitflow & Hardening"

### Added
- **Gitflow**: Standardized branch lifecycle in `docs/GITFLOW.md`.
- **Gitflow Review Gate**: Rule enforcing branch naming and PR-based landing.

### Fixed
- All 15 findings from v0.52 production audit.
- 4 must-fix findings from audit round 2.
- Hardcoded absolute paths in documentation.

---

## [0.51.0] — 2026-09-30 — "Soma CLI & Distribution"

### Added
- **Soma CLI** (`soma_cli/`): `soma init`, `soma status`, `soma report`.
- Starter pack manifests and templates.
- CLI entrypoints in `pyproject.toml`.

### Fixed
- 10 audit findings across argument validation, path resolution, error reporting.

---

## [0.50.0] — 2026-09-29 — "Incentive-Compatible Governance"

> Tagged release — Version jump from v0.22.0 reflects Phases 23–50: TTC Oracles, JIT context, interoception, and the evidence pipeline.

### Added
- **Evidence Pipeline**: `evidence_collector.py`, `fitness_updater.py`, `cell_expiry.py`, `oracle_checkpoint.py`, `post_session_hook.sh`.
- **Mechanism Design Framework** (`docs/MECHANISM_DESIGN.md`).
- **Fitness Updater**: Automated fitness scoring from evidence ledgers.
- **Cell Expiry**: Time- and session-based cell lifecycle enforcement.
- **Oracle Checkpoint**: Cell health classification with evidence grounding.
- **Trap Cells**: `trap-fix-one-not-all`, `trap-unverified-delegation`, `trap-local-green-ci-red`.
- README trustworthiness rewrite.

### Changed
- Fitness ledger decoupled from frontmatter → append-only JSONL.
- `pyyaml` accepted as mandatory dependency.
- Idle overhead stabilized at ~3,800 tokens/turn (down 8.6%).
- 6 audit rounds completed.

### Fixed
- Tautological assertions and brittle source-code grepping remediated (515+ tests).
- Critical fitness inflation bug.
- CI execution hang from hook test sourcing.

---

## [0.31.0] — 2026-09-29 — "Human Insight Pipeline"

### Added
- **Human Insight Pipeline**: Structured pathway for human-observed defects to influence cell fitness.
- **TDD Protocol** (`genome/.oracles/tdd-protocol.md`): Test-driven development with sequential phase gates.
- **Mechanism Design Framework**: Incentive-compatible governance architecture documentation.
- **Evidence Collector**: Automated correlation of rule compliance with session outcomes.

---

## [0.30.0] — 2026-09-29 — "Two-Layer Verification Foundation"

### Added
- **Two-Layer Verification Framework**: Deterministic AST tools (Layer 1) + adversarial information-partitioned agents (Layer 2).
- **Import Guard** (`import_guard`): Layer 1 tool detecting unguarded third-party imports that crash CI.
- **Keyring Secret Storage**: Secure credential management for inference providers.

---

## [0.25.0] — 2026-09-28 — "TTC & Biological Docs"

### Added
- **TTC/Tempest MCP Tooling**: Test-Time Compute oracle integration with MCP server.
- **Last Gasp Auto-Escalator**: Pre-failure evaluation mechanism that auto-escalates before token budget is consumed.
- **Biological Documentation Suite**: PHYLOGENY.md, MECHANISM_DESIGN.md, and naming unification docs.

### Fixed
- 15 bug fixes across the governance pipeline.

---

## [0.22.0] — 2026-09-28 — "Soma Rebirth"

### Breaking Changes
- **Project renamed**: Prism AI Steering → **Soma**
- **Repository**: `prism-ai-steering` → `soma`
- **SDK packages**: `prism-steering` → `soma-steering` (Python + npm)
- **Config**: `steering.conf` → `soma.conf`
- **Directory**: `.prism/` → `.soma/` (auto-migrated on install)

### Added — Biological Naming Unification
- `rules/` → `genome/` — Rules are now **Genes** in the organism's **Genome**
- `skills/` → `organs/` — Skills are now **Organs** (complex multi-cell structures)
- `scripts/` → `enzymes/` — Scripts are now **Enzymes** (catalytic reactions)
- `governance/` → `immune_system/` — Governance is the **Immune System**
- `EVOLUTION.md` → `PHYLOGENY.md` — Project history as evolutionary tree
- Half-Life → Telomere Shortening — Biological aging mechanism
- `governance_*.py` → `immune_*.py` — All governance scripts renamed
- Auto-migration in `install.sh`: detects `.prism/` and renames to `.soma/`

### Added — Host-Agent Delegation (Provider Abstraction)
- `enzymes/inference_provider.py` — Multi-provider inference abstraction
- Supports Gemini, Anthropic, OpenAI, and prompt-only mode
- `--provider` flag on `cell_create_nl.py`: `auto|gemini|anthropic|openai|prompt-only`
- `SOMA_INFERENCE_PROVIDER` config key in `soma.conf`
- No API key required when running inside an AI agent via MCP

### Added — MCP Stdio Server
- `soma_mcp/` — Model Context Protocol server for host-agent delegation
- Tools: `soma_create_cell`, `soma_scan`, `soma_grade`, `soma_coverage`, `soma_fitness`, `soma_list_cells`
- `soma_create_cell` delegates LLM reasoning to the host agent — zero API key needed
- Runnable as `python -m soma_mcp` or configured in any agent's MCP settings
- Works with Gemini Antigravity, Claude Code, Cursor, and any MCP-compatible agent

## [0.21.1] — 2026-09-28

### Added
- `cell_enforce.py`: Auto-generates enforcement artifacts for promoted cells
- Mechanical cells generate pre-commit hook checks in `.soma/enforcement/`
- Gate cells generate runtime assertion classes in `.soma/enforcement/`
- `enforcement_artifact` field links cells to their generated artifacts
- Coverage map now shows enforcement tier per directory
- Pre-commit hook runs mechanical checks from `.soma/enforcement/`
- Auto-trigger enforcement generation on tier promotion
- Script count: 38 → 39

## [0.21.0] — 2026-09-28

### Added
- Tiered enforcement system: cells declare `advisory`, `mechanical`, or `gate` enforcement level
- `cell_escaped_defects.py`: Independent defect tracking from CI/tests/crashes (breaks self-evaluation loop)
- Enhanced fitness formula: `bayesian_mean × (1 - escaped_defect_rate) × tier_weight`
- Enforcement tier promotion/demotion lifecycle in `cell_promote.py --tier-check`
- Tier distribution in governance report card
- Backfilled all existing cells with `enforcement: advisory`
- Script count: 37 → 38

## [0.20.0] — 2026-09-27

### Added
- Natural language cell creation (`cell_create_nl.py`) via Gemini API with multi-source API key resolution
- Python SDK (`soma_sdk/`): `pip install soma-steering` for programmatic governance access
- Counterfactual replay (`--counterfactual --cell <name>`): ROI estimation against historical commits
- Adversarial cell testing (`cell_adversarial.py`): probe cells for bypass vulnerabilities
- Governance entropy rate (`immune_entropy.py`): fossilization detection via Shannon entropy
- `pyproject.toml` for PyPI packaging
- Script count: 34 → 37

## [0.19.1] — 2026-09-27

### Fixed
- `cell_create.sh`: Added `--minimum-mode` and `--id` flags
- `cell_coverage.py`: Excludes .soma/, vendor/, .git/ from coverage counts
- `cell_fitness.py`: Fixed UnboundLocalError in --bayesian mode

### Added
- `install/hooks/pre-commit`: Git pre-commit hook for automatic cell scanning
- `cell_deps.py`: Cell dependency graph with Mermaid output
- `immune_grade.py`: Single-grade governance report card
- Script count: 32 → 34

## [0.19.0] — 2026-09-27

### Added
- Wall extinction immunity (walls immune to apoptosis, get APOPTOSIS_WARNING instead)
- Specificity penalty (anti-Goodhart: penalize cells triggering >80% of sessions)
- Bayesian cell fitness (`--bayesian`): Beta-Binomial posterior with Jeffrey's prior
- Antifragile fitness bonus (+5% per survived Tempest/Maelstrom review)
- Signal-to-noise ratio (SNR dB) per cell in fitness output
- `cell_quorum.py`: Detect systemic issues when ≥3 cells trigger simultaneously
- `cell_coverage.py`: Visualize governance blind spots across codebase
- `immune_replay.py`: Retrospective "would cells have caught this?" analysis
- `immune_trends.py`: Cross-session trend dashboard with Shannon diversity index
- Dormant spore archive (pruned cells saved to `.spores.jsonl`, reactivated on match)
- `cell_genesis_stochastic.py`: Random template injection every N sessions
- Mulch→Cell pipeline: Tempest findings auto-create vacuole cells
- Script count: 27 → 32

## [0.18.1] — 2026-09-27

### Fixed
- Wire `escalation_sentinel.sh` into `immune_init.sh` (was orphaned)
- Escalation sentinel now scans walls AND membranes for `minimum_mode`
- Thorns terminology disambiguation in README

### Added
- `cell_scan.py`: Automated diff→cell triggering via git diff and target_paths
- `target_paths` field in cell YAML schema
- `DEFAULT_REVIEW_MODE` and `MINIMUM_REVIEW_MODE` in soma.conf
- Session fitness dashboard in session_close.sh

## [0.18.0] — 2026-09-27

### Added
- Centralized workspace resolution (`soma_resolve.py`) — CWD-first, vendor-safe
- Automated evolutionary loop in `session_close.sh`
- Apoptotic fast-kill in `cell_fitness.py` (FP > 2×TP)
- Homeostatic governance intensity in `immune_init.sh`

### Changed
- All scripts use `soma_resolve.py` instead of inline resolution
- Script count: 25 → 26

## [0.17.1] — 2026-09-27

### Added
- Cell lineage tracking (`lineage` block in YAML) — phylogenetic tree support
- Per-type telomere shortening configuration (`CELL_TELOMERE_WALL`, etc.)
- Effector→Memory auto-transition via `decay_to` field
- Benchmark protocol (`docs/BENCHMARK.md`)

## [0.17.0] — 2026-09-27

### Added
- GA crossover operator (`cell_crossover.py`) — merges complementary cell hypotheses
- Tournament selection (`cell_tournament.py`) — diversity-preserving cell selection
- Cell metamorphosis (`cell_metamorphose.py`) — vacuole → wall → rule maturity paths
- Horizontal gene transfer (`cell_transfer.sh`) — cross-project cell sharing with fitness reset
- Fitness landscape visualization (`fitness_landscape.py`) — ASCII governance dashboard
- Confidence telomere shortening decay in `cell_fitness.py` — stale cells fade naturally
- Effector/memory cell flags in `cell_create.sh` — incident response patterns
- Incident response templates (`templates/incident-response/`)
- `CELL_TELOMERE_DAYS` configuration in `soma.conf.example`

### Changed
- Script count: 20 → 25
- `cell_signal.sh` now records `last_trigger_date` for telomere shortening calculation

## [0.16.0] — 2026-09-27

### Added
- External fitness signal API (`cell_signal.sh`) — any system (CI/CD, monitoring, game results) can feed outcomes to cells
- Programmatic cell creation (`cell_create.sh`) — create cells from automated systems
- Cell demotion (`cell_demote.py`) — reverse promotion when cells cause issues in new contexts
- Cell templates by domain (`templates/`) — RL training, web backend, infrastructure, data pipeline
- 14 domain-specific cell templates with self-pruning (`expiry_sessions: 5`)
- Template auto-detection in Genesis Stage 5 based on project dependencies

### Changed
- Script count: 18 → 20

## [0.15.1] — 2026-09-27

### Added
- Liveness sentinel script (`liveness_sentinel.sh`) for subagent health monitoring
- Enhanced Genesis Lichen phase with magic number / hardcoded coordinate detection
- Enhanced Plasmodesmata detection with explicit patterns (pip install -e, shared DBs, protobuf imports)

## [0.15.0] — 2026-09-27

### Added
- Team topology: `TEAM_REPO` and `ORG_REPO` configuration for multi-developer governance convergence
- `team_sync.sh` for push/pull/status of shared cells and metrics
- Clean uninstaller (`uninstall.sh`) with backup/restore and manifest tracking
- Install manifest (`~/.soma/manifest.json`) for safe uninstall
- Backup-on-install: archives existing config before overwriting
- Peer-reviewed research abstract (`ABSTRACT.md`) with 5-reviewer record (`REVIEWS.md`)
- GitHub Actions CI workflow
- `CONTRIBUTING.md` with CLA language
- `VERSION` file and semantic versioning

### Changed
- Deprecated legacy per-platform installers in favor of unified `install.sh`
- Script count: 15 → 17

## [0.14.0] — 2026-09-27

### Added
- Cross-repo fitness aggregation (`cell_fitness.py --cross-repo`)
- Adaptive cell refinement (`cell_adapt.py`)
- Speciation/promotion path (`cell_promote.py`) — local cells graduate to global rules
- Plasmodesmata cell type for cross-repo connections

## [0.13.0] — 2026-09-27

### Added
- Cytogenesis infrastructure (`.soma/cells/`)
- Cell fitness scoring (`cell_fitness.py`)
- Cell selection lifecycle (`cell_selection.sh`)
- Four cell types: Vacuole, Chloroplast, Cell Wall, Membrane
- Genesis Stage 5: automated cell generation

## [0.12.0] — 2026-09-27

### Added
- Calibrated tokenizer (1.35 ratio, validated against Gemini API)
- Apache 2.0 license, NOTICE file, privacy statement
- Privacy-safe metrics via `METRICS_REPO` configuration
- Rule compression optimization

### Changed
- Token census now uses empirical calibration instead of estimates

## [0.11.0] — 2026-09-27

### Added
- Cross-platform validation (bash + PowerShell)
- Genesis onboarding skill (5-stage codebase reconnaissance)
- 66-session expanded dataset analysis
- Unified installer (`install.sh`) replacing per-platform scripts

### Changed
- Renamed project from internal naming to Soma

## [0.10.0] — 2026-09-26

### Added
- Tempest cross-conversation analysis
- Subagent nesting (E11)
- Adaptive review orchestrator
- Escalation sentinel script

## [0.9.0] — 2026-09-26

### Added
- Maelstrom academic integration (Refutation Gate, Boundary Verification, Orthogonal Personas)
- FPSR metric (First-Pass Success Rate)

## [0.1.0–0.8.0] — 2026-09-26

### Added
- Initial governance rules (Providence, cost optimization, subagent delegation)
- Review protocol (Breeze through Tempest, Spores through Mulch)
- Testing and git workflow rules
- Lifecycle hooks (governance_init, safety_gate, session_close)
- Experiment framework (E1–E22)
- Metrics infrastructure (token census, metrics snapshot)
