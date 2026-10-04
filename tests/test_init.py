"""Tests for soma init — Phase B test gate.

All tests use tmp_path to avoid touching the real filesystem.
"""
import os
import argparse

import pytest

from conftest import symlink_or_skip


class TestDetectPlatform:
    """Platform detection based on directory markers."""

    def test_gemini_detected(self, tmp_path):
        (tmp_path / ".gemini").mkdir()
        from soma_cli.init import detect_platform
        assert detect_platform(tmp_path) == "gemini"

    def test_claude_detected(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        from soma_cli.init import detect_platform
        assert detect_platform(tmp_path) == "claude"

    def test_cursor_detected_dir(self, tmp_path):
        (tmp_path / ".cursor").mkdir()
        from soma_cli.init import detect_platform
        assert detect_platform(tmp_path) == "cursor"

    def test_cursor_detected_file(self, tmp_path):
        (tmp_path / ".cursorrules").write_text("")
        from soma_cli.init import detect_platform
        assert detect_platform(tmp_path) == "cursor"

    def test_copilot_detected(self, tmp_path):
        gh = tmp_path / ".github" / "copilot"
        gh.mkdir(parents=True)
        from soma_cli.init import detect_platform
        assert detect_platform(tmp_path) == "copilot"

    def test_unknown_when_empty(self, tmp_path):
        from soma_cli.init import detect_platform
        assert detect_platform(tmp_path) == "unknown"

    def test_gemini_takes_priority(self, tmp_path):
        """When multiple markers exist, gemini wins (most common)."""
        (tmp_path / ".gemini").mkdir()
        (tmp_path / ".cursor").mkdir()
        from soma_cli.init import detect_platform
        assert detect_platform(tmp_path) == "gemini"


class TestDetectProjectType:
    """Project type detection based on config files."""

    def test_python_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("")
        from soma_cli.init import detect_project_type
        assert detect_project_type(tmp_path) == "python"

    def test_python_setup_py(self, tmp_path):
        (tmp_path / "setup.py").write_text("")
        from soma_cli.init import detect_project_type
        assert detect_project_type(tmp_path) == "python"

    def test_javascript(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        from soma_cli.init import detect_project_type
        assert detect_project_type(tmp_path) == "javascript"

    def test_rust(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("")
        from soma_cli.init import detect_project_type
        assert detect_project_type(tmp_path) == "rust"

    def test_go(self, tmp_path):
        (tmp_path / "go.mod").write_text("")
        from soma_cli.init import detect_project_type
        assert detect_project_type(tmp_path) == "go"

    def test_unknown_when_empty(self, tmp_path):
        from soma_cli.init import detect_project_type
        assert detect_project_type(tmp_path) == "unknown"


class TestGetRulesDir:
    """Verify correct rules directory per platform."""

    def test_gemini_rules_dir(self, tmp_path):
        from soma_cli.init import get_rules_dir
        result = get_rules_dir("gemini", tmp_path)
        assert result.parts[-3:] == (".gemini", "config", "rules")

    def test_cursor_rules_dir(self, tmp_path):
        from soma_cli.init import get_rules_dir
        result = get_rules_dir("cursor", tmp_path)
        assert result.parts[-2:] == (".cursor", "rules")

    def test_claude_rules_dir(self, tmp_path):
        from soma_cli.init import get_rules_dir
        result = get_rules_dir("claude", tmp_path)
        assert str(result).endswith(".claude")

    def test_unknown_raises(self, tmp_path):
        from soma_cli.init import get_rules_dir
        with pytest.raises(ValueError, match="Unsupported platform"):
            get_rules_dir("unknown", tmp_path)


class TestInstallStarterRules:
    """Verify starter rule installation."""

    def test_dry_run_creates_no_files(self, tmp_path):
        from soma_cli.init import install_starter_rules
        rules_dir = tmp_path / "rules"
        installed = install_starter_rules(rules_dir, dry_run=True)
        assert len(installed) == 5
        assert not rules_dir.exists()

    def test_installs_five_rules(self, tmp_path):
        from soma_cli.init import install_starter_rules
        rules_dir = tmp_path / "rules"
        installed = install_starter_rules(rules_dir, dry_run=False)
        assert len(installed) == 5
        assert rules_dir.exists()
        # Each rule should be a .md file in the target
        for name in installed:
            rule_file = rules_dir / f"{name}.md"
            assert rule_file.exists(), f"Missing: {rule_file}"
            content = rule_file.read_text()
            assert len(content) > 100, f"Rule {name} seems too short"

    def test_starter_rules_are_the_right_five(self, tmp_path):
        from soma_cli.init import install_starter_rules, STARTER_RULES
        assert len(STARTER_RULES) == 5
        expected = {"providence", "destructive-ops", "testing",
                    "cost-optimization", "git-workflow"}
        assert set(STARTER_RULES) == expected


class TestExistingSomaDir:
    """Verify behavior when .soma/ already exists."""

    def test_existing_soma_dir_detected(self, tmp_path):
        (tmp_path / ".soma").mkdir()
        from soma_cli.init import check_existing_install
        assert check_existing_install(tmp_path) is True

    def test_no_soma_dir(self, tmp_path):
        from soma_cli.init import check_existing_install
        assert check_existing_install(tmp_path) is False


class TestRunInit:
    """End-to-end init flow."""

    def test_init_dry_run(self, tmp_path, capsys):
        from soma_cli.init import run_init
        (tmp_path / ".gemini").mkdir()
        (tmp_path / "pyproject.toml").write_text("")
        args = argparse.Namespace(
            dry_run=True, platform=None, yes=True,
            _project_root=tmp_path,  # test override
        )
        result = run_init(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "Detected platform" in captured.out or "gemini" in captured.out.lower()

    def test_init_with_forced_platform(self, tmp_path, capsys):
        from soma_cli.init import run_init
        (tmp_path / "pyproject.toml").write_text("")
        args = argparse.Namespace(
            dry_run=True, platform="claude", yes=True,
            _project_root=tmp_path,
        )
        result = run_init(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "claude" in captured.out.lower()


class TestSkipExistingAndForce:
    """Tests for skip-existing and --force overwrite logic."""

    def test_skips_existing_rules(self, tmp_path):
        """Pre-existing rule with custom content is preserved without --force."""
        from soma_cli.init import install_starter_rules
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        custom_content = "# My custom providence rule\nDo not touch."
        (rules_dir / "providence.md").write_text(custom_content)

        install_starter_rules(rules_dir, dry_run=False, force=False)

        assert (rules_dir / "providence.md").read_text() == custom_content

    def test_force_overwrites_existing(self, tmp_path):
        """Pre-existing rule is overwritten when force=True."""
        from soma_cli.init import install_starter_rules
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        (rules_dir / "providence.md").write_text("old content")

        install_starter_rules(rules_dir, dry_run=False, force=True)

        new_content = (rules_dir / "providence.md").read_text()
        assert new_content != "old content"
        assert len(new_content) > 100  # real rule content


class TestSymlinkGuard:
    """Tests for symlink destination guard in install_starter_rules."""

    def test_symlink_destination_skipped(self, tmp_path):
        """Symlink destinations in rules_dir are not followed."""
        from soma_cli.init import install_starter_rules
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        target_file = tmp_path / "target.txt"
        target_file.write_text("original target content")
        symlink_or_skip(target_file, rules_dir / "providence.md")

        install_starter_rules(rules_dir, dry_run=False, force=True)

        # Symlink should still be a symlink (skipped, not overwritten)
        assert (rules_dir / "providence.md").is_symlink()
        # Target file should be untouched
        assert target_file.read_text() == "original target content"


class TestCopilotInstructionsDetection:
    """Tests for copilot-instructions.md detection."""

    def test_copilot_detected_instructions_file(self, tmp_path):
        """copilot-instructions.md triggers copilot platform detection."""
        from soma_cli.init import detect_platform
        gh_dir = tmp_path / ".github"
        gh_dir.mkdir()
        (gh_dir / "copilot-instructions.md").write_text("# Instructions")

        assert detect_platform(tmp_path) == "copilot"


class TestClaudeMd:
    """Tests for Claude CLAUDE.md concatenation."""

    def test_claude_md_created(self, tmp_path):
        """CLAUDE.md is created when installing for Claude platform."""
        from soma_cli.init import install_starter_rules, _install_claude_md
        rules_dir = tmp_path / "claude_rules"
        install_starter_rules(rules_dir, dry_run=False)
        _install_claude_md(rules_dir)

        claude_md = rules_dir / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "<!-- SOMA:START -->" in content
        assert "<!-- SOMA:END -->" in content
        assert "providence" in content.lower()

    def test_claude_md_appends_to_existing(self, tmp_path):
        """CLAUDE.md appends Soma section to existing content."""
        from soma_cli.init import install_starter_rules, _install_claude_md
        rules_dir = tmp_path / "claude_rules"
        install_starter_rules(rules_dir, dry_run=False)

        claude_md = rules_dir / "CLAUDE.md"
        claude_md.write_text("# Existing project instructions\n")
        _install_claude_md(rules_dir)

        content = claude_md.read_text()
        assert content.startswith("# Existing project instructions")
        assert "<!-- SOMA:START -->" in content

    def test_claude_md_skips_without_force(self, tmp_path):
        """CLAUDE.md soma section not replaced without --force."""
        from soma_cli.init import install_starter_rules, _install_claude_md
        rules_dir = tmp_path / "claude_rules"
        install_starter_rules(rules_dir, dry_run=False)

        claude_md = rules_dir / "CLAUDE.md"
        claude_md.write_text("<!-- SOMA:START -->\nPLACEHOLDER_ORIGINAL_CONTENT_XYZ\n<!-- SOMA:END -->\n")
        _install_claude_md(rules_dir, force=False)

        assert "PLACEHOLDER_ORIGINAL_CONTENT_XYZ" in claude_md.read_text()

    def test_claude_md_replaces_with_force(self, tmp_path):
        """CLAUDE.md soma section replaced with --force."""
        from soma_cli.init import install_starter_rules, _install_claude_md
        rules_dir = tmp_path / "claude_rules"
        install_starter_rules(rules_dir, dry_run=False)

        claude_md = rules_dir / "CLAUDE.md"
        claude_md.write_text("<!-- SOMA:START -->\nPLACEHOLDER_ORIGINAL_CONTENT_XYZ\n<!-- SOMA:END -->\n")
        _install_claude_md(rules_dir, force=True)

        content = claude_md.read_text()
        assert "PLACEHOLDER_ORIGINAL_CONTENT_XYZ" not in content
        assert "providence" in content.lower()


class TestConfirmation:
    """Tests for --yes confirmation prompt."""

    def test_init_aborts_without_yes(self, tmp_path, monkeypatch, capsys):
        """Init aborts when user says no to confirmation."""
        from soma_cli.init import run_init
        (tmp_path / ".gemini").mkdir()
        monkeypatch.setattr("builtins.input", lambda _: "n")
        args = argparse.Namespace(
            dry_run=False, platform="gemini", yes=False, force=False,
            _project_root=tmp_path,
        )
        result = run_init(args)
        assert result == 0
        assert "Aborted" in capsys.readouterr().out

    def test_init_proceeds_with_yes(self, tmp_path, capsys):
        """Init proceeds when --yes is passed."""
        from soma_cli.init import run_init
        (tmp_path / ".gemini").mkdir()
        args = argparse.Namespace(
            dry_run=False, platform="gemini", yes=True, force=False,
            _project_root=tmp_path,
        )
        result = run_init(args)
        assert result == 0
        assert "Done!" in capsys.readouterr().out
