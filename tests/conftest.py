"""Shared fixtures for the Soma regression suite.

The suite deliberately avoids requiring pyyaml: several invariants under test
exist precisely because `soma_mcp/` must work on a bare interpreter.
"""
import os
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def repo_root():
    return REPO_ROOT


def require_bash():
    """Path to bash, or skip. Prefers /bin/bash: on macOS that is 3.2, the
    oldest supported shell and the one that surfaced SOMA-C03. Windows has
    no /bin/bash for native processes; Git Bash is found on PATH or Git installation."""
    if os.name == "nt":
        for git_bash in (r"C:\Program Files\Git\usr\bin\bash.exe", r"C:\Program Files (x86)\Git\usr\bin\bash.exe"):
            if os.path.exists(git_bash):
                return git_bash
    path = "/bin/bash" if os.path.exists("/bin/bash") else shutil.which("bash")
    if not path:
        pytest.skip("bash is not available")
    return path


@pytest.fixture(scope="session")
def bash():
    return require_bash()


def symlink_or_skip(target, link):
    """Create a symlink, or skip: Windows needs Developer Mode or admin
    rights (WinError 1314)."""
    try:
        os.symlink(str(target), str(link))
    except (OSError, NotImplementedError):
        # On POSIX a failure here is a test bug; don't let it hide the
        # symlink-escape security tests behind a skip.
        if os.name != "nt":
            raise
        pytest.skip("symlinks are unavailable")


@pytest.fixture
def fake_home(tmp_path):
    """An isolated HOME so installer tests never touch the real one."""
    home = tmp_path / "home"
    home.mkdir()
    return home


def run(cmd, cwd=REPO_ROOT, env=None, stdin=subprocess.DEVNULL, timeout=120):
    """Run a command and return CompletedProcess with text output."""
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
        # Under Git Bash resolve_home() prefers USERPROFILE, so a HOME-only
        # override would still point the installer at the real profile (BUG-010).
        if "HOME" in env and "USERPROFILE" not in env:
            full_env["USERPROFILE"] = env["HOME"]
    return subprocess.run(
        cmd, cwd=cwd, env=full_env, stdin=stdin,
        capture_output=True, text=True, timeout=timeout,
    )


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def iter_source_files(root, extensions):
    """Yield absolute paths under root matching extensions, skipping caches."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in {"__pycache__", ".git", "node_modules", ".pytest_cache"}
        ]
        for fn in filenames:
            if any(fn.endswith(ext) for ext in extensions):
                yield os.path.join(dirpath, fn)
