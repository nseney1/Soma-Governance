"""Cross-file documentation accuracy checks for release-critical contracts."""
import ast
import json
import re
from pathlib import Path

from conftest import REPO_ROOT, read

ROOT = Path(REPO_ROOT)


def _literal_assignment(path, name):
    tree = ast.parse(read(str(path)))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "frozenset":
            value = value.args[0]
        return set(ast.literal_eval(value))
    raise AssertionError(f"{name} not found in {path.relative_to(ROOT)}")


def _readme_mcp_row(readme, label):
    section = readme.split("### MCP Server (Recommended)", 1)[1].split("### SDK", 1)[0]
    row = next(line for line in section.splitlines() if line.startswith(f"| {label}"))
    return set(re.findall(r"`(soma_[a-z_]+)`", row))


def _script_groups():
    lifecycle_enzymes = {
        ROOT / "enzymes" / name
        for name in (
            "immune_init.sh", "safety_gate.sh", "session_close.sh",
            "post_session_hook.sh", "escalation_sentinel.sh", "liveness_sentinel.sh",
        )
    }
    lifecycle = lifecycle_enzymes | {ROOT / "install" / "hooks" / "pre-commit"}
    all_enzymes = {
        path for path in (ROOT / "enzymes").iterdir()
        if path.is_file() and path.suffix in {".py", ".sh"} and path.name != "__init__.py"
    }
    return {
        "Lifecycle Scripts (Hooks)": lifecycle,
        "Verification Scripts": {
            path for path in (ROOT / "immune_system" / "verification").iterdir()
            if path.is_file() and path.suffix == ".py" and path.name != "__init__.py"
        },
        "CLI Commands": {ROOT / "soma"} | {
            path for path in (ROOT / "soma_cli").iterdir()
            if path.is_file() and path.suffix == ".py" and path.name != "__init__.py"
        },
        "Install Scripts": {
            ROOT / "install.sh", ROOT / "install.ps1",
            ROOT / "install" / "install.sh", ROOT / "install" / "install.ps1",
            ROOT / "install" / "uninstall.sh", ROOT / "install" / "uninstall.ps1",
        },
        "Utility Scripts": all_enzymes - lifecycle_enzymes,
        "SDK Modules": {
            path for path in (ROOT / "soma_sdk").iterdir()
            if path.is_file() and path.suffix == ".py" and path.name != "__init__.py"
        },
        "MCP and Core Modules": {
            path for directory in (ROOT / "soma_mcp", ROOT / "soma_core")
            for path in directory.iterdir()
            if path.is_file() and path.suffix == ".py"
            and path.name not in {"__init__.py", "__main__.py"}
        },
    }


def _tool_definition_names(path):
    tree = ast.parse(read(str(path)))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "TOOL_DEFINITIONS"
                   for target in node.targets):
            continue
        definitions = ast.literal_eval(node.value)
        return {definition["name"] for definition in definitions}
    raise AssertionError("TOOL_DEFINITIONS not found")


def test_readme_mcp_tool_inventory_matches_code():
    readme = read(str(ROOT / "README.md"))
    section = readme.split("### MCP Server (Recommended)", 1)[1].split("### SDK", 1)[0]
    documented = set(re.findall(r"`(soma_[a-z_]+)`", section))
    expected = _tool_definition_names(ROOT / "soma_mcp" / "tools.py")
    assert documented == expected
    assert len(expected) == 15


def test_readme_mcp_tiers_match_server_definitions():
    readme = read(str(ROOT / "README.md"))
    source = ROOT / "soma_mcp" / "server.py"
    expected = {
        "Read (default)": _literal_assignment(source, "_READ_TOOLS"),
        "Write (default; receipt required)": _literal_assignment(source, "_WRITE_TOOLS"),
        "Execute (opt-in; receipt required)": _literal_assignment(source, "_EXECUTE_TOOLS"),
    }
    documented = {label: _readme_mcp_row(readme, label) for label in expected}
    assert documented == expected
    assert len(set().union(*documented.values())) == 15


def test_documentation_index_local_links_exist():
    index = ROOT / "docs" / "index.md"
    missing = []
    for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", read(str(index))):
        if "://" in target or target.startswith("#"):
            continue
        relative = target.split("#", 1)[0]
        if relative and not (index.parent / relative).resolve().exists():
            missing.append(target)
    assert not missing, f"docs/index.md has missing local links: {missing}"


def test_javascript_readme_uses_package_manifest_name():
    package = json.loads(read(str(ROOT / "soma_sdk_js" / "package.json")))
    name = package["name"]
    sdk_readme = read(str(ROOT / "soma_sdk_js" / "README.md"))
    top_readme = read(str(ROOT / "README.md"))
    assert sdk_readme.startswith(f"# {name}\n")
    assert f"npm install {name}" in sdk_readme
    assert f"require('{name}')" in sdk_readme
    assert f"npm install {name}" in top_readme


def test_windows_issue_sections_match_bug_registry():
    version = read(str(ROOT / "VERSION")).strip()
    registry = json.loads(read(str(ROOT / "docs" / "project" / "BUG_REGISTRY.json")))
    bugs = {bug["id"]: bug for bug in registry["bugs"]}
    windows = read(str(ROOT / "docs" / "KNOWN_ISSUES_WINDOWS.md"))
    assert windows.startswith(f"# Known Issues — Windows (v{version})")
    fixed, open_issues = windows.split("## Open issues", 1)
    for bug_id in ("BUG-008", "BUG-009", "BUG-011"):
        assert bugs[bug_id]["fixed_in"] == f"v{version}"
        assert f"### {bug_id}:" in fixed
        assert f"### {bug_id}:" not in open_issues
    for bug_id in ("BUG-010", "BUG-012", "BUG-013", "BUG-035", "BUG-036",
                   "BUG-037", "BUG-038"):
        assert bugs[bug_id]["status"] == "fixed"
        assert f"### {bug_id}:" in fixed
        assert f"### {bug_id}:" not in open_issues
    for bug_id in ("BUG-014",):
        assert bugs[bug_id]["status"] == "open"
        assert f"### {bug_id}:" in open_issues


def test_scripts_reference_counts_match_unique_source_paths():
    groups = _script_groups()
    flattened = [path for paths in groups.values() for path in paths]
    assert all(path.exists() for path in flattened)
    assert len(flattened) == len(set(flattened)), "script categories overlap"

    reference = read(str(ROOT / "docs" / "architecture" / "scripts.md"))
    for label, paths in groups.items():
        match = re.search(rf"\[{re.escape(label)}[^]]*\][^\n]*\|\s*(\d+)\s*\|", reference)
        assert match, f"summary row missing for {label}"
        assert int(match.group(1)) == len(paths), label

    total = re.search(r"\| \*\*Total\*\* \| \| \*\*(\d+)\*\* \|", reference)
    assert total
    assert int(total.group(1)) == len(flattened)


def test_readme_automation_count_matches_enzyme_files():
    count = len({
        path for path in (ROOT / "enzymes").iterdir()
        if path.is_file() and path.suffix in {".py", ".sh"} and path.name != "__init__.py"
    })
    readme = read(str(ROOT / "README.md"))
    assert f"Automation_Scripts-{count}-" in readme
    assert f"Soma includes {count} task-specific scripts" in readme


def test_readme_core_rule_count_and_inventory_match_genome():
    rules = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "genome").rglob("*.md")
        if path.name not in {"META.md", "README.md"}
    }
    readme = read(str(ROOT / "README.md"))
    assert f"Core_Rules-{len(rules)}-" in readme
    section = readme.split("## 📐 Core Rules", 1)[1].split("## 🔧 Agent Skills", 1)[0]
    linked = {target for target in re.findall(r"\]\((genome/[^)]+\.md)\)", section)}
    assert linked == rules
