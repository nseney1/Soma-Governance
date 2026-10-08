"""Behavioral tests for pure Python PlatformAdapters."""
from pathlib import Path
import pytest

from soma_cli.platforms import (
    PlatformAdapter,
    PlatformInstallResult,
    GeminiAdapter,
    ClaudeAdapter,
    KiroAdapter,
    CopilotAdapter,
    McpAdapter,
    get_adapter,
)


def test_get_adapter_registry():
    """Verify registry returns correct adapter instances for all supported platforms."""
    expected = {
        "gemini": GeminiAdapter,
        "claude": ClaudeAdapter,
        "kiro": KiroAdapter,
        "copilot": CopilotAdapter,
        "mcp": McpAdapter,
    }
    for name, expected_cls in expected.items():
        adapter = get_adapter(name)
        assert isinstance(adapter, expected_cls)
        assert adapter.name == name

    with pytest.raises(ValueError, match="Unknown platform"):
        get_adapter("unknown-platform-xyz")


def test_gemini_adapter_install_and_uninstall(tmp_path):
    """Verify GeminiAdapter installs rules, skills, and hooks in isolated environment."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    genome = workspace / "genome"
    genome.mkdir()
    (genome / "providence.md").write_text("# Providence", encoding="utf-8")

    organs = workspace / "organs" / "test-skill"
    organs.mkdir(parents=True)
    (organs / "SKILL.md").write_text("# Test Skill", encoding="utf-8")

    adapter = GeminiAdapter(workspace=workspace, home=home)

    res = adapter.install(local=False, dry_run=False)
    assert res.success
    assert res.scope == "global"
    assert (home / ".gemini" / "config" / "rules" / "providence.md").is_file()
    assert (home / ".gemini" / "config" / "skills" / "test-skill" / "SKILL.md").is_file()
    assert (home / ".gemini" / "config" / "plugins" / "governance" / "hooks.json").is_file()
    assert adapter.verify(local=False)

    un_res = adapter.uninstall(local=False, dry_run=False)
    assert un_res.success
    assert not (home / ".gemini" / "config" / "rules" / "providence.md").exists()
    assert not (home / ".gemini" / "config" / "plugins" / "governance" / "hooks.json").exists()


def test_claude_adapter_install_and_uninstall(tmp_path):
    """Verify ClaudeAdapter writes CLAUDE.md integration instructions."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    adapter = ClaudeAdapter(workspace=workspace, home=home)
    res = adapter.install(local=True, dry_run=False)
    assert res.success
    claude_md = workspace / "CLAUDE.md"
    assert claude_md.is_file()
    assert adapter.verify(local=True)

    un_res = adapter.uninstall(local=True, dry_run=False)
    assert un_res.success
    assert not claude_md.exists()


def test_kiro_adapter_install_and_uninstall(tmp_path):
    """Verify KiroAdapter installs steering rules and skills."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    genome = workspace / "genome"
    genome.mkdir()
    (genome / "providence.md").write_text("# Providence", encoding="utf-8")

    adapter = KiroAdapter(workspace=workspace, home=home)
    res = adapter.install(local=False, dry_run=False)
    assert res.success
    assert (home / ".kiro" / "steering" / "providence.md").is_file()
    assert adapter.verify(local=False)

    un_res = adapter.uninstall(local=False, dry_run=False)
    assert un_res.success
    assert not (home / ".kiro" / "steering" / "providence.md").exists()


def test_copilot_adapter_install_and_uninstall(tmp_path):
    """Verify CopilotAdapter writes .github/copilot-instructions.md and instructions/."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    genome = workspace / "genome"
    genome.mkdir()
    (genome / "providence.md").write_text("# Providence", encoding="utf-8")

    adapter = CopilotAdapter(workspace=workspace)
    res = adapter.install(local=True, dry_run=False)
    assert res.success
    assert (workspace / ".github" / "copilot-instructions.md").is_file()
    assert (workspace / ".github" / "instructions" / "providence.md").is_file()
    assert adapter.verify()

    un_res = adapter.uninstall(local=True, dry_run=False)
    assert un_res.success
    assert not (workspace / ".github" / "copilot-instructions.md").exists()


def test_mcp_adapter_install_and_uninstall(tmp_path):
    """Verify McpAdapter writes and removes .mcp.json."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    adapter = McpAdapter(workspace=workspace)
    res = adapter.install(local=True, dry_run=False)
    assert res.success
    assert (workspace / ".mcp.json").is_file()
    assert adapter.verify(local=True)

    un_res = adapter.uninstall(local=True, dry_run=False)
    assert un_res.success
    assert not adapter.verify(local=True)
