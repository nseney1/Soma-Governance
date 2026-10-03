#!/usr/bin/env bash
set -euo pipefail

# Symlink-safe resolution
PRG="${BASH_SOURCE[0]}"
while [ -h "$PRG" ]; do
  DIR="$(cd -P "$(dirname "$PRG")" && pwd)"
  PRG="$(readlink "$PRG")"
  [[ $PRG != /* ]] && PRG="$DIR/$PRG"
done
REPO_DIR="$(cd -P "$(dirname "$PRG")/.." && pwd)"

source "$REPO_DIR/enzymes/common.sh"
load_config "$REPO_DIR"

DRY_RUN=false
KEEP_CONFIG=false
FORCE=false
NO_RESTORE=false
PURGE_DATA=false
POSITIONAL_ARGS=()

usage() {
  cat <<'USAGE'
Soma uninstaller

Usage: bash install/uninstall.sh [platform] [options]
  platform: gemini (default) | kiro | copilot | claude | mcp

Options:
  --dry-run       Print the removal plan without deleting anything
  --force         Skip the deletion confirmation prompt.
                  Does NOT disable the restore offer (use --no-restore).
  --no-restore    Do not offer to restore the previous configuration
  --keep-config   Never remove soma.conf
  --purge-data    Also remove user-authored governance data:
                  .soma/cells/, fitness.jsonl, docs/snapshots/
                  (these are PRESERVED by default)
  -h, --help      Show this help

Never removed without --purge-data: your cells, fitness history and snapshots.
USAGE
}

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --keep-config) KEEP_CONFIG=true ;;
    --force) FORCE=true ;;
    --no-restore) NO_RESTORE=true ;;
    --purge-data) PURGE_DATA=true ;;
    -h|--help) usage; exit 0 ;;
    -*) log_error "Unknown option: $arg"; usage; exit 1 ;;
    *) POSITIONAL_ARGS+=("$arg") ;;
  esac
done

PLATFORM="${POSITIONAL_ARGS[0]:-${SOMA_PLATFORM:-gemini}}"

DETECTED_OS="$(detect_os)"
RESOLVED_HOME="$(resolve_home "$DETECTED_OS")"
WORK_DIR="$(pwd)"
# The path checker maps MSYS paths with cygpath. Resolve it here, from PATH
# only: native Windows Python given a bare name also searches the current
# directory, which is the project being uninstalled from.
SOMA_CYGPATH=""
if [ "$DETECTED_OS" = "windows" ] && command -v cygpath >/dev/null 2>&1; then
  SOMA_CYGPATH="$(cygpath -m "$(command -v cygpath)")"
fi
export SOMA_CYGPATH
MANIFEST_PATH="$RESOLVED_HOME/.soma/manifest.json"
MANIFEST_IS_LOCAL=false
if [ -f "$WORK_DIR/.soma/manifest.json" ]; then
  # A project-level .soma is repository content, i.e. attacker-controllable:
  # as a symlink it would point the manifest (and its removal) outside the
  # project. Refuse it. A symlinked ~/.soma stays allowed: the home directory
  # is user-controlled (dotfile managers link it).
  if [ -L "$WORK_DIR/.soma" ]; then
    log_error "Refusing to use $WORK_DIR/.soma/manifest.json: $WORK_DIR/.soma is a symlink."
    log_error "A project-level .soma must be a real directory. Nothing was removed."
    exit 1
  fi
  MANIFEST_PATH="$WORK_DIR/.soma/manifest.json"
  MANIFEST_IS_LOCAL=true
fi
# Root the manifest removal is confined to at the sink: the whole project for
# a local manifest (so a .soma swapped for a symlink later is caught), its own
# directory for ~/.soma (which may legitimately be a symlink).
MANIFEST_SINK_ROOT="$(dirname "$MANIFEST_PATH")"
[ "$MANIFEST_IS_LOCAL" = "false" ] || MANIFEST_SINK_ROOT="$WORK_DIR"

# ── Path Confinement ──────────────────────────────────────────────
# Allowed roots mirror where install.sh writes:
#  - a project-local manifest ($(pwd)/.soma/manifest.json) only ever records
#    paths under the project directory;
#  - the home manifest records $RESOLVED_HOME paths, plus project paths for
#    installs that write into $(pwd) while keeping global scope (kiro --local
#    mcp.json, the git pre-commit hook).
#  - backup_dir is always $RESOLVED_HOME/.soma/backup/<stamp>, for both
#    manifest kinds, so the restore source is confined to that directory.
# The old check was a lexical prefix match: `$HOME/x/../../etc/y` and
# `$HOME/link/y` (link -> outside) both passed, offenders were skipped
# silently, and backup_dir was never checked at all.
if [ "$MANIFEST_IS_LOCAL" = "true" ]; then
  ALLOWED_ROOTS=("$WORK_DIR")
else
  ALLOWED_ROOTS=("$RESOLVED_HOME" "$WORK_DIR")
fi
BACKUP_ROOTS=("$RESOLVED_HOME/.soma/backup")
# The sink re-check additionally admits the repo itself: --purge-data and
# soma.conf removal target $REPO_DIR, which is script-derived, not manifest data.
SINK_ROOTS=("${ALLOWED_ROOTS[@]}" "$REPO_DIR")

# Safe = absolute; no `.`/`..` segments; under an allowed root (canonicalised)
# by commonpath; no component between the root and the target is a symlink;
# canonical parent inside the root; not the root itself; the root is not `/`.
# A final-component symlink is acceptable for removal (it is unlinked, never
# followed) but not for a restore source (it would be read through).
# Paths travel via argv/env, never interpolated into the source.
PATH_CHECK_PY='
import json, os, subprocess, sys

# Messages name the offending path; on a cp1252 console a non-cp1252 or
# unencodable one would crash the report instead of showing it.
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

# Under Git Bash/MSYS/Cygwin, shell paths (/c/Users/..., /tmp/...) reach this
# native Windows interpreter unconverted through the environment, stdin and the
# manifest; only argv is auto-converted. Map them with cygpath so roots and
# targets compare in one form. If cygpath is missing or fails, the path stays
# unmapped and is refused: fail closed. SOMA_CYGPATH is the absolute path the
# shell resolved; a bare name would be looked up in the current directory too.
_native = {}
_cygpath = os.environ.get("SOMA_CYGPATH", "")

def posix_form(p):
    return os.name == "nt" and p.startswith("/") and not p.startswith("//")

def native(p):
    if not posix_form(p):
        return p
    if p not in _native:
        mapped = ""
        if os.path.isabs(_cygpath):
            try:
                out = subprocess.run([_cygpath, "-m", "--", p], capture_output=True, timeout=30)
                if out.returncode == 0:
                    mapped = out.stdout.decode("utf-8").rstrip("\r\n")
            except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
                pass
        _native[p] = mapped if mapped and os.path.isabs(mapped) else None
    return _native[p]

def prep_roots(raw):
    out = []
    for r in raw:
        if not r or not (os.path.isabs(r) or posix_form(r)):
            continue
        r = native(r)
        if r is None:
            continue
        lex = os.path.normpath(r)
        real = os.path.realpath(lex)
        if os.path.dirname(real) == real:
            continue
        out.append((lex, real))
    return out

def under(base, p):
    try:
        return os.path.commonpath([base, p]) == base
    except ValueError:
        return False

def check(target, roots, kind):
    if not isinstance(target, str):
        return "not a string"
    if not target:
        return "empty path"
    if any(c in target for c in "\n\r\0"):
        return "contains a control character"
    # read_manifest_field must be able to write every accepted entry; an encode
    # error there ends the list early and the rest silently leave the plan.
    try:
        target.encode("utf-8", "surrogateescape")
    except UnicodeEncodeError:
        return "not encodable as a path"
    if not (os.path.isabs(target) or posix_form(target)):
        return "not an absolute path"
    if any(s in (".", "..") for s in target.replace("\\", "/").split("/")):
        return "contains a . or .. segment"
    if os.name == "nt":
        # Win32 drops trailing spaces and dots from a segment and reads ":" as
        # a stream separator, so realpath would check a different name than
        # the one given (`sub\.. ` is `sub\..`). rm takes it literally today;
        # refuse it rather than rely on that.
        body = target[2:] if target[1:2] == ":" else target
        if ":" in body:
            return "contains : (alternate data stream)"
        if any(s and s[-1] in " ." for s in target.replace("\\", "/").split("/")):
            return "has a segment that ends in a space or dot"
    # Only after the segment check: cygpath folds `..` away.
    target = native(target)
    if target is None:
        return "cannot be mapped to a Windows path (cygpath missing or failed)"
    if not roots:
        return "no usable allowed root"
    norm = os.path.normpath(target)
    reasons = []
    for lex, real in roots:
        if under(lex, norm):
            rel = os.path.relpath(norm, lex)
        elif under(real, norm):
            rel = os.path.relpath(norm, real)
        else:
            continue
        if rel == os.curdir:
            reasons.append("is an allowed root itself")
            continue
        bad = None
        cur = real
        for part in rel.split(os.sep)[:-1]:
            cur = os.path.join(cur, part)
            # A symlinked ancestor that stays inside the root (stow-style
            # ~/.kiro -> ~/dotfiles/.kiro) is fine; one that leaves it is not.
            if os.path.islink(cur) and not under(real, os.path.realpath(cur)):
                bad = "intermediate component is a symlink leaving the allowed root: " + cur
                break
        if bad is None and not under(real, os.path.realpath(os.path.dirname(norm))):
            bad = "canonical parent escapes the allowed root"
        if bad is None and kind == "source" and os.path.islink(norm):
            bad = "restore source is a symlink"
        if bad is None:
            return None
        reasons.append(bad)
    return reasons[0] if reasons else "outside the allowed roots"

def env_roots(name):
    return prep_roots(os.environ.get(name, "").split("\n"))

mode = sys.argv[1]
if mode == "manifest":
    try:
        with open(os.environ["SOMA_MANIFEST"], "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        print("  manifest unreadable: %s" % exc)
        sys.exit(2)
    if not isinstance(data, dict):
        print("  manifest is not a JSON object")
        sys.exit(2)
    roots = env_roots("SOMA_ROOTS")
    bad = []
    for field in ("files", "organs", "hooks", "mcp_configs"):
        value = data.get(field)
        if value is None:
            continue
        if not isinstance(value, list):
            bad.append((field, json.dumps(value), "must be a list"))
            continue
        for item in value:
            if item == "":
                continue
            why = check(item, roots, "remove")
            if why:
                shown = item if isinstance(item, str) else json.dumps(item)
                bad.append((field, shown, why))
    bd = data.get("backup_dir")
    if bd is not None and bd != "":
        why = check(bd, env_roots("SOMA_BACKUP_ROOTS"), "source")
        if why:
            bad.append(("backup_dir", bd if isinstance(bd, str) else json.dumps(bd), why))
    for field, item, why in bad:
        print("  UNSAFE %s entry: %s  (%s)" % (field, item, why))
    sys.exit(1 if bad else 0)
elif mode == "plan":
    roots = env_roots("SOMA_ROOTS")
    bad = 0
    for raw in sys.stdin.buffer.read().split(b"\0"):
        if not raw:
            continue
        target = os.fsdecode(raw)
        why = check(target, roots, "remove")
        if why:
            print("  UNSAFE plan entry: %s  (%s)" % (target, why))
            bad += 1
    sys.exit(1 if bad else 0)
elif mode == "path":
    kind, target = sys.argv[2], sys.argv[3]
    why = check(target, prep_roots(sys.argv[4:]), kind)
    if why:
        print(why)
        sys.exit(1)
    sys.exit(0)
sys.exit(2)
'

join_lines() { local IFS=$'\n'; printf '%s' "$*"; }

# check_confined <remove|source> <target> <root>...
# Fails closed without a working Python 3 (BUG-043). The old lexical prefix
# fallback could not see symlinked components, so a manifestless uninstall on
# such a host followed `$HOME/link/...` out of the allowed roots.
check_confined() {
  local kind="$1" target="$2"; shift 2
  if ! resolve_python; then
    CONFINE_REASON="no working Python 3 to verify confinement (install Python 3 or set SOMA_PYTHON)"
    return 1
  fi
  CONFINE_REASON="$(soma_python -I -S -c "$PATH_CHECK_PY" path "$kind" "$target" "$@" 2>&1)" && return 0
  return 1
}

# Re-validate at the sink, immediately before rm/sed. Validation and removal
# are separated by the plan, the prompt and earlier removals; a component can
# be swapped for a symlink in between. Abort rather than follow it.
guard_sink() {
  local kind="$1" target="$2"; shift 2
  [ $# -gt 0 ] || set -- ${SINK_ROOTS[@]+"${SINK_ROOTS[@]}"}
  if ! check_confined "$kind" "$target" "$@"; then
    log_error "Refusing to touch $target: $CONFINE_REASON"
    log_error "It no longer passes the confinement check. Aborting; remaining items left in place."
    exit 1
  fi
}

MANIFEST_EXISTS=false
if [ -f "$MANIFEST_PATH" ]; then
  MANIFEST_EXISTS=true
fi
MANIFEST_PLATFORM=""
MANIFEST_SCOPE=""
RESTORED_ANY=false

# ── Restore Helpers ───────────────────────────────────────────────
# The backup directory name differs from the destination name (genome -> rules,
# organs -> skills), so `cp -r src dst` would nest src inside dst. Copy contents
# instead. Also creates the destination parent: `[ -f x ] && cp x dir/` aborted
# the whole script under `set -e` when dir/ did not exist.
restore_dir_contents() {
  local src="$1" dst="$2"
  [ -d "$src" ] || return 0
  guard_sink source "$src" "${BACKUP_ROOTS[@]}"
  guard_sink remove "$dst"
  mkdir -p "$dst" || return 0
  # Dotfiles included; an empty source is not an error.
  if find "$src" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null | grep -q .; then
    cp -R "$src"/. "$dst"/ 2>/dev/null || {
      log_warn "Could not fully restore $src -> $dst"
      return 0
    }
  fi
  echo "  restored $dst"
  RESTORED_ANY=true
  return 0
}

restore_file() {
  local src="$1" dst="$2"
  [ -f "$src" ] || return 0
  guard_sink source "$src" "${BACKUP_ROOTS[@]}"
  guard_sink remove "$dst"
  mkdir -p "$(dirname "$dst")" || return 0
  cp -- "$src" "$dst" 2>/dev/null || {
    log_warn "Could not restore $src -> $dst"
    return 0
  }
  echo "  restored $dst"
  RESTORED_ANY=true
  return 0
}

remove_soma_mcp_server() {
  local config_file="$1"
  guard_sink remove "$config_file"
  SOMA_MCP_FILE="$config_file" soma_python - <<'PY'
import json
import os
import stat
import tempfile

path = os.environ["SOMA_MCP_FILE"]
with open(path, "r", encoding="utf-8") as handle:
    data = json.load(handle)
if not isinstance(data, dict):
    raise ValueError("MCP configuration root must be a JSON object")
servers = data.get("mcpServers")
if not isinstance(servers, dict) or "soma" not in servers:
    raise ValueError("MCP configuration has no owned mcpServers.soma entry")
del servers["soma"]
parent = os.path.dirname(path) or "."
fd, temp_path = tempfile.mkstemp(prefix=".soma-mcp-", dir=parent, text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.chmod(temp_path, stat.S_IMODE(os.stat(path).st_mode))
    os.replace(temp_path, path)
except Exception:
    try:
        os.unlink(temp_path)
    except FileNotFoundError:
        pass
    raise
PY
  echo "Cleaned soma MCP server from $config_file"
}

echo "Uninstalling Soma ($PLATFORM)..."
[ "$DRY_RUN" = "true" ] && echo "Mode: DRY-RUN (no files will be deleted)"

FILES_TO_REMOVE=()
DIRS_TO_REMOVE=()
MODIFY_FILES=()
MCP_CONFIGS_TO_CLEAN=()
UNVERIFIED_MCP=()
BACKUP_DIR=""

add_known_rule_files() {
  local target_dir="$1" suffix="${2:-.md}" rule name target
  while IFS= read -r rule; do
    [ -n "$rule" ] || continue
    name="$(basename "$rule" .md)"
    target="$target_dir/$name$suffix"
    [ -f "$target" ] && FILES_TO_REMOVE+=("$target")
  done < <(find "$REPO_DIR/genome" -type f -name "*.md" | sort)
  return 0
}

add_known_skill_dirs() {
  local target_dir="$1" skill name target
  [ -d "$REPO_DIR/organs" ] || return 0
  for skill in "$REPO_DIR"/organs/*/; do
    [ -d "$skill" ] || continue
    name="$(basename "$skill")"
    target="$target_dir/$name"
    [ -d "$target" ] && DIRS_TO_REMOVE+=("$target")
  done
  return 0
}

queue_mcp_config() {
  local path="$1"
  [ -f "$path" ] || return 0
  if ! resolve_python; then
    # Cannot tell whether it holds an owned soma server; refused below.
    UNVERIFIED_MCP+=("$path")
    return 0
  fi
  if SOMA_MCP_FILE="$path" soma_python - <<'PY'
import json
import os
with open(os.environ["SOMA_MCP_FILE"], "r", encoding="utf-8") as handle:
    data = json.load(handle)
servers = data.get("mcpServers") if isinstance(data, dict) else None
raise SystemExit(0 if isinstance(servers, dict) and "soma" in servers else 1)
PY
  then
    MCP_CONFIGS_TO_CLEAN+=("$path")
  fi
  return 0
}

validate_soma_mcp_config() {
  local path="$1"
  SOMA_MCP_FILE="$path" soma_python - <<'PY'
import json
import os
with open(os.environ["SOMA_MCP_FILE"], "r", encoding="utf-8") as handle:
    data = json.load(handle)
if not isinstance(data, dict):
    raise ValueError("MCP configuration root must be a JSON object")
servers = data.get("mcpServers")
if not isinstance(servers, dict) or "soma" not in servers:
    raise ValueError("MCP configuration has no owned mcpServers.soma entry")
PY
}

# claude_settings_py <check|clean> <settings.json> (BUG-045)
#   check: exit 0 iff the file holds a hooks.soma entry.
#   clean: drop hooks.soma; write an exclusive mkstemp temp in the same
#          directory, give it the original mode, os.replace on success and
#          unlink it on failure. Refuses (exit 4) a symlinked file.
claude_settings_py() {
  SOMA_SETTINGS_FILE="$2" soma_python - "$1" <<'PY'
import json
import os
import stat
import sys
import tempfile

path = os.environ["SOMA_SETTINGS_FILE"]
st = os.lstat(path)
if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
    sys.exit(4)
with open(path, "r", encoding="utf-8") as handle:
    data = json.load(handle)
hooks = data.get("hooks") if isinstance(data, dict) else None
if not isinstance(hooks, dict) or "soma" not in hooks:
    sys.exit(1)
if sys.argv[1] == "check":
    sys.exit(0)
del hooks["soma"]
fd, temp_path = tempfile.mkstemp(prefix=".settings.json.", suffix=".tmp",
                                 dir=os.path.dirname(path) or ".")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.chmod(temp_path, stat.S_IMODE(st.st_mode))
    os.replace(temp_path, path)
except Exception:
    try:
        os.unlink(temp_path)
    except FileNotFoundError:
        pass
    raise
PY
}

# Queue a Claude settings.json for hooks.soma removal, or warn and skip it.
# Symlinks (the file or its .claude parent) are refused outright: rewriting
# through them edits a file outside the allowed roots.
CLAUDE_SETTINGS_TO_CLEAN=()
queue_claude_settings() {
  local path="$1" queued
  [ -e "$path" ] || [ -L "$path" ] || return 0
  for queued in ${CLAUDE_SETTINGS_TO_CLEAN[@]+"${CLAUDE_SETTINGS_TO_CLEAN[@]}"}; do
    [ "$queued" != "$path" ] || return 0
  done
  if [ -L "$path" ] || [ -L "$(dirname "$path")" ]; then
    log_warn "Not modifying $path: it or its .claude directory is a symlink. Remove hooks.soma by hand."
    return 0
  fi
  [ -f "$path" ] || return 0
  if ! resolve_python; then
    log_warn "Not inspecting $path: no working Python 3. Remove hooks.soma by hand."
    return 0
  fi
  claude_settings_py check "$path" 2>/dev/null || return 0
  if ! check_confined remove "$path" "${ALLOWED_ROOTS[@]}"; then
    log_warn "Not modifying $path: $CONFINE_REASON"
    return 0
  fi
  CLAUDE_SETTINGS_TO_CLEAN+=("$path")
}

# Reads one field from the manifest. The path is passed through the environment
# rather than interpolated into the Python source: a quote in the path used to
# be a silent SyntaxError (swallowed by 2>/dev/null), and a crafted directory
# name was code execution.
read_manifest_field() {
  SOMA_MANIFEST="$MANIFEST_PATH" soma_python -c '
import json, os, sys
# Bash reads one path per line as UTF-8. Native Windows Python would write
# CRLF (leaving a CR on every entry but the last) in the console code page.
sys.stdout.reconfigure(encoding="utf-8", errors="surrogateescape", newline="\n")
field = sys.argv[1]
with open(os.environ["SOMA_MANIFEST"], "r", encoding="utf-8") as fh:
    data = json.load(fh)
value = data.get(field)
if value is None:
    pass
elif isinstance(value, list):
    for item in value:
        if item:
            print(item)
else:
    print(value)
' "$1"
}

if [ "$MANIFEST_EXISTS" = "true" ]; then
  echo "Found manifest at $MANIFEST_PATH. Reading paths..."

  if ! resolve_python; then
    _python_missing_error
    log_error "A manifest exists at $MANIFEST_PATH but no working Python 3 is available to read it."
    log_error "Refusing to continue: guessing paths risks an incomplete uninstall."
    log_error "Install Python 3, or delete the manifest to use pattern-based removal."
    exit 1
  fi

  # Validate before use. Failures inside process substitution are invisible to
  # `set -e`, so the old code silently produced an empty removal plan, deleted
  # the manifest, and reported "Uninstall complete."
  if ! MANIFEST_PLATFORM="$(read_manifest_field platform 2>/dev/null)"; then
    log_error "Manifest at $MANIFEST_PATH is unreadable or not valid JSON."
    log_error "Refusing to continue. Repair or delete it, then re-run."
    exit 1
  fi

  # Platform guard: the manifest branch used to ignore $PLATFORM entirely, so
  # `uninstall.sh mcp` against a kiro manifest deleted the kiro install.
  if [ -n "$MANIFEST_PLATFORM" ] && [ "$MANIFEST_PLATFORM" != "$PLATFORM" ]; then
    if [ "$FORCE" = "true" ]; then
      log_warn "PLATFORM MISMATCH: manifest records '$MANIFEST_PLATFORM', you asked for '$PLATFORM'."
      log_warn "--force supplied, continuing: the '$MANIFEST_PLATFORM' paths will be removed."
    else
      log_error "PLATFORM MISMATCH: manifest records '$MANIFEST_PLATFORM', you asked for '$PLATFORM'."
      log_error "Re-run as: bash install/uninstall.sh $MANIFEST_PLATFORM"
      log_error "Or pass --force to remove the '$MANIFEST_PLATFORM' paths anyway."
      exit 1
    fi
  fi

  # Validate the WHOLE manifest before building the plan. Any unsafe entry in
  # files/organs/hooks/backup_dir aborts with nothing touched; the old code
  # skipped offenders silently and removed the rest.
  validate_rc=0
  validate_out="$(SOMA_MANIFEST="$MANIFEST_PATH" \
    SOMA_ROOTS="$(join_lines "${ALLOWED_ROOTS[@]}")" \
    SOMA_BACKUP_ROOTS="$(join_lines "${BACKUP_ROOTS[@]}")" \
    soma_python -I -S -c "$PATH_CHECK_PY" manifest 2>&1)" || validate_rc=$?
  if [ "$validate_rc" -ne 0 ]; then
    log_error "Manifest at $MANIFEST_PATH contains unsafe entries:"
    printf '%s\n' "$validate_out" >&2
    log_error "Allowed roots: ${ALLOWED_ROOTS[*]} (backup_dir: ${BACKUP_ROOTS[*]})"
    log_error "Refusing to continue. Nothing was removed and the manifest was kept."
    exit 1
  fi

  BACKUP_DIR="$(read_manifest_field backup_dir)"
  MANIFEST_SCOPE="$(read_manifest_field scope)"

  while IFS= read -r f; do
    [ -n "$f" ] || continue
    if [[ "$f" == *"/copilot-instructions.md" ]] || [[ "$f" == *"/CLAUDE.md" ]]; then
      MODIFY_FILES+=("$f")
    else
      FILES_TO_REMOVE+=("$f")
    fi
  done <<< "$(read_manifest_field files)"

  while IFS= read -r d; do
    [ -n "$d" ] && DIRS_TO_REMOVE+=("$d")
  done <<< "$(read_manifest_field organs)"

  while IFS= read -r h; do
    [ -n "$h" ] && FILES_TO_REMOVE+=("$h")
  done <<< "$(read_manifest_field hooks)"

  while IFS= read -r mcp_config; do
    [ -n "$mcp_config" ] && MCP_CONFIGS_TO_CLEAN+=("$mcp_config")
  done <<< "$(read_manifest_field mcp_configs)"
else
  echo "No manifest found. Falling back to source-owned names..."
  case "$PLATFORM" in
    gemini)
      add_known_rule_files "$RESOLVED_HOME/.gemini/config/rules"
      add_known_skill_dirs "$RESOLVED_HOME/.gemini/config/skills"
      add_known_rule_files "$WORK_DIR/.soma/rules"
      add_known_skill_dirs "$WORK_DIR/.soma/skills"
      [ -f "$RESOLVED_HOME/.gemini/config/plugins/governance/hooks.json" ] && \
        FILES_TO_REMOVE+=("$RESOLVED_HOME/.gemini/config/plugins/governance/hooks.json")
      [ -f "$WORK_DIR/.soma/plugins/governance/hooks.json" ] && \
        FILES_TO_REMOVE+=("$WORK_DIR/.soma/plugins/governance/hooks.json")
      true
      ;;
    kiro)
      add_known_rule_files "$RESOLVED_HOME/.kiro/steering"
      add_known_skill_dirs "$RESOLVED_HOME/.kiro/skills"
      [ -f "$RESOLVED_HOME/.kiro/hooks/hooks.json" ] && \
        FILES_TO_REMOVE+=("$RESOLVED_HOME/.kiro/hooks/hooks.json")
      queue_mcp_config "$RESOLVED_HOME/.kiro/settings/mcp.json"
      queue_mcp_config "$WORK_DIR/.kiro/settings/mcp.json"
      ;;
    copilot)
      add_known_rule_files "$WORK_DIR/.github/instructions" ".instructions.md"
      if [ -f "$RESOLVED_HOME/copilot-instructions.md" ]; then
        MODIFY_FILES+=("$RESOLVED_HOME/copilot-instructions.md")
      fi
      ;;
    claude)
      if [ -f "$WORK_DIR/CLAUDE.md" ]; then
        MODIFY_FILES+=("$WORK_DIR/CLAUDE.md")
      fi
      if [ -f "$RESOLVED_HOME/.claude/CLAUDE.md" ]; then
        MODIFY_FILES+=("$RESOLVED_HOME/.claude/CLAUDE.md")
      fi
      queue_mcp_config "$WORK_DIR/.mcp.json"
      ;;
    mcp)
      queue_mcp_config "$WORK_DIR/.mcp.json"
      ;;
  esac
fi

# ── User-Authored Data ────────────────────────────────────────────
# Cells, fitness history and snapshots are authored by the user, not installed
# by install.sh. Uninstalling a tool must not delete the user's work, so these
# are PRESERVED unless --purge-data is passed explicitly.
PRESERVED_PATHS=()
[ -d "$REPO_DIR/.soma/cells" ] && PRESERVED_PATHS+=("$REPO_DIR/.soma/cells")
[ -f "$REPO_DIR/fitness.jsonl" ] && PRESERVED_PATHS+=("$REPO_DIR/fitness.jsonl")
[ -d "$REPO_DIR/docs/snapshots" ] && PRESERVED_PATHS+=("$REPO_DIR/docs/snapshots")

if [ "$PURGE_DATA" = "true" ]; then
  if [ -d "$REPO_DIR/.soma/cells" ]; then
    DIRS_TO_REMOVE+=("$REPO_DIR/.soma/cells")
  fi
  [ -f "$REPO_DIR/fitness.jsonl" ] && FILES_TO_REMOVE+=("$REPO_DIR/fitness.jsonl")
  if [ -d "$REPO_DIR/docs/snapshots" ]; then
    DIRS_TO_REMOVE+=("$REPO_DIR/docs/snapshots")
  fi
  PRESERVED_PATHS=()
fi

# soma.conf is user configuration. Listed separately so the plan can label it
# as such instead of burying it among installed artifacts.
CONFIG_TO_REMOVE=()
if [ "$KEEP_CONFIG" = "false" ] && [ -f "$REPO_DIR/soma.conf" ]; then
  CONFIG_TO_REMOVE+=("$REPO_DIR/soma.conf")
fi

# ── Reconcile the Plan With Disk ──────────────────────────────────
# A manifest entry recorded as a file can exist as a directory, or be gone. The
# plan printed "[FILE]" for everything while the removal loop was [ -f ]-guarded,
# so directories were advertised as deletions and then silently left in place.
# Note: ${arr[@]+"${arr[@]}"} — on Bash 3.2, "${arr[@]}" on an empty array is
# fatal under `set -u`, which is why this script used to disable `set -u` across
# the entire removal section.
REAL_FILES=()
REAL_DIRS=()
for p in ${FILES_TO_REMOVE[@]+"${FILES_TO_REMOVE[@]}"} ${DIRS_TO_REMOVE[@]+"${DIRS_TO_REMOVE[@]}"}; do
  if [ -d "$p" ]; then
    REAL_DIRS+=("$p")
  elif [ -f "$p" ]; then
    REAL_FILES+=("$p")
  fi
done
FILES_TO_REMOVE=(${REAL_FILES[@]+"${REAL_FILES[@]}"})
DIRS_TO_REMOVE=(${REAL_DIRS[@]+"${REAL_DIRS[@]}"})

REAL_MOD=()
for m in ${MODIFY_FILES[@]+"${MODIFY_FILES[@]}"}; do
  [ -f "$m" ] && REAL_MOD+=("$m")
done
MODIFY_FILES=(${REAL_MOD[@]+"${REAL_MOD[@]}"})

REAL_MCP=()
for mcp_config in ${MCP_CONFIGS_TO_CLEAN[@]+"${MCP_CONFIGS_TO_CLEAN[@]}"}; do
  [ -f "$mcp_config" ] && REAL_MCP+=("$mcp_config")
done
MCP_CONFIGS_TO_CLEAN=(${REAL_MCP[@]+"${REAL_MCP[@]}"})

# Parse every owned MCP config before deleting anything. If it was corrupted or
# concurrently replaced, retain all installed files and the ownership manifest
# so the uninstall can be retried safely.
for mcp_config in ${MCP_CONFIGS_TO_CLEAN[@]+"${MCP_CONFIGS_TO_CLEAN[@]}"}; do
  if ! validate_soma_mcp_config "$mcp_config"; then
    log_error "MCP configuration is invalid or no longer contains the owned soma server: $mcp_config"
    log_error "Refusing to continue. Nothing was removed and the manifest was kept."
    exit 1
  fi
done

queue_claude_settings "$WORK_DIR/.claude/settings.json"
queue_claude_settings "$RESOLVED_HOME/.claude/settings.json"

# Confine the complete plan (manifest, fallback and --purge-data entries alike)
# before anything is touched, so a refusal never leaves a half-removed install.
# The manifest file itself is confined to MANIFEST_SINK_ROOT at the sink.
# Without a working Python 3 the plan cannot be confined (symlinked components
# are invisible to a lexical check), so any non-empty plan is refused: fail
# closed (BUG-043). The manifest branch already exited above in that case.
if ! resolve_python; then
  UNCONFINED_COUNT=$(( ${#FILES_TO_REMOVE[@]} + ${#DIRS_TO_REMOVE[@]} + ${#MODIFY_FILES[@]} + ${#MCP_CONFIGS_TO_CLEAN[@]} + ${#CONFIG_TO_REMOVE[@]} + ${#UNVERIFIED_MCP[@]} ))
  if [ "$UNCONFINED_COUNT" -gt 0 ]; then
    _python_missing_error
    log_error "Cannot verify that the $UNCONFINED_COUNT planned removal(s) stay inside the allowed roots without Python 3."
    log_error "Refusing to continue. Nothing was removed. Install Python 3 or set SOMA_PYTHON, then re-run."
    exit 1
  fi
else
  plan_rc=0
  plan_out="$(
    for p in ${FILES_TO_REMOVE[@]+"${FILES_TO_REMOVE[@]}"} ${DIRS_TO_REMOVE[@]+"${DIRS_TO_REMOVE[@]}"} \
             ${MODIFY_FILES[@]+"${MODIFY_FILES[@]}"} ${MCP_CONFIGS_TO_CLEAN[@]+"${MCP_CONFIGS_TO_CLEAN[@]}"} \
             ${CONFIG_TO_REMOVE[@]+"${CONFIG_TO_REMOVE[@]}"}; do
      [ "$p" = "$MANIFEST_PATH" ] || printf '%s\0' "$p"
    done | SOMA_ROOTS="$(join_lines "${SINK_ROOTS[@]}")" soma_python -I -S -c "$PATH_CHECK_PY" plan 2>&1
  )" || plan_rc=$?
  if [ "$plan_rc" -ne 0 ]; then
    log_error "The removal plan contains paths outside the allowed roots:"
    printf '%s\n' "$plan_out" >&2
    log_error "Refusing to continue. Nothing was removed."
    exit 1
  fi
fi

echo ""
echo "The following will be removed/modified:"
if [ "$MANIFEST_EXISTS" = "true" ]; then echo "  - [MANIFEST] $MANIFEST_PATH"; fi
for f in ${FILES_TO_REMOVE[@]+"${FILES_TO_REMOVE[@]}"}; do echo "  - [FILE] $f"; done
for d in ${DIRS_TO_REMOVE[@]+"${DIRS_TO_REMOVE[@]}"}; do echo "  - [DIR]  $d"; done
for m in ${MODIFY_FILES[@]+"${MODIFY_FILES[@]}"}; do echo "  - [MOD]  $m (remove soma sections, keep the rest)"; done
for mcp_config in ${MCP_CONFIGS_TO_CLEAN[@]+"${MCP_CONFIGS_TO_CLEAN[@]}"}; do echo "  - [MCP]  $mcp_config (remove mcpServers.soma, keep the rest)"; done
for c in ${CONFIG_TO_REMOVE[@]+"${CONFIG_TO_REMOVE[@]}"}; do echo "  - [USER CONFIG] $c (pass --keep-config to keep it)"; done
for s in ${CLAUDE_SETTINGS_TO_CLEAN[@]+"${CLAUDE_SETTINGS_TO_CLEAN[@]}"}; do echo "  - [MOD]  $s (remove hooks.soma, keep the rest)"; done

MANIFEST_COUNT=0
[ "$MANIFEST_EXISTS" != "true" ] || MANIFEST_COUNT=1
PLAN_COUNT=$(( MANIFEST_COUNT + ${#FILES_TO_REMOVE[@]} + ${#DIRS_TO_REMOVE[@]} + ${#MODIFY_FILES[@]} + ${#MCP_CONFIGS_TO_CLEAN[@]} + ${#CONFIG_TO_REMOVE[@]} + ${#CLAUDE_SETTINGS_TO_CLEAN[@]} ))
if [ "$PLAN_COUNT" -eq 0 ]; then
  echo "Nothing to remove."
  exit 0
fi

if [ ${#PRESERVED_PATHS[@]} -gt 0 ]; then
  echo ""
  echo "Preserved (user-authored — pass --purge-data to remove):"
  for p in ${PRESERVED_PATHS[@]+"${PRESERVED_PATHS[@]}"}; do echo "  - [KEEP] $p"; done
fi

if [ "$DRY_RUN" = "false" ] && [ "$FORCE" = "false" ]; then
  # `read -p` returns 1 at EOF, and under `set -e` that aborted the script with
  # a bare exit 1 in CI, containers, or `curl | bash`. Abort explicitly instead.
  if [ ! -t 0 ]; then
    echo ""
    log_error "Confirmation required but stdin is not a terminal."
    log_error "Aborting without removing anything. Re-run with --force, or --dry-run to preview."
    exit 2
  fi
  echo ""
  read -r -p "Proceed with deletion? (y/N): " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
  fi
fi

if [ "$DRY_RUN" = "true" ]; then
  # Preview the restore mapping here. The old dry-run preview lived inside the
  # restore block further down, which this early exit made unreachable.
  if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
    echo ""
    echo "Would offer to restore from: $BACKUP_DIR"
    case "$PLATFORM" in
      gemini)
        if [ "$MANIFEST_SCOPE" = "local" ]; then
          echo "  $BACKUP_DIR/genome     -> $WORK_DIR/.soma/rules"
          echo "  $BACKUP_DIR/organs     -> $WORK_DIR/.soma/skills"
          echo "  $BACKUP_DIR/governance -> $WORK_DIR/.soma/plugins/governance"
        else
          echo "  $BACKUP_DIR/genome     -> $RESOLVED_HOME/.gemini/config/rules"
          echo "  $BACKUP_DIR/organs     -> $RESOLVED_HOME/.gemini/config/skills"
          echo "  $BACKUP_DIR/governance -> $RESOLVED_HOME/.gemini/config/plugins/governance"
        fi
        ;;
      kiro)
        echo "  $BACKUP_DIR/genome -> $RESOLVED_HOME/.kiro/steering"
        echo "  $BACKUP_DIR/organs -> $RESOLVED_HOME/.kiro/skills"
        echo "  $BACKUP_DIR/hooks  -> $RESOLVED_HOME/.kiro/hooks"
        ;;
      copilot)
        echo "  $BACKUP_DIR/copilot-instructions.md -> $RESOLVED_HOME/copilot-instructions.md"
        ;;
      claude)
        if [ "$MANIFEST_SCOPE" = "local" ]; then
          echo "  $BACKUP_DIR/CLAUDE.md -> $(pwd)/CLAUDE.md"
        else
          echo "  $BACKUP_DIR/CLAUDE.md -> $RESOLVED_HOME/.claude/CLAUDE.md"
        fi
        echo "  $BACKUP_DIR/.mcp.json -> $(pwd)/.mcp.json"
        ;;
      mcp)
        echo "  $BACKUP_DIR/.mcp.json -> $(pwd)/.mcp.json"
        ;;
    esac
  fi
  echo ""
  echo "Dry-run complete. Nothing was removed."
  exit 0
fi

# Inventory in-place backups BEFORE removing anything: cleaning a [MOD] file
# writes a fresh .bak containing Soma content, and the parent of a removed file
# may disappear.
for f in ${FILES_TO_REMOVE[@]+"${FILES_TO_REMOVE[@]}"}; do
  # The manifest itself is script-derived; see MANIFEST_SINK_ROOT.
  if [ "$f" = "$MANIFEST_PATH" ]; then
    guard_sink remove "$f" "$MANIFEST_SINK_ROOT"
  else
    guard_sink remove "$f"
  fi
  if [ -L "$f" ]; then
    rm -f "$f" && echo "Removed symlink $f"
  elif [ -f "$f" ]; then
    rm -f "$f" && echo "Removed $f"
  fi
done
for d in ${DIRS_TO_REMOVE[@]+"${DIRS_TO_REMOVE[@]}"}; do
  guard_sink remove "$d"
  if [ -L "$d" ]; then
    rm -f "$d" && echo "Removed directory symlink $d"
  elif [ -d "$d" ]; then
    rm -rf "$d" && echo "Removed $d/"
  fi
done

for m in ${MODIFY_FILES[@]+"${MODIFY_FILES[@]}"}; do
  guard_sink remove "$m"
  if [ -L "$m" ]; then
    # sed -i would read through the link and replace it with a regular file.
    log_warn "Not modifying $m: it is a symlink. Remove the Soma section by hand."
    continue
  fi
  if [ -f "$m" ]; then
    sed -i.bak '/^# Copilot Global Instructions/,$d' "$m" && rm -f "$m.bak"
    sed -i.bak '/^# Soma Governance Rules/,$d' "$m" && rm -f "$m.bak"
    # Truncating at our header can leave an empty file behind. Remove it only if
    # nothing but whitespace remains, so a user's own content is never lost.
    if [ ! -s "$m" ] || [ -z "$(tr -d '[:space:]' < "$m")" ]; then
      rm -f "$m"
      echo "Cleaned and removed $m (contained only soma content)"
    else
      echo "Cleaned $m"
    fi
  fi
done

for mcp_config in ${MCP_CONFIGS_TO_CLEAN[@]+"${MCP_CONFIGS_TO_CLEAN[@]}"}; do
  if [ -f "$mcp_config" ]; then
    remove_soma_mcp_server "$mcp_config"
  fi
done

for c in ${CONFIG_TO_REMOVE[@]+"${CONFIG_TO_REMOVE[@]}"}; do
  guard_sink remove "$c"
  if [ -f "$c" ]; then
    rm -f "$c" && echo "Removed user config $c"
  fi
done

# Clean soma hooks from claude settings.json (queued, confined and previewed
# above; BUG-045). Re-checked at the sink: the symlink test and guard_sink
# catch a component swapped since planning.
for settings_file in ${CLAUDE_SETTINGS_TO_CLEAN[@]+"${CLAUDE_SETTINGS_TO_CLEAN[@]}"}; do
  if [ -L "$settings_file" ] || [ -L "$(dirname "$settings_file")" ]; then
    log_warn "Not modifying $settings_file: it or its .claude directory became a symlink."
    continue
  fi
  guard_sink remove "$settings_file" "${ALLOWED_ROOTS[@]}"
  if claude_settings_py clean "$settings_file"; then
    echo "Cleaned soma hooks from $settings_file"
  else
    log_warn "Could not rewrite $settings_file — left unchanged."
  fi
done

# If manifest file exists and wasn't caught by the array (e.g. empty)
if [ -f "$MANIFEST_PATH" ]; then
  guard_sink remove "$MANIFEST_PATH" "$MANIFEST_SINK_ROOT"
  rm -f "$MANIFEST_PATH"
fi

if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
  # Restore source: re-check right before it is read from.
  guard_sink source "$BACKUP_DIR" "${BACKUP_ROOTS[@]}"
  echo ""
  if [ "$NO_RESTORE" = "true" ]; then
    echo "Skipping restore (--no-restore). Backup left at $BACKUP_DIR"
  elif [ ! -t 0 ]; then
    # Previously `read -p` here aborted the script under `set -e` at EOF.
    echo "Not restoring: stdin is not a terminal."
    echo "Backup preserved at $BACKUP_DIR — copy from it manually if needed."
  else
      # --force skips the DELETION prompt only. It used to also skip restore,
      # so the one flag meant for automation disabled recovery.
      read -r -p "Restore previous configuration from backup? [y/N] " restore_confirm
      if [[ "$restore_confirm" =~ ^[Yy]$ ]]; then
        echo "Restoring from $BACKUP_DIR..."
        case "$PLATFORM" in
          gemini)
            if [ "$MANIFEST_SCOPE" = "local" ]; then
              restore_dir_contents "$BACKUP_DIR/genome" "$WORK_DIR/.soma/rules"
              restore_dir_contents "$BACKUP_DIR/organs" "$WORK_DIR/.soma/skills"
              restore_dir_contents "$BACKUP_DIR/governance" "$WORK_DIR/.soma/plugins/governance"
            else
              restore_dir_contents "$BACKUP_DIR/genome" "$RESOLVED_HOME/.gemini/config/rules"
              restore_dir_contents "$BACKUP_DIR/organs" "$RESOLVED_HOME/.gemini/config/skills"
              restore_dir_contents "$BACKUP_DIR/governance" "$RESOLVED_HOME/.gemini/config/plugins/governance"
            fi
            ;;
          kiro)
            restore_dir_contents "$BACKUP_DIR/genome" "$RESOLVED_HOME/.kiro/steering"
            restore_dir_contents "$BACKUP_DIR/organs" "$RESOLVED_HOME/.kiro/skills"
            restore_dir_contents "$BACKUP_DIR/hooks" "$RESOLVED_HOME/.kiro/hooks"
            ;;
          copilot)
            restore_file "$BACKUP_DIR/copilot-instructions.md" "$RESOLVED_HOME/copilot-instructions.md"
            ;;
          claude)
            # A local install backed up the project CLAUDE.md, so restore it to
            # the scope it came from rather than always to the global home.
            if [ "$MANIFEST_SCOPE" = "local" ]; then
              restore_file "$BACKUP_DIR/CLAUDE.md" "$(pwd)/CLAUDE.md"
            else
              restore_file "$BACKUP_DIR/CLAUDE.md" "$RESOLVED_HOME/.claude/CLAUDE.md"
            fi
            restore_file "$BACKUP_DIR/.mcp.json" "$(pwd)/.mcp.json"
            ;;
          mcp)
            restore_file "$BACKUP_DIR/.mcp.json" "$(pwd)/.mcp.json"
            ;;
        esac
        if [ "$RESTORED_ANY" = "true" ]; then
          echo "Restore complete."
        else
          # Do not claim success when nothing was found to restore.
          log_warn "Nothing was restored: $BACKUP_DIR held no recognised payload."
        fi
      else
        echo "Skipping restore. Backup left at $BACKUP_DIR"
      fi
  fi
fi

echo "Uninstall complete."
