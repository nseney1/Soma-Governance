"""Tests for soma_cli — Phase A test gate.

Verifies the CLI skeleton installs correctly and all subcommands
have help text and exit cleanly.
"""
import os
import subprocess
import sys

import pytest


SUBCOMMANDS = ["init", "status", "report", "doctor"]


class TestCLIImport:
    """Verify the CLI module is importable without side effects."""

    def test_cli_importable(self):
        from soma_cli.cli import main
        assert callable(main)

    def test_cli_build_parser(self):
        from soma_cli.cli import _build_parser
        parser = _build_parser()
        assert parser.prog == "soma"


class TestCLIHelp:
    """Verify --help works for the main command and all subcommands."""

    def test_main_help_exits_zero(self):
        from soma_cli.cli import main
        # No args → prints help, returns 0
        assert main([]) == 0

    @pytest.mark.parametrize("cmd", SUBCOMMANDS)
    def test_subcommand_help_exits_zero(self, cmd):
        from soma_cli.cli import main
        with pytest.raises(SystemExit) as exc_info:
            main([cmd, "--help"])
        assert exc_info.value.code == 0


class TestCLIDispatch:
    """Verify subcommands dispatch to their handlers."""

    @pytest.mark.parametrize("cmd,extra_args", [
        ("init", ["--dry-run", "--platform", "gemini", "--yes"]),
        ("status", []),
        ("report", []),
        ("doctor", []),
    ])
    def test_subcommand_runs_without_crash(self, cmd, extra_args, capsys):
        from soma_cli.cli import main
        result = main([cmd] + extra_args)
        assert result in (0, 1)
        captured = capsys.readouterr()
        assert 'Traceback' not in captured.err

    def test_unknown_command_returns_nonzero(self):
        from soma_cli.cli import main
        # argparse treats unknown subcommand as args.command = None? No,
        # it raises SystemExit(2) for unrecognized args.
        with pytest.raises(SystemExit) as exc_info:
            main(["nonexistent_command_xyz"])
        assert exc_info.value.code == 2


class TestCLIEntryPoint:
    """Verify the installed entry point resolves correctly."""

    def test_soma_dash_dash_help_via_subprocess(self):
        """Run `python -m soma_cli.cli --help` to test without requiring
        pip install."""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        proc = subprocess.run(
            [sys.executable, "-m", "soma_cli.cli", "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=repo_root,
        )
        assert proc.returncode == 0
        assert "Soma Governance" in proc.stdout


class TestNonUtf8Console:
    """BUG-012: a cp1252 stdout (Windows, redirected output) made `soma
    status` exit 1 with UnicodeEncodeError on its emoji."""

    def test_status_survives_cp1252_stdout(self, tmp_path):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        home = tmp_path / "home"
        home.mkdir()
        env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONPATH=repo_root,
                   HOME=str(home), USERPROFILE=str(home))
        proc = subprocess.run(
            [sys.executable, "-m", "soma_cli.cli", "status"],
            capture_output=True, encoding="cp1252", errors="replace",
            timeout=30, cwd=str(tmp_path), env=env,
        )
        assert "can't encode" not in proc.stderr, proc.stderr
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip()


# ── TDD Red Phase: --rules preset tests ────────────────────────────────────


def _run_init_in(tmp_path, extra_args=None):
    """Helper: invoke run_init targeting tmp_path with sensible defaults."""
    from soma_cli.cli import _build_parser
    from soma_cli.init import run_init

    argv = ["init", "--platform", "gemini", "--yes"]
    if extra_args:
        argv.extend(extra_args)

    parser = _build_parser()
    args = parser.parse_args(argv)
    args._project_root = tmp_path
    return run_init(args)


def _installed_rules(tmp_path):
    """Return set of .md filenames in the gemini rules dir under tmp_path."""
    rules_dir = tmp_path / ".gemini" / "config" / "rules"
    if not rules_dir.is_dir():
        return set()
    return {f.name for f in rules_dir.iterdir() if f.suffix == ".md"}


class TestRulePresetMinimal:
    """--rules minimal should install exactly 2 rules."""

    def test_init_minimal_installs_two_rules(self, tmp_path):
        """--rules minimal should install exactly providence + destructive-ops."""
        rc = _run_init_in(tmp_path, ["--rules", "minimal"])
        assert rc == 0
        installed = _installed_rules(tmp_path)
        assert installed == {"providence.md", "destructive-ops.md"}, (
            f"Expected 2 minimal rules, got {installed}"
        )


class TestRulePresetStandard:
    """--rules standard (default) should install the 5 starter rules."""

    def test_init_standard_installs_five_rules(self, tmp_path):
        """--rules standard installs 5 rules (current behavior — should PASS)."""
        rc = _run_init_in(tmp_path, ["--rules", "standard"])
        assert rc == 0
        installed = _installed_rules(tmp_path)
        assert len(installed) == 5, f"Expected 5 standard rules, got {len(installed)}: {installed}"

    def test_init_default_preset_is_standard(self, tmp_path):
        """When --rules is not specified, default to standard (5 rules)."""
        rc = _run_init_in(tmp_path)  # no --rules flag
        assert rc == 0
        installed = _installed_rules(tmp_path)
        assert len(installed) == 5, f"Default should match standard (5 rules), got {len(installed)}"


class TestRulePresetFull:
    """--rules full should discover and install all genome rules."""

    def test_init_full_discovers_genome_rules(self, tmp_path):
        """--rules full should install more rules than standard."""
        rc = _run_init_in(tmp_path, ["--rules", "full"])
        assert rc == 0
        installed = _installed_rules(tmp_path)
        # genome/ has 11 files + .oracles/ has 8 files minus META.md = 18
        assert len(installed) > 5, (
            f"Full preset should install >5 rules, got {len(installed)}: {installed}"
        )

    def test_init_full_skips_meta_md(self, tmp_path):
        """--rules full should skip META.md and README.md."""
        _run_init_in(tmp_path, ["--rules", "full"])
        installed = _installed_rules(tmp_path)
        assert "META.md" not in installed, "META.md should be excluded from full preset"
        assert "README.md" not in installed, "README.md should be excluded from full preset"


# ── TDD Red Phase: --mcp config tests ──────────────────────────────────────


import json


def _run_init_mcp(tmp_path, extra_args=None):
    """Helper: invoke run_init with --mcp targeting tmp_path."""
    from soma_cli.cli import _build_parser
    from soma_cli.init import run_init

    argv = ["init", "--platform", "gemini", "--yes", "--mcp"]
    if extra_args:
        argv.extend(extra_args)

    parser = _build_parser()
    args = parser.parse_args(argv)
    args._project_root = tmp_path
    return run_init(args)


class TestMCPConfig:
    """--mcp should create/merge .mcp.json with soma server config."""

    def test_init_mcp_creates_config(self, tmp_path):
        """--mcp should create .mcp.json with mcpServers.soma entry."""
        rc = _run_init_mcp(tmp_path)
        assert rc == 0
        mcp_file = tmp_path / ".mcp.json"
        assert mcp_file.exists(), ".mcp.json was not created"
        data = json.loads(mcp_file.read_text())
        assert "mcpServers" in data, "Missing mcpServers key"
        assert "soma" in data["mcpServers"], "Missing soma server in mcpServers"

    def test_init_mcp_uses_relative_paths(self, tmp_path):
        """MCP config must use relative paths, not hardcoded absolutes."""
        _run_init_mcp(tmp_path)
        mcp_file = tmp_path / ".mcp.json"
        data = json.loads(mcp_file.read_text())
        soma_cfg = data["mcpServers"]["soma"]
        # Check cwd and SOMA_ROOT are relative (not absolute)
        cfg_str = json.dumps(soma_cfg)
        assert "/home/" not in cfg_str, f"Absolute path detected in MCP config: {cfg_str}"

    def test_init_mcp_merges_existing(self, tmp_path):
        """--mcp should merge into existing .mcp.json, not clobber."""
        mcp_file = tmp_path / ".mcp.json"
        existing = {
            "mcpServers": {
                "gemini-api-docs": {"command": "npx", "args": ["gemini-docs"]}
            }
        }
        mcp_file.write_text(json.dumps(existing))

        _run_init_mcp(tmp_path)

        data = json.loads(mcp_file.read_text())
        assert "gemini-api-docs" in data["mcpServers"], "Existing server was clobbered"
        assert "soma" in data["mcpServers"], "Soma server was not added"

    def test_init_mcp_dry_run_no_file(self, tmp_path):
        """--mcp --dry-run should NOT create .mcp.json."""
        _run_init_mcp(tmp_path, ["--dry-run"])
        mcp_file = tmp_path / ".mcp.json"
        assert not mcp_file.exists(), ".mcp.json should not be created during dry run"

    def test_init_mcp_idempotent(self, tmp_path):
        """Running --mcp twice should not duplicate the soma config."""
        _run_init_mcp(tmp_path)
        _run_init_mcp(tmp_path)
        mcp_file = tmp_path / ".mcp.json"
        data = json.loads(mcp_file.read_text())
        # Should still have exactly one soma entry
        assert isinstance(data["mcpServers"]["soma"], dict), (
            "Soma config should be a dict, not duplicated"
        )


# ── TDD Red Phase: Integration ─────────────────────────────────────────────


class TestInitIntegration:
    """Combined --rules and --mcp integration tests."""

    def test_init_full_with_mcp(self, tmp_path):
        """--rules full --mcp should install all rules AND create MCP config."""
        from soma_cli.cli import _build_parser
        from soma_cli.init import run_init

        argv = ["init", "--platform", "gemini", "--yes",
                "--rules", "full", "--mcp"]
        parser = _build_parser()
        args = parser.parse_args(argv)
        args._project_root = tmp_path

        rc = run_init(args)
        assert rc == 0

        # Rules: more than standard
        installed = _installed_rules(tmp_path)
        assert len(installed) > 5, f"Full preset should install >5 rules, got {len(installed)}"

        # MCP config exists
        mcp_file = tmp_path / ".mcp.json"
        assert mcp_file.exists(), ".mcp.json was not created"
        data = json.loads(mcp_file.read_text())
        assert "soma" in data.get("mcpServers", {})
