"""soma init — Set up governance for this project.

Detects platform and project type, installs starter rules.
"""
from __future__ import annotations

import argparse
import importlib.resources
import json
import os
import shlex
import shutil
import sys
from pathlib import Path


# ── Starter Pack ────────────────────────────────────────────────────────────
# The 5 rules that deliver immediate value on any project, any language.
# Keys are the rule stems — files are bundled in soma_cli/starter_rules/.

STARTER_RULES = [
    "providence",
    "destructive-ops",
    "testing",
    "cost-optimization",
    "git-workflow",
]

MINIMAL_RULES = ["providence", "destructive-ops"]

# Legacy mapping for manifest cross-validation (starter_pack.txt)
STARTER_RULES_LEGACY = {
    "providence": "genome/providence.md",
    "destructive-ops": "genome/destructive-ops.md",
    "testing": "genome/.oracles/testing.md",
    "cost-optimization": "genome/cost-optimization.md",
    "git-workflow": "genome/.oracles/git-workflow.md",
}


def _get_starter_rule_path(name: str) -> Path | None:
    """Resolve the path to a bundled starter rule file.

    Uses importlib.resources to find files inside the soma_cli package,
    working in both editable installs and wheel distributions.
    """
    try:
        ref = importlib.resources.files("soma_cli") / "starter_rules" / f"{name}.md"
        # Materialize to a real path (works for both installed and editable)
        path = Path(str(ref))
        if path.is_file():
            return path
    except (TypeError, FileNotFoundError):
        pass
    return None


# ── Detection ───────────────────────────────────────────────────────────────

def detect_platform(project_root: Path) -> str:
    """Detect the AI platform from directory markers.

    Returns: 'gemini' | 'claude' | 'cursor' | 'copilot' | 'unknown'
    """
    project_root = Path(project_root)

    if (project_root / ".gemini").is_dir():
        return "gemini"
    if (project_root / ".claude").is_dir():
        return "claude"
    if (project_root / ".cursor").is_dir() or (project_root / ".cursorrules").is_file():
        return "cursor"
    if (project_root / ".github" / "copilot").is_dir() or (project_root / ".github" / "copilot-instructions.md").is_file():
        return "copilot"

    return "unknown"


def detect_project_type(project_root: Path) -> str:
    """Detect the project type from config files.

    Returns: 'python' | 'javascript' | 'rust' | 'go' | 'dotnet' | 'unknown'
    """
    project_root = Path(project_root)
    checks = [
        (["pyproject.toml", "setup.py", "setup.cfg"], "python"),
        (["package.json"], "javascript"),
        (["Cargo.toml"], "rust"),
        (["go.mod"], "go"),
    ]
    for files, lang in checks:
        for f in files:
            if (project_root / f).exists():
                return lang
    return "unknown"


# ── Rules directory per platform ────────────────────────────────────────────

def get_rules_dir(platform: str, home: Path | None = None,
                  project_root: Path | None = None) -> Path:
    """Return the target rules directory for the given platform.

    Args:
        platform: One of 'gemini', 'claude', 'cursor', 'copilot'.
        home: Home directory override (for testing).
        project_root: Project directory override (for copilot, which is project-relative).

    Returns:
        Path to the platform's rules directory.

    Raises:
        ValueError: If platform is unsupported.
    """
    if home is None:
        home = Path.home()
    home = Path(home)
    if project_root is None:
        project_root = Path.cwd()
    project_root = Path(project_root)

    dirs = {
        "gemini": home / ".gemini" / "config" / "rules",
        "claude": home / ".claude",
        "cursor": home / ".cursor" / "rules",
        "copilot": project_root / ".github" / "copilot",
    }
    if platform not in dirs:
        raise ValueError(
            f"Unsupported platform: '{platform}'. "
            f"Supported: {', '.join(sorted(dirs))}"
        )
    return dirs[platform]

# ── Pre-commit Hook ─────────────────────────────────────────────────────────

_SOMA_HOOK_START = "# >>> soma pre-commit >>>"
_SOMA_HOOK_END = "# <<< soma pre-commit <<<"
# Bump when the block body changes; `soma doctor` flags blocks without it.
SOMA_HOOK_FORMAT = "# soma-hook-format: 2"


def _hook_block(python: str | None = None) -> str:
    """The marked pre-commit block (POSIX sh).

    BUG-047: a bare `soma checkpoint` aborted every commit with only
    `soma: not found` when soma was not on the hook's PATH (GUI clients,
    non-login shells, BUG-041 setups). Try `soma`, then the interpreter that
    ran `soma init`; otherwise fail closed with a message that names the fix.
    """
    py = python if python is not None else sys.executable
    if os.name == "nt":
        py = py.replace("\\", "/")  # Git for Windows runs hooks in MSYS sh
    q = shlex.quote(py)
    return (
        f"{_SOMA_HOOK_START}\n"
        "# Installed by soma init — runs deterministic quality checks before commit.\n"
        f"{SOMA_HOOK_FORMAT}\n"
        "if command -v soma >/dev/null 2>&1; then\n"
        "  soma checkpoint --pre-commit || exit $?\n"
        f"elif {q} -c 'import soma_cli' >/dev/null 2>&1; then\n"
        f"  {q} -m soma_cli checkpoint --pre-commit || exit $?\n"
        "else\n"
        "  echo \"soma pre-commit: cannot run the checkpoint. 'soma' is not on this hook's PATH\" >&2\n"
        f"  echo \"  and the interpreter that ran 'soma init' cannot import soma_cli: \"{q} >&2\n"
        "  echo \"  Run 'soma doctor' (or: python3 -m soma_cli doctor --fix-path) to put soma on PATH,\" >&2\n"
        "  echo \"  then re-run 'soma init' to refresh this hook.\" >&2\n"
        "  exit 1\n"
        "fi\n"
        f"{_SOMA_HOOK_END}\n"
    )


def _replace_hook_block(content: str, block: str) -> str | None:
    """content with its marked block swapped for block, or None if malformed."""
    start = content.find(_SOMA_HOOK_START)
    end = content.find(_SOMA_HOOK_END, start)
    if start < 0 or end < 0:
        return None
    # Whole lines: from the start of the START line through the END line.
    line_start = content.rfind("\n", 0, start) + 1
    end += len(_SOMA_HOOK_END)
    if content.startswith("\r\n", end):
        end += 2
    elif content.startswith("\n", end):
        end += 1
    return content[:line_start] + block + content[end:]


def install_hook(project_root: Path, dry_run: bool = False,
                 python: str | None = None) -> bool:
    """Install a git pre-commit hook that runs soma checkpoint.

    Args:
        project_root: Root of the git repository.
        dry_run: If True, preview without creating files.
        python: Interpreter for the fallback (default: sys.executable).

    Returns:
        True if hook was installed (or would be in dry-run), False if
        no .git directory exists.
    """
    project_root = Path(project_root)
    git_hooks_dir = project_root / ".git" / "hooks"

    if not git_hooks_dir.is_dir():
        return False

    if dry_run:
        return True

    hook_file = git_hooks_dir / "pre-commit"
    block = _hook_block(python)

    if hook_file.exists():
        content = hook_file.read_text(encoding="utf-8")
        if _SOMA_HOOK_START in content:
            # Re-init refreshes the block in place; user lines stay put.
            updated = _replace_hook_block(content, block)
            if updated is None:
                print(f"  ⚠️  {hook_file} has an unterminated soma block; left unchanged")
                return True
            if updated != content:
                hook_file.write_text(updated, encoding="utf-8")
        else:
            # Append to existing hook
            if not content.endswith("\n"):
                content += "\n"
            content += "\n" + block
            hook_file.write_text(content, encoding="utf-8")
    else:
        hook_file.write_text("#!/bin/sh\n\n" + block, encoding="utf-8")

    # Ensure executable
    hook_file.chmod(hook_file.stat().st_mode | 0o755)
    return True


# ── Installation ────────────────────────────────────────────────────────────

def check_existing_install(project_root: Path) -> bool:
    """Check if Soma is already installed in this project."""
    return (Path(project_root) / ".soma").is_dir()


def _get_soma_root() -> Path:
    """Find the Soma source root (repo root with genome/ dir).

    Tries importlib.resources (works for editable installs) then falls
    back to CWD.
    """
    try:
        pkg_root = Path(str(importlib.resources.files("soma_cli"))).parent
        if (pkg_root / "genome").is_dir():
            return pkg_root
    except (TypeError, FileNotFoundError):
        pass
    cwd = Path.cwd()
    if (cwd / "genome").is_dir():
        return cwd
    return cwd


def _discover_full_rules() -> list[Path]:
    """Discover all genome rule .md files for the full preset.

    Scans genome/ and genome/.oracles/, skipping META.md and README.md.
    """
    soma_root = _get_soma_root()
    genome_dir = soma_root / "genome"
    if not genome_dir.is_dir():
        return []

    skip = {"META.md", "README.md"}
    results: list[Path] = []

    # Top-level genome/*.md
    for f in sorted(genome_dir.glob("*.md")):
        if f.is_file() and f.name not in skip:
            results.append(f)

    # genome/.oracles/*.md
    oracles_dir = genome_dir / ".oracles"
    if oracles_dir.is_dir():
        for f in sorted(oracles_dir.glob("*.md")):
            if f.is_file() and f.name not in skip:
                results.append(f)

    return results


def install_rules(
    rules_dir: Path,
    preset: str = "standard",
    dry_run: bool = False,
    force: bool = False,
) -> list[str]:
    """Install rules to the target directory based on the chosen preset.

    Args:
        rules_dir: Target directory for rules.
        preset: One of 'minimal', 'standard', 'full'.
        dry_run: If True, only print what would be done.
        force: If True, overwrite existing rules.

    Returns:
        List of installed rule names.
    """
    if preset == "full":
        sources = _discover_full_rules()
        return _copy_rule_files(rules_dir, sources, force=force, dry_run=dry_run)
    elif preset == "minimal":
        names = MINIMAL_RULES
    else:  # standard
        names = STARTER_RULES

    return _install_named_rules(rules_dir, names, force=force, dry_run=dry_run)


def _install_named_rules(
    rules_dir: Path,
    names: list[str],
    force: bool = False,
    dry_run: bool = False,
) -> list[str]:
    """Install named rules from the starter_rules bundle."""
    installed = []
    for name in names:
        source = _get_starter_rule_path(name)
        if source is None:
            print(f"  ⚠️  {name}: source not found")
            continue

        dest = rules_dir / f"{name}.md"
        if dest.is_symlink():
            print(f"  ⚠️  {name}: skipped (destination is a symlink)")
            continue
        if dest.exists() and not force:
            print(f"  ℹ️  {name}: already exists, skipping (use --force to overwrite)")
            installed.append(name)
            continue

        if not dry_run:
            rules_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        installed.append(name)

    return installed


def _copy_rule_files(
    rules_dir: Path,
    sources: list[Path],
    force: bool = False,
    dry_run: bool = False,
) -> list[str]:
    """Copy a list of source .md files into rules_dir."""
    installed = []
    for src in sources:
        dest = rules_dir / src.name
        if dest.is_symlink():
            print(f"  ⚠️  {src.name}: skipped (destination is a symlink)")
            continue
        if dest.exists() and not force:
            print(f"  ℹ️  {src.stem}: already exists, skipping (use --force to overwrite)")
            installed.append(src.stem)
            continue

        if not dry_run:
            rules_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        installed.append(src.stem)

    return installed


def install_starter_rules(
    rules_dir: Path,
    dry_run: bool = False,
    force: bool = False,
) -> list[str]:
    """Install the 5 starter rules to the target directory.

    Backward-compatible wrapper around install_rules().

    Args:
        rules_dir: Target directory for rules.
        dry_run: If True, don't create files.
        force: If True, overwrite existing rules.

    Returns:
        List of installed rule names.
    """
    return _install_named_rules(rules_dir, STARTER_RULES, force=force, dry_run=dry_run)


# ── MCP Config ──────────────────────────────────────────────────────────────

def generate_mcp_config(project_root: Path, dry_run: bool = False) -> None:
    """Create or merge .mcp.json for the governed project.

    Existing servers and unrelated keys are preserved. Invalid or structurally
    incompatible JSON fails before the configuration is modified.
    """
    workspace = str(Path(project_root).resolve())
    mcp_file = Path(workspace) / ".mcp.json"

    soma_entry = {
        "command": "python3",
        "args": ["-m", "soma_mcp"],
        "cwd": workspace,
        "env": {"SOMA_WORKSPACE": workspace},
    }

    if dry_run:
        print(f"  Would create/update: {mcp_file}")
        return

    if mcp_file.exists():
        data = json.loads(mcp_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{mcp_file} must contain a JSON object")
    else:
        data = {}

    servers = data.get("mcpServers")
    if servers is None:
        servers = {}
        data["mcpServers"] = servers
    elif not isinstance(servers, dict):
        raise ValueError(f"{mcp_file} field 'mcpServers' must be a JSON object")
    servers["soma"] = soma_entry

    mode = None
    if mcp_file.exists():
        try:
            mode = os.stat(mcp_file).st_mode
        except OSError:
            pass

    # Write beside the destination with unique pid temp name and replace only after
    # serialization succeeds, preserving original file mode.
    temp_file = mcp_file.with_name(f".{mcp_file.name}.{os.getpid()}.tmp")
    try:
        temp_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        if mode is not None:
            try:
                os.chmod(temp_file, mode)
            except OSError:
                pass
        temp_file.replace(mcp_file)
    finally:
        if temp_file.exists():
            temp_file.unlink()
    print(f"  📡 MCP config written to {mcp_file}")


# ── Main flow ───────────────────────────────────────────────────────────────

def run_init(args: argparse.Namespace) -> int:
    """Main init flow. Returns exit code."""
    # Allow test override of project root
    project_root = getattr(args, "_project_root", Path.cwd())
    project_root = Path(project_root)

    dry_run = args.dry_run
    forced_platform = args.platform

    print()
    print("  🧬 Soma Governance — Setup")
    print()

    # 1. Detect platform
    if forced_platform:
        platform = forced_platform
        print(f"  Platform: {platform} (forced)")
    else:
        platform = detect_platform(project_root)
        # Fallback: check home directory if project-level detection fails
        if platform == "unknown" and not getattr(args, "_project_root", None):
            platform = detect_platform(Path.home())
        if platform == "unknown":
            print("  ⚠️  Could not detect platform.")
            print("     Use --platform to specify: gemini, claude, cursor, copilot")
            return 1
        print(f"  Detected platform: {platform}")

    # 2. Detect project type
    project_type = detect_project_type(project_root)
    if project_type != "unknown":
        print(f"  Detected project: {project_type}")
    else:
        print("  Project type: unknown (rules are language-agnostic)")

    # 3. Check existing install
    if check_existing_install(project_root):
        print()
        print("  ℹ️  Existing Soma installation detected (.soma/ directory).")
        print("     Starter rules will be added alongside existing rules.")

    print()

    # 4. Resolve target directory
    try:
        # Use project_root as home override for testing
        home = getattr(args, "_project_root", None)
        rules_dir = get_rules_dir(platform, home=home, project_root=project_root)
    except ValueError as e:
        print(f"  ❌ {e}")
        return 1

    # 5. Confirmation prompt (unless --yes or --dry-run)
    skip_confirm = getattr(args, "yes", False) or dry_run
    if not skip_confirm:
        print(f"  Will install starter rules to: {rules_dir}")
        try:
            answer = input("  Proceed? [Y/n] ").strip().lower()
            if answer and answer not in ("y", "yes"):
                print("  Aborted.")
                return 0
        except (EOFError, KeyboardInterrupt):
            print("\n  Aborted.")
            return 0
    print()

    # 6. Install rules based on preset
    preset = getattr(args, "rules", "standard")
    force = getattr(args, 'force', False)

    if dry_run:
        print(f"  Installing rules (preset={preset}, dry run)...")
    else:
        print(f"  Installing rules (preset={preset})...")

    installed = install_rules(rules_dir, preset=preset, dry_run=dry_run, force=force)

    for name in installed:
        print(f"    ✅ {name}")

    print()

    # 7. MCP config (if requested)
    if getattr(args, "mcp", False):
        generate_mcp_config(project_root, dry_run=dry_run)

    # 7.5. Install pre-commit hook
    hook_result = install_hook(project_root, dry_run=dry_run)
    if hook_result and not dry_run:
        print("    🪝 Pre-commit hook installed (.git/hooks/pre-commit)")
    elif hook_result and dry_run:
        print("    🪝 Would install pre-commit hook")

    # 8. Claude-specific: concatenate rules into CLAUDE.md
    if platform == "claude" and installed and not dry_run:
        _install_claude_md(rules_dir, force=force)

    if dry_run:
        print("  Dry run complete. No files were created.")
        print(f"  Target: {rules_dir}")
    elif not installed:
        print("  ❌ No rules were installed. Check that Soma source files exist.")
        return 1
    else:
        print("  Done! Your next agent session will be governed.")
        print(f"  Rules installed to: {rules_dir}")

    print()
    print("  After a session, run: soma report")
    print()

    return 0


# ── Claude helpers ──────────────────────────────────────────────────────────

SOMA_MARKER_START = "<!-- SOMA:START -->"
SOMA_MARKER_END = "<!-- SOMA:END -->"


def _install_claude_md(rules_dir: Path, force: bool = False) -> None:
    """Concatenate installed rules into CLAUDE.md for Claude Code.

    Claude Code reads CLAUDE.md, not individual .md files. We concatenate
    all installed rules between SOMA markers so we can update them later.
    """
    claude_md = rules_dir / "CLAUDE.md"  # ~/.claude/CLAUDE.md

    # Build the soma governance section
    sections = []
    for rule_file in sorted(rules_dir.glob("*.md")):
        if rule_file.is_file() and rule_file.name != "CLAUDE.md":
            content = rule_file.read_text(encoding="utf-8").strip()
            sections.append(f"## {rule_file.stem}\n\n{content}")

    if not sections:
        return

    soma_block = (
        f"{SOMA_MARKER_START}\n"
        f"# Soma Governance Rules\n\n"
        + "\n\n---\n\n".join(sections)
        + f"\n{SOMA_MARKER_END}\n"
    )

    if claude_md.exists():
        existing = claude_md.read_text(encoding="utf-8")
        has_start = SOMA_MARKER_START in existing
        has_end = SOMA_MARKER_END in existing

        if has_start and has_end:
            start_idx = existing.index(SOMA_MARKER_START)
            end_idx = existing.index(SOMA_MARKER_END) + len(SOMA_MARKER_END)
            # Guard against inverted markers
            if start_idx >= end_idx:
                print("  ⚠️  CLAUDE.md has corrupted SOMA markers, skipping")
                return
            if not force:
                print("  ℹ️  CLAUDE.md already has Soma rules (use --force to update)")
                return
            # Replace existing section
            updated = existing[:start_idx] + soma_block + existing[end_idx:]
            claude_md.write_text(updated, encoding="utf-8")
        elif has_start or has_end:
            # Partial markers — refuse without --force to avoid corruption
            if not force:
                print("  ⚠️  CLAUDE.md has partial SOMA markers (use --force to replace)")
                return
            # Force: remove the orphan marker line and append fresh block
            lines = existing.splitlines(True)
            lines = [l for l in lines if SOMA_MARKER_START not in l and SOMA_MARKER_END not in l]
            claude_md.write_text("".join(lines).rstrip() + "\n\n" + soma_block, encoding="utf-8")
        else:
            # No markers — append
            claude_md.write_text(existing.rstrip() + "\n\n" + soma_block, encoding="utf-8")
    else:
        claude_md.write_text(soma_block, encoding="utf-8")

    print(f"  📝 Updated {claude_md}")
