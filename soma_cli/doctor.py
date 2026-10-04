"""soma doctor — System health check.

`soma doctor --fix-path [--yes]` is the opt-in PATH fixer: the installers
never edit dotfiles, and this command only does so after --yes or an
interactive confirmation. Every line it appends is recorded in
~/.soma/manifest.json (`path_lines`) so install/uninstall.sh can remove it.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterable, Mapping, TextIO

FIX_PATH_MARKER = "# added by soma doctor --fix-path"
_EDITABLE_SHELLS = ("zsh", "bash", "fish")


def _check_python_version() -> bool:
    """Check Python >= 3.9."""
    ok = sys.version_info >= (3, 9)
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if ok:
        print(f"  ✅ Python {ver} (≥ 3.9)")
    else:
        print(f"  ❌ Python {ver} (requires ≥ 3.9)")
    return ok


def _check_pyyaml() -> bool:
    """Check that pyyaml is importable."""
    try:
        import yaml  # noqa: F401
        print("  ✅ pyyaml installed")
        return True
    except ImportError:
        print("  ❌ pyyaml not installed")
        return False


def _check_platform() -> str | None:
    """Detect AI platform; return platform name or None on failure."""
    from soma_cli.init import detect_platform

    platform = detect_platform(Path.cwd())
    # Fallback: check home directory for global AI configs
    if platform == "unknown":
        platform = detect_platform(Path.home())
    if platform != "unknown":
        print(f"  ✅ Platform detected: {platform}")
        return platform
    print("  ❌ No AI platform detected")
    return None


def _check_rules(platform: str | None) -> bool:
    """Check that rules directory has ≥1 .md file."""
    if platform is None:
        print("  ❌ Rules check skipped (no platform)")
        return False
    from soma_cli.init import get_rules_dir

    rules_dir = get_rules_dir(platform)
    md_files = [
        p for p in rules_dir.glob("*.md")
        if p.name.lower() not in ("readme.md", "claude.md")
    ] if rules_dir.is_dir() else []
    if md_files:
        print(f"  ✅ Rules installed ({len(md_files)} .md files in {rules_dir})")
        return True
    print(f"  ❌ No .md rules found in {rules_dir}")
    return False


def _check_evidence_dir() -> bool:
    """Check .soma/evidence/ exists and is writable (read-only check)."""
    evidence = Path.cwd() / ".soma" / "evidence"
    if evidence.is_dir():
        if os.access(str(evidence), os.W_OK):
            print(f"  ✅ Evidence directory writable ({evidence})")
            return True
        print(f"  ❌ Evidence directory not writable ({evidence})")
        return False
    # Directory doesn't exist — check if parent is writable
    parent = evidence.parent
    if parent.is_dir() and os.access(str(parent), os.W_OK):
        print(f"  ✅ Evidence directory can be created ({evidence})")
        return True
    print(f"  ❌ Evidence directory does not exist ({evidence})")
    return False


def _check_cli_resolvable() -> bool:
    """Check that 'soma' CLI is on PATH."""
    path = shutil.which("soma")
    if path:
        print(f"  ✅ soma CLI resolvable ({path})")
        return True
    print("  ❌ soma CLI not found on PATH")
    from soma_cli.pathcheck import build_hint
    hint = build_hint()
    if hint:
        print("\n".join("    " + line for line in hint.splitlines()))
    return False


# ── MCP launcher ─────────────────────────────────────────────────────────────

# MCP configs start the server as `python3 -m soma_mcp`. The import probe runs
# without -I so user site-packages count, but drops the implicit CWD entry so
# doctor never imports (executes) a soma_mcp that happens to sit in the cwd.
_IMPORT_PROBE = "import sys; sys.path[:1] = [p for p in sys.path[:1] if p]; import soma_mcp"


def probe_mcp_launcher(path_env: str | None = None,
                       timeout: float = 10.0) -> tuple[str, str]:
    """Resolve `python3` from PATH like an MCP host and classify it.

    Returns (status, detail); status is one of ok, missing, store_stub,
    broken, no_soma_mcp.
    """
    path_env = os.environ.get("PATH", "") if path_env is None else path_env
    exe = shutil.which("python3", path=path_env)
    if not exe:
        return "missing", "python3 is not on PATH"

    def _run(argv: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run([exe, *argv], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, errors="replace",
                              timeout=timeout)

    try:
        proc = _run(["-I", "-S", "-c", "import sys; print(sys.version_info[0])"])
    except subprocess.TimeoutExpired:
        return "broken", f"{exe} timed out after {timeout:g}s"
    except OSError as exc:
        return "broken", f"{exe} could not be started: {exc}"
    out = proc.stdout.strip()
    # The App Installer stub exits 49, or prints a Store message and nothing
    # on stdout, instead of running Python.
    store_msg = "microsoft store" in (proc.stdout + proc.stderr).lower()
    if proc.returncode == 49 or (not out and store_msg):
        return "store_stub", exe
    if proc.returncode != 0 or out != "3":
        err = (proc.stderr.strip() or out)[:200]
        return "broken", f"{exe} exited {proc.returncode}: {err}"

    try:
        imp = _run(["-c", _IMPORT_PROBE])
    except subprocess.TimeoutExpired:
        return "broken", f"{exe} timed out after {timeout:g}s importing soma_mcp"
    except OSError as exc:
        return "broken", f"{exe} could not be started: {exc}"
    if imp.returncode != 0:
        return "no_soma_mcp", exe
    return "ok", exe


def _check_mcp_launcher(path_env: str | None = None) -> bool:
    """Advisory: report whether `python3 -m soma_mcp` would start."""
    status, detail = probe_mcp_launcher(path_env)
    if status == "ok":
        print(f"  ✅ MCP launcher: python3 ({detail}) runs and imports soma_mcp")
        return True
    if status == "missing":
        print("  ⚠️  MCP launcher: python3 not found on PATH. MCP configs start the\n"
              "      server with `python3 -m soma_mcp`; install Python 3 from python.org\n"
              "      or put it on PATH (only needed if you use the MCP server).")
    elif status == "store_stub":
        print(f"  ⚠️  MCP launcher: {detail} is the Windows Store App Installer stub, not Python.\n"
              "      Fix: Settings > Apps > Advanced app settings > App execution aliases:\n"
              "      turn off python.exe and python3.exe, then install Python from python.org\n"
              "      (or make sure the real python3 comes first on PATH).")
    elif status == "no_soma_mcp":
        print(f"  ⚠️  MCP launcher: {detail} runs but cannot import soma_mcp.\n"
              f"      Install it for that interpreter: {detail} -m pip install --user soma-governance")
    else:
        print(f"  ⚠️  MCP launcher: {detail}")
    return False


# ── Pre-commit hook (BUG-047) ────────────────────────────────────────────────

def _check_precommit_hook(project_root: Path | None = None) -> bool | None:
    """False for a pre-BUG-047 soma hook block, True if current, None if absent."""
    from soma_cli.init import SOMA_HOOK_FORMAT, _SOMA_HOOK_START

    hook = Path.cwd() if project_root is None else Path(project_root)
    hook = hook / ".git" / "hooks" / "pre-commit"
    try:
        text = hook.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if _SOMA_HOOK_START not in text:
        return None
    if SOMA_HOOK_FORMAT in text:
        print(f"  ✅ Pre-commit hook is current ({hook})")
        return True
    print(f"  ❌ Pre-commit hook uses an old soma block ({hook}).\n"
          "      It aborts commits with `soma: not found` when soma is not on the\n"
          "      hook's PATH (BUG-047). Re-run `soma init` to refresh it.")
    return False


# ── --fix-path ───────────────────────────────────────────────────────────────

def _under(base: str, path: str) -> bool:
    try:
        return os.path.commonpath([base, path]) == base
    except ValueError:
        return False


def _umask_mode(mode: int = 0o666) -> int:
    current = os.umask(0)
    os.umask(current)
    return mode & ~current


def _atomic_write(path: str, data: bytes, mode: int) -> None:
    """Exclusive temp in the same directory, given mode, os.replace."""
    fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.soma-",
                               suffix=".tmp", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _write_preserving_mode(path: str, data: bytes) -> None:
    real = os.path.realpath(path)
    mode = stat.S_IMODE(os.stat(real).st_mode) if os.path.exists(real) else _umask_mode()
    _atomic_write(real, data, mode)


def _confined_rc(rc_path: str, home: str) -> tuple[str | None, str]:
    """(real path to write, "") or (None, reason). Must resolve inside HOME."""
    if not os.path.isabs(rc_path):
        return None, f"{rc_path} is not an absolute path"
    home_real = os.path.realpath(home)
    real = os.path.realpath(rc_path)
    if real == home_real or not _under(home_real, real):
        if os.path.islink(rc_path):
            return None, f"{rc_path} is a symlink to {real}, outside your home directory"
        return None, f"{rc_path} resolves outside your home directory ({real})"
    if os.path.lexists(real) and not os.path.isfile(real):
        return None, f"{real} exists but is not a regular file"
    return real, ""


def _load_manifest(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("manifest is not a JSON object")
    if not isinstance(data.get("path_lines", []), list):
        raise ValueError("manifest field path_lines is not a list")
    return data


def _expand_home(path: str, home: str) -> str:
    if path == "~" or path.startswith("~/"):
        path = os.path.join(home, path[2:])
    return os.path.normpath(path)


def fix_path(yes: bool = False, *,
             env: Mapping[str, str] | None = None,
             home: str | None = None,
             candidates: Iterable[str] | None = None,
             which: Callable[..., str | None] | None = None,
             platform: str | None = None,
             os_name: str | None = None,
             stdin: TextIO | None = None) -> int:
    """Append the pathcheck PATH line to the shell rc file (opt-in).

    Dry run unless `yes` or an interactive y. Returns a process exit code.
    """
    from soma_cli import pathcheck

    env = os.environ if env is None else env
    home = os.path.expanduser("~") if home is None else home
    which = shutil.which if which is None else which
    platform = sys.platform if platform is None else platform
    os_name = os.name if os_name is None else os_name
    stdin = sys.stdin if stdin is None else stdin
    path_env = env.get("PATH", "")
    py = "python" if os_name == "nt" else "python3"

    found = which("soma", path=path_env)
    if found:
        print(f"✅ soma is already on PATH ({found}). Nothing to change.")
        return 0
    directory = pathcheck.scripts_dir(
        candidates if candidates is not None else pathcheck.default_candidates())
    if directory is None:
        print("❌ The 'soma' command is not installed for this Python, so there is no\n"
              f"   directory to add to PATH. Install it with: {py} -m pip install soma-governance")
        return 1
    sep = ";" if os_name == "nt" else ":"
    if pathcheck.on_path(directory, path_env, sep=sep, casefold=os_name == "nt"):
        print(f"✅ {directory} is already on PATH. Nothing to change.\n"
              "   Open a new terminal (or run `hash -r` / `rehash`) so the shell picks it up.")
        return 0
    venv = pathcheck._active_venv_prefix()
    if venv and pathcheck._home_relative(directory, venv, casefold=os_name == "nt") is not None:
        print(f"❌ soma is installed in the virtual environment {venv}. --fix-path will not\n"
              "   put a virtualenv's bin directory in a global startup file; activate it instead.")
        return 1

    shell = pathcheck.detect_shell(env, os_name=os_name)
    line = pathcheck.remedy(shell, directory, home, os_name=os_name)
    if shell not in _EDITABLE_SHELLS:
        if shell == "pwsh":
            print("ℹ️  soma doctor --fix-path never edits PowerShell's $PROFILE: it runs on every\n"
                  "   PowerShell start, may be signed or governed by an execution policy, and on\n"
                  "   Windows the persistent user Path (not the profile) is where PATH belongs.\n"
                  "   Run this yourself, then open a new terminal:")
        else:
            print(f"ℹ️  Unrecognised shell ({env.get('SHELL') or 'SHELL unset'}). --fix-path only edits\n"
                  "   zsh, bash and fish startup files. Add the equivalent of this line to yours:")
        print(f"      {line}")
        return 0

    rc_path = _expand_home(pathcheck.rc_file(shell, env=env, platform=platform) or "", home)
    marked = f"{line}  {FIX_PATH_MARKER}"
    real, why = _confined_rc(rc_path, home)
    if real is None:
        print(f"❌ Refusing to edit {rc_path}: {why}.\n"
              "   Nothing was changed. Add this line yourself if you want it:\n"
              f"      {marked}")
        return 1

    marked_b = marked.encode("utf-8", "surrogateescape")
    existing = None
    if os.path.isfile(real):
        with open(real, "rb") as fh:
            existing = fh.read()
        if any(raw.rstrip(b"\r\n") == marked_b for raw in existing.splitlines(True)):
            print(f"✅ {rc_path} already contains the soma PATH line. Nothing to change.")
            return 0

    print(f"soma doctor --fix-path will append this line to {rc_path}:\n      {marked}")
    if not yes:
        if not stdin.isatty():
            print("Dry run: nothing was changed. Re-run with --yes to apply "
                  "(or run it in a terminal to confirm).")
            return 0
        print("Append it? [y/N] ", end="", flush=True)
        if stdin.readline().strip().lower() not in ("y", "yes"):
            print("Not changed.")
            return 0

    manifest_path = os.path.join(home, ".soma", "manifest.json")
    try:
        old_manifest = None
        if os.path.exists(manifest_path):
            with open(manifest_path, "rb") as fh:
                old_manifest = fh.read()
        data = _load_manifest(manifest_path)
    except (OSError, ValueError) as exc:
        print(f"❌ Cannot record the change in {manifest_path}: {exc}\n"
              "   Nothing was changed (uninstall could not remove an unrecorded line).")
        return 1

    created = existing is None
    existing = existing or b""
    nl = b"\r\n" if b"\r\n" in existing else b"\n"
    prefix = bool(existing) and not existing.endswith(b"\n")
    entry = {"file": rc_path, "line": marked, "created": created, "prefix_newline": prefix}
    entries = [e for e in data.get("path_lines", [])
               if not (isinstance(e, dict) and e.get("file") == rc_path and e.get("line") == marked)]
    data["path_lines"] = entries + [entry]

    # Record first: an entry without its line is harmless (uninstall warns);
    # a line without its entry could never be removed by uninstall.
    try:
        os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
        _write_preserving_mode(manifest_path, (json.dumps(data, indent=2) + "\n").encode("utf-8"))
    except OSError as exc:
        print(f"❌ Cannot write {manifest_path}: {exc}. Nothing was changed.")
        return 1
    try:
        os.makedirs(os.path.dirname(real), exist_ok=True)
        mode = _umask_mode() if created else stat.S_IMODE(os.stat(real).st_mode)
        _atomic_write(real, existing + (nl if prefix else b"") + marked_b + nl, mode)
    except OSError as exc:
        try:
            if old_manifest is None:
                os.unlink(manifest_path)
            else:
                _write_preserving_mode(manifest_path, old_manifest)
        except OSError:
            pass
        print(f"❌ Could not write {rc_path}: {exc}. Nothing was changed.")
        return 1
    print(f"✅ Added to {rc_path} (recorded in {manifest_path} for uninstall).\n"
          f"   Open a new terminal, or run: source {rc_path}")
    return 0


def run_doctor(args: argparse.Namespace) -> int:
    """Run all health checks. Returns 0 if all pass, 1 otherwise."""
    if getattr(args, "fix_path", False):
        return fix_path(yes=getattr(args, "yes", False))
    if getattr(args, "yes", False):
        print("--yes only applies to --fix-path", file=sys.stderr)
        return 2
    print("soma doctor — running health checks:\n")
    results: list[bool] = []

    results.append(_check_python_version())
    results.append(_check_pyyaml())
    platform = _check_platform()
    results.append(platform is not None)
    results.append(_check_rules(platform))
    results.append(_check_evidence_dir())
    results.append(_check_cli_resolvable())
    hook_ok = _check_precommit_hook()
    if hook_ok is not None:
        results.append(hook_ok)
    # Advisory: only MCP users need it, so it does not fail the run.
    _check_mcp_launcher()

    passed = sum(results)
    total = len(results)
    print(f"\n{passed}/{total} checks passed.")
    return 0 if all(results) else 1
