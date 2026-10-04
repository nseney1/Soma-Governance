"""BUG-037: under Git Bash with a python.org install, `python3` can be the
Windows App Installer stub. `command -v python3` succeeds, but running it
prints a Microsoft Store message and exits 49, so every shell-script Python
call failed: hooks.json rendered empty, the MCP config named a command that
can't start, and the safety gate asked about every command.

Each test puts a fake stub first on PATH, which reproduces this on any OS."""
import json
import os
import re
import subprocess
import sys

import pytest

from conftest import REPO_ROOT, run

RESOLVER = os.path.join(REPO_ROOT, "enzymes", "soma_python.sh").replace("\\", "/")
COMMON = os.path.join(REPO_ROOT, "enzymes", "common.sh").replace("\\", "/")
SAFETY_GATE = os.path.join(REPO_ROOT, "enzymes", "safety_gate.sh")
INSTALL_SH = os.path.join(REPO_ROOT, "install", "install.sh")

STUB = ('#!/bin/sh\n'
        'echo "Python was not found; run without arguments to install from the '
        'Microsoft Store, or disable this shortcut" >&2\n'
        'exit 49\n')


def _sh_quote(text):
    return "'" + text.replace("'", "'\\''") + "'"


def _write_exe(path, text):
    # write_bytes, not write_text(newline=): that keyword needs Python 3.10.
    path.write_bytes(text.encode("utf-8"))
    path.chmod(0o755)


def _real(name_args=""):
    """A wrapper that runs this interpreter (optionally dropping `-3`)."""
    drop = '[ "${1:-}" = "-3" ] && shift\n' if name_args == "-3" else ""
    return f'#!/bin/sh\n{drop}exec {_sh_quote(sys.executable)} "$@"\n'


def _bin(tmp_path, python3=STUB, python=None, py=STUB):
    """A PATH directory that shadows python3, python and py."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    _write_exe(d / "python3", python3)
    _write_exe(d / "python", python if python is not None else _real())
    _write_exe(d / "py", py)
    return d


def _env(bin_dir, home=None, **extra):
    # Never inherit a resolution from the shell running the tests.
    env = {"PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
           "SOMA_PYTHON_RESOLVED": ""}
    if home is not None:
        env.update(HOME=str(home), USERPROFILE=str(home))
    env.update(extra)
    return env


def _bash(bash, script, bin_dir, **extra):
    return run([bash, "-c", "unset SOMA_PYTHON SOMA_PYTHON_RESOLVED\n" + script],
               env=_env(bin_dir, **extra))


# ── Resolver ─────────────────────────────────────────────────────────


def test_resolver_skips_the_store_stub(bash, tmp_path):
    bin_dir = _bin(tmp_path)
    proc = _bash(bash, f'. {_sh_quote(RESOLVER)}\nsoma_resolve_python\n'
                       '"$SOMA_PYTHON" -c "import sys; print(sys.version_info[0])"', bin_dir)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "3"


def test_resolver_falls_back_to_the_py_launcher(bash, tmp_path):
    bin_dir = _bin(tmp_path, python=STUB, py=_real("-3"))
    proc = _bash(bash, f'. {_sh_quote(RESOLVER)}\nsoma_resolve_python\n'
                       '"$SOMA_PYTHON" -c "print(42)"', bin_dir)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "42"


def test_resolver_reports_when_no_interpreter_works(bash, tmp_path):
    bin_dir = _bin(tmp_path, python=STUB)
    proc = _bash(bash, f'. {_sh_quote(RESOLVER)}\n'
                       'soma_resolve_python && rc=0 || rc=$?\n'
                       'echo "rc=$rc [${SOMA_PYTHON}]"', bin_dir)
    assert proc.stdout.strip() == "rc=1 []", proc.stdout + proc.stderr


def _resolve_with(bash, bin_dir, **extra):
    return run([bash, "-c", f'. {_sh_quote(RESOLVER)}\n'
                            'soma_resolve_python && rc=0 || rc=$?\n'
                            'printf "rc=%s [%s] resolved=%s" "$rc" "$SOMA_PYTHON" "${SOMA_PYTHON_RESOLVED:-}"'],
               env=_env(bin_dir, **extra))


@pytest.mark.parametrize("which", ["deleted interpreter", "store stub"])
def test_broken_preset_fails_loudly_without_falling_back(bash, tmp_path, which):
    """A preset is an explicit choice: if it doesn't run Python 3.9+, say so
    rather than quietly using another interpreter (maintainer, #81)."""
    bin_dir = _bin(tmp_path)  # a working `python` is on PATH, and must not be used
    if which == "store stub":
        preset = str(bin_dir / "python3").replace("\\", "/")
    else:
        preset = str(tmp_path / "deleted-venv" / "python").replace("\\", "/")
    proc = _resolve_with(bash, bin_dir, SOMA_PYTHON=preset)
    assert proc.stdout == "rc=1 [] resolved=0", proc.stdout + proc.stderr
    assert "SOMA_PYTHON" in proc.stderr and preset in proc.stderr


def test_child_script_does_not_replace_a_rejected_preset(bash, tmp_path):
    """The parent exports an empty SOMA_PYTHON after rejecting the preset; a
    child that then probed would quietly use another interpreter."""
    bin_dir = _bin(tmp_path)  # a working `python` is on PATH
    preset = str(bin_dir / "python3").replace("\\", "/")
    child = (f'. {_sh_quote(RESOLVER)}; soma_resolve_python && rc=0 || rc=$?; '
             'printf "rc=%s [%s]" "$rc" "$SOMA_PYTHON"')
    proc = run([bash, "-c", f'. {_sh_quote(RESOLVER)}\nsoma_resolve_python || true\n'
                            f'bash -c {_sh_quote(child)}'],
               env=_env(bin_dir, SOMA_PYTHON=preset))
    assert proc.stdout == "rc=1 []", proc.stdout + proc.stderr


def test_preset_soma_python_is_kept(bash, tmp_path):
    preset = sys.executable.replace("\\", "/")
    proc = _resolve_with(bash, _bin(tmp_path), SOMA_PYTHON=preset)
    assert proc.stdout == f"rc=0 [{preset}] resolved=1", proc.stderr


def test_resolution_is_marked_for_child_scripts(bash, tmp_path):
    proc = _resolve_with(bash, _bin(tmp_path))
    assert proc.stdout.startswith("rc=0 [") and proc.stdout.endswith("] resolved=1"), proc.stderr


def test_marked_resolution_from_a_parent_is_not_probed_again(bash, tmp_path):
    """Hooks run under tight timeouts, so a child trusts its parent's result.
    The stub stands in for 'anything': it would fail a probe."""
    bin_dir = _bin(tmp_path)
    inherited = str(bin_dir / "python3").replace("\\", "/")
    proc = _resolve_with(bash, bin_dir, SOMA_PYTHON=inherited, SOMA_PYTHON_RESOLVED="1")
    assert proc.stdout == f"rc=0 [{inherited}] resolved=1", proc.stderr


def test_resolver_leaves_stdin_for_the_hook(bash, tmp_path):
    """Hooks read their JSON payload from stdin after resolving."""
    bin_dir = _bin(tmp_path)
    proc = subprocess.run(
        [bash, "-c", f'unset SOMA_PYTHON\n. {_sh_quote(RESOLVER)}\nsoma_resolve_python\ncat'],
        input='{"payload": 1}', capture_output=True, encoding="utf-8", timeout=60,
        env=dict(os.environ, **_env(bin_dir)),
    )
    assert proc.stdout == '{"payload": 1}', proc.stderr


# ── Callers ──────────────────────────────────────────────────────────


def _install_hooks(bash, repo_dir, target, bin_dir):
    return _bash(bash, f'. {_sh_quote(COMMON)}\n'
                       f'install_hooks {_sh_quote(str(repo_dir).replace(chr(92), "/"))} '
                       f'{_sh_quote(str(target).replace(chr(92), "/"))}', bin_dir)


def test_install_hooks_renders_with_the_store_stub(bash, tmp_path):
    bin_dir = _bin(tmp_path)
    target = tmp_path / "hooks"
    proc = _install_hooks(bash, REPO_ROOT, target, bin_dir)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    hooks = json.loads((target / "hooks.json").read_text(encoding="utf-8"))
    command = hooks["safety-gate"]["PreToolUse"][0]["hooks"][0]["command"]
    assert command.endswith("/safety_gate.sh")


def test_install_hooks_writes_utf8_for_a_non_ascii_path(bash, tmp_path):
    """W28: rendered through the default encoding and print(), so a path with
    'é' became cp1252 bytes on Windows and hooks.json wasn't valid UTF-8."""
    bin_dir = _bin(tmp_path)
    repo = tmp_path / "projé"
    (repo / "install").mkdir(parents=True)
    with open(os.path.join(REPO_ROOT, "install", "hooks.json.template"), encoding="utf-8") as f:
        (repo / "install" / "hooks.json.template").write_text(f.read(), encoding="utf-8")
    target = tmp_path / "hooks"
    proc = _install_hooks(bash, repo, target, bin_dir)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    hooks = json.loads((target / "hooks.json").read_bytes().decode("utf-8"))
    assert "projé/enzymes/session_close.sh" in hooks["session-close"]["Stop"][0]["command"]


def _gate(bash, bin_dir, home, command_line):
    payload = json.dumps({"toolCall": {"args": {"CommandLine": command_line}}})
    proc = subprocess.run([bash, SAFETY_GATE], input=payload, capture_output=True, encoding="utf-8",
                          timeout=60, env=dict(os.environ, **_env(bin_dir, home=home)))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_safety_gate_allows_a_harmless_command_with_the_store_stub(bash, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    assert _gate(bash, _bin(tmp_path), home, "ls -la")["decision"] == "allow"


def test_safety_gate_still_stops_rm_rf_home_with_the_store_stub(bash, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    decision = _gate(bash, _bin(tmp_path), home, "rm -rf ~")
    assert decision["decision"] == "force_ask"
    assert "Recursive delete" in decision["reason"]


def test_init_hook_stays_quiet_between_checks_with_the_store_stub(bash, tmp_path):
    """The hook reads invocationNum before sourcing common.sh; if that parse
    fails it falls back to 0 and runs its full check on every model call."""
    home = tmp_path / "home"
    home.mkdir()
    proc = subprocess.run(
        [bash, os.path.join(REPO_ROOT, "enzymes", "immune_init.sh")],
        input='{"invocationNum": 2}', capture_output=True, encoding="utf-8", timeout=60,
        env=dict(os.environ, **_env(_bin(tmp_path), home=home)),
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "{}"
    # The full check also prints {} in an empty home, but reports on stderr.
    assert proc.stderr == ""


def test_sweep_runs_in_an_empty_home_with_the_store_stub(bash, tmp_path):
    """immune_sweep.sh used $RESOLVED_HOME without setting it, so under
    set -u it died at startup with "unbound variable"."""
    home = tmp_path / "home"
    home.mkdir()
    proc = run([bash, os.path.join(REPO_ROOT, "enzymes", "immune_sweep.sh")],
               cwd=str(tmp_path), env=_env(_bin(tmp_path), home=home))
    assert "unbound variable" not in proc.stderr, proc.stderr
    assert proc.returncode == 0, proc.stdout[-1000:] + proc.stderr[-1000:]


# Every variable enzymes/inference_provider.py resolve_provider() reads.
_PROVIDER_ENV = ("SOMA_INFERENCE_PROVIDER", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                 "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL",
                 "GOOGLE_APPLICATION_CREDENTIALS")


def _offline_provider_env(extra):
    """metrics_snapshot.sh runs token_census.py, which resolves an inference
    provider. A test must never reach the developer's real credentials: drop
    every provider variable, use keyring's null backend and pin the offline
    prompt-only provider (its count_tokens is a local estimate)."""
    env = {k: v for k, v in os.environ.items() if k not in _PROVIDER_ENV}
    env.update(extra)
    env.update(SOMA_INFERENCE_PROVIDER="prompt-only",
               PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring")
    return env


def test_metrics_snapshot_reads_utf8_skill_files(bash, tmp_path):
    """It opened organs/staff-review/SKILL.md in the locale encoding, so on
    Windows (cp1252) it crashed with UnicodeDecodeError."""
    home = tmp_path / "home"
    home.mkdir()
    # Not conftest.run(): that merges os.environ, so it can't remove keys.
    proc = subprocess.run(
        [bash, os.path.join(REPO_ROOT, "enzymes", "metrics_snapshot.sh")],
        cwd=str(tmp_path), stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=120, env=_offline_provider_env(_env(_bin(tmp_path), home=home)))
    assert "UnicodeDecodeError" not in proc.stderr, proc.stderr[-1000:]
    assert proc.returncode == 0, proc.stderr[-1000:]


def test_cell_signal_records_an_outcome_with_the_store_stub(bash, tmp_path):
    """cell_signal.sh sourced common.sh from a scripts/ directory that doesn't
    exist, so nothing set up Python before its helper ran."""
    project = tmp_path / "project"
    cells = project / ".soma" / "cells"
    cells.mkdir(parents=True)
    with open(os.path.join(REPO_ROOT, ".soma", "cells", "walls", "trap-path-traversal.md"),
              encoding="utf-8") as f:
        original = f.read()
    cell = cells / "trap-path-traversal.md"
    cell.write_text(original, encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    proc = run([bash, os.path.join(REPO_ROOT, "enzymes", "cell_signal.sh"),
                "trap-path-traversal", "tp"],
               cwd=str(project), env=_env(_bin(tmp_path), home=home, SOMA_ROOT=""))
    assert "command not found" not in proc.stderr, proc.stderr
    assert proc.returncode == 0, proc.stdout[-1000:] + proc.stderr[-1000:]
    assert "tp recorded" in proc.stdout
    assert cell.read_text(encoding="utf-8") != original


def test_pre_commit_warns_when_the_resolver_is_missing(bash, tmp_path):
    """An older vendored enzymes/ with a newer hook used to skip silently."""
    (tmp_path / "enzymes").mkdir()
    proc = run([bash, os.path.join(REPO_ROOT, "install", "hooks", "pre-commit")],
               cwd=str(tmp_path), env=_env(_bin(tmp_path)))
    assert proc.returncode == 0, proc.stderr
    assert "soma_python.sh" in proc.stderr


def _install_mcp(bash, bin_dir, tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    proc = run([bash, INSTALL_SH, "mcp"], cwd=str(project),
               env=_env(bin_dir, home=home, SOMA_PYTHON=""))
    assert proc.returncode == 0, proc.stdout[-1000:] + proc.stderr[-1000:]
    return json.loads((project / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["soma"]


def test_mcp_config_is_merged_with_the_store_stub_and_names_python3(bash, tmp_path):
    """The merge itself runs through the resolver, so it no longer fails on
    the stub. The config always says python3: a resolved path would pin an
    interpreter that upgrades or removal break, and differ between machines;
    `soma doctor` reports the stub instead (maintainer's decision, #81)."""
    soma = _install_mcp(bash, _bin(tmp_path), tmp_path)
    assert soma["command"] == "python3"


# ── Every call site ──────────────────────────────────────────────────

# soma_python.sh is the one place that probes python3.
SHELL_SOURCES = (
    [os.path.join("enzymes", f) for f in sorted(os.listdir(os.path.join(REPO_ROOT, "enzymes")))
     if f.endswith(".sh") and f != "soma_python.sh"]
    + [os.path.join("install", f) for f in ("install.sh", "uninstall.sh")]
    + [os.path.join("install", "hooks", "pre-commit"), "Makefile"]
)
# python3 run with arguments, probed with `command -v`, or named in an argv
# list inside embedded Python.
BARE_PYTHON3 = re.compile(
    r"""\bpython3\s+(-|"|'|\$)|command\s+-v\s+python3\b|\[\s*['"]python3['"]\s*,""")


def test_no_shell_script_runs_python3_directly():
    hits = []
    for rel in SHELL_SOURCES:
        with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
            for number, line in enumerate(f, 1):
                # Comments and messages may name python3 (e.g. the manual
                # `claude mcp add soma python3 -m soma_mcp` hint).
                if line.lstrip().startswith(("#", "echo ", "log_")):
                    continue
                if BARE_PYTHON3.search(line):
                    hits.append(f"{rel}:{number}: {line.strip()}")
    assert hits == []


# A top-level source of the resolver (or common.sh, which sources it), anchored
# to the script's own location rather than the current directory.
ANCHORED_SOURCE = re.compile(
    r'^source "(\$\(dirname "\$\{BASH_SOURCE\[0\]\}"\)|\$\(dirname "\$0"\)'
    r'|\$SCRIPTS?_DIR|\$DIR|\$REPO_DIR)/(enzymes/)?(soma_python|common)\.sh"')


def test_every_soma_py_caller_sources_the_resolver_first():
    """cell_signal, cell_create and cell_transfer called soma_py after a
    conditional, cwd-relative source of common.sh that usually didn't run."""
    missing = []
    for rel in SHELL_SOURCES:
        if rel == "Makefile" or rel.endswith("common.sh"):
            continue
        with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
            lines = f.read().splitlines()
        first_use = next((n for n, line in enumerate(lines)
                          if re.search(r"\bsoma_py\b", line) and not line.lstrip().startswith("#")),
                         None)
        if first_use is None:
            continue
        if not any(ANCHORED_SOURCE.match(line) for line in lines[:first_use]):
            missing.append(f"{rel}:{first_use + 1}")
    assert missing == []


# ── Python entry points that name an interpreter ─────────────────────


def test_soma_init_mcp_config_names_python3_with_the_store_stub(tmp_path, monkeypatch):
    """Same rule as install.sh: always python3, even when it is the stub."""
    from soma_cli.init import generate_mcp_config
    stub_dir = tmp_path / "pybin"
    stub_dir.mkdir()
    _write_exe(stub_dir / "python3", STUB)
    (stub_dir / "python3.bat").write_text("@exit /b 49\r\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(stub_dir))
    generate_mcp_config(tmp_path)
    data = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert data["mcpServers"]["soma"]["command"] == "python3"


PYTHON_SOURCES = [
    os.path.join(directory, name)
    for directory in ("enzymes", "soma_cli", "soma_mcp", "soma_core", "soma_sdk",
                      os.path.join("immune_system", "verification"))
    for name in sorted(os.listdir(os.path.join(REPO_ROOT, directory)))
    if name.endswith(".py")
]


def test_no_python_code_spawns_python3_by_name():
    """subprocess argv lists should use sys.executable; generated gate code
    in cell_enforce.py spawned 'python3'."""
    hits = []
    for rel in PYTHON_SOURCES:
        with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
            for number, line in enumerate(f, 1):
                if re.search(r"""\[\s*['"]python3['"]\s*,""", line):
                    hits.append(f"{rel}:{number}: {line.strip()}")
    assert hits == []


def test_generated_gate_assertion_compiles():
    sys.path.insert(0, os.path.join(REPO_ROOT, "enzymes"))
    try:
        from cell_enforce import generate_gate_assertion
    finally:
        sys.path.pop(0)
    source = generate_gate_assertion(
        {"_name": "demo-gate", "type": "wall", "hypothesis": "h", "target_paths": ["a.py"]},
        str(REPO_ROOT))
    compile(source, "demo_gate.py", "exec")
    assert "import sys" in source and "sys.executable" in source


# ── Install/uninstall round trip (v0.90 lane, ported onto #81) ───────


def test_enzyme_without_common_sh_survives_the_store_stub(bash, tmp_path):
    """liveness_sentinel.sh called python3 directly and exited 49."""
    home = tmp_path / "home"
    home.mkdir()
    payload = json.dumps({"agents": [{"name": "scout", "dispatched": "2026-01-01T00:00:00Z",
                                      "timeout_seconds": 1}]})
    proc = run([bash, os.path.join(REPO_ROOT, "enzymes", "liveness_sentinel.sh"),
                "--check", payload], cwd=str(tmp_path),
               env=_env(_bin(tmp_path), home=home, SOMA_PYTHON=""))
    assert proc.returncode == 0, proc.stderr
    assert "scout" in proc.stdout


def test_install_uninstall_round_trip_with_the_store_stub(bash, tmp_path):
    """install.sh rendered no hooks.json; uninstall.sh's manifest validation
    ran the stub (exit 49) and refused every entry."""
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    env = _env(_bin(tmp_path), home=home, SOMA_PYTHON="")
    proc = run([bash, INSTALL_SH, "kiro"], cwd=str(project), env=env)
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
    hooks = home / ".kiro" / "hooks" / "hooks.json"
    assert hooks.exists() and hooks.stat().st_size > 0, proc.stdout[-800:]
    proc = run([bash, os.path.join(REPO_ROOT, "install", "uninstall.sh"), "kiro",
                "--force", "--no-restore"], cwd=str(project), env=env)
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
    assert not hooks.exists()
    assert not (home / ".soma" / "manifest.json").exists()
