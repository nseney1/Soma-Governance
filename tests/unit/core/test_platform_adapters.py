"""Behavioral tests for pure Python PlatformAdapters."""
import json
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


def test_claude_adapter_preserves_user_content_on_uninstall(tmp_path):
    """BUG-088 (#142): Uninstalling Claude configuration must preserve existing user content."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    claude_md = workspace / "CLAUDE.md"
    user_content = "# My Custom Claude Config\n\n- Do not delete this file!\n"
    claude_md.write_text(user_content, encoding="utf-8")

    adapter = ClaudeAdapter(workspace=workspace, home=home)
    install_res = adapter.install(local=True, dry_run=False)
    assert install_res.success
    assert "Soma Governance Integration" in claude_md.read_text(encoding="utf-8")
    assert "# My Custom Claude Config" in claude_md.read_text(encoding="utf-8")

    uninstall_res = adapter.uninstall(local=True, dry_run=False)
    assert uninstall_res.success
    assert claude_md.is_file(), "CLAUDE.md was deleted instead of preserving user content!"
    assert claude_md.read_text(encoding="utf-8").strip() == user_content.strip()
    assert "Soma Governance Integration" not in claude_md.read_text(encoding="utf-8")
    assert not adapter.verify(local=True)


def test_claude_adapter_cleans_mcp_server_on_uninstall(tmp_path):
    """BUG-088 (#142): ClaudeAdapter uninstall cleans soma entry from .mcp.json."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    mcp_json = workspace / ".mcp.json"
    mcp_json.write_text(json.dumps({
        "mcpServers": {
            "soma": {"command": "soma-mcp", "args": []},
            "other": {"command": "other-tool", "args": []},
        }
    }), encoding="utf-8")

    adapter = ClaudeAdapter(workspace=workspace, home=home)
    res = adapter.uninstall(local=True, dry_run=False)
    assert res.success
    assert mcp_json.is_file()
    data = json.loads(mcp_json.read_text(encoding="utf-8"))
    assert "soma" not in data.get("mcpServers", {})
    assert "other" in data.get("mcpServers", {})


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
