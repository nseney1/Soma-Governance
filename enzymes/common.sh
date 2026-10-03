#!/usr/bin/env bash
# Soma — Shared Library
# Sourced by install.sh and platform wrappers.
# Provides config loading, validation, backup, and formatting utilities.

set -euo pipefail

# ── Colors & Formatting ──────────────────────────────────────────
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly RED='\033[0;31m'
readonly CYAN='\033[0;36m'
readonly NC='\033[0m' # No Color

# ── Unicode & Formatting ─────────────────────────────────────────
supports_unicode() {
  [ "${NO_UNICODE:-0}" = "1" ] && return 1
  local locale="${LC_ALL:-${LC_CTYPE:-${LANG:-}}}"
  if [[ "$locale" =~ [Uu][Tt][Ff]-?8 ]]; then
    return 0
  fi
  [ -n "${WT_SESSION:-}" ] && return 0
  return 1
}

log_info()  {
  if supports_unicode; then
    echo -e "  ${GREEN}✅${NC} $*"
  else
    echo -e "  ${GREEN}[OK]${NC} $*"
  fi
}
log_warn()  {
  if supports_unicode; then
    echo -e "  ${YELLOW}⚠${NC}  $*"
  else
    echo -e "  ${YELLOW}[WARN]${NC} $*"
  fi
}
log_skip()  {
  if supports_unicode; then
    echo -e "  ${CYAN}⏭${NC}  $*"
  else
    echo -e "  ${CYAN}[SKIP]${NC} $*"
  fi
}
log_error() {
  if supports_unicode; then
    echo -e "  ${RED}❌${NC} $*" >&2
  else
    echo -e "  ${RED}[ERROR]${NC} $*" >&2
  fi
}

# ── OS & Path Resolution ──────────────────────────────────────────
detect_os() {
  if [ -f /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; then
    echo "wsl"
  elif uname -r 2>/dev/null | grep -qi microsoft; then
    echo "wsl"
  else
    case "$(uname -s 2>/dev/null)" in
      Darwin*)              echo "macos" ;;
      Linux*)               echo "linux" ;;
      MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
      *)
        case "${OSTYPE:-}" in
          darwin*)          echo "macos" ;;
          linux*)           echo "linux" ;;
          msys*|cygwin*)    echo "windows" ;;
          *)                echo "linux" ;;
        esac
        ;;
    esac
  fi
}

# Returns $HOME, or fails loudly. Never emits a literal "~": inside double
# quotes the shell does not expand it, so "${HOME:-~}" used to produce a
# relative directory named "~" in the launch directory. A "global" install then
# landed in ./~/ and install.sh ran `rm -rf ./~/.soma/backup` against it.
_home_or_fail() {
  if [ -n "${HOME:-}" ]; then
    echo "$HOME"
    return 0
  fi
  log_error "Cannot resolve a home directory: neither HOME nor USERPROFILE is set."
  log_error "Set HOME (or USERPROFILE on Windows) and re-run."
  return 1
}

resolve_home() {
  local os="${1:-$(detect_os)}"
  case "$os" in
    wsl)
      if command -v wslpath &>/dev/null && command -v cmd.exe &>/dev/null; then
        local win_prof
        win_prof="$(cmd.exe /C 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')"
        if [ -n "$win_prof" ]; then
          wslpath -u "$win_prof" 2>/dev/null && return 0
        fi
      fi
      _home_or_fail
      ;;
    windows)
      if [ -n "${USERPROFILE:-}" ]; then
        if command -v cygpath &>/dev/null; then
          cygpath -u "$USERPROFILE"
        else
          echo "$USERPROFILE" | sed -e 's|\\|/|g' -e 's|^\([A-Za-z]\):|/\L\1|'
        fi
      else
        _home_or_fail
      fi
      ;;
    macos|linux|*)
      _home_or_fail
      ;;
  esac
}

normalize_path() {
  local p="$1"
  local os="${2:-$(detect_os)}"
  if [ "$os" = "windows" ]; then
    if command -v cygpath &>/dev/null; then
      cygpath -w "$p" 2>/dev/null || echo "$p" | sed 's|/|\\|g'
    else
      echo "$p" | sed -E 's|^/([a-zA-Z])/|\1:\\|' | sed 's|/|\\|g'
    fi
  else
    echo "$p"
  fi
}

# (P7: resolve_script_dir removed — zero callers confirmed repo-wide)

# ── Python Interpreter Resolution ────────────────────────────────
# `command -v python3` is not proof of a working interpreter: under Git Bash
# it can be the Windows Store App Installer stub, which exits 49 with no
# output (BUG-037). A candidate is accepted only if it actually runs Python 3.
# SOMA_PYTHON (one executable path) overrides the search. Resolved once when
# this file is sourced so $(...) subshells reuse it; call through soma_python.
SOMA_PYTHON_CMD=()

# The probe only needs sys: -I -S keeps PYTHON* env vars, site-packages and
# the current directory out of it (matches uninstall.sh's checker calls).
_python_candidate_works() {
  "$@" -I -S -c 'import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)' \
    </dev/null >/dev/null 2>&1
}

resolve_python() {
  [ "${#SOMA_PYTHON_CMD[@]}" -gt 0 ] && return 0
  if [ -n "${SOMA_PYTHON:-}" ]; then
    _python_candidate_works "$SOMA_PYTHON" || return 1
    SOMA_PYTHON_CMD=("$SOMA_PYTHON")
    return 0
  fi
  local cand
  for cand in "python3" "python"; do
    if command -v "$cand" >/dev/null 2>&1 && _python_candidate_works "$cand"; then
      SOMA_PYTHON_CMD=("$cand")
      return 0
    fi
  done
  if command -v py >/dev/null 2>&1 && _python_candidate_works py -3; then
    SOMA_PYTHON_CMD=(py -3)
    return 0
  fi
  return 1
}

_python_missing_error() {
  log_error "No working Python 3 interpreter found (tried ${SOMA_PYTHON:+SOMA_PYTHON=$SOMA_PYTHON, }python3, python, py -3). Install Python 3 or set SOMA_PYTHON to its path."
}

# soma_python <args...> — run the resolved interpreter, or fail loudly (127).
soma_python() {
  if ! resolve_python; then
    _python_missing_error
    return 127
  fi
  "${SOMA_PYTHON_CMD[@]}" "$@"
}

resolve_python || true

# ── Configuration Loading ────────────────────────────────────────
# Loads soma.conf if present. Environment variables take precedence.
load_config() {
  local repo_dir="$1"
  local conf="$repo_dir/soma.conf"

  if [ -f "$conf" ]; then
    # Safe config parsing (S2 fix: no arbitrary code execution)
    while IFS= read -r line || [ -n "$line" ]; do
      line="${line//$'\r'/}"         # Strip CRLF
      line="${line#"${line%%[![:space:]]*}"}"  # Trim leading whitespace
      [[ -z "$line" || "$line" =~ ^# ]] && continue
      if [[ "$line" =~ ^([A-Za-z0-9_]+)[[:space:]]*=[[:space:]]*(.*)$ ]]; then
        key="${BASH_REMATCH[1]}"; val="${BASH_REMATCH[2]}"
        val="${val%%#*}"             # Strip inline comments
        # Strip surrounding quotes
        [[ "$val" =~ ^\"(.*)\"$ || "$val" =~ ^\'(.*)\'$ ]] && val="${BASH_REMATCH[1]}"
        case "$key" in
          SOMA_PLATFORM|TEAM_SIZE|APPROVAL_CHAIN|GIT_STRATEGY|RULES_SUBSET|ENABLE_HOOKS|TEAM_REPO|TEAM_MEMBER_ID|ORG_REPO|METRICS_REPO)
            [ -z "${!key:-}" ] && export "$key=$val" ;;
        esac
      fi
    done < "$conf"
  fi

  # Apply defaults for any unset variables
  TEAM_SIZE="${TEAM_SIZE:-solo}"
  GIT_STRATEGY="${GIT_STRATEGY:-trunk}"
  APPROVAL_CHAIN="${APPROVAL_CHAIN:-none}"
  RULES_SUBSET="${RULES_SUBSET:-all}"
  ENABLE_HOOKS="${ENABLE_HOOKS:-true}"
  # Thorns fix #6: namespaced to avoid Docker/CI PLATFORM collision
  SOMA_PLATFORM="${SOMA_PLATFORM:-gemini}"
  TEAM_REPO="${TEAM_REPO:-}"
  TEAM_MEMBER_ID="${TEAM_MEMBER_ID:-}"
  ORG_REPO="${ORG_REPO:-}"
  METRICS_REPO="${METRICS_REPO:-}"
}

# ── Enum Validation ──────────────────────────────────────────────
# Validates a value against a whitelist of allowed values.
validate_enum() {
  local name="$1"
  local value="$2"
  shift 2
  local allowed=("$@")

  for v in "${allowed[@]}"; do
    [ "$value" = "$v" ] && return 0
  done

  log_error "Invalid $name: '$value' (allowed: ${allowed[*]})"
  exit 1
}

# ── Validate All Configuration ───────────────────────────────────
validate_config() {
  validate_enum "TEAM_SIZE" "$TEAM_SIZE" solo small team enterprise
  validate_enum "GIT_STRATEGY" "$GIT_STRATEGY" trunk feature-branch gitflow
  validate_enum "APPROVAL_CHAIN" "$APPROVAL_CHAIN" none peer lead
  validate_enum "RULES_SUBSET" "$RULES_SUBSET" all core minimal
  validate_enum "ENABLE_HOOKS" "$ENABLE_HOOKS" true false
  validate_enum "SOMA_PLATFORM" "$SOMA_PLATFORM" gemini kiro copilot claude mcp
}

# ── Rule Subset Resolution ───────────────────────────────────────
# Sets RULE_LIST based on RULES_SUBSET. Empty = install all.
resolve_subset() {
  case "$RULES_SUBSET" in
    minimal) RULE_LIST="providence.md subagent-delegation.md destructive-ops.md" ;;
    core)    RULE_LIST="providence.md cost-optimization.md subagent-delegation.md testing.md git-workflow.md destructive-ops.md" ;;
    all)     RULE_LIST="" ;;
  esac
}

# ── Rule Inclusion Check ─────────────────────────────────────────
# Returns 0 if the rule should be installed, 1 if skipped.
should_install() {
  local name="$1"
  # Empty RULE_LIST = install everything
  [ -z "$RULE_LIST" ] && return 0
  # Use -- to prevent filenames like -rf from being parsed as grep options
  echo "$RULE_LIST" | grep -qw -- "$name"
}

# ── Backup Retention ─────────────────────────────────────────────
# Keep only the most recent $SOMA_BACKUP_RETENTION ".bak.<epoch>" siblings of
# $1. These were minted per run with no bound: steering and skill directories
# ended up 70-80% backups. They are also unreachable by uninstall, because the
# manifest globs "*.md" and can never match "NAME.md.bak.1790693059".
_prune_backups() {
  local target="$1"
  local keep="${SOMA_BACKUP_RETENTION:-3}"
  case "$keep" in
    ''|*[!0-9]*) keep=3 ;;
  esac
  local dir base victim
  dir="$(dirname "$target")"
  base="$(basename "$target")"
  [ -d "$dir" ] || return 0
  find "$dir" -maxdepth 1 -name "${base}.bak.*" 2>/dev/null \
    | awk -F'\\.bak\\.' 'NF==2 && $2 ~ /^[0-9]+$/ { print $2"\t"$0 }' \
    | sort -rn \
    | awk -v k="$keep" 'NR>k { sub(/^[0-9]+\t/, ""); print }' \
    | while IFS= read -r victim; do
        [ -n "$victim" ] || continue
        rm -rf -- "$victim"
      done
  return 0
}

# ── File Backup (Timestamped) ────────────────────────────────────
# Creates a timestamped backup to prevent clobbering.
backup_file() {
  local target="$1"
  [ "${DRY_RUN:-false}" = "true" ] && return 0
  if [ -f "$target" ]; then
    local ts
    ts="$(date +%s 2>/dev/null || echo 'bak')"
    local backup="${target}.bak.${ts}"
    cp -- "$target" "$backup"
    log_warn "$(basename "$target") backed up to $(basename "$backup")"
    _prune_backups "$target"
  fi
}

# ── Directory Backup (Safe) ──────────────────────────────────────
# Removes existing .bak dir first to prevent recursive nesting.
backup_dir() {
  local target="$1"
  [ "${DRY_RUN:-false}" = "true" ] && return 0
  if [ -d "$target" ]; then
    local ts
    ts="$(date +%s 2>/dev/null || echo 'bak')"
    local backup="${target}.bak.${ts}"
    # Remove stale backup if exists to prevent nesting
    [ -d "$backup" ] && rm -rf -- "$backup"
    cp -r -- "$target" "$backup"
    log_warn "$(basename "$target")/ backed up to $(basename "$backup")/"
    _prune_backups "$target"
  fi
}

# ── Portable Frontmatter Strip ───────────────────────────────────
# Strips YAML frontmatter (--- delimited) using awk (not BSD-incompatible sed).
strip_frontmatter() {
  awk '
    BEGIN { in_front=0; found=0 }
    NR==1 && /^---$/ { in_front=1; next }
    in_front && /^---$/ { in_front=0; found=1; next }
    !in_front && found { print }
    !in_front && !found { print }
  '
}

# ── Team Override Application ────────────────────────────────────
# Appends team/gitflow/approval overrides to installed rule copies.
# Idempotent: checks for existing override marker before appending.
apply_team_overrides() {
  local rules_dir="$1"

  # Team branching override
  local git_wf="$rules_dir/git-workflow.md"
  [ -f "$rules_dir/git-workflow.instructions.md" ] && git_wf="$rules_dir/git-workflow.instructions.md"

  if [ "$TEAM_SIZE" != "solo" ]; then
    if [ "${DRY_RUN:-false}" = "true" ]; then
      log_info "[dry-run] would apply team branching override to $(basename "$git_wf")"
    elif [ -f "$rules_dir/git-workflow.md" ] || [ -f "$rules_dir/git-workflow.instructions.md" ]; then
      if ! grep -q "## Team Workflow Overrides" "$git_wf" 2>/dev/null; then
        cat >> "$git_wf" << 'TEAM_OVERRIDE'

## Team Workflow Overrides (auto-generated)
- **All changes via feature branches**: Direct commits to main are prohibited for teams.
- **PR descriptions**: Every PR must include a summary of what changed and why.
- **Review required**: At least one peer review before merge.
- **Branch naming**: Use `feature/<name>`, `fix/<name>`, `chore/<name>` prefixes.
TEAM_OVERRIDE
        log_info "$(basename "$git_wf"): team branching enforced"
      fi
    fi
  fi

  # Gitflow override
  if [ "$GIT_STRATEGY" = "gitflow" ]; then
    if [ "${DRY_RUN:-false}" = "true" ]; then
      log_info "[dry-run] would apply gitflow strategy override to $(basename "$git_wf")"
    elif [ -f "$rules_dir/git-workflow.md" ] || [ -f "$rules_dir/git-workflow.instructions.md" ]; then
      if ! grep -q "## Gitflow Overrides" "$git_wf" 2>/dev/null; then
        cat >> "$git_wf" << 'GITFLOW_OVERRIDE'

## Gitflow Overrides (auto-generated)
- **develop branch**: All feature branches merge to `develop`, not `main`.
- **release branches**: Cut `release/<version>` from `develop` when preparing a release.
- **hotfix branches**: Branch from `main` as `hotfix/<name>`, merge back to both `main` and `develop`.
GITFLOW_OVERRIDE
        log_info "$(basename "$git_wf"): gitflow strategy applied"
      fi
    fi
  fi

  # Approval chain override (quoted heredoc — Thorns fix: prevents prompt injection)
  local dest_ops="$rules_dir/destructive-ops.md"
  [ -f "$rules_dir/destructive-ops.instructions.md" ] && dest_ops="$rules_dir/destructive-ops.instructions.md"

  if [ "$APPROVAL_CHAIN" != "none" ]; then
    if [ "${DRY_RUN:-false}" = "true" ]; then
      log_info "[dry-run] would apply $APPROVAL_CHAIN approval chain override to $(basename "$dest_ops")"
    elif [ -f "$rules_dir/destructive-ops.md" ] || [ -f "$rules_dir/destructive-ops.instructions.md" ]; then
      if ! grep -q "## Approval Chain Override" "$dest_ops" 2>/dev/null; then
        local chain="$APPROVAL_CHAIN"
        cat >> "$dest_ops" << APPROVAL_OVERRIDE

## Approval Chain Override (auto-generated)
- **Approval required**: All destructive operations require ${chain} approval before execution.
- **Document approver**: When executing destructive ops, cite who approved and when.
APPROVAL_OVERRIDE
        log_info "$(basename "$dest_ops"): $APPROVAL_CHAIN approval chain enforced"
      fi
    fi
  fi
}

# ── Hooks Installation ───────────────────────────────────────────
# Renders hooks.json.template with resolved paths and installs to target.
install_hooks() {
  local repo_dir="$1"
  local target_dir="$2"
  local template="$repo_dir/install/hooks.json.template"
  # Fallback: check repo root for backward compatibility
  [ ! -f "$template" ] && template="$repo_dir/hooks.json.template"
  local scripts_dir="$repo_dir/enzymes"
  local target="$target_dir/hooks.json"

  if [ ! -f "$template" ]; then
    log_warn "hooks.json.template not found, skipping hooks installation"
    return 0
  fi

  if [ "${DRY_RUN:-false}" = "true" ]; then
    log_info "[dry-run] would install hooks.json to $(normalize_path "$target_dir")/"
    return 0
  fi

  mkdir -p "$target_dir"

  # Thorns fix #4: Use python for safe JSON templating instead of sed.
  # No interpreter is an error, not a skip: silently missing hooks leave the
  # safety gate uninstalled (BUG-037).
  if ! resolve_python; then
    _python_missing_error
    log_error "hooks.json not installed"
    return 1
  fi
  # Render to a temp file beside the target and replace it only once the
  # result is known-good JSON: truncating hooks.json first left an empty or
  # missing file (and no safety gate) whenever rendering failed. The template
  # is UTF-8 regardless of the locale encoding. Mode "x" refuses to follow a
  # pre-planted file or symlink at the temp path.
  local tmp="$target_dir/.hooks.json.$$.tmp"
  local rc=0
  soma_python -c "
import json, sys
with open(sys.argv[1], encoding='utf-8') as fh:
    rendered = fh.read().replace('{{SCRIPTS_DIR}}', sys.argv[2])
try:
    json.loads(rendered)
except ValueError as exc:
    sys.stderr.write('invalid JSON: %s\n' % exc)
    sys.exit(3)
with open(sys.argv[3], 'x', encoding='utf-8', newline='') as fh:
    fh.write(rendered)
" "$template" "$scripts_dir" "$tmp" || rc=$?

  if [ "$rc" -ne 0 ]; then
    rm -f -- "$tmp"
    if [ "$rc" -eq 3 ]; then
      log_error "hooks.json rendering produced invalid JSON"
    else
      log_error "hooks.json rendering failed (exit $rc)"
    fi
    log_error "hooks.json not installed; any existing $(basename "$target_dir")/hooks.json was left unchanged"
    return 1
  fi
  if ! mv -f -- "$tmp" "$target"; then
    rm -f -- "$tmp"
    log_error "Could not move rendered hooks.json into place at $target"
    return 1
  fi
  log_info "hooks.json installed to $(basename "$target_dir")/"
}
