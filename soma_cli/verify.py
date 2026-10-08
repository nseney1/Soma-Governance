"""soma verify — run verification on changed files.

Supports Layer 1 (deterministic tools) and Layer 2 (adversarial LLM pair).
Maps Verdict outcomes to exit codes: SHIP=0, BLOCK=1, REVISE=1.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Any


# Lazy imports to keep CLI responsive
def _get_verification():
    from soma_core.verification import runner, Verdict
    return runner, Verdict


# ── Exit Code Mapping ─────────────────────────────────────────────────

def _lazy_verdict():
    from soma_core.verification import Verdict
    return Verdict


class _VerdictExitCodesProxy(dict):
    """Lazy dict proxy for VERDICT_EXIT_CODES."""
    _loaded = False

    def _ensure(self):
        if not self._loaded:
            V = _lazy_verdict()
            super().__setitem__(V.SHIP, 0)
            super().__setitem__(V.BLOCK, 1)
            super().__setitem__(V.REVISE, 1)
            self._loaded = True

    def __getitem__(self, key):
        self._ensure()
        return super().__getitem__(key)

    def __contains__(self, key):
        self._ensure()
        return super().__contains__(key)

    def __len__(self):
        self._ensure()
        return super().__len__()

    def __iter__(self):
        self._ensure()
        return super().__iter__()


VERDICT_EXIT_CODES = _VerdictExitCodesProxy()


def verdict_to_exit_code(verdict) -> int:
    """Map a Verdict enum to an exit code."""
    VERDICT_EXIT_CODES._ensure()
    return VERDICT_EXIT_CODES[verdict]


# ── Target File Resolution ────────────────────────────────────────────

def resolve_target_files(args: argparse.Namespace) -> list[str]:
    """Resolve target files from --files flag or git staged/changed files."""
    if args.files:
        repo_root = os.path.realpath(
            (str(args.ws.root) if getattr(args, "ws", None) is not None else None)
            or getattr(args, 'workspace', None)
            or getattr(args, 'repo_root', None)
            or getattr(args, '_project_root', None)
            or getattr(args, '_root', None)
            or os.getcwd()
        )
        safe_files = []
        for f in args.files:
            resolved = os.path.realpath(os.path.join(repo_root, f))
            if not resolved.startswith(repo_root + os.sep) and resolved != repo_root:
                from soma_cli import sanitize_display
                print(f"Warning: skipping out-of-tree file: {sanitize_display(f)}", file=sys.stderr)
                continue
            safe_files.append(f)
        if not safe_files:
            print("Error: all specified files are outside the repository", file=sys.stderr)
        return safe_files

    # Default: query git for staged/changed files
    git_cwd = (
        str(args.ws.root)
        if getattr(args, 'ws', None) is not None
        else (
            getattr(args, 'workspace', None)
            or getattr(args, 'repo_root', None)
            or getattr(args, '_project_root', None)
            or getattr(args, '_root', None)
            or os.getcwd()
        )
    )
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", "HEAD"],
            capture_output=True, text=True, timeout=10, cwd=git_cwd,
        )
        files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except (subprocess.SubprocessError, FileNotFoundError):
        files = []

    # Also check staged files
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True, text=True, timeout=10, cwd=git_cwd,
        )
        staged = [f.strip() for f in result.stdout.splitlines() if f.strip()]
        files = list(dict.fromkeys(files + staged))  # dedupe, preserve order
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    # If working tree is clean (all committed), check branch diff against base branch or HEAD~1
    if not files:
        base_candidates = []
        if os.environ.get("GITHUB_BASE_REF"):
            base_ref = os.environ["GITHUB_BASE_REF"]
            base_candidates.extend([f"origin/{base_ref}...HEAD", f"{base_ref}...HEAD"])
        base_candidates.extend(["origin/main...HEAD", "main...HEAD", "origin/develop...HEAD", "develop...HEAD", "HEAD~1"])

        for ref in base_candidates:
            try:
                res = subprocess.run(
                    ["git", "diff", "--name-only", "--diff-filter=ACMR", ref],
                    capture_output=True, text=True, timeout=10, cwd=git_cwd,
                )
                if res.returncode == 0:
                    cand_files = [f.strip() for f in res.stdout.splitlines() if f.strip()]
                    if cand_files:
                        files = cand_files
                        break
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

    return files


def discover_test_evidence(target_files: list[str], repo_root: str) -> tuple[list[str], str]:
    """Discover matching test files, parse test names via AST, and execute tests.

    Returns (test_names, test_results).
    """
    import ast
    all_test_names: list[str] = []
    discovered_test_files: list[str] = []

    for tf in target_files:
        full_path = os.path.join(repo_root, tf) if not os.path.isabs(tf) else tf
        basename = os.path.basename(full_path)
        if basename.startswith("test_") and basename.endswith(".py"):
            if os.path.isfile(full_path) and full_path not in discovered_test_files:
                discovered_test_files.append(full_path)
            continue

        stem = os.path.splitext(basename)[0]
        # Candidate test file locations
        candidates = [
            os.path.join(repo_root, os.path.dirname(tf), f"test_{stem}.py"),
            os.path.join(repo_root, "tests", f"test_{stem}.py"),
            os.path.join(repo_root, f"test_{stem}.py"),
        ]
        # Also check tests/ directory matching prefix
        tests_dir = os.path.join(repo_root, "tests")
        if os.path.isdir(tests_dir):
            try:
                for fname in os.listdir(tests_dir):
                    if fname.startswith(f"test_{stem}") and fname.endswith(".py"):
                        candidates.append(os.path.join(tests_dir, fname))
            except OSError:
                pass

        for cand in candidates:
            if os.path.isfile(cand) and cand not in discovered_test_files:
                discovered_test_files.append(cand)

    for test_file in discovered_test_files:
        try:
            with open(test_file, "r", encoding="utf-8", errors="ignore") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("test_") and node.name not in all_test_names:
                        all_test_names.append(node.name)
        except Exception:
            continue

    if not discovered_test_files:
        return ([], "")

    from soma_core.verification.test_runner import resolve_pytest_cmd, NoTestRunnerFoundError

    pytest_cmd = resolve_pytest_cmd(workspace=repo_root)
    if not pytest_cmd:
        raise NoTestRunnerFoundError(
            f"Found {len(discovered_test_files)} associated test file(s) for changed targets, "
            "but no pytest runner was discovered on PATH or in virtual environment."
        )

    # Run tests with resolved pytest command
    run_outputs = []
    for test_file in discovered_test_files:
        try:
            res = subprocess.run(
                pytest_cmd + [test_file, "-q", "--tb=no"],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=repo_root,
            )
            out = (res.stdout or "") + (res.stderr or "")
            run_outputs.append(f"[{os.path.basename(test_file)}]\n{out.strip()}")
        except Exception as e:
            run_outputs.append(f"[{os.path.basename(test_file)}] error: {e}")

    return (all_test_names, "\n\n".join(run_outputs))


# ── Plan & Provider Resolution ────────────────────────────────────────

def resolve_task_plan(args: argparse.Namespace, repo_root: str) -> str | None:
    """Resolve task plan from --plan, --plan-file, or standard plan conventions."""
    if getattr(args, 'plan', None):
        return args.plan.strip()

    plan_file = getattr(args, 'plan_file', None)
    if plan_file:
        plan_path = plan_file if os.path.isabs(plan_file) else os.path.join(repo_root, plan_file)
        if not os.path.isfile(plan_path):
            print(f"Error: plan file not found: {plan_file}", file=sys.stderr)
            return None
        try:
            with open(plan_path, encoding='utf-8') as f:
                return f.read().strip()
        except OSError as e:
            print(f"Error: could not read plan file {plan_file}: {e}", file=sys.stderr)
            return None

    # Check conventional plan files
    for default_name in ("docs/plan.md", ".soma/plan.md", "PLAN.md"):
        cand = os.path.join(repo_root, default_name)
        if os.path.isfile(cand):
            try:
                with open(cand, encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        return content
            except OSError:
                pass

    return None


def is_usable_provider(provider) -> bool:
    """Return True if provider can perform programmatic generation."""
    if provider is None:
        return False
    try:
        from soma_core.inference_provider import PromptOnlyProvider
        if isinstance(provider, PromptOnlyProvider):
            return False
    except ImportError:
        pass
    return hasattr(provider, 'generate') or callable(provider)


def resolve_cli_provider(args: argparse.Namespace, repo_root: str):
    """Resolve configured inference provider or return None if none available."""
    try:
        from soma_core.inference_provider import resolve_key, resolve_provider, PromptOnlyProvider
    except ImportError:
        return None

    explicit_provider = getattr(args, 'provider', None)
    if not explicit_provider:
        explicit_provider = resolve_key(repo_root, ["SOMA_INFERENCE_PROVIDER"])

    # If no provider is explicitly requested, check if any API key exists
    if not explicit_provider:
        has_key = any(
            resolve_key(repo_root, [k])
            for k in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]
        )
        if not has_key:
            return None

    try:
        provider = resolve_provider(workspace=repo_root, provider_name=explicit_provider)
        if not is_usable_provider(provider) and explicit_provider not in ("prompt-only", "prompt"):
            return None
        return provider
    except Exception as e:
        print(f"Warning: could not initialize inference provider: {e}", file=sys.stderr)
        return None


def format_layer2_summary(result) -> str:
    """Format Layer 2 arbitration results for CLI output."""
    from soma_core.verification import Verdict
    lines = []
    verdict_str = result.verdict.name if hasattr(result.verdict, 'name') else str(result.verdict)
    icon = "✅" if result.verdict == Verdict.SHIP else "🔴"
    lines.append(f"Layer 2: {icon} {verdict_str}")

    if result.divergences:
        lines.append(f"  Divergences ({len(result.divergences)}):")
        for d in result.divergences:
            pred_desc = f" [{d.prediction.severity.value}] {d.prediction.risk}" if d.prediction else ""
            lines.append(f"    - {d.category.value} ({d.divergence_type}):{pred_desc}")
            if d.resolution:
                lines.append(f"      Resolution: {d.resolution}")

    if result.convergences:
        lines.append(f"  Convergences ({len(result.convergences)}): {', '.join(c.value for c in result.convergences)}")

    return "\n".join(lines)


def verify_release_gate(repo_root: str) -> tuple[bool, str]:
    """Check Release Gate 4.5: assert latest arbitration evidence is a valid SHIP receipt.

    Returns:
        (passed, message) tuple.
    """
    from soma_core.verification.review_adapter import get_latest_arbitration_evidence

    cycle_num, data = get_latest_arbitration_evidence(repo_root)
    if not data or cycle_num == 0:
        return False, "Release Gate 4.5 FAIL: No arbitration evidence found in .soma/evidence/. Run 'soma verify' first."

    verdict = str(data.get("verdict", "")).lower()
    if verdict != "ship":
        divergences = data.get("divergence_count", 0)
        return False, (
            f"Release Gate 4.5 FAIL: Latest arbitration cycle {cycle_num} verdict is '{verdict.upper()}' "
            f"with {divergences} divergence(s). Must achieve SHIP verdict before release."
        )

    # 1. Clean working tree requirement
    try:
        status_res = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=repo_root, timeout=5,
        )
        if status_res.returncode != 0:
            return False, f"Release Gate 4.5 FAIL: git status check failed: {status_res.stderr.strip()}"
        def _is_dirty(line: str) -> bool:
            parts = line.strip().split(maxsplit=1)
            if len(parts) < 2:
                return False
            path = parts[1].strip()
            # Ignore soma runtime evidence, metrics, and telemetry
            if path.startswith(".soma/evidence") or "/.soma/evidence" in path:
                return False
            if path.startswith(".soma/metrics") or "/.soma/metrics" in path:
                return False
            if path.startswith(".soma/telemetry") or "/.soma/telemetry" in path:
                return False
            if path.startswith(".soma/cells") or "/.soma/cells" in path:
                return False
            if path == ".soma/human_insights.jsonl" or path.endswith("/.soma/human_insights.jsonl"):
                return False
            # Ignore test runners and python cache artifacts
            if "__pycache__" in path or path.endswith(".pyc"):
                return False
            if ".pytest_cache" in path:
                return False
            return True

        dirty_lines = [line for line in status_res.stdout.splitlines() if line.strip() and _is_dirty(line)]
        if dirty_lines:
            return False, (
                f"Release Gate 4.5 FAIL: Working tree is dirty ({len(dirty_lines)} modified/untracked files). "
                f"Clean working tree required for release verification."
            )
    except Exception as e:
        return False, f"Release Gate 4.5 FAIL: git status execution failed: {e}"

    # 2. Cryptographic Tree Hash Assertion
    recorded_tree = data.get("tree_hash")
    if not recorded_tree:
        return False, f"Release Gate 4.5 FAIL: Arbitration cycle {cycle_num} missing cryptographic tree_hash binding."

    try:
        tree_res = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            capture_output=True, text=True, cwd=repo_root, timeout=5,
        )
        if tree_res.returncode != 0:
            return False, f"Release Gate 4.5 FAIL: git rev-parse HEAD^{{tree}} failed: {tree_res.stderr.strip()}"
        current_tree = tree_res.stdout.strip()
        if current_tree != recorded_tree:
            return False, (
                f"Release Gate 4.5 FAIL: Tree hash mismatch. Current tree '{current_tree}' does not match "
                f"arbitration receipt tree '{recorded_tree}'. Code was modified after verification."
            )
    except Exception as e:
        return False, f"Release Gate 4.5 FAIL: git tree hash resolution failed: {e}"

    # 3. Target File Coverage & Diff Resolution
    git_target = None
    try:
        for cand in ("origin/main...HEAD", "main...HEAD", "origin/develop...HEAD", "HEAD~1"):
            res = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=ACMR", cand],
                capture_output=True, text=True, cwd=repo_root, timeout=5,
            )
            if res.returncode == 0:
                git_target = res.stdout.splitlines()
                break
    except Exception as e:
        return False, f"Release Gate 4.5 FAIL: git diff execution failed: {e}"

    if git_target is None:
        return False, "Release Gate 4.5 FAIL: Unable to resolve git diff against base branch."

    py_changed = [
        f.strip() for f in git_target
        if f.strip().endswith(".py")
        and not f.startswith("tests/")
        and not f.endswith("__init__.py")
    ]
    if not py_changed:
        return True, f"Release Gate 4.5 PASS: Arbitration cycle {cycle_num} verified with SHIP verdict (tree {recorded_tree[:8]})."

    recorded_targets = set(data.get("target_files", []))
    if not recorded_targets:
        return False, (
            f"Release Gate 4.5 FAIL: Arbitration cycle {cycle_num} has empty target_files, "
            f"but {len(py_changed)} non-test Python files were modified in branch diff."
        )

    uncovered = [f for f in py_changed if f not in recorded_targets]
    if uncovered:
        return False, (
            f"Release Gate 4.5 FAIL: Arbitration cycle {cycle_num} does not cover changed files: "
            f"{', '.join(uncovered)}"
        )

    return True, f"Release Gate 4.5 PASS: Arbitration cycle {cycle_num} verified with SHIP verdict (tree {recorded_tree[:8]})."


# ── Main Handler ──────────────────────────────────────────────────────

def run_verify(args: argparse.Namespace) -> int:
    """Run verification on target files.

    Args:
        args: Parsed CLI arguments with layer1_only, dry_run, files, repo_root.

    Returns:
        Exit code: 0 for SHIP, 1 for BLOCK/REVISE or errors.
    """
    runner, Verdict = _get_verification()

    from soma_core.workspace import Workspace

    # Resolve repo root
    ws_obj = getattr(args, 'ws', None) or Workspace.resolve(
        getattr(args, 'workspace', None)
        or getattr(args, 'repo_root', None)
        or getattr(args, '_project_root', None)
        or getattr(args, '_root', None)
    )
    repo_root = str(ws_obj.root)
    if not os.path.isdir(repo_root):
        print(f"Error: repo root does not exist: {repo_root}", file=sys.stderr)
        return 1

    # ── Release Gate 4.5 Check ────────────────────────────────────────
    if getattr(args, 'release_gate', False):
        passed, msg = verify_release_gate(repo_root)
        if passed:
            print(f"✅ {msg}")
            return 0
        else:
            print(f"🔴 {msg}", file=sys.stderr)
            return 1

    # Resolve target files
    target_files = resolve_target_files(args)

    # Fail if all explicit --files were filtered out (out-of-tree)
    if getattr(args, 'files', None) and not target_files:
        return 1

    # Validate file existence when explicit files are provided
    if getattr(args, 'files', None) and not getattr(args, 'dry_run', False):
        missing = [f for f in target_files if not os.path.exists(os.path.join(repo_root, f))]
        if missing:
            for f in missing:
                print(f"Error: file not found: {f}", file=sys.stderr)
            return 1

    # ── Dry Run ───────────────────────────────────────────────────────
    if getattr(args, 'dry_run', False):
        layer_mode = "Layer 1 only" if getattr(args, 'layer1_only', False) else "Layer 1 + Layer 2"
        print(f"Dry run — {layer_mode}")
        print(f"Repo root: {repo_root}")
        print(f"Files to verify ({len(target_files)}):")
        for f in target_files:
            print(f"  {f}")
        return 0

    # ── Clean Repository ──────────────────────────────────────────────
    if not target_files:
        print("Layer 1: 0 files changed (clean repository)")
        return 0

    # ── Run Layer 1 ───────────────────────────────────────────────────
    results = runner.run_layer1(
        changed_files=target_files,
        repo_root=repo_root,
    )

    layer1_pass = runner.gate_verdict(results)
    if not layer1_pass:
        for r in results:
            if not r.verdict:
                print(f"🔴 {r.tool}: {r.target} — {r.detail}")
    summary = runner.format_summary(results)
    print(summary)

    def _record_telemetry(passed: bool, verdict: Any):
        try:
            from soma_core.outcomes import record_verification_telemetry
            record_verification_telemetry(
                workspace=repo_root,
                target_files=target_files,
                passed=passed,
                verdict=verdict,
                layer1_evidence=results,
                source="session",
            )
        except Exception:
            pass

    if getattr(args, 'layer1_only', False):
        _record_telemetry(layer1_pass, "PASS" if layer1_pass else "FAIL")
        return 0 if layer1_pass else 1

    # ── In-Band Verification Mode ─────────────────────────────────────
    if getattr(args, 'in_band', False):
        from soma_core.verification import VerificationPipeline
        pipeline = VerificationPipeline()
        pipeline_res = pipeline.run(
            changed_files=target_files,
            workspace=ws_obj,
            task_plan=resolve_task_plan(args, repo_root) or "Interactive in-band verification",
            in_band=True,
            rebuttal=None,
        )
        if pipeline_res.charge_sheet:
            print("\n📋 SOMA IN-BAND CHARGE SHEET (SOMA-V01)")
            print(f"Target files ({len(pipeline_res.charge_sheet.target_files)}): {', '.join(pipeline_res.charge_sheet.target_files)}")
            print(f"Prosecution charges ({len(pipeline_res.charge_sheet.predictions)}):")
            for idx, p in enumerate(pipeline_res.charge_sheet.predictions, 1):
                sev = p.severity.value if hasattr(p.severity, "value") else str(p.severity)
                cat = p.category.value if hasattr(p.category, "value") else str(p.category)
                print(f"  {idx}. [{sev.upper()}] {cat} in '{p.affected_function}': {p.risk}")
                print(f"     Mechanism: {p.mechanism}")
            print("\nRebuttal instructions:")
            print("  Submit defense claims citing evidence_file, evidence_line, and tests covering the fix.")
            _record_telemetry(False, "REVISE")
            return 1

    # ── Run Layer 2 (full verification) ───────────────────────────────
    provider = resolve_cli_provider(args, repo_root)
    if provider is None:
        _record_telemetry(layer1_pass, "PASS" if layer1_pass else "FAIL")
        if not layer1_pass:
            return 1
        print("Notice: No inference provider configured. Layer 2 skipped (Layer 1 deterministic checks passed).",
              file=sys.stderr)
        return 0

    task_plan = resolve_task_plan(args, repo_root)
    if getattr(args, 'plan_file', None) and task_plan is None:
        return 1

    if not task_plan:
        _record_telemetry(layer1_pass, "PASS" if layer1_pass else "FAIL")
        if not layer1_pass:
            return 1
        print("Notice: No task plan provided (--plan or --plan-file). Layer 2 skipped (Layer 1 deterministic checks passed).",
              file=sys.stderr)
        return 0

    llm_backend = provider.generate if hasattr(provider, 'generate') else provider
    try:
        test_names, test_results = discover_test_evidence(target_files, repo_root)
    except Exception as e:
        print(f"Error: Test discovery and execution failed: {e}", file=sys.stderr)
        _record_telemetry(False, "BLOCK")
        return 1
    from soma_core.verification import VerificationPipeline

    pipeline = VerificationPipeline()
    try:
        pipeline_res = pipeline.run(
            changed_files=target_files,
            workspace=ws_obj,
            task_plan=task_plan,
            backend=llm_backend,
            test_names=test_names,
            test_results=test_results,
            layer1_evidence=results,
        )
    except Exception as e:
        print(f"Error: Layer 2 verification failed: {e}", file=sys.stderr)
        _record_telemetry(False, "BLOCK")
        return 1

    if pipeline_res.arbitration_result:
        print(format_layer2_summary(pipeline_res.arbitration_result))

    if pipeline_res.evidence_path:
        print(f"Arbitration evidence saved: {pipeline_res.evidence_path}")
    elif getattr(pipeline_res, "persistence_error", None):
        print(f"Error: Could not save arbitration evidence: {pipeline_res.persistence_error}", file=sys.stderr)
        _record_telemetry(False, "BLOCK")
        return 1

    l2_exit = verdict_to_exit_code(pipeline_res.verdict)
    overall_passed = bool(layer1_pass and l2_exit == 0)
    _record_telemetry(overall_passed, pipeline_res.verdict)
    if not layer1_pass or l2_exit != 0:
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    from soma_cli.cli import main
    sys.exit(main(["verify"] + sys.argv[1:]))

