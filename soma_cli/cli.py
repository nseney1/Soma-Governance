#!/usr/bin/env python3
"""Soma CLI — governance commands for AI coding agents.

User-facing interface uses plain language (rules, automations, etc).
Internal code retains biological naming (genome, enzymes, cells).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _version() -> str:
    version_file = Path(__file__).resolve().parent.parent / "VERSION"
    if version_file.is_file():
        try:
            val = version_file.read_text(encoding="utf-8").strip()
            if val:
                return val
        except OSError:
            pass
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("soma-governance")
        except PackageNotFoundError:
            pass
    except ImportError:
        pass
    return "unknown"


class SomaParser(argparse.ArgumentParser):
    """ArgumentParser ensuring global flags like plumbing default properly."""

    def parse_args(self, args=None, namespace=None):
        ns = super().parse_args(args=args, namespace=namespace)
        if not hasattr(ns, "plumbing"):
            ns.plumbing = False
        if not hasattr(ns, "plain"):
            ns.plain = False
        if not hasattr(ns, "no_emoji"):
            ns.no_emoji = False
        if getattr(ns, "no_emoji", False):
            ns.plain = True
        if not hasattr(ns, "verbose"):
            ns.verbose = False
        if not hasattr(ns, "quiet"):
            ns.quiet = False
        if not hasattr(ns, "format"):
            ns.format = None
        if not hasattr(ns, "workspace"):
            ns.workspace = None
        return ns


def _build_parser() -> argparse.ArgumentParser:
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--plumbing", "--internal", action="store_true",
                               default=argparse.SUPPRESS,
                               help="Display raw internal biological terms")
    common_parser.add_argument("--plain", action="store_true",
                               default=argparse.SUPPRESS,
                               help="Strip ANSI styling and Unicode emojis for plain logs")
    common_parser.add_argument("--no-emoji", action="store_true",
                               default=argparse.SUPPRESS,
                               help="Strip Unicode emojis from output (alias for --plain)")
    common_parser.add_argument("--format", choices=["text", "json", "mermaid"],
                               default=argparse.SUPPRESS,
                               help="Output format")
    common_parser.add_argument("--json", action="store_true",
                               default=False,
                               help="Emit machine-readable JSON output (shortcut for --format json)")
    common_parser.add_argument("-v", "--verbose", action="store_true",
                               default=argparse.SUPPRESS,
                               help="Verbose diagnostic output")
    common_parser.add_argument("-q", "--quiet", action="store_true",
                               default=argparse.SUPPRESS,
                               help="Suppress informational messages")
    common_parser.add_argument("--workspace", type=str,
                               default=argparse.SUPPRESS,
                               help="Target workspace root")

    parser = SomaParser(
        prog="soma",
        description="Soma Governance — make AI coding agents trustworthy",
        parents=[common_parser],
    )
    parser.add_argument("--version", action="version",
                        version=f"soma {_version()}")

    sub = parser.add_subparsers(dest="command", parser_class=SomaParser)

    # soma init
    p_init = sub.add_parser("init", parents=[common_parser], help="Set up governance for this project")
    p_init.add_argument("--dry-run", action="store_true",
                        help="Show what would be installed without doing it")
    p_init.add_argument("--platform", choices=["gemini", "claude", "cursor", "copilot", "kiro"],
                        help="Skip platform detection, force a platform")
    p_init.add_argument("--rules", choices=["minimal", "standard", "full"],
                        default="standard",
                        help="Rule set to install (default: standard)")
    p_init.add_argument("--mcp", action="store_true",
                        help="Generate .mcp.json for JIT cell matching")
    p_init.add_argument("--yes", "-y", action="store_true",
                        help="Skip confirmation prompts")
    p_init.add_argument("--force", action="store_true",
                        help="Overwrite existing rules")

    # soma status
    p_status = sub.add_parser("status", aliases=["rules"], parents=[common_parser], help="Show active rules and stats")

    # soma report
    p_report = sub.add_parser("report", parents=[common_parser], help="Session report card")
    p_report.add_argument("--session", type=int, default=-1,
                          help="Session index (default: latest)")

    # soma doctor
    p_doctor = sub.add_parser("doctor", aliases=["audit"], parents=[common_parser], help="System health and governance audit")
    p_doctor.add_argument("--fix-path", action="store_true",
                          help="Add soma's scripts directory to your shell startup file "
                               "(dry run unless confirmed or --yes; zsh/bash/fish only)")
    p_doctor.add_argument("--yes", "-y", action="store_true",
                          help="With --fix-path: apply without asking")

    # soma verify
    p_verify = sub.add_parser("verify", aliases=["check"], parents=[common_parser], help="Run verification on changed files")
    p_verify.add_argument("--files", nargs="*", default=None,
                          help="Explicit list of files to verify")
    p_verify.add_argument("--layer1-only", action="store_true",
                          help="Skip Layer 2 (fast deterministic checks only)")
    p_verify.add_argument("--dry-run", action="store_true",
                          help="Show what would be checked without running")
    p_verify.add_argument("--plan", default=None,
                          help="Task plan or prompt context for Layer 2 adversarial verification")
    p_verify.add_argument("--plan-file", default=None,
                          help="Path to file containing task plan or prompt context")
    p_verify.add_argument("--provider", default=None,
                          help="Inference provider to use (gemini, anthropic, openai, keyring, prompt)")
    p_verify.add_argument("--in-band", action="store_true",
                          help="Generate an in-band charge sheet for conversational rebuttal (zero external API keys)")
    p_verify.add_argument("--release-gate", action="store_true",
                          help="Check Release Gate 4.5: assert latest arbitration evidence is a valid SHIP receipt")

    # soma sync
    p_sync = sub.add_parser("sync", parents=[common_parser], help="Reconcile evidence JSONL with cell frontmatter")
    p_sync.add_argument("--dry-run", action="store_true",
                        help="Show what would change without writing")

    # soma checkpoint
    p_checkpoint = sub.add_parser("checkpoint", parents=[common_parser], help="Run deterministic quality checks")
    p_checkpoint.add_argument("--pre-commit", action="store_true",
                              help="Warn mode: exit 0 even if issues found (unless --strict)")
    p_checkpoint.add_argument("--strict", action="store_true",
                              help="In pre-commit mode, exit 1 on issues")
    p_checkpoint.add_argument("--require-arbitration", action="store_true",
                              help="Require valid passing arbitration evidence without requiring full --strict")

    # soma oracle
    p_oracle = sub.add_parser("oracle", parents=[common_parser], help="Cell health classification and recommendations")
    p_oracle.add_argument("--session-count", type=int, default=None,
                          help="Override session count for expiry calculation")

    # soma promote
    p_promote = sub.add_parser("promote", parents=[common_parser], help="Evaluate cell promotion candidates")
    p_promote.add_argument("--dry-run", action="store_true",
                           help="Show candidates without performing promotions")
    p_promote.add_argument("--force", action="store_true",
                           help="Force promotion of --cell, bypassing evidence thresholds")
    p_promote.add_argument("--cell", type=str, default=None,
                           help="Target cell ID for --force promotion")
    p_promote.add_argument("--tier-check", action="store_true",
                           help="Evaluate enforcement tier transitions and apply decay")

    # soma demote
    p_demote = sub.add_parser("demote", parents=[common_parser], help="Evaluate cell demotion candidates")
    p_demote.add_argument("--dry-run", action="store_true",
                          help="Show candidates without performing demotions")
    p_demote.add_argument("--force", action="store_true",
                          help="Force demotion of --cell, bypassing evidence thresholds")
    p_demote.add_argument("--cell", type=str, default=None,
                          help="Target cell ID for --force demotion")

    # soma harvest
    p_harvest = sub.add_parser("harvest", parents=[common_parser], help="Retroactively harvest telemetry and fitness evidence")
    p_harvest.add_argument("--git", action="store_true", default=True,
                           help="Harvest recent git commit history to seed cell fitness")
    p_harvest.add_argument("--limit", type=int, default=30,
                           help="Maximum number of commits to inspect (default: 30)")
    p_harvest.add_argument("--dry-run", action="store_true",
                           help="Preview harvested evidence without writing to disk")

    # soma genesis
    p_genesis = sub.add_parser("genesis", aliases=["analyze"], parents=[common_parser], help="Analyze codebase and generate governance cells")
    p_genesis.add_argument("--dry-run", action="store_true",
                           help="Show candidates without writing files")
    p_genesis.add_argument("--min-confidence", type=float, default=0.5,
                           help="Minimum confidence threshold (default: 0.5)")
    p_genesis.add_argument("--force", action="store_true",
                           help="Overwrite existing cells with same name")
    p_genesis.add_argument("--yes", "-y", action="store_true",
                           help="Skip confirmation prompts")
    p_genesis.add_argument("--install-hooks", action="store_true",
                           help="Install git pre-commit hook automatically")
    p_genesis.add_argument("--no-hooks", action="store_true",
                           help="Do not install git pre-commit hook")

    # soma completion
    from soma_cli.completion import SHELLS
    p_completion = sub.add_parser("completion", parents=[common_parser], help="Print a shell completion script")
    p_completion.add_argument("shell", choices=list(SHELLS),
                              help="Target shell")

    # soma hook
    p_hook = sub.add_parser("hook", parents=[common_parser], help="Manage and run cross-platform lifecycle hooks")
    p_hook_sub = p_hook.add_subparsers(dest="hook_action", parser_class=SomaParser)

    # Porcelain subcommands
    p_hook_install = p_hook_sub.add_parser("install", parents=[common_parser], help="Install pre-commit hook into git repository")
    p_hook_install.add_argument("--force", action="store_true", help="Overwrite symlinks pointing outside repository")
    p_hook_install.add_argument("--dry-run", action="store_true", help="Preview without creating or modifying hook")

    p_hook_status = p_hook_sub.add_parser("status", parents=[common_parser], help="Inspect pre-commit hook and interpreter status")

    p_hook_uninstall = p_hook_sub.add_parser("uninstall", parents=[common_parser], help="Safely remove Soma pre-commit hook")
    p_hook_uninstall.add_argument("--force", action="store_true", help="Force removal")
    p_hook_uninstall.add_argument("--dry-run", action="store_true", help="Preview without modifying disk")

    # Lifecycle phases
    p_h_precommit = p_hook_sub.add_parser("pre-commit", parents=[common_parser], help="Run pre-commit quality check")
    p_h_precommit.add_argument("--strict", action="store_true", help="In pre-commit, exit 1 on issues")

    p_h_safety = p_hook_sub.add_parser("safety-gate", parents=[common_parser], help="PreToolUse safety check")
    p_h_safety.add_argument("--cmd", type=str, default=None, help="Command line string for safety-gate check")

    p_h_preinv = p_hook_sub.add_parser("pre-invocation", parents=[common_parser], help="PreInvocation monitor")
    p_h_close = p_hook_sub.add_parser("session-close", parents=[common_parser], help="Post-session close")

    p_h_post = p_hook_sub.add_parser("post-session", parents=[common_parser], help="Post-session hook")
    p_h_post.add_argument("--transcript", default=None, help="Path to transcript.jsonl for post-session hook")

    for alias in ("governance-monitor", "immune-init", "stop"):
        p_hook_sub.add_parser(alias, parents=[common_parser], help=f"Hook phase {alias}")

    # soma transfer
    p_transfer = sub.add_parser("transfer", parents=[common_parser], help="Transfer a cell to another project or export/import for HGT")
    p_transfer.add_argument("action_or_cell_id", nargs="?", default="", help="Subcommand ('export'/'import') or ID of cell to transfer")
    p_transfer.add_argument("extra_cell_id", nargs="?", default="", help="ID of cell or path to packet file")
    p_transfer.add_argument("--to", dest="target_dir", default="", help="Path to target project")
    p_transfer.add_argument("--tags", type=str, default="", help="Comma-separated compatibility tags (e.g. 'python,pytest')")
    p_transfer.add_argument("--output", "-o", type=str, default="", help="Output path for exported JSON rule (e.g. 'rule.soma.json')")

    # soma quarantine
    p_quarantine = sub.add_parser("quarantine", parents=[common_parser], help="Inspect and manage quarantined corrupt files")
    p_quarantine_sub = p_quarantine.add_subparsers(dest="quarantine_action", parser_class=SomaParser)

    p_q_list = p_quarantine_sub.add_parser("list", parents=[common_parser], help="List all quarantined files")

    p_q_inspect = p_quarantine_sub.add_parser("inspect", parents=[common_parser], help="Inspect a quarantined file")
    p_q_inspect.add_argument("target", nargs="?", default="", help="Filename or path of quarantined file")

    p_q_prune = p_quarantine_sub.add_parser("prune", parents=[common_parser], help="Prune old quarantined files")
    p_q_prune.add_argument("--older-than-days", type=int, default=30, help="Prune files older than N days (default 30)")

    # soma prune
    p_prune = sub.add_parser("prune", parents=[common_parser], help="Prune extinct or apoptotic rules")
    p_prune.add_argument("--execute", action="store_true", help="Execute pruning decisions (archive expired rules)")
    p_prune.add_argument("--dry-run", action="store_true", help="Simulate pruning decisions without archiving files")

    # soma install
    p_install = sub.add_parser("install", parents=[common_parser], help="Install Soma governance rules and configuration")
    p_install.add_argument("--platform", "-p", choices=["gemini", "kiro", "copilot", "claude", "mcp"], default=None,
                           help="Target platform (default: auto-detected or gemini)")
    p_install.add_argument("--local", action="store_true", help="Install to project-local directory")
    p_install.add_argument("--dry-run", action="store_true", help="Show what would be installed without writing files")

    # soma uninstall
    p_uninstall = sub.add_parser("uninstall", parents=[common_parser], help="Uninstall Soma governance rules and configuration")
    p_uninstall.add_argument("--platform", "-p", choices=["gemini", "kiro", "copilot", "claude", "mcp"], default=None,
                             help="Target platform (default: auto-detected or gemini)")
    p_uninstall.add_argument("--local", action="store_true", help="Uninstall from project-local directory")
    p_uninstall.add_argument("--dry-run", action="store_true", help="Show what would be uninstalled without deleting files")

    # soma clean-global-rules
    p_clean_rules = sub.add_parser("clean-global-rules", parents=[common_parser], help="Cleanse leaked internal rules from global platform directories")
    p_clean_rules.add_argument("--dry-run", action="store_true", help="Simulate cleanse without removing files (default)")
    p_clean_rules.add_argument("--force", action="store_true", help="Execute removal of leaked rules with quarantine backup")
    p_clean_rules.add_argument("--quarantine-dir", type=str, default="", help="Custom quarantine directory (default: ~/.soma/quarantine)")

    # soma capture-insight
    p_insight = sub.add_parser("capture-insight", parents=[common_parser], help="Capture a human insight and persist to evidence, optionally scaffolding a Wall cell")
    p_insight.add_argument("--insight", required=True, type=str, help="Human insight description")
    p_insight.add_argument("--context-files", nargs="+", required=True, type=str, help="Context files relevant to the insight")
    p_insight.add_argument("--category", type=str, default=None, help="Insight category (e.g. security, performance, correctness)")
    p_insight.add_argument("--scaffold-wall", action="store_true", help="Scaffold a Wall cell enforcing invariants for the context files")
    p_insight.add_argument("--wall-id", type=str, default=None, help="Explicit ID for the scaffolded Wall cell")
    p_insight.add_argument("--source-conversation", type=str, default=None, help="Source conversation identifier")

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    """Set up governance for this project."""
    from soma_cli.init import run_init
    return run_init(args)


def cmd_status(args: argparse.Namespace) -> int:
    """Show active rules and stats."""
    from soma_cli.status import run_status
    return run_status(args)


def cmd_report(args: argparse.Namespace) -> int:
    """Session report card."""
    from soma_cli.report import run_report
    return run_report(args)


def cmd_doctor(args: argparse.Namespace) -> int:
    """System health check."""
    from soma_cli.doctor import run_doctor
    return run_doctor(args)


def cmd_audit(args: argparse.Namespace) -> int:
    """Run system and policy health audit (porcelain alias for doctor)."""
    return cmd_doctor(args)


def cmd_verify(args: argparse.Namespace) -> int:
    """Run verification on changed files."""
    from soma_cli.verify import run_verify
    return run_verify(args)


def cmd_check(args: argparse.Namespace) -> int:
    """Run verification on changed files (porcelain alias for verify)."""
    return cmd_verify(args)


def cmd_checkpoint(args: argparse.Namespace) -> int:
    """Run deterministic quality checks."""
    from soma_cli.checkpoint import run_checkpoint
    return run_checkpoint(args)


def cmd_oracle(args: argparse.Namespace) -> int:
    """Cell health classification and recommendations."""
    from soma_cli.oracle import run_oracle
    return run_oracle(args)


def cmd_promote(args: argparse.Namespace) -> int:
    """Evaluate cell promotion candidates."""
    from soma_cli.promote import run_promote
    return run_promote(args)


def cmd_sync(args: argparse.Namespace) -> int:
    """Reconcile evidence with cell frontmatter."""
    from soma_cli.sync import run_sync
    return run_sync(args)


def cmd_demote(args: argparse.Namespace) -> int:
    """Evaluate cell demotion candidates."""
    from soma_cli.demote import run_demote
    return run_demote(args)


def cmd_harvest(args: argparse.Namespace) -> int:
    """Retroactively harvest telemetry and fitness evidence."""
    from soma_cli.harvest import run_harvest
    return run_harvest(args)


def cmd_genesis(args: argparse.Namespace) -> int:
    """Analyze codebase and generate governance cells."""
    from soma_cli.genesis import run_genesis
    return run_genesis(args)


def cmd_completion(args: argparse.Namespace) -> int:
    """Print a shell completion script."""
    from soma_cli.completion import run_completion
    return run_completion(args)


def cmd_hook(args: argparse.Namespace) -> int:
    """Run lifecycle hooks natively across platforms."""
    from soma_cli.hooks import run_hook
    return run_hook(args)


def cmd_transfer(args: argparse.Namespace) -> int:
    """Transfer a cell to another project with fitness reset."""
    from soma_cli.transfer import run_transfer
    return run_transfer(args)


def cmd_quarantine(args: argparse.Namespace) -> int:
    """Inspect and manage quarantined corrupt files."""
    from soma_cli.quarantine import run_quarantine
    return run_quarantine(args)


def cmd_prune(args: argparse.Namespace) -> int:
    """Prune extinct or apoptotic rules."""
    from soma_core.lifecycle import prune_cells
    dry_run = getattr(args, "dry_run", False)
    execute = getattr(args, "execute", False)
    if dry_run:
        execute = False
    ws = getattr(args, "ws", None) or getattr(args, "workspace", None) or getattr(args, "_project_root", None)
    return prune_cells(workspace=ws, execute=execute)


def cmd_install(args: argparse.Namespace) -> int:
    """Install Soma rules and configuration for configured platform."""
    from soma_cli.platforms import get_adapter
    platform = getattr(args, "platform", None) or "gemini"
    local = getattr(args, "local", False)
    dry_run = getattr(args, "dry_run", False)
    workspace = getattr(args, "_project_root", None)
    try:
        adapter = get_adapter(platform, workspace=workspace)
        res = adapter.install(local=local, dry_run=dry_run)
        for msg in res.messages:
            print(msg)
        for err in res.errors:
            print(f"Error: {err}", file=sys.stderr)
        return 0 if res.success else 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def cmd_uninstall(args: argparse.Namespace) -> int:
    """Uninstall Soma rules and configuration for configured platform."""
    from soma_cli.platforms import get_adapter
    platform = getattr(args, "platform", None) or "gemini"
    local = getattr(args, "local", False)
    dry_run = getattr(args, "dry_run", False)
    workspace = getattr(args, "_project_root", None)
    try:
        adapter = get_adapter(platform, workspace=workspace)
        res = adapter.uninstall(local=local, dry_run=dry_run)
        for msg in res.messages:
            print(msg)
        for err in res.errors:
            print(f"Error: {err}", file=sys.stderr)
        return 0 if res.success else 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def cmd_clean_global_rules(args: argparse.Namespace) -> int:
    """Cleanse leaked internal rules from global platform directories."""
    from soma_cli.clean_rules import run_clean_rules
    return run_clean_rules(args)


def cmd_capture_insight(args: argparse.Namespace) -> int:
    """Capture a human insight and persist it to JSONL, optionally scaffolding a Wall cell."""
    import json
    from soma_core.insights import capture_insight

    ws = getattr(args, "ws", None)
    ws_path = str(ws.root) if ws is not None else (getattr(args, "workspace", None) or getattr(args, "_project_root", None) or ".")

    try:
        record = capture_insight(
            workspace=ws_path,
            insight=getattr(args, "insight", ""),
            context_files=getattr(args, "context_files", []),
            source_conversation=getattr(args, "source_conversation", None),
            category=getattr(args, "category", None),
            scaffold_wall=bool(getattr(args, "scaffold_wall", False)),
            wall_id=getattr(args, "wall_id", None),
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "json", False) or getattr(args, "format", None) == "json":
        print(json.dumps(record, indent=2))
    else:
        wall_msg = f" (scaffolded {record.get('wall_file')})" if record.get("wall_file") else ""
        print(f"Captured insight for {len(record.get('context_files', []))} files{wall_msg}.")
    return 0


COMMANDS = {
    "init": cmd_init,
    "status": cmd_status,
    "rules": cmd_status,
    "report": cmd_report,
    "doctor": cmd_doctor,
    "audit": cmd_audit,
    "verify": cmd_verify,
    "check": cmd_check,
    "checkpoint": cmd_checkpoint,
    "sync": cmd_sync,
    "oracle": cmd_oracle,
    "promote": cmd_promote,
    "demote": cmd_demote,
    "harvest": cmd_harvest,
    "genesis": cmd_genesis,
    "analyze": cmd_genesis,
    "completion": cmd_completion,
    "hook": cmd_hook,
    "transfer": cmd_transfer,
    "quarantine": cmd_quarantine,
    "prune": cmd_prune,
    "install": cmd_install,
    "uninstall": cmd_uninstall,
    "clean-global-rules": cmd_clean_global_rules,
    "capture-insight": cmd_capture_insight,
}


def main(argv: list[str] | None = None) -> int:
    # Output uses emoji. On a cp1252 stdout (Windows, redirected) printing
    # one raised UnicodeEncodeError and the command exited 1 (BUG-012).
    # stderr already defaults to errors="backslashreplace".
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "plumbing"):
        args.plumbing = False

    fmt = getattr(args, "format", None)
    is_json = getattr(args, "json", False) or fmt == "json"
    args.json = is_json
    if is_json and not fmt:
        args.format = "json"

    if args.command is None:
        parser.print_help()
        return 0

    handler = COMMANDS.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    try:
        from soma_core.workspace import Workspace

        if args.command == "completion":
            args.ws = None
        elif args.command == "init":
            raw_ws = getattr(args, "workspace", None) or Path.cwd()
            args.ws = Workspace.for_init(raw_ws)
        else:
            raw_ws = getattr(args, "workspace", None)
            args.ws = Workspace.resolve(raw_ws)

        if args.ws is not None:
            args._project_root = args.ws.root
            args.workspace = str(args.ws.root)

        func = globals().get(handler.__name__, handler)
        return func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
