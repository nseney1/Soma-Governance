"""BUG-010: installer tests must never resolve the real user profile.

Under Git Bash, enzymes/common.sh resolve_home() prefers USERPROFILE over
HOME, so a test that overrode only HOME ran install.sh/uninstall.sh against
the real Windows profile (rewriting ~/.claude/CLAUDE.md, ~/.soma/manifest.json
and creating ~/.kiro). The shared ``run`` helper must keep both in step.
"""
import os

from conftest import run

RESOLVE_AND_MARK = 'source enzymes/common.sh; h="$(resolve_home)"; touch "$h/marker"'


def test_home_only_override_isolates_installer_home(tmp_path, bash):
    home = tmp_path / "home"
    home.mkdir()

    proc = run([bash, "-c", RESOLVE_AND_MARK], env={"HOME": str(home)})

    assert proc.returncode == 0, proc.stderr
    assert (home / "marker").exists(), "installer home resolved outside the test's HOME"


def test_explicit_userprofile_is_not_overridden(tmp_path, bash):
    home = tmp_path / "home"
    profile = tmp_path / "profile"
    home.mkdir()
    profile.mkdir()

    proc = run([bash, "-c", RESOLVE_AND_MARK],
               env={"HOME": str(home), "USERPROFILE": str(profile)})

    assert proc.returncode == 0, proc.stderr
    # resolve_home prefers USERPROFILE only on Windows.
    expected = profile if os.name == "nt" else home
    assert (expected / "marker").exists()
