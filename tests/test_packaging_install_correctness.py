"""Regression coverage for v0.89 packaging and installer ownership fixes."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from conftest import REPO_ROOT, read, run

INSTALL_SH = os.path.join(REPO_ROOT, "install", "install.sh")
UNINSTALL_SH = os.path.join(REPO_ROOT, "install", "uninstall.sh")
INSTALL_PS1 = os.path.join(REPO_ROOT, "install", "install.ps1")
UNINSTALL_PS1 = os.path.join(REPO_ROOT, "install", "uninstall.ps1")


def same_path(a: str, b: str) -> bool:
    # Under Git Bash the generator writes C:/... (forward slashes).
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def isolated_env(home: Path) -> dict[str, str]:
    return {"HOME": str(home), "USERPROFILE": str(home)}


def mcp_case_path(project: Path, home: Path, platform: str, args: tuple[str, ...]) -> Path:
    if platform == "kiro":
        base = project if "--local" in args else home
        return base / ".kiro" / "settings" / "mcp.json"
    return project / ".mcp.json"


@pytest.mark.parametrize(
    "platform,args",
    [("mcp", ()), ("claude", ("--local",)),
     ("kiro", ("--local",)), ("kiro", ())],
)
def test_bash_mcp_generators_merge_and_target_project(tmp_path, bash, platform, args):
    home = tmp_path / "home"
    project = tmp_path / "governed-project"
    home.mkdir()
    project.mkdir()
    config = mcp_case_path(project, home, platform, args)
    config.parent.mkdir(parents=True, exist_ok=True)
    original = {
        "unrelated": {"keep": True},
        "mcpServers": {"other": {"command": "other-server"}},
    }
    config.write_text(json.dumps(original), encoding="utf-8")

    proc = run(
        [bash, INSTALL_SH, platform, *args],
        cwd=str(project),
        env=isolated_env(home),
    )
    assert proc.returncode == 0, proc.stdout[-1000:] + proc.stderr[-1000:]

    merged = json.loads(config.read_text(encoding="utf-8"))
    assert merged["unrelated"] == original["unrelated"]
    assert merged["mcpServers"]["other"] == original["mcpServers"]["other"]
    soma = merged["mcpServers"]["soma"]
    assert same_path(soma["cwd"], str(project))
    assert same_path(soma["env"]["SOMA_WORKSPACE"], str(project))
    assert "SOMA_ROOT" not in soma["env"]
    # A source checkout fallback is allowed only when the package cannot be
    # imported normally from the governed project.
    if "PYTHONPATH" in soma["env"]:
        assert same_path(soma["env"]["PYTHONPATH"], REPO_ROOT)


@pytest.mark.parametrize(
    "platform,args",
    [("mcp", ()), ("claude", ("--local",)),
     ("kiro", ("--local",)), ("kiro", ())],
)
def test_bash_mcp_generators_reject_invalid_json_unchanged(
    tmp_path, bash, platform, args
):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    config = mcp_case_path(project, home, platform, args)
    config.parent.mkdir(parents=True, exist_ok=True)
    invalid = b'{"mcpServers": invalid-json\n'
    config.write_bytes(invalid)

    proc = run(
        [bash, INSTALL_SH, platform, *args],
        cwd=str(project),
        env=isolated_env(home),
    )
    assert proc.returncode != 0
    assert config.read_bytes() == invalid


def test_bash_mcp_uninstall_removes_only_soma_server(tmp_path, bash):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    config = project / ".mcp.json"
    config.write_text(
        json.dumps({
            "unrelated": [1, 2, 3],
            "mcpServers": {"other": {"command": "keep-me"}},
        }),
        encoding="utf-8",
    )

    install_proc = run(
        [bash, INSTALL_SH, "mcp"], cwd=str(project), env=isolated_env(home)
    )
    assert install_proc.returncode == 0, install_proc.stderr[-800:]
    uninstall_proc = run(
        [bash, UNINSTALL_SH, "mcp", "--force", "--no-restore", "--keep-config"],
        cwd=str(project),
        env=isolated_env(home),
    )
    assert uninstall_proc.returncode == 0, uninstall_proc.stderr[-800:]

    remaining = json.loads(config.read_text(encoding="utf-8"))
    assert remaining["unrelated"] == [1, 2, 3]
    assert remaining["mcpServers"] == {"other": {"command": "keep-me"}}


def test_python_init_mcp_merge_targets_project(tmp_path):
    from soma_cli.init import generate_mcp_config

    config = tmp_path / ".mcp.json"
    config.write_text(
        json.dumps({
            "unrelated": "preserve",
            "mcpServers": {"other": {"command": "keep"}},
        }),
        encoding="utf-8",
    )
    generate_mcp_config(tmp_path)
    merged = json.loads(config.read_text(encoding="utf-8"))
    assert merged["unrelated"] == "preserve"
    assert merged["mcpServers"]["other"] == {"command": "keep"}
    soma = merged["mcpServers"]["soma"]
    assert soma["cwd"] == str(tmp_path)
    assert soma["env"] == {"SOMA_WORKSPACE": str(tmp_path)}


def test_python_init_invalid_mcp_json_is_unchanged(tmp_path):
    from soma_cli.init import generate_mcp_config

    config = tmp_path / ".mcp.json"
    invalid = b"{ definitely not json\n"
    config.write_bytes(invalid)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        generate_mcp_config(tmp_path)
    assert config.read_bytes() == invalid


@pytest.mark.parametrize("platform", ["kiro", "gemini"])
def test_manifestless_uninstall_removes_only_repo_names(tmp_path, bash, platform):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    if platform == "kiro":
        rules = home / ".kiro" / "steering"
        skills = home / ".kiro" / "skills"
    else:
        rules = home / ".gemini" / "config" / "rules"
        skills = home / ".gemini" / "config" / "skills"
    rules.mkdir(parents=True)
    skills.mkdir(parents=True)

    personal_rule = rules / "personal-rule.md"
    personal_rule.write_text("personal\n", encoding="utf-8")
    personal_skill = skills / "personal-skill"
    personal_skill.mkdir()
    (personal_skill / "SKILL.md").write_text("personal\n", encoding="utf-8")

    soma_rule = rules / "providence.md"
    soma_rule.write_text("installed soma rule\n", encoding="utf-8")
    source_skill = next(p for p in (Path(REPO_ROOT) / "organs").iterdir() if p.is_dir())
    soma_skill = skills / source_skill.name
    soma_skill.mkdir()
    (soma_skill / "SKILL.md").write_text("installed soma skill\n", encoding="utf-8")

    proc = run(
        [bash, UNINSTALL_SH, platform, "--force", "--no-restore", "--keep-config"],
        cwd=str(project),
        env=isolated_env(home),
    )
    assert proc.returncode == 0, proc.stdout[-1000:] + proc.stderr[-1000:]
    assert personal_rule.exists()
    assert personal_skill.is_dir()
    assert not soma_rule.exists()
    assert not soma_skill.exists()


def test_mcp_example_targets_governed_workspace():
    example = json.loads(read(os.path.join(REPO_ROOT, ".mcp.json.example")))
    soma = example["mcpServers"]["soma"]
    assert soma["cwd"] == "."
    assert soma["env"] == {"SOMA_WORKSPACE": "."}


def test_packaging_excludes_private_soma_state_and_includes_genome_package():
    manifest = read(os.path.join(REPO_ROOT, "MANIFEST.in"))
    assert "recursive-include .soma" not in manifest
    assert "prune .soma" in manifest
    assert ".soma/evidence" not in manifest
    assert ".soma/dreams" not in manifest

    pyproject = read(os.path.join(REPO_ROOT, "pyproject.toml"))
    assert '"genome*"' in pyproject
    assert re.search(r"(?m)^genome\s*=\s*\[", pyproject)
    assert '"*.md"' in pyproject and '".oracles/*.md"' in pyproject
    assert os.path.isfile(os.path.join(REPO_ROOT, "genome", "__init__.py"))


def test_powershell_installer_has_exact_manifest_and_utf8_contract():
    src = read(INSTALL_PS1)
    for token in (
        "$InstalledFiles", "$InstalledOrgans", "$InstalledHooks",
        "$InstalledMcpConfigs", "function Write-InstallManifest",
        '"platform"', '"scope"', '"backup_dir"', '"files"', '"organs"', '"hooks"',
    ):
        assert token in src, f"missing PowerShell ownership contract: {token}"
    assert "Record-InstalledFile" in src
    assert "Record-InstalledOrgan" in src
    assert "Write-InstallManifest" in src
    assert "Merge-SomaMcpConfig" in src and "ConvertFrom-Json" in src

    for lineno, line in enumerate(src.splitlines(), 1):
        code = line.strip()
        if code.startswith("#") or not re.search(r"\bGet-Content\s+-", code):
            continue
        assert "-Encoding UTF8" in code, f"install.ps1:{lineno} lacks explicit UTF-8: {code}"


def test_powershell_uninstall_consumes_mcp_ownership_and_guards_restore_map():
    src = read(UNINSTALL_PS1)
    assert 'Get-ManifestPathList -Object $Manifest -Name "mcp_configs"' in src
    assert "Remove-SomaMcpServer" in src
    preflight = src.index("# Parse every manifest-owned MCP config")
    execute = src.index("# ── Execute")
    assert preflight < execute
    restore_loop = src[src.index("foreach ($m in $ConsolidatedMap)"):]
    copy_pos = restore_loop.index("Copy-RestoreItem -Source $m.Source")
    before_copy = restore_loop[:copy_pos]
    assert "Assert-SafeSinkPath -Path $m.Source -Roots $BackupRoots -Source" in before_copy
    assert "Assert-SafeSinkPath -Path $m.Destination -Roots $script:SinkRoots -RejectFinalReparsePoint" in before_copy


def test_powershell_subset_records_only_paths_actually_written():
    src = read(INSTALL_PS1)
    # Every platform that copies individual rules must record the target only
    # in the write branch, after the subset guard's `continue`.
    assert src.count("Record-InstalledFile -Path $targetPath") >= 3
    assert re.search(
        r"Should-InstallRule[\s\S]+?continue[\s\S]+?Copy-Item[\s\S]+?Record-InstalledFile -Path \$targetPath",
        src,
    )


def test_owned_mcp_corruption_aborts_before_uninstall_mutation(tmp_path, bash):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    config = project / ".mcp.json"

    installed = run(
        [bash, INSTALL_SH, "mcp"], cwd=str(project), env=isolated_env(home)
    )
    assert installed.returncode == 0, installed.stderr[-800:]
    manifest = project / ".soma" / "manifest.json"
    assert manifest.exists()

    corrupted = b'{"mcpServers": broken\n'
    config.write_bytes(corrupted)
    proc = run(
        [bash, UNINSTALL_SH, "mcp", "--force", "--no-restore", "--keep-config"],
        cwd=str(project),
        env=isolated_env(home),
    )
    assert proc.returncode != 0
    assert config.read_bytes() == corrupted
    assert manifest.exists(), "ownership ledger was deleted after MCP preflight failure"
