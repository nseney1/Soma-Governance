"""Red-team follow-ups to BUG-037/BUG-043 (v0.90 hardening).

- BUG-044: inline `python -c` / `python -` put the CWD on sys.path[0], so a
  json.py in the user's project (hooks run there; uninstall runs anywhere)
  executed inside every enzyme, install and uninstall snippet. soma_py now
  drops the CWD entry for inline code; it does NOT use -I, which would also
  hide user site-packages (a `pip --user` PyYAML on Windows).
- BUG-045: the Claude settings.json cleanup in uninstall.sh bypassed the
  confinement guard, the plan preview and --dry-run, followed symlinks and
  wrote a predictable, non-exclusive temp file.
- A project-level `.soma` that is a symlink redirected manifest removal
  outside the project. Run from $HOME, `./.soma` is the home manifest.
- install_hooks: temp cleanup on signals; existing hooks.json mode kept.
- immune_sweep.sh word-split transcript paths containing spaces.
- session_close.sh sourced common.sh via a lexical dirname (symlink-unsafe).

Every subprocess runs with HOME and USERPROFILE isolated in tmp (BUG-010).
"""
import json
import os
import shutil
import stat
import sys

import pytest

from conftest import REPO_ROOT, read, run, symlink_or_skip

ENZYMES = os.path.join(REPO_ROOT, "enzymes")
INSTALL = os.path.join(REPO_ROOT, "install", "install.sh")
UNINSTALL = os.path.join(REPO_ROOT, "install", "uninstall.sh")
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="POSIX modes/signals/shims")


def _env(tmp_path, **extra):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    # SOMA_PYTHON_RESOLVED="": never inherit a resolution from the test shell.
    env = {"HOME": str(home), "USERPROFILE": str(home), "SOMA_PYTHON": sys.executable,
           "SOMA_PYTHON_RESOLVED": ""}
    env.update(extra)
    return env


def _write_exe(path, body):
    # write_bytes, not write_text(newline=): that keyword needs Python 3.10.
    path.write_bytes(("#!/bin/sh\n" + body + "\n").encode("utf-8"))
    path.chmod(0o755)


# ── BUG-044: CWD module hijack via inline Python ───────────────────────────

def _evil_dir(tmp_path, name="evil"):
    d = tmp_path / name
    d.mkdir()
    marker = tmp_path / "HIJACKED"
    (d / "json.py").write_text(
        "open(%r, 'a').write('pwned\\n')\n" % str(marker), encoding="utf-8")
    return d, marker


def _fake_repo(tmp_path, template_text='{"cmd": "{{SCRIPTS_DIR}}/x.sh"}'):
    repo = tmp_path / "repo"
    (repo / "install").mkdir(parents=True)
    (repo / "enzymes").mkdir()
    (repo / "install" / "hooks.json.template").write_text(template_text, encoding="utf-8")
    return repo


def test_install_hooks_ignores_cwd_modules(tmp_path, bash):
    evil, marker = _evil_dir(tmp_path)
    repo = _fake_repo(tmp_path)
    target = tmp_path / "out"
    script = f'source "{ENZYMES}/common.sh"; install_hooks "{repo}" "{target}"'
    proc = run([bash, "-c", script], cwd=str(evil), env=_env(tmp_path))
    assert not marker.exists(), "json.py from the CWD was executed"
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(read(str(target / "hooks.json")))["cmd"].endswith("/x.sh")


def test_hook_enzyme_ignores_cwd_modules(tmp_path, bash):
    evil, marker = _evil_dir(tmp_path)
    payload = tmp_path / "stdin.json"
    payload.write_text(json.dumps({"toolCall": {"args": {"CommandLine": "ls"}}}),
                       encoding="utf-8")
    with open(str(payload), "rb") as stdin:
        proc = run([bash, os.path.join(ENZYMES, "safety_gate.sh")], cwd=str(evil),
                   env=_env(tmp_path), stdin=stdin)
    assert not marker.exists(), "json.py from the hook CWD was executed"
    assert '"allow"' in proc.stdout, proc.stdout + proc.stderr


def test_install_and_uninstall_ignore_cwd_modules(tmp_path, bash):
    evil, marker = _evil_dir(tmp_path)
    env = _env(tmp_path)
    proc = run([bash, INSTALL, "mcp"], cwd=str(evil), env=env)
    assert not marker.exists(), "install.sh executed json.py from the CWD"
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
    assert (evil / ".soma" / "manifest.json").exists()
    proc = run([bash, UNINSTALL, "mcp", "--force", "--no-restore", "--keep-config"],
               cwd=str(evil), env=env)
    assert not marker.exists(), "uninstall.sh executed json.py from the CWD"
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
    assert not (evil / ".soma" / "manifest.json").exists()


@POSIX_ONLY
@pytest.mark.parametrize("has_pkg", [True, False])
def test_mcp_probe_still_sees_workspace_package(tmp_path, bash, has_pkg):
    """The soma_mcp probe is the intentional exception: it must still find a
    workspace-local soma_mcp (no PYTHONPATH fallback), and add the fallback
    when there is none -- without importing json.py from the workspace."""
    ws, marker = _evil_dir(tmp_path, "ws")
    imported = tmp_path / "IMPORTED"
    if has_pkg:
        (ws / "soma_mcp").mkdir()
        (ws / "soma_mcp" / "__init__.py").write_text(
            "import json\nopen(%r, 'w').write('x')\n" % str(imported), encoding="utf-8")
    # -S (and an empty PYTHONPATH) hide any other soma_mcp so only the
    # workspace can satisfy it.
    shim = tmp_path / "py"
    _write_exe(shim, f'exec "{sys.executable}" -S "$@"')
    proc = run([bash, INSTALL, "mcp"], cwd=str(ws),
               env=_env(tmp_path, SOMA_PYTHON=str(shim), PYTHONPATH=""))
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
    assert not marker.exists(), "probe executed json.py from the workspace"
    server_env = json.loads(read(str(ws / ".mcp.json")))["mcpServers"]["soma"]["env"]
    if has_pkg:
        assert "PYTHONPATH" not in server_env, "workspace soma_mcp should satisfy probe without PYTHONPATH fallback"
    else:
        assert server_env.get("PYTHONPATH") == REPO_ROOT


def test_inline_enzyme_ignores_cwd_modules(tmp_path, bash):
    """immune_init.sh parses its stdin payload with inline `-c` Python."""
    evil, marker = _evil_dir(tmp_path)
    payload = tmp_path / "stdin.json"
    payload.write_text('{"invocationNum": 2}', encoding="utf-8")
    with open(str(payload), "rb") as stdin:
        proc = run([bash, os.path.join(ENZYMES, "immune_init.sh")], cwd=str(evil),
                   env=_env(tmp_path), stdin=stdin)
    assert not marker.exists(), "json.py from the hook CWD was executed"
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_uninstall_manifest_reader_ignores_cwd_modules(tmp_path, bash):
    """read_manifest_field runs inline Python with CWD = the project."""
    evil, marker = _evil_dir(tmp_path)
    _manifest(evil / ".soma", platform="mcp")
    proc = run([bash, UNINSTALL, "mcp", "--dry-run", "--keep-config"],
               cwd=str(evil), env=_env(tmp_path))
    assert not marker.exists(), "uninstall manifest reader executed json.py from the CWD"
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]


def test_soma_py_drops_the_cwd_only_for_inline_code(tmp_path, bash):
    evil, marker = _evil_dir(tmp_path)
    script_py = tmp_path / "s.py"
    script_py.write_text("import os, sys\n"
                         "print(int(sys.path[0] == os.path.dirname(os.path.abspath(__file__))))\n",
                         encoding="utf-8")
    sh = (f'source "{ENZYMES}/soma_python.sh"; soma_resolve_python; '
          f'soma_py -c "import json, sys; print(int(\'\' in sys.path), sys.flags.isolated, sys.argv[1:])" a "b c"; '
          f'printf "%s\\n" "import json, sys" "print(int(\'\' in sys.path), sys.flags.isolated, sys.argv[1:])" '
          f'| soma_py - x; '
          f'soma_py "{script_py}"')
    proc = run([bash, "-c", sh], cwd=str(evil), env=_env(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == ["0 0 ['a', 'b c']", "0 0 ['x']", "1"], proc.stdout
    assert not marker.exists()


def test_inline_code_still_sees_user_site_packages(tmp_path, bash):
    """The reason BUG-044 is not fixed with -I: that also drops user
    site-packages, where Windows users often have `pip install --user` PyYAML."""
    user_base = tmp_path / "userbase"
    env = _env(tmp_path, PYTHONUSERBASE=str(user_base), PYTHONNOUSERSITE="")
    probe = run([sys.executable, "-c", "import site; print(int(site.ENABLE_USER_SITE)); "
                 "print(site.getusersitepackages())"], env=env)
    enabled, user_site = probe.stdout.splitlines()
    if enabled != "1":
        pytest.skip("user site-packages disabled for this interpreter (venv?)")
    os.makedirs(user_site)
    with open(os.path.join(user_site, "soma_usersite_probe.py"), "w", encoding="utf-8") as f:
        f.write("VALUE = 'from-user-site'\n")
    sh = (f'source "{ENZYMES}/soma_python.sh"; soma_resolve_python; '
          f'soma_py -c "import soma_usersite_probe as m; print(m.VALUE)"; '
          f'echo "import soma_usersite_probe as m; print(m.VALUE)" | soma_py -')
    proc = run([bash, "-c", sh], cwd=str(tmp_path), env=env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == ["from-user-site", "from-user-site"], proc.stdout + proc.stderr


# ── BUG-045: Claude settings.json cleanup ──────────────────────────────────

SETTINGS = {"hooks": {"soma": {"cmd": "x"}, "other": {"cmd": "y"}}, "keep": 1}


def _settings(path, mode=0o640):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(SETTINGS), encoding="utf-8")
    path.chmod(mode)
    return path


def _uninstall_claude(bash, tmp_path, proj, *extra):
    return run([bash, UNINSTALL, "claude", "--force", "--no-restore",
                "--keep-config", *extra], cwd=str(proj), env=_env(tmp_path))


@POSIX_ONLY
def test_settings_cleanup_removes_soma_hooks_and_keeps_mode(tmp_path, bash):
    proj = tmp_path / "proj"
    proj.mkdir()
    home_settings = _settings(tmp_path / "home" / ".claude" / "settings.json", 0o640)
    proj_settings = _settings(proj / ".claude" / "settings.json", 0o600)
    proc = _uninstall_claude(bash, tmp_path, proj)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for path, mode in ((home_settings, 0o640), (proj_settings, 0o600)):
        data = json.loads(read(str(path)))
        assert "soma" not in data["hooks"], path
        assert data["hooks"]["other"] == {"cmd": "y"} and data["keep"] == 1
        assert stat.S_IMODE(path.stat().st_mode) == mode, path
        assert sorted(os.listdir(str(path.parent))) == ["settings.json"], "temp left"


@POSIX_ONLY
def test_settings_cleanup_refuses_symlinked_file(tmp_path, bash):
    proj = tmp_path / "proj"
    proj.mkdir()
    outside = _settings(tmp_path / "outside" / "settings.json")
    before = read(str(outside))
    link = tmp_path / "home" / ".claude" / "settings.json"
    link.parent.mkdir(parents=True)
    symlink_or_skip(outside, link)
    proc = _uninstall_claude(bash, tmp_path, proj)
    assert link.is_symlink(), "symlink was replaced"
    assert read(str(outside)) == before, "file outside HOME was rewritten"
    assert "symlink" in (proc.stdout + proc.stderr)


@POSIX_ONLY
def test_settings_cleanup_refuses_symlinked_claude_dir(tmp_path, bash):
    proj = tmp_path / "proj"
    proj.mkdir()
    outside = _settings(tmp_path / "outside" / "settings.json")
    before = read(str(outside))
    symlink_or_skip(outside.parent, proj / ".claude")
    _uninstall_claude(bash, tmp_path, proj)
    assert read(str(outside)) == before, "file behind a symlinked .claude was rewritten"
    assert sorted(os.listdir(str(outside.parent))) == ["settings.json"]


@POSIX_ONLY
def test_settings_cleanup_dry_run_previews_and_changes_nothing(tmp_path, bash):
    proj = tmp_path / "proj"
    proj.mkdir()
    path = _settings(tmp_path / "home" / ".claude" / "settings.json")
    before = read(str(path))
    proc = _uninstall_claude(bash, tmp_path, proj, "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert read(str(path)) == before
    assert str(path) in proc.stdout, "settings.json missing from the plan preview"


# ── Project-level .soma symlink: manifest removal ─────────────────────────

def _manifest(d, platform="kiro"):
    d.mkdir(parents=True, exist_ok=True)
    m = d / "manifest.json"
    m.write_text(json.dumps({"platform": platform, "files": [], "organs": [],
                             "hooks": [], "mcp_configs": []}), encoding="utf-8")
    return m


@POSIX_ONLY
def test_project_soma_symlink_manifest_is_not_removed(tmp_path, bash):
    proj = tmp_path / "proj"
    proj.mkdir()
    outside = _manifest(tmp_path / "outside")
    symlink_or_skip(outside.parent, proj / ".soma")
    proc = run([bash, UNINSTALL, "kiro", "--force", "--no-restore", "--keep-config"],
               cwd=str(proj), env=_env(tmp_path))
    assert outside.exists(), "manifest outside the project was deleted"
    assert proc.returncode != 0
    assert "symlink" in proc.stderr, proc.stderr


@POSIX_ONLY
def test_home_soma_symlink_manifest_is_still_removed(tmp_path, bash):
    proj = tmp_path / "proj"
    proj.mkdir()
    dotfiles = _manifest(tmp_path / "dotfiles" / "soma")
    (tmp_path / "home").mkdir()
    symlink_or_skip(dotfiles.parent, tmp_path / "home" / ".soma")
    proc = run([bash, UNINSTALL, "kiro", "--force", "--no-restore", "--keep-config"],
               cwd=str(proj), env=_env(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not dotfiles.exists(), "user-controlled ~/.soma symlink manifest kept"


def test_uninstall_from_home_treats_dot_soma_as_the_home_manifest(tmp_path, bash):
    """Run from $HOME, ./.soma/manifest.json IS ~/.soma/manifest.json: it must
    keep the home roots, not be confined as a project-local manifest."""
    home = tmp_path / "home"
    home.mkdir()
    _manifest(home / ".soma")
    proc = run([bash, UNINSTALL, "kiro", "--force", "--no-restore", "--keep-config"],
               cwd=str(home), env=_env(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (home / ".soma" / "manifest.json").exists()


@POSIX_ONLY
def test_uninstall_from_home_allows_a_symlinked_home_soma(tmp_path, bash):
    """...including when ~/.soma is a symlink (here into HOME itself): the
    project-level symlink refusal must not fire for the home directory."""
    home = tmp_path / "home"
    home.mkdir()
    real = _manifest(home / "dotfiles" / "soma")
    symlink_or_skip(real.parent, home / ".soma")
    proc = run([bash, UNINSTALL, "kiro", "--force", "--no-restore", "--keep-config"],
               cwd=str(home), env=_env(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "symlink" not in proc.stderr, proc.stderr
    assert not real.exists(), "home manifest behind a symlinked ~/.soma was kept"


# ── install_hooks: mode preservation and signal cleanup ───────────────────

@POSIX_ONLY
def test_install_hooks_preserves_existing_mode(tmp_path, bash):
    repo = _fake_repo(tmp_path)
    target = tmp_path / "out"
    target.mkdir()
    (target / "hooks.json").write_text("{}", encoding="utf-8")
    (target / "hooks.json").chmod(0o600)
    script = f'umask 022; source "{ENZYMES}/common.sh"; install_hooks "{repo}" "{target}"'
    proc = run([bash, "-c", script], env=_env(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert stat.S_IMODE((target / "hooks.json").stat().st_mode) == 0o600
    assert "x.sh" in read(str(target / "hooks.json"))


@POSIX_ONLY
def test_install_hooks_removes_temp_on_term(tmp_path, bash):
    """The renderer finishes writing the temp file, then the shell running
    install_hooks gets SIGTERM before the mv: no temp may be left behind and
    the existing hooks.json must be untouched."""
    repo = _fake_repo(tmp_path)
    target = tmp_path / "out"
    target.mkdir()
    (target / "hooks.json").write_text('{"orig": 1}', encoding="utf-8")
    shim = tmp_path / "py"
    _write_exe(shim, (
        'case "$*" in *.hooks.json.*)\n'
        f'  "{sys.executable}" "$@"; rc=$?; kill -TERM $PPID; exit $rc;;\n'
        'esac\n'
        f'exec "{sys.executable}" "$@"'))
    script = (f'source "{ENZYMES}/common.sh"; trap "echo CALLER_TRAP" EXIT; '
              f'install_hooks "{repo}" "{target}"; echo "rc=$?"')
    proc = run([bash, "-c", script], env=_env(tmp_path, SOMA_PYTHON=str(shim)))
    assert sorted(os.listdir(str(target))) == ["hooks.json"], "temp file left behind"
    assert read(str(target / "hooks.json")) == '{"orig": 1}'
    assert "CALLER_TRAP" in proc.stdout, "caller's EXIT trap was clobbered"


# ── immune_sweep.sh: transcript paths with spaces ─────────────────────────

def test_immune_sweep_handles_spaces_in_brain_dir(tmp_path, bash):
    data = tmp_path / "data dir"
    logs = data / "brain" / "abcdef12-session" / ".system_generated" / "logs"
    logs.mkdir(parents=True)
    (logs / "transcript.jsonl").write_text(
        "\n".join(json.dumps({"step_index": i, "type": "PLANNER_RESPONSE"})
                  for i in range(60)) + "\n", encoding="utf-8")
    proc = run([bash, os.path.join(ENZYMES, "immune_sweep.sh"), "--active-only"],
               cwd=str(tmp_path), env=_env(tmp_path, SOMA_DATA_DIR=str(data)))
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
    assert "abcdef12: 60 steps" in proc.stdout, proc.stdout[-800:] + proc.stderr[-800:]


# ── session_close.sh: symlink-safe common.sh sourcing ─────────────────────

def test_session_close_via_symlink_sources_common(tmp_path, bash):
    # A copy outside any git checkout: session_close commits+pushes a dirty
    # steering repo, which must never be this one.
    fake = tmp_path / "fake" / "enzymes"
    fake.mkdir(parents=True)
    for name in ("session_close.sh", "common.sh", "soma_python.sh"):
        shutil.copy(os.path.join(ENZYMES, name), str(fake / name))
    links = tmp_path / "links"
    links.mkdir()
    symlink_or_skip(fake / "session_close.sh", links / "session_close.sh")
    proj = tmp_path / "proj"
    proj.mkdir()
    proc = run([bash, str(links / "session_close.sh")], cwd=str(proj), env=_env(tmp_path))
    assert "No such file" not in proc.stderr, proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr
