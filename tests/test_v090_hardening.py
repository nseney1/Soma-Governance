"""v0.90 hardening follow-ups to BUG-037 (#81's enzymes/soma_python.sh).

- cell_transfer.sh read an unset $REPO_DIR (aborts under common.sh's set -u).
- BUG-042: immune_sweep.sh read an unset $RESOLVED_HOME (fixed by #81).
- cell_create/cell_transfer/cell_signal located common.sh via a lexical
  dirname, so invoking them through a symlink could not find it.
- install_hooks truncated hooks.json before rendering, and read the template
  in the locale encoding.
- BUG-043: manifestless uninstall fell back to a lexical (symlink-blind)
  confinement check when no working Python 3 existed. It must fail closed.

Every subprocess runs with HOME and USERPROFILE isolated in tmp (BUG-010).
"""
import json
import os
import stat
import subprocess
import sys

import pytest

from conftest import REPO_ROOT, read, run, symlink_or_skip

STORE_STUB_EXIT = 49
ENZYMES = os.path.join(REPO_ROOT, "enzymes")


def _write_exe(path, body):
    # write_bytes, not write_text(newline=): that keyword needs Python 3.10.
    path.write_bytes(("#!/bin/sh\n" + body + "\n").encode("utf-8"))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _env(tmp_path, **extra):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    # SOMA_PYTHON_RESOLVED="": never inherit a resolution from the test shell.
    env = {"HOME": str(home), "USERPROFILE": str(home), "SOMA_PYTHON": sys.executable,
           "SOMA_PYTHON_RESOLVED": ""}
    env.update(extra)
    return env


def _snapshot(root):
    out = {}
    for dirpath, _dirs, files in os.walk(str(root)):
        for name in files:
            p = os.path.join(dirpath, name)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, str(root))] = fh.read()
    return out


# ── cell_transfer.sh: repo root resolution ─────────────────────────────────

CELL = """---
id: vac-transfer-me
type: vacuole
fitness:
  triggers: 7
  true_positives: 3
---
# Vacuole: transfer me
"""


@pytest.fixture
def projects(tmp_path):
    pytest.importorskip("yaml")  # the transfer helper itself needs PyYAML
    src = tmp_path / "src"
    (src / ".soma" / "cells" / "vacuoles").mkdir(parents=True)
    (src / ".soma" / "cells" / "vacuoles" / "vac-transfer-me.md").write_text(
        CELL, encoding="utf-8")
    (src / "sub" / "dir").mkdir(parents=True)
    dst = tmp_path / "dst"
    (dst / ".soma").mkdir(parents=True)
    return src, dst


def _assert_transferred(src, dst, cwd):
    out = dst / ".soma" / "cells" / "vacuoles" / "vac-transfer-me.md"
    assert out.exists(), "cell was not copied"
    assert "true_positives: 0" in read(str(out))
    log = src / ".soma" / "metrics" / "transfers.jsonl"
    assert log.exists(), "transfer was not logged in the source project"
    if cwd != src:
        assert not (cwd / ".soma").exists(), "metrics written relative to CWD"


def test_cell_transfer_resolves_repo_from_subdirectory(tmp_path, projects, bash):
    src, dst = projects
    cwd = src / "sub" / "dir"
    proc = run([bash, os.path.join(ENZYMES, "cell_transfer.sh"), "transfer-me",
                "--to", str(dst)], cwd=str(cwd), env=_env(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "unbound variable" not in proc.stderr
    _assert_transferred(src, dst, cwd)


def test_cell_transfer_honours_soma_root(tmp_path, projects, bash):
    src, dst = projects
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    proc = run([bash, os.path.join(ENZYMES, "cell_transfer.sh"), "transfer-me",
                "--to", str(dst)], cwd=str(elsewhere),
               env=_env(tmp_path, SOMA_ROOT=str(src)))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    _assert_transferred(src, dst, elsewhere)


def test_cell_transfer_without_a_project_fails_clearly(tmp_path, bash):
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    dst = tmp_path / "dst"
    (dst / ".soma").mkdir(parents=True)
    proc = run([bash, os.path.join(ENZYMES, "cell_transfer.sh"), "x",
                "--to", str(dst)], cwd=str(nowhere), env=_env(tmp_path, SOMA_ROOT=""))
    assert proc.returncode != 0
    assert "unbound variable" not in proc.stderr
    assert ".soma" in proc.stderr and "SOMA_ROOT" in proc.stderr, proc.stderr


# ── BUG-042: immune_sweep.sh without SOMA_DATA_DIR ─────────────────────────

def test_immune_sweep_runs_without_soma_data_dir(tmp_path, bash):
    env = _env(tmp_path)
    full_env = dict(os.environ)
    full_env.pop("SOMA_DATA_DIR", None)
    full_env.update(env)
    proc = subprocess.run(
        [bash, os.path.join(ENZYMES, "immune_sweep.sh")], cwd=str(tmp_path),
        env=full_env, stdin=subprocess.DEVNULL, capture_output=True,
        encoding="utf-8", errors="replace", timeout=120)
    assert "unbound variable" not in proc.stderr, proc.stderr
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
    # The default data dir lives under the isolated home, never the real one.
    assert (tmp_path / "home" / ".gemini" / "antigravity").exists()


# ── Symlink-safe self-location ─────────────────────────────────────────────

@pytest.fixture
def link_dir(tmp_path):
    d = tmp_path / "links"
    d.mkdir()
    return d


def _link(link_dir, name):
    link = link_dir / name
    symlink_or_skip(os.path.join(ENZYMES, name), link)
    return str(link)


def test_cell_create_via_symlink(tmp_path, link_dir, bash):
    proj = tmp_path / "proj"
    (proj / ".soma" / "cells").mkdir(parents=True)
    proc = run([bash, _link(link_dir, "cell_create.sh"), "--type", "vacuole",
                "--hypothesis", "linked", "--id", "vac-linked"],
               cwd=str(proj), env=_env(tmp_path))
    assert "No such file" not in proc.stderr, proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert list((proj / ".soma" / "cells").rglob("*vac-linked*"))


def test_cell_transfer_via_symlink(tmp_path, projects, link_dir, bash):
    src, dst = projects
    proc = run([bash, _link(link_dir, "cell_transfer.sh"), "transfer-me",
                "--to", str(dst)], cwd=str(src), env=_env(tmp_path))
    assert "No such file" not in proc.stderr, proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr
    _assert_transferred(src, dst, src)


def test_cell_signal_via_symlink(tmp_path, link_dir, bash):
    proj = tmp_path / "proj"
    (proj / ".soma" / "cells").mkdir(parents=True)
    proc = run([bash, _link(link_dir, "cell_signal.sh")], cwd=str(proj),
               env=_env(tmp_path))
    assert "No such file" not in proc.stderr, proc.stderr
    assert proc.returncode == 2, proc.stdout + proc.stderr  # usage, not a crash
    assert "Usage" in proc.stdout


# ── install_hooks: encoding and atomic render ──────────────────────────────

def _fake_repo(tmp_path, template_text):
    repo = tmp_path / "repo"
    (repo / "install").mkdir(parents=True)
    (repo / "enzymes").mkdir()
    tpl = repo / "install" / "hooks.json.template"
    tpl.write_text(template_text, encoding="utf-8")
    return repo, tpl


def _install_hooks(bash, tmp_path, repo, target, **extra):
    script = (f'source "{ENZYMES}/common.sh"; '
              f'install_hooks "{repo}" "{target}"')
    return run([bash, "-c", script], env=_env(tmp_path, **extra))


def test_install_hooks_renders_utf8_template_under_ascii_locale(tmp_path, bash):
    repo, _ = _fake_repo(
        tmp_path, '{"hooks": [{"name": "gate \u2705", "cmd": "{{SCRIPTS_DIR}}/x.sh"}]}')
    target = tmp_path / "out"
    proc = _install_hooks(bash, tmp_path, repo, target, LC_ALL="C", LANG="C",
                          PYTHONUTF8="0", PYTHONCOERCECLOCALE="0",
                          PYTHONIOENCODING="")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(read(str(target / "hooks.json")))
    assert data["hooks"][0]["name"] == "gate \u2705"
    assert data["hooks"][0]["cmd"] == str(repo / "enzymes").replace("\\", "/") + "/x.sh"


ORIGINAL_HOOKS = '{"hooks": "original"}\n'


def _existing_target(tmp_path):
    target = tmp_path / "out"
    target.mkdir()
    (target / "hooks.json").write_text(ORIGINAL_HOOKS, encoding="utf-8")
    return target


def test_install_hooks_invalid_render_keeps_existing_hooks(tmp_path, bash):
    repo, _ = _fake_repo(tmp_path, '{ not json {{SCRIPTS_DIR}}')
    target = _existing_target(tmp_path)
    proc = _install_hooks(bash, tmp_path, repo, target)
    assert proc.returncode != 0
    assert read(str(target / "hooks.json")) == ORIGINAL_HOOKS
    assert os.listdir(str(target)) == ["hooks.json"], "temp file left behind"


def test_install_hooks_failed_render_keeps_existing_hooks(tmp_path, bash):
    if os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0):
        pytest.skip("needs POSIX permissions enforced for this user")
    repo, tpl = _fake_repo(tmp_path, '{"cmd": "{{SCRIPTS_DIR}}"}')
    tpl.chmod(0)  # rendering (the read) fails; the -f existence check passes
    target = _existing_target(tmp_path)
    try:
        proc = _install_hooks(bash, tmp_path, repo, target)
    finally:
        tpl.chmod(0o644)
    assert proc.returncode != 0
    assert read(str(target / "hooks.json")) == ORIGINAL_HOOKS
    assert os.listdir(str(target)) == ["hooks.json"], "temp file left behind"


# ── BUG-043: manifestless uninstall fails closed without Python ────────────

def test_manifestless_uninstall_without_python_removes_nothing(tmp_path, bash):
    if os.name == "nt":
        pytest.skip("POSIX shebang shims; the stub is simulated, not native")
    proj = tmp_path / "proj"
    proj.mkdir()
    home = tmp_path / "home"
    env = _env(tmp_path)
    proc = run([bash, os.path.join(REPO_ROOT, "install", "install.sh"), "kiro"],
               cwd=str(proj), env=env)
    assert proc.returncode == 0, proc.stderr[-800:]
    (home / ".soma" / "manifest.json").unlink()
    hooks = home / ".kiro" / "hooks" / "hooks.json"
    assert hooks.exists()
    before = _snapshot(home)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("python3", "python", "py"):
        _write_exe(fake_bin / name, f"exit {STORE_STUB_EXIT}")
    env = dict(env, SOMA_PYTHON="",
               PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))
    proc = run([bash, os.path.join(REPO_ROOT, "install", "uninstall.sh"), "kiro",
                "--force", "--no-restore", "--keep-config"], cwd=str(proj), env=env)
    assert proc.returncode != 0, "uninstall proceeded without a confinement check"
    assert "SOMA_PYTHON" in proc.stderr, proc.stderr
    assert _snapshot(home) == before, "files were removed"
