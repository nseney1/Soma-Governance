"""Claude platform installation adapter."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from soma_cli.platforms.base import PlatformAdapter, PlatformInstallResult


SOMA_MARKER_START = "<!-- SOMA:START -->"
SOMA_MARKER_END = "<!-- SOMA:END -->"

__all__ = ["ClaudeAdapter", "SOMA_MARKER_START", "SOMA_MARKER_END"]


class ClaudeAdapter(PlatformAdapter):
    """Platform adapter for Anthropic Claude Code / Desktop environments."""

    name: str = "claude"

    def get_target_paths(self, local: bool = False) -> tuple[Path, Path]:
        """Return (claude_md_path, mcp_config_path)."""
        if local:
            return self.workspace / "CLAUDE.md", self.workspace / ".mcp.json"
        claude_dir = self.home / ".claude"
        return claude_dir / "CLAUDE.md", self.home / ".claude.json"

    def render_config(self) -> str:
        """Render governance instructions to embed in CLAUDE.md."""
        rules = self.get_source_rules()
        rule_list = "\n".join(f"- `{r.stem}`: {r.name}" for r in rules[:10])
        body = (
            "# Soma Governance Integration\n\n"
            "This project is governed by Soma. Rules are checked adaptively.\n\n"
            "## Active Core Rules\n"
            f"{rule_list}\n\n"
            "Run `soma doctor` to verify system health.\n"
        )
        return f"{SOMA_MARKER_START}\n{body}{SOMA_MARKER_END}\n"

    def render_mcp_config(self) -> dict[str, Any]:
        """Render standard MCP server configuration for Claude."""
        return {
            "mcpServers": {
                "soma": {
                    "command": "soma-mcp",
                    "args": [],
                }
            }
        }

    def install(self, local: bool = False, dry_run: bool = False) -> PlatformInstallResult:
        result = PlatformInstallResult(
            platform=self.name,
            success=True,
            scope="local" if local else "global",
        )
        claude_md, mcp_json = self.get_target_paths(local=local)

        if not dry_run:
            claude_md.parent.mkdir(parents=True, exist_ok=True)

        content = self.render_config()
        if dry_run:
            result.installed_files.append(claude_md)
        else:
            try:
                if claude_md.is_file():
                    existing = claude_md.read_text(encoding="utf-8")
                    if SOMA_MARKER_START in existing and SOMA_MARKER_END in existing:
                        start_idx = existing.index(SOMA_MARKER_START)
                        end_idx = existing.index(SOMA_MARKER_END) + len(SOMA_MARKER_END)
                        updated = existing[:start_idx] + content + existing[end_idx:]
                        claude_md.write_text(updated.strip() + "\n", encoding="utf-8")
                    elif "Soma Governance Integration" not in existing:
                        claude_md.write_text(existing.rstrip() + "\n\n" + content, encoding="utf-8")
                else:
                    claude_md.write_text(content, encoding="utf-8")
                result.installed_files.append(claude_md)
            except Exception as exc:
                result.errors.append(f"Failed to write {claude_md}: {exc}")
                result.success = False

        result.messages.append(f"Installed Claude configuration to {claude_md}")
        return result

    def uninstall(self, local: bool = False, dry_run: bool = False) -> PlatformInstallResult:
        result = PlatformInstallResult(
            platform=self.name,
            success=True,
            scope="local" if local else "global",
        )
        claude_md, mcp_json = self.get_target_paths(local=local)
        if claude_md.is_file():
            if dry_run:
                result.uninstalled_files.append(claude_md)
            else:
                try:
                    existing = claude_md.read_text(encoding="utf-8")
                    if SOMA_MARKER_START in existing and SOMA_MARKER_END in existing:
                        start_idx = existing.index(SOMA_MARKER_START)
                        end_idx = existing.index(SOMA_MARKER_END) + len(SOMA_MARKER_END)
                        remaining = (existing[:start_idx] + existing[end_idx:]).strip()
                    elif "# Soma Governance Integration" in existing or "# Soma Governance Rules" in existing:
                        lines = existing.splitlines()
                        kept_lines = []
                        skipping = False
                        for line in lines:
                            if line.strip() in ("# Soma Governance Integration", "# Soma Governance Rules"):
                                skipping = True
                            elif skipping and line.startswith("# ") and line.strip() not in ("# Soma Governance Integration", "# Soma Governance Rules"):
                                skipping = False
                                kept_lines.append(line)
                            elif not skipping:
                                kept_lines.append(line)
                        remaining = "\n".join(kept_lines).strip()
                    else:
                        remaining = ""

                    if not remaining:
                        claude_md.unlink()
                        result.uninstalled_files.append(claude_md)
                    else:
                        claude_md.write_text(remaining + "\n", encoding="utf-8")
                        result.uninstalled_files.append(claude_md)
                except Exception as exc:
                    result.errors.append(f"Failed to remove {claude_md}: {exc}")
                    result.success = False

        if mcp_json.is_file():
            try:
                data = json.loads(mcp_json.read_text(encoding="utf-8"))
                if "mcpServers" in data and "soma" in data["mcpServers"]:
                    if dry_run:
                        result.uninstalled_files.append(mcp_json)
                    else:
                        del data["mcpServers"]["soma"]
                        if not data["mcpServers"] and len(data) == 1:
                            mcp_json.unlink()
                        else:
                            mcp_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
                        result.uninstalled_files.append(mcp_json)
            except Exception:
                pass

        result.messages.append(f"Uninstalled Claude configuration from {claude_md}")
        return result

    def verify(self, local: bool = False) -> bool:
        claude_md, _ = self.get_target_paths(local=local)
        if not claude_md.is_file():
            return False
        content = claude_md.read_text(encoding="utf-8")
        return (
            (SOMA_MARKER_START in content and SOMA_MARKER_END in content)
            or "Soma Governance Integration" in content
        )
