"""BUG-037: resolve a *working* Python 3 instead of trusting `command -v`.

Under Git Bash `python3` can be the Windows Store App Installer stub:
`command -v python3` succeeds, but running it exits 49 with no output. The
shell enzymes and installer used to call `python3` directly, so
install_hooks() rendered an empty hooks.json and every enzyme `python3` call
failed. The fix resolves one interpreter (python3, python, py -3), accepting a
candidate only if it actually runs, and routes every call through it.

The stub is reproduced on any OS with a fake PATH entry that exits 49.
"""
import json
import os
import re
import stat
import sys

import pytest

from conftest import REPO_ROOT, read, run

STORE_STUB_EXIT = 49


def _write_exe(path, body):
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def fake_bin(tmp_path):
    """A PATH prefix where `python3` is the Store stub."""
    if os.name == "nt":
        pytest.skip("POSIX shebang shims; the stub is simulated, not native")
    d = tmp_path / "bin"
    d.mkdir()
    _write_exe(d / "python3", f"exit {STORE_STUB_EXIT}")
    return d


def _env(tmp_path, fake_bin):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        "HOME": str(home),
        "USERPROFILE": str(home),  # BUG-010
        "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
        "SOMA_PYTHON": "",
    }


def _shim_real_python(fake_bin, name="python"):
    _write_exe(fake_bin / name, f'exec "{sys.executable}" "$@"')


def test_resolver_skips_store_stub_and_picks_working_python(tmp_path, fake_bin, bash):
    _shim_real_python(fake_bin)
    script = (
        'source enzymes/common.sh; resolve_python; '
        'echo "picked=${SOMA_PYTHON_CMD[*]}"; '
        'soma_python -c "import sys; print(\'ran\', sys.version_info[0])"'
    )
    proc = run([bash, "-c", script], env=_env(tmp_path, fake_bin))
    assert proc.returncode == 0, proc.stderr
    assert "picked=python\n" in proc.stdout
    assert "ran 3" in proc.stdout


def test_install_hooks_renders_hooks_with_store_stub_first_on_path(tmp_path, fake_bin, bash):
    _shim_real_python(fake_bin)
    target = tmp_path / "hooks"
    script = f'source enzymes/common.sh; install_hooks "{REPO_ROOT}" "{target}"'
    proc = run([bash, "-c", script], env=_env(tmp_path, fake_bin))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    hooks = target / "hooks.json"
    assert hooks.exists() and hooks.stat().st_size > 0, "hooks.json was not rendered"
    rendered = json.loads(read(str(hooks)))
    assert "{{SCRIPTS_DIR}}" not in json.dumps(rendered)


def test_install_hooks_fails_loudly_without_a_working_python(tmp_path, fake_bin, bash):
    for name in ("python", "py"):
        _write_exe(fake_bin / name, f"exit {STORE_STUB_EXIT}")
    target = tmp_path / "hooks"
    script = f'source enzymes/common.sh; install_hooks "{REPO_ROOT}" "{target}"'
    proc = run([bash, "-c", script], env=_env(tmp_path, fake_bin))
    assert proc.returncode != 0, "hooks were silently skipped"
    assert "No working Python 3 interpreter" in proc.stderr
    assert not (target / "hooks.json").exists()


def test_soma_python_override_is_honoured(tmp_path, fake_bin, bash):
    env = _env(tmp_path, fake_bin)
    env["SOMA_PYTHON"] = sys.executable
    proc = run([bash, "-c", 'source enzymes/common.sh; soma_python -c "print(42)"'], env=env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "42"


def test_resolver_falls_back_to_py_launcher(tmp_path, fake_bin, bash):
    # python3 and python are both Store stubs; only the launcher works, and
    # only when asked for Python 3 explicitly.
    _write_exe(fake_bin / "python", f"exit {STORE_STUB_EXIT}")
    _write_exe(fake_bin / "py",
               f'[ "$1" = "-3" ] || exit 64\nshift\nexec "{sys.executable}" "$@"')
    script = (
        'source enzymes/common.sh; resolve_python; '
        'echo "picked=${SOMA_PYTHON_CMD[*]}"; '
        'soma_python -c "import sys; print(\'ran\', sys.version_info[0])"'
    )
    proc = run([bash, "-c", script], env=_env(tmp_path, fake_bin))
    assert proc.returncode == 0, proc.stderr
    assert "picked=py -3\n" in proc.stdout
    assert "ran 3" in proc.stdout


def test_probe_runs_isolated(tmp_path, fake_bin, bash):
    # The probe only needs sys: -I -S keeps a hostile PYTHONPATH/site or a
    # cwd module from running during resolution (matches uninstall.sh).
    log = tmp_path / "argv.log"
    shim = fake_bin / "recording-python"
    _write_exe(shim, f'echo "$*" >> "{log}"\nexec "{sys.executable}" "$@"')
    env = _env(tmp_path, fake_bin)
    env["SOMA_PYTHON"] = str(shim)
    proc = run([bash, "-c", "source enzymes/common.sh; resolve_python"], env=env)
    assert proc.returncode == 0, proc.stderr
    first = read(str(log)).splitlines()[0]
    assert first.startswith("-I -S -c "), first


def test_enzyme_without_prior_common_sh_survives_store_stub(tmp_path, fake_bin, bash):
    # liveness_sentinel.sh called python3 directly and exited 49.
    _shim_real_python(fake_bin)
    payload = json.dumps({"agents": [{"name": "scout",
                                      "dispatched": "2026-01-01T00:00:00Z",
                                      "timeout_seconds": 1}]})
    proc = run([bash, os.path.join(REPO_ROOT, "enzymes", "liveness_sentinel.sh"),
                "--check", payload], env=_env(tmp_path, fake_bin))
    assert proc.returncode == 0, proc.stderr
    assert "scout" in proc.stdout


def test_install_uninstall_round_trip_with_store_stub(tmp_path, fake_bin, bash):
    # install.sh rendered no hooks.json; uninstall.sh's manifest validation
    # ran the stub (exit 49) and refused every entry.
    _shim_real_python(fake_bin)
    env = _env(tmp_path, fake_bin)
    home = tmp_path / "home"
    install = os.path.join(REPO_ROOT, "install", "install.sh")
    uninstall = os.path.join(REPO_ROOT, "install", "uninstall.sh")

    proc = run([bash, install, "kiro"], env=env)
    assert proc.returncode == 0, proc.stderr[-800:]
    hooks = home / ".kiro" / "hooks" / "hooks.json"
    assert hooks.exists() and hooks.stat().st_size > 0, proc.stdout[-800:]

    proc = run([bash, uninstall, "kiro", "--force", "--no-restore"], env=env)
    assert proc.returncode == 0, proc.stderr[-800:]
    assert not hooks.exists()
    assert not (home / ".soma" / "manifest.json").exists()


# A `python3` in shell command position: start of line or after a shell
# separator / substitution opener. Quoted strings ("python3") don't match.
BARE_PYTHON3 = re.compile(r"(?:^|[\s;&|(`])python3(?=\s|$)")
SHELL_FILES = sorted(
    os.path.join("enzymes", n) for n in os.listdir(os.path.join(REPO_ROOT, "enzymes"))
    if n.endswith(".sh")
) + [os.path.join("install", "install.sh"), os.path.join("install", "uninstall.sh")]


@pytest.mark.parametrize("rel", SHELL_FILES)
def test_shell_scripts_do_not_invoke_bare_python3(rel):
    offenders = []
    for num, line in enumerate(read(os.path.join(REPO_ROOT, rel)).splitlines(), 1):
        code = line.strip()
        if code.startswith("#") or code.startswith("echo ") or "log_" in code:
            continue
        if BARE_PYTHON3.search(line):
            offenders.append(f"{rel}:{num}: {code}")
    assert not offenders, "route through soma_python (BUG-037):\n" + "\n".join(offenders)
