"""Uninstall path-confinement regression tests.

uninstall.sh used a lexical prefix check, so a manifest entry such as
``$HOME/safe/../../outside/victim`` or ``$HOME/link/victim`` (``link`` being a
symlink out of HOME) passed and was deleted. Unsafe entries were also skipped
silently, and ``backup_dir`` (a restore *source*) was never checked at all.

Every hostile manifest here must fail closed: nonzero exit, nothing outside
the allowed roots touched, the legitimate entries in the same manifest left in
place (validation happens before any mutation), and the manifest retained.

All runs use an isolated HOME and an isolated project cwd under tmp_path.
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from conftest import REPO_ROOT, read, require_bash, run, symlink_or_skip

UNINSTALL_SH = os.path.join(REPO_ROOT, "install", "uninstall.sh")
UNINSTALL_PS1 = os.path.join(REPO_ROOT, "install", "uninstall.ps1")

SENTINEL_BYTES = b"outside sentinel - must survive\n"


@pytest.fixture
def layout(tmp_path):
    """home/, project/ and outside/ as siblings, so outside/ is under neither
    allowed root. Returns a dict of the paths plus prepared content."""
    home = tmp_path / "home"
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    for d in (home, project, outside):
        d.mkdir()

    victim = outside / "victim"
    victim.write_bytes(SENTINEL_BYTES)
    victim_dir = outside / "victim-dir"
    victim_dir.mkdir()
    (victim_dir / "inner").write_bytes(SENTINEL_BYTES)

    # A legitimate installed file + skill dir under HOME.
    steering = home / ".kiro" / "steering"
    steering.mkdir(parents=True)
    legit_file = steering / "soma-rule.md"
    legit_file.write_text("soma rule\n", encoding="utf-8")
    legit_skill = home / ".kiro" / "skills" / "soma-skill"
    legit_skill.mkdir(parents=True)
    (legit_skill / "SKILL.md").write_text("soma skill\n", encoding="utf-8")

    backup_dir = home / ".soma" / "backup" / "2026-01-01T00-00-00"
    backup_dir.mkdir(parents=True)

    return {
        "home": home, "project": project, "outside": outside,
        "victim": victim, "victim_dir": victim_dir,
        "legit_file": legit_file, "legit_skill": legit_skill,
        "backup_dir": backup_dir,
    }


def write_manifest(path, files=(), organs=(), hooks=(), backup_dir=None,
                   platform="kiro", scope="global"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "version": "test",
        "platform": platform,
        "scope": scope,
        "backup_dir": None if backup_dir is None else str(backup_dir),
        "files": [str(p) for p in files],
        "organs": [str(p) for p in organs],
        "hooks": [str(p) for p in hooks],
    }), encoding="utf-8")
    return path


def home_manifest(layout, **kw):
    return write_manifest(layout["home"] / ".soma" / "manifest.json", **kw)


def uninstall(layout, platform="kiro", *extra):
    return run(
        [require_bash(), UNINSTALL_SH, platform, "--force", "--no-restore",
         "--keep-config", *extra],
        cwd=str(layout["project"]),
        env={"HOME": str(layout["home"]), "USERPROFILE": str(layout["home"])},
    )


def snapshot_outside(layout):
    out = {}
    for root, _dirs, files in os.walk(layout["outside"]):
        for fn in files:
            p = os.path.join(root, fn)
            with open(p, "rb") as f:
                out[p] = f.read()
    return out


def assert_failed_closed(proc, layout, manifest, before, offending):
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, (
        f"unsafe manifest was accepted (exit 0):\n{combined[-1500:]}"
    )
    assert snapshot_outside(layout) == before, "files outside the allowed roots changed"
    assert layout["legit_file"].exists(), (
        "legitimate in-root file was deleted: validation did not run before mutation"
    )
    assert layout["legit_skill"].is_dir(), "legitimate in-root skill dir was deleted"
    assert manifest.exists(), "manifest was deleted despite failing validation"
    assert offending in combined, (
        f"offending entry {offending!r} was not reported:\n{combined[-1500:]}"
    )


# ── Hostile manifests ───────────────────────────────────────────────────

def test_dotdot_escape_is_refused(layout):
    # `safe` must exist, or the kernel cannot traverse the `..` and rm fails anyway.
    (layout["home"] / "safe").mkdir()
    hostile = f"{layout['home']}/safe/../../outside/victim"
    manifest = home_manifest(layout, files=[layout["legit_file"], hostile],
                             organs=[layout["legit_skill"]])
    before = snapshot_outside(layout)
    proc = uninstall(layout)
    assert_failed_closed(proc, layout, manifest, before, hostile)


def test_absolute_path_outside_roots_is_refused(layout):
    hostile = str(layout["victim"])
    manifest = home_manifest(layout, files=[layout["legit_file"], hostile],
                             organs=[layout["legit_skill"]])
    before = snapshot_outside(layout)
    proc = uninstall(layout)
    assert_failed_closed(proc, layout, manifest, before, hostile)


def test_outside_dir_in_organs_is_refused(layout):
    hostile = str(layout["victim_dir"])
    manifest = home_manifest(layout, files=[layout["legit_file"]],
                             organs=[layout["legit_skill"], hostile])
    before = snapshot_outside(layout)
    proc = uninstall(layout)
    assert_failed_closed(proc, layout, manifest, before, hostile)


def test_intermediate_symlink_escape_is_refused(layout):
    link = layout["home"] / "link"
    symlink_or_skip(str(layout["outside"]), str(link))
    hostile_file = f"{link}/victim"
    hostile_dir = f"{link}/victim-dir"
    manifest = home_manifest(layout, files=[layout["legit_file"], hostile_file],
                             organs=[layout["legit_skill"], hostile_dir])
    before = snapshot_outside(layout)
    proc = uninstall(layout)
    assert_failed_closed(proc, layout, manifest, before, hostile_file)
    assert hostile_dir in proc.stdout + proc.stderr, "every offender must be reported"


def test_symlinked_hook_parent_is_refused(layout):
    link = layout["home"] / ".git-link"
    symlink_or_skip(str(layout["outside"]), str(link))
    hostile = f"{link}/victim"
    manifest = home_manifest(layout, files=[layout["legit_file"]],
                             organs=[layout["legit_skill"]], hooks=[hostile])
    before = snapshot_outside(layout)
    proc = uninstall(layout)
    assert_failed_closed(proc, layout, manifest, before, hostile)


def test_backup_dir_outside_roots_is_refused(layout):
    hostile = str(layout["outside"])
    manifest = home_manifest(layout, files=[layout["legit_file"]],
                             organs=[layout["legit_skill"]], backup_dir=hostile)
    before = snapshot_outside(layout)
    proc = uninstall(layout)
    assert_failed_closed(proc, layout, manifest, before, hostile)


def test_relative_entry_is_refused(layout):
    hostile = "outside/victim"
    manifest = home_manifest(layout, files=[layout["legit_file"], hostile],
                             organs=[layout["legit_skill"]])
    before = snapshot_outside(layout)
    proc = uninstall(layout)
    assert_failed_closed(proc, layout, manifest, before, hostile)


def test_root_itself_is_refused(layout):
    hostile = str(layout["home"])
    manifest = home_manifest(layout, files=[layout["legit_file"]],
                             organs=[layout["legit_skill"], hostile])
    before = snapshot_outside(layout)
    proc = uninstall(layout)
    assert_failed_closed(proc, layout, manifest, before, hostile)


def test_project_manifest_cannot_reach_into_home(layout):
    """A project-local manifest is confined to the project directory."""
    manifest = write_manifest(
        layout["project"] / ".soma" / "manifest.json",
        files=[layout["project"] / ".mcp.json", layout["legit_file"]],
        platform="mcp", scope="local",
    )
    (layout["project"] / ".mcp.json").write_text('{"soma": 1}\n', encoding="utf-8")
    before = snapshot_outside(layout)
    proc = uninstall(layout, "mcp")
    assert_failed_closed(proc, layout, manifest, before, str(layout["legit_file"]))
    assert (layout["project"] / ".mcp.json").exists(), "in-root file removed before validation"


def test_dry_run_also_refuses(layout):
    hostile = str(layout["victim"])
    manifest = home_manifest(layout, files=[layout["legit_file"], hostile])
    before = snapshot_outside(layout)
    proc = uninstall(layout, "kiro", "--dry-run")
    assert_failed_closed(proc, layout, manifest, before, hostile)


# ── Legitimate manifests ────────────────────────────────────────────────

def test_legitimate_home_manifest_is_removed(layout):
    hook = layout["home"] / ".kiro" / "hooks" / "hooks.json"
    hook.parent.mkdir(parents=True)
    hook.write_text("{}\n", encoding="utf-8")
    project_file = layout["project"] / ".kiro" / "settings" / "mcp.json"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("{}\n", encoding="utf-8")
    manifest = home_manifest(
        layout, files=[layout["legit_file"], project_file],
        organs=[layout["legit_skill"]], hooks=[hook],
        backup_dir=layout["backup_dir"],
    )
    before = snapshot_outside(layout)
    proc = uninstall(layout)
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    assert not layout["legit_file"].exists()
    assert not layout["legit_skill"].exists()
    assert not hook.exists()
    assert not project_file.exists(), "project-dir entry in a home manifest not removed"
    assert not manifest.exists()
    assert layout["backup_dir"].is_dir(), "--no-restore must leave the backup in place"
    assert snapshot_outside(layout) == before


def test_legitimate_project_manifest_is_removed(layout):
    """install.sh writes local manifests to $(pwd)/.soma but always records a
    backup_dir under $HOME/.soma/backup — that must stay accepted."""
    mcp = layout["project"] / ".mcp.json"
    mcp.write_text('{"soma": 1}\n', encoding="utf-8")
    manifest = write_manifest(
        layout["project"] / ".soma" / "manifest.json",
        files=[mcp], platform="mcp", scope="local",
        backup_dir=layout["backup_dir"],
    )
    proc = uninstall(layout, "mcp")
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    assert not mcp.exists()
    assert not manifest.exists()
    assert layout["legit_file"].exists(), "home content touched by a project uninstall"


def test_final_component_symlink_is_unlinked_not_followed(layout):
    """A symlink as the final component is removed itself; its target survives."""
    link = layout["home"] / ".kiro" / "steering" / "linked.md"
    symlink_or_skip(str(layout["victim"]), str(link))
    dir_link = layout["home"] / ".kiro" / "skills" / "linked-skill"
    symlink_or_skip(str(layout["victim_dir"]), str(dir_link))
    manifest = home_manifest(layout, files=[link], organs=[dir_link])
    before = snapshot_outside(layout)
    proc = uninstall(layout)
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    assert not os.path.lexists(str(link))
    assert not os.path.lexists(str(dir_link))
    assert snapshot_outside(layout) == before, "symlink target was followed"
    assert not manifest.exists()


# ── Sink re-check ───────────────────────────────────────────────────────

def _path_check(kind, target, *roots):
    """Run the checker that uninstall.sh's guard_sink uses, in path mode."""
    src = read(UNINSTALL_SH)
    m = re.search(r"^PATH_CHECK_PY='(.*?)^'$", src, re.S | re.M)
    assert m, "PATH_CHECK_PY block not found in uninstall.sh"
    import subprocess, sys
    return subprocess.run(
        [sys.executable, "-I", "-S", "-c", m.group(1), "path", kind, target, *map(str, roots)],
        capture_output=True, text=True,
    )


def test_sink_check_rejects_component_swapped_for_symlink(layout):
    """Simulates the window between validation and rm: a directory that was
    real at validation time is replaced by a symlink out of the root."""
    target = layout["home"] / ".kiro" / "steering" / "soma-rule.md"
    assert _path_check("remove", str(target), layout["home"]).returncode == 0
    steering = layout["home"] / ".kiro" / "steering"
    os.rename(str(steering), str(layout["home"] / "steering-moved"))
    symlink_or_skip(str(layout["outside"]), str(steering))
    proc = _path_check("remove", str(target), layout["home"])
    assert proc.returncode == 1 and "symlink" in proc.stdout


def test_sink_check_rejects_backup_source_symlink(layout):
    link = layout["home"] / ".soma" / "backup" / "evil"
    symlink_or_skip(str(layout["outside"]), str(link))
    proc = _path_check("source", str(link), layout["home"] / ".soma" / "backup")
    assert proc.returncode == 1, "restore source symlink was accepted"
    assert _path_check("source", str(layout["backup_dir"]),
                       layout["home"] / ".soma" / "backup").returncode == 0


# ── Git Bash path forms (BUG-036) ───────────────────────────────────────
# Under Git Bash, resolve_home and $(pwd) give MSYS paths (/c/Users/...), and
# install.sh records them in the manifest. Native Windows Python only gets
# them converted on argv: SOMA_ROOTS (past its first line), the plan on stdin
# and the manifest JSON arrive as /c/..., which os.path.isabs() rejects, so
# every entry was refused.

needs_msys = pytest.mark.skipif(
    os.name != "nt" or shutil.which("cygpath") is None,
    reason="MSYS path forms only reach the checker under Git Bash/MSYS on Windows",
)


def msys(p):
    out = subprocess.run(["cygpath", "-u", str(p)], capture_output=True, check=True)
    return out.stdout.decode("utf-8").strip()


def _checker(mode, *args, stdin=b"", env=None):
    src = read(UNINSTALL_SH)
    m = re.search(r"^PATH_CHECK_PY='(.*?)^'$", src, re.S | re.M)
    assert m, "PATH_CHECK_PY block not found in uninstall.sh"
    full_env = dict(os.environ)
    # uninstall.sh exports the absolute cygpath it resolved from PATH.
    full_env["SOMA_CYGPATH"] = shutil.which("cygpath") or ""
    full_env.update(env or {})
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-c", m.group(1), mode, *args],
        input=stdin, capture_output=True, env=full_env,
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")


def _plan(targets, roots, env=None):
    env = dict(env or {}, SOMA_ROOTS="\n".join(roots))
    return _checker("plan", stdin="\0".join(targets).encode("utf-8"), env=env)


@needs_msys
def test_msys_form_plan_entries_inside_roots_are_accepted(layout):
    project_file = layout["project"] / ".kiro" / "settings" / "mcp.json"
    rc, out = _plan([msys(layout["legit_file"]), msys(layout["legit_skill"]), msys(project_file)],
                    [msys(layout["home"]), msys(layout["project"])])
    assert rc == 0, out


@needs_msys
def test_msys_form_manifest_is_accepted(layout):
    manifest = home_manifest(
        layout, files=[msys(layout["legit_file"])], organs=[msys(layout["legit_skill"])],
        backup_dir=msys(layout["backup_dir"]),
    )
    rc, out = _checker("manifest", env={
        "SOMA_MANIFEST": str(manifest),
        "SOMA_ROOTS": "\n".join([msys(layout["home"]), msys(layout["project"])]),
        "SOMA_BACKUP_ROOTS": msys(layout["home"] / ".soma" / "backup"),
    })
    assert rc == 0, out


@needs_msys
def test_msys_form_non_ascii_home_is_accepted(tmp_path):
    home = tmp_path / "hôme"
    target = home / ".kiro" / "steering" / "soma-rule.md"
    target.parent.mkdir(parents=True)
    target.write_text("soma rule\n", encoding="utf-8")
    rc, out = _plan([msys(target)], [msys(home)])
    assert rc == 0, out


@needs_msys
def test_msys_form_dotdot_is_refused_as_dotdot(layout):
    (layout["home"] / "safe").mkdir()
    hostile = msys(layout["home"]) + "/safe/../../outside/victim"
    rc, out = _plan([hostile], [msys(layout["home"])])
    assert rc == 1 and "contains a . or .. segment" in out, out


@needs_msys
def test_msys_form_outside_roots_is_refused_as_outside(layout):
    rc, out = _plan([msys(layout["victim"])], [msys(layout["home"]), msys(layout["project"])])
    assert rc == 1 and "outside the allowed roots" in out, out


@needs_msys
@pytest.mark.parametrize("cygpath", ["", "cygpath"], ids=["unset", "bare-name"])
def test_msys_form_without_absolute_cygpath_is_refused(layout, cygpath):
    # A bare name is refused, not looked up: the lookup would search the cwd.
    rc, out = _plan([msys(layout["legit_file"])], [str(layout["home"])],
                    env={"SOMA_CYGPATH": cygpath})
    assert rc == 1 and "cannot be mapped to a Windows path" in out, out


@needs_msys
def test_msys_form_home_manifest_is_removed(layout):
    """The shape install.sh writes under Git Bash: every path in MSYS form."""
    hook = layout["home"] / ".kiro" / "hooks" / "hooks.json"
    hook.parent.mkdir(parents=True)
    hook.write_text("{}\n", encoding="utf-8")
    second = layout["legit_file"].with_name("soma-other.md")
    second.write_text("soma rule\n", encoding="utf-8")
    manifest = home_manifest(
        layout, files=[msys(layout["legit_file"]), msys(second)],
        organs=[msys(layout["legit_skill"])],
        hooks=[msys(hook)], backup_dir=msys(layout["backup_dir"]),
    )
    before = snapshot_outside(layout)
    proc = uninstall(layout)
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    assert not layout["legit_file"].exists()
    assert not second.exists()
    assert not layout["legit_skill"].exists()
    assert not hook.exists()
    assert not manifest.exists()
    assert snapshot_outside(layout) == before


@needs_msys
def test_cygpath_in_the_project_dir_is_not_run(layout, monkeypatch):
    """Native Windows Python searches the current directory before PATH for a
    bare program name; uninstall runs from the project dir. A planted
    cygpath.exe (here hostname.exe, whose output maps nothing) must not be
    the one the checker runs."""
    # Some shells set this, which turns the current-directory search off;
    # a default Git Bash doesn't.
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    hostname = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "hostname.exe")
    if not os.path.isfile(hostname):
        pytest.skip("needs hostname.exe as the planted binary")
    shutil.copy(hostname, str(layout["project"] / "cygpath.exe"))
    second = layout["legit_file"].with_name("soma-other.md")
    second.write_text("soma rule\n", encoding="utf-8")
    manifest = home_manifest(layout, files=[msys(layout["legit_file"]), msys(second)])
    proc = uninstall(layout)
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    assert not layout["legit_file"].exists() and not second.exists()
    assert not manifest.exists()


# ── Win32 name normalisation (hardening) ────────────────────────────────
# Windows drops trailing spaces and dots from a path segment and reads `:` as
# a stream separator, so `sub\.. ` names `sub\..`. Python's realpath applies
# that; bash and rm take the name literally, so today such an entry never
# reaches rm. The checker refuses it anyway rather than rely on that.

needs_windows = pytest.mark.skipif(os.name != "nt", reason="Win32 path normalisation")


@needs_windows
@pytest.mark.parametrize("rel", [
    "sub\\.. ", "sub\\..  ", "sub\\...", "sub\\.. .", "sub\\. ",
    "sub\\.. \\x", "sub\\x\\... \\...", "sub\\x.", "sub\\x ",
])
def test_segment_ending_in_space_or_dot_is_refused(layout, rel):
    target = str(layout["home"]) + "\\" + rel
    rc, out = _plan([target], [str(layout["home"])])
    assert rc == 1 and "ends in a space or dot" in out, out


@needs_windows
@pytest.mark.parametrize("rel", ["sub::$INDEX_ALLOCATION", "sub\\x:ads", "sub\\..::$INDEX_ALLOCATION"])
def test_stream_syntax_is_refused(layout, rel):
    target = str(layout["home"]) + "\\" + rel
    rc, out = _plan([target], [str(layout["home"])])
    assert rc == 1 and "alternate data stream" in out, out


@needs_msys
def test_msys_form_stream_syntax_is_refused(layout):
    rc, out = _plan([msys(layout["home"]) + "/sub/x:ads"], [msys(layout["home"])])
    assert rc == 1 and "alternate data stream" in out, out


@needs_windows
@pytest.mark.parametrize("rel", ["sub\\x.y", ".kiro\\steering\\soma-rule.md", "sub\\a b\\c"])
def test_ordinary_dots_and_spaces_are_still_accepted(layout, rel):
    target = str(layout["home"]) + "\\" + rel
    rc, out = _plan([target], [str(layout["home"])])
    assert rc == 0, out


def test_unencodable_manifest_entry_is_refused(layout):
    """A lone surrogate can't be written out by read_manifest_field: the
    encode error ended the list early and the entries after it silently
    dropped out of the plan. Validation must refuse it up front instead."""
    hostile = str(layout["home"] / ".kiro" / "steering" / "bad-\ud800.md")
    manifest = home_manifest(layout, files=[hostile, layout["legit_file"]],
                             organs=[layout["legit_skill"]])
    before = snapshot_outside(layout)
    proc = uninstall(layout)
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, combined[-1500:]
    assert "not encodable" in combined, combined[-1500:]
    assert layout["legit_file"].exists() and layout["legit_skill"].is_dir()
    assert manifest.exists()
    assert snapshot_outside(layout) == before


def test_every_manifest_entry_reaches_the_plan(layout):
    """read_manifest_field hands entries to bash one per line. On Windows,
    Python's text stdout wrote CRLF and cp1252, so every entry but the last
    kept a trailing CR and non-ASCII names arrived as the wrong bytes: those
    files silently dropped out of the plan."""
    steering = layout["legit_file"].parent
    # The non-ASCII name goes last, where only the encoding can drop it.
    names = ["soma-a.md", "soma-b.md", "règle-ô.md"]
    files = []
    for name in names:
        p = steering / name
        p.write_text("soma rule\n", encoding="utf-8")
        files.append(p)
    manifest = home_manifest(layout, files=files, organs=[layout["legit_skill"]])
    proc = uninstall(layout)
    assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
    left = [p.name for p in files if p.exists()]
    assert left == [], f"left in place: {left}"
    assert not manifest.exists()


def test_every_sink_is_guarded():
    """Each rm/sed after the plan must be preceded by guard_sink."""
    src = read(UNINSTALL_SH)
    execute = src[src.index("# Inventory in-place backups BEFORE removing anything"):]
    execute = execute[:execute.index("# Clean soma hooks from claude settings.json")]
    execute += src[src.index('if [ -f "$MANIFEST_PATH" ]; then\n  guard_sink'):][:200]
    lines = execute.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"(rm -r?f|sed -i)", stripped):
            window = "\n".join(lines[max(0, i - 15):i])
            assert "guard_sink" in window, f"unguarded sink: {stripped}"


# ── PowerShell (static; pwsh is not available in this test environment) ─

def _ps1():
    return read(UNINSTALL_PS1)


def test_ps1_defines_safe_manifest_path_check():
    src = _ps1()
    m = re.search(r"function Test-SafeManifestPath\s*\{(.*?)\n\}", src, re.S)
    assert m, "Test-SafeManifestPath is not defined"
    body = m.group(1)
    assert "GetFullPath" in body, "must canonicalise with [IO.Path]::GetFullPath"
    assert "'..'" in body or '".."' in body, "must reject '..' segments"
    assert "OrdinalIgnoreCase" in body, "root prefix compare must be case-insensitive"
    assert "ReparsePoint" in body, "must reject reparse-point (symlink/junction) ancestors"
    assert "UserHome" in src and "WorkDir" in src


def test_ps1_validates_every_manifest_field_before_planning():
    src = _ps1()
    start = src.index("# ── Manifest Confinement")
    plan_idx = src.index("# ── Build the Removal Plan")
    assert start < plan_idx, "manifest confinement must run before the plan is built"
    validate = src[start:plan_idx]
    for field in ("files", "organs", "hooks", "backup_dir"):
        assert re.search(rf'"{field}"', validate), (
            f"manifest field {field!r} is not validated before the plan is built"
        )
    assert validate.count("Test-SafeManifestPath") >= 2, (
        "both the list fields and backup_dir must go through Test-SafeManifestPath"
    )
    assert "-RejectFinalReparsePoint" in validate, "backup_dir is a restore source"
    assert re.search(r"Test-SafeManifestPath[\s\S]*?exit 1", validate), (
        "validation failure must exit 1 before any removal"
    )
    # The manifest-derived plan must not be built from unvalidated data.
    assert src.index("Get-ManifestPathList -Object $Manifest") > start


def test_ps1_rechecks_before_every_removal():
    src = _ps1()
    execute = src[src.index("# ── Execute"):]
    removals = [m.start() for m in re.finditer(r"Remove-Item -LiteralPath \$(f|d|c) ", execute)]
    assert removals, "expected Remove-Item calls in the execute block"
    for pos in removals:
        window = execute[max(0, pos - 600):pos]
        assert "Assert-SafeSinkPath" in window or "Test-SafeManifestPath" in window, (
            "Remove-Item is not preceded by a sink re-check:\n" + execute[pos:pos + 80]
        )
    remove_section = src[src.index("function Remove-SomaSection"):]
    remove_section = remove_section[:remove_section.index("\n}\n")]
    assert "Assert-SafeSinkPath" in remove_section or "Test-SafeManifestPath" in remove_section, (
        "Remove-SomaSection writes/removes without a sink re-check"
    )
