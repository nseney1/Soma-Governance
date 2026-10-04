import contextlib
import hmac
import json
import os
import secrets
import sys
import time
import traceback
from collections import defaultdict
from typing import Any, Dict

from .tools import TOOL_DEFINITIONS, execute_tool
from .security import confine_workspace
from soma_core.receipts import (
    issue_receipt,
    verify_receipt,
    strip_server_owned,
    target_paths,
    compute_file_digest,
    compute_cell_digest,
)

_session_token = None
_canonical_workspace = None
_execution_enabled = False

_READ_TOOLS = frozenset({
    "soma_scan", "soma_list_cells", "soma_grade", "soma_coverage", "soma_fitness",
    "soma_request_receipt"
})
_WRITE_TOOLS = frozenset({
    "soma_report_outcome", "soma_capture_insight", "soma_create_cell"
})
_EXECUTE_TOOLS = frozenset({
    "soma_propose_change", "soma_verify_changes", "soma_checkpoint",
    "soma_audit_security", "soma_audit_performance", "soma_generate_manifest",
})

_tool_call_times = defaultdict(list)
_RATE_LIMITS = {
    "soma_propose_change": (5, 60),
    "soma_report_outcome": (20, 60),
    "soma_verify_changes": (5, 60),
    "soma_checkpoint": (3, 60),
}


def _check_rate_limit(tool_name: str) -> bool:
    """Return True if the call is within rate limits, False if exceeded."""
    if tool_name not in _RATE_LIMITS:
        return True
    max_calls, window_seconds = _RATE_LIMITS[tool_name]
    now = time.monotonic()
    timestamps = _tool_call_times[tool_name]
    # Prune old entries
    _tool_call_times[tool_name] = [t for t in timestamps if now - t < window_seconds]
    if len(_tool_call_times[tool_name]) >= max_calls:
        return False
    _tool_call_times[tool_name].append(now)
    return True

# Messages that mean "the operation did not happen", regardless of the tool.
_ERROR_STATUSES = ("FAIL", "FAILED", "ERROR", "REJECTED", "BLOCKED", "ESCALATION_REQUIRED")
_ERROR_TEXT_PREFIXES = ("ERROR", "CRITICAL ERROR")


def _server_version() -> str:
    """Resolve the version from a single source of truth."""
    version_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION"
    )
    if os.path.isfile(version_file):
        try:
            with open(version_file, "r", encoding="utf-8") as fh:
                val = fh.read().strip()
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


def send_response(response: Dict[str, Any]):
    # stdout is the JSON-RPC transport: only framed responses may be written here.
    print(json.dumps(response), flush=True)


def _is_error_text(value: Any) -> bool:
    return isinstance(value, str) and value.lstrip().upper().startswith(_ERROR_TEXT_PREFIXES)


def _is_error_result(result: Any) -> bool:
    """Decide whether a tool result represents a failure.

    A tool can signal failure three ways: an "error" key, an explicit failure
    "status", or a failure-prefixed message string. Checking only for "error"
    reported rejected proposals and failing audits as successes.
    """
    if _is_error_text(result):
        return True
    if isinstance(result, dict):
        if "error" in result:
            return True
        if str(result.get("status", "")).upper() in _ERROR_STATUSES:
            return True
        # Tools that wrap a human-readable verdict in {"result": "..."}.
        if _is_error_text(result.get("result")):
            return True
    return False

def _error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _state_digests(args: Dict[str, Any]):
    """(file_digest, cell_digest) for the canonical workspace and the
    target paths named in args. Raises ValueError on a path escape."""
    return (
        compute_file_digest(_canonical_workspace, target_paths(args)),
        compute_cell_digest(_canonical_workspace),
    )


def send_error(id: Any, code: int, message: str):
    send_response({
        "jsonrpc": "2.0",
        "id": id,
        "error": {
            "code": code,
            "message": message
        }
    })

def handle_request(request: Dict[str, Any]) -> Dict[str, Any]:
    method = request.get("method")
    params = request.get("params", {})
    req_id = request.get("id")

    if method == "initialize":
        global _session_token
        _session_token = secrets.token_hex(32)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "soma-mcp",
                    "version": _server_version(),
                    "_sessionToken": _session_token
                }
            }
        }
    elif method == "tools/list":
        if not _session_token:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32002,
                    "message": "Server not initialized"
                }
            }
            
        tools = TOOL_DEFINITIONS
        if not _execution_enabled:
            tools = [t for t in tools if t["name"] not in _EXECUTE_TOOLS]
            
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": tools
            }
        }
    elif method == "tools/call":
        if not _session_token:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32002,
                    "message": "Server not initialized"
                }
            }
            
        name = params.get("name")
        args = params.get("arguments", {})

        if not isinstance(args, dict):
            return _error(req_id, -32602, "Tool arguments must be an object.")

        if name == "soma_request_receipt":
            operation = args.get("operation")
            if operation not in _EXECUTE_TOOLS and operation not in _WRITE_TOOLS:
                return _error(req_id, -32602,
                              f"Tool '{operation}' does not require a receipt or does not exist.")
            if operation in _EXECUTE_TOOLS and not _execution_enabled:
                return _error(req_id, -32600, "Execution capabilities are disabled.")
            if not _canonical_workspace:
                return _error(req_id, -32600, "Server workspace is not configured.")

            # Bind the receipt to exactly what will be dispatched: the client
            # arguments minus server-owned keys (workspace is always the
            # operator-configured one), plus the current content of the target
            # files and the governance cells. Any change before redemption
            # makes the receipt stale.
            op_args = strip_server_owned(args.get("arguments", {}))
            try:
                file_digest, cell_digest = _state_digests(op_args)
            except ValueError as exc:
                return _error(req_id, -32602, str(exc))
            receipt_id = issue_receipt(
                session_id=_session_token,
                workspace=_canonical_workspace,
                operation=operation,
                args=op_args,
                file_digest=file_digest,
                cell_digest=cell_digest,
                ttl_seconds=300
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps({"receipt": receipt_id})}],
                    "isError": False
                }
            }

        # The client never chooses the workspace, for read tools included:
        # strip whatever it sent and dispatch against the canonical one.
        receipt = args.get("receipt")
        args = strip_server_owned(args)

        # Rate limit check BEFORE consuming receipt
        if not _check_rate_limit(name):
            limit_info = _RATE_LIMITS.get(name, (0, 0))
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32000,
                    "message": f"Rate limit exceeded for '{name}': max {limit_info[0]} calls per {limit_info[1]}s"
                }
            }

        # Both EXECUTE and WRITE tools require a valid receipt
        if name in _EXECUTE_TOOLS or name in _WRITE_TOOLS:
            if name in _EXECUTE_TOOLS and not _execution_enabled:
                return _error(req_id, -32600, "Execution capabilities are disabled.")
            if not _canonical_workspace:
                return _error(req_id, -32600, "Server workspace is not configured.")
            if not receipt or not isinstance(receipt, str):
                return _error(req_id, -32600, f"Tool '{name}' requires a valid 'receipt'.")

            # Recompute the state digests now; a target file or cell edited
            # since issuance no longer matches and the receipt is consumed.
            try:
                file_digest, cell_digest = _state_digests(args)
            except ValueError as exc:
                return _error(req_id, -32602, str(exc))
            if not verify_receipt(
                receipt_id=receipt,
                session_id=_session_token,
                workspace=_canonical_workspace,
                operation=name,
                args=args,
                file_digest=file_digest,
                cell_digest=cell_digest,
                consume=True
            ):
                return _error(req_id, -32600, "Invalid, expired, or mismatched receipt.")

        # Inject the operator-configured workspace only after verification, so
        # the hashed arguments match issuance and dispatch cannot be redirected.
        if _canonical_workspace:
            args["workspace"] = _canonical_workspace

        try:
            # Tool implementations (and the enzymes they call) may print progress
            # notes. stdout belongs to the JSON-RPC framing, so any stray writes
            # are re-routed to stderr instead of corrupting the stream.
            with contextlib.redirect_stdout(sys.stderr):
                result = execute_tool(name, args)
            is_error = _is_error_result(result)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result) if not isinstance(result, str) else result
                        }
                    ],
                    "isError": is_error
                }
            }
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error: {e!s}"
                        }
                    ],
                    "isError": True
                }
            }
    elif method == "notifications/initialized":
        # Just return None for notifications, no response
        return None
    else:
        # Method not found
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}"
            }
        }

def run_stdio_server():
    global _canonical_workspace
    global _execution_enabled

    workspace_env = os.environ.get("SOMA_WORKSPACE") or os.getcwd()
    try:
        from .security import confine_workspace
        _canonical_workspace = confine_workspace(workspace_env)
    except ValueError as e:
        print(f"Error: Invalid canonical workspace: {e}", file=sys.stderr)
        return 1
        
    _execution_enabled = os.environ.get("SOMA_EXECUTION_ENABLED") == "1"

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                send_error(None, -32700, "Parse error")
                continue
                
            try:
                if request.get("jsonrpc") != "2.0":
                    continue # ignore invalid
                    
                if "id" in request:
                    # It's a request
                    response = handle_request(request)
                    if response:
                        send_response(response)
                else:
                    # It's a notification
                    handle_request(request)
            except Exception:
                traceback.print_exc(file=sys.stderr)
                if "id" in request:
                    send_error(request["id"], -32603, "Internal error")
    except (BrokenPipeError, KeyboardInterrupt):
        pass
                    
    return 0

def main():
    sys.exit(run_stdio_server())
