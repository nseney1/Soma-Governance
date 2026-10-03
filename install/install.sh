#!/usr/bin/env bash
set -euo pipefail

# Unified Installer — soma
# Replaces install-gemini.sh, install-kiro.sh, install-copilot.sh
# Usage: bash install.sh [platform] [mode] [--dry-run] [--local]
#   platform: gemini (default) | kiro | copilot | claude | mcp
#   mode:     global (default) | project  (copilot only)
#   options:  --dry-run, -n, --local, --jit (v0.23 MCP-first mode)

# Symlink-safe resolution (Thorns fix #3)
PRG="${BASH_SOURCE[0]}"
while [ -h "$PRG" ]; do
  DIR="$(cd -P "$(dirname "$PRG")" && pwd)"
  PRG="$(readlink "$PRG")"
  [[ $PRG != /* ]] && PRG="$DIR/$PRG"
done
REPO_DIR="$(cd -P "$(dirname "$PRG")/.." && pwd)"

source "$REPO_DIR/enzymes/common.sh"

# Load config FIRST so soma.conf values are available
load_config "$REPO_DIR"

# Parse CLI flags & positional arguments
DRY_RUN=false
LOCAL_INSTALL=false
JIT_MODE=false
POSITIONAL_ARGS=()

for arg in "$@"; do
  case "$arg" in
    --dry-run|-n)
      DRY_RUN=true
      ;;
    --local)
      LOCAL_INSTALL=true
      ;;
    --hooks)
      INSTALL_GIT_HOOKS=true
      ;;
    --jit)
      JIT_MODE=true
      ;;
    *)
      POSITIONAL_ARGS+=("$arg")
      ;;
  esac
done
export DRY_RUN
export LOCAL_INSTALL

# CLI arg > soma.conf > default
SOMA_PLATFORM="${POSITIONAL_ARGS[0]:-$SOMA_PLATFORM}"
PLATFORM="$SOMA_PLATFORM"  # alias for use in case statement
MODE="${POSITIONAL_ARGS[1]:-global}"

validate_config
resolve_subset

# OS Detection & Home Resolution
DETECTED_OS="$(detect_os)"
RESOLVED_HOME="$(resolve_home "$DETECTED_OS")"

# ── Migration: .prism/ → .soma/ ──
# Auto-detect and migrate existing Prism (legacy) installations
migrate_prism_to_soma() {
  local target_dir="$1"
  local old_dir="$target_dir/.prism"
  local new_dir="$target_dir/.soma"
  
  if [ -d "$old_dir" ] && [ ! -d "$new_dir" ]; then
    log_info "Detected legacy .prism/ directory — migrating to .soma/"
    if [ "$DRY_RUN" = "true" ]; then
      log_info "[DRY-RUN] Would rename $old_dir → $new_dir"
    else
      mv "$old_dir" "$new_dir"
      # Leave a symlink for backward compatibility during transition
      ln -sf ".soma" "$old_dir" 2>/dev/null || true
      log_info "✅ Migrated .prism/ → .soma/"
    fi
  elif [ -d "$old_dir" ] && [ -d "$new_dir" ]; then
    log_warn "Both .prism/ and .soma/ exist. Using .soma/ — remove .prism/ manually if no longer needed."
  fi
}

# Run migration for global home and local project
migrate_prism_to_soma "$RESOLVED_HOME"
if [ "$LOCAL_INSTALL" = "true" ]; then
  migrate_prism_to_soma "$(pwd)"
fi

# ── Installed-Path Recording ──────────────────────────────────────
# The manifest MUST list what this installer actually wrote. It used to be
# built by `find`-ing the destination directories, which enrolled every
# pre-existing file in the user's steering/skills/hooks dirs — so uninstall
# deleted third-party skills and hand-written hooks it never installed.
# Newline-delimited rather than arrays: empty arrays are fatal under `set -u`
# on Bash 3.2, which macOS still ships.
INSTALLED_FILES=""
INSTALLED_SKILLS=""
INSTALLED_HOOKS=""
INSTALLED_MCP_CONFIGS=""
# Truthful scope. Only a branch that really wrote to project-local paths may
# set this to "local"; the old code labelled every non-gemini --local install
# "global" while still writing a global manifest.
INSTALL_SCOPE="global"

record_installed_file()  { [ -n "${1:-}" ] && INSTALLED_FILES="${INSTALLED_FILES}$1"$'\n'; return 0; }
record_installed_skill() { [ -n "${1:-}" ] && INSTALLED_SKILLS="${INSTALLED_SKILLS}$1"$'\n'; return 0; }
record_installed_hook()  { [ -n "${1:-}" ] && INSTALLED_HOOKS="${INSTALLED_HOOKS}$1"$'\n'; return 0; }
record_mcp_config()      { [ -n "${1:-}" ] && INSTALLED_MCP_CONFIGS="${INSTALLED_MCP_CONFIGS}$1"$'\n'; return 0; }

# Newline-delimited paths on stdin -> JSON array. Escapes backslash and quote
# so Windows paths and odd filenames cannot produce invalid JSON.
_json_array_from_lines() {
  awk '
    BEGIN { printf "["; first = 1 }
    length($0) > 0 {
      s = $0
      gsub(/\\/, "\\\\", s)
      gsub(/"/, "\\\"", s)
      if (!first) printf ","
      printf "\"%s\"", s
      first = 0
    }
    END { printf "]" }
  '
}

write_manifest() {
  if [ "$DRY_RUN" = "true" ]; then return 0; fi
  local manifest_dir="$RESOLVED_HOME/.soma"
  local scope="$INSTALL_SCOPE"
  if [ "$scope" = "local" ]; then
    manifest_dir="$(pwd)/.soma"
  fi
  mkdir -p "$manifest_dir"
  local target_json="$manifest_dir/manifest.json"
  
  local t_repo=${TEAM_REPO:-null}
  [ "$t_repo" != "null" ] && t_repo="\"$t_repo\""
  
  local o_repo=${ORG_REPO:-null}
  [ "$o_repo" != "null" ] && o_repo="\"$o_repo\""
  
  local m_repo=${METRICS_REPO:-null}
  [ "$m_repo" != "null" ] && m_repo="\"$m_repo\""
  
  # Exactly what this run wrote — never a scan of the destination directory.
  local files_arr skills_arr hooks_arr mcp_configs_arr
  files_arr="$(printf '%s' "$INSTALLED_FILES" | _json_array_from_lines)"
  skills_arr="$(printf '%s' "$INSTALLED_SKILLS" | _json_array_from_lines)"
  hooks_arr="$(printf '%s' "$INSTALLED_HOOKS" | _json_array_from_lines)"
  mcp_configs_arr="$(printf '%s' "$INSTALLED_MCP_CONFIGS" | _json_array_from_lines)"
  
  local ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  local backup_path=${BACKUP_DIR:-null}
  [ "$backup_path" != "null" ] && backup_path="\"$backup_path\""
  
  local version
  version=$(cat "$REPO_DIR/VERSION" 2>/dev/null || echo "unknown")
  
  cat > "$target_json" <<EOF
{
  "version": "$version",
  "installed_at": "$ts",
  "platform": "$PLATFORM",
  "scope": "$scope", 
  "rules_subset": "$RULES_SUBSET",
  "source_repo": "$REPO_DIR",
  "team_repo": $t_repo,
  "org_repo": $o_repo,
  "metrics_repo": $m_repo,
  "backup_dir": $backup_path,
  "files": $files_arr,
  "organs": $skills_arr,
  "hooks": $hooks_arr,
  "mcp_configs": $mcp_configs_arr
}
EOF
}

# Intentional exception to soma_python's -I (BUG-044): this probe must answer
# "would `python3 -m soma_mcp` started in <workspace> find soma_mcp?", so it
# deliberately honours PYTHONPATH, user site-packages and the workspace itself,
# and may import a workspace-local soma_mcp. It calls the resolved interpreter
# directly (no -I) but drops the implicit CWD entry and appends the workspace
# LAST, so stdlib names (json.py, os.py, ...) in the workspace cannot shadow
# the modules soma_mcp imports. Same boolean as the old `cd ws && import`.
_soma_mcp_importable_from() {
  resolve_python || return 1
  "${SOMA_PYTHON_CMD[@]}" -c '
import sys
if sys.path and sys.path[0] == "":
    del sys.path[0]
sys.path.append(sys.argv[1])
import soma_mcp
' "$1" </dev/null >/dev/null 2>&1
}

# Merge only mcpServers.soma and preserve every unrelated key/server. The
# governed workspace is both the server cwd and SOMA_WORKSPACE. A normal
# installed package is preferred; source-checkout installs add PYTHONPATH only
# when `python3 -m soma_mcp` is otherwise unavailable from that workspace.
merge_mcp_config() {
  local config_file="$1" workspace="$2" source_fallback=""
  if ! resolve_python; then
    _python_missing_error
    log_error "Python 3 is required to safely merge MCP JSON configuration."
    return 1
  fi
  if ! _soma_mcp_importable_from "$workspace"; then
    source_fallback="$REPO_DIR"
  fi
  SOMA_MCP_FILE="$config_file" SOMA_WORKSPACE="$workspace" \
    SOMA_SOURCE_FALLBACK="$source_fallback" soma_python - <<'PY'
import json
import os
import stat
import tempfile

path = os.environ["SOMA_MCP_FILE"]
workspace = os.environ["SOMA_WORKSPACE"]
fallback = os.environ.get("SOMA_SOURCE_FALLBACK", "")
if os.path.exists(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("MCP configuration root must be a JSON object")
else:
    data = {}
servers = data.get("mcpServers")
if servers is None:
    servers = {}
    data["mcpServers"] = servers
elif not isinstance(servers, dict):
    raise ValueError("MCP configuration field 'mcpServers' must be a JSON object")
env = {"SOMA_WORKSPACE": workspace}
if fallback:
    env["PYTHONPATH"] = fallback
servers["soma"] = {
    "command": "python3",
    "args": ["-m", "soma_mcp"],
    "cwd": workspace,
    "env": env,
}
parent = os.path.dirname(path) or "."
fd, temp_path = tempfile.mkstemp(prefix=".soma-mcp-", dir=parent, text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    if os.path.exists(path):
        os.chmod(temp_path, stat.S_IMODE(os.stat(path).st_mode))
    os.replace(temp_path, path)
except Exception:
    try:
        os.unlink(temp_path)
    except FileNotFoundError:
        pass
    raise
PY
}

SOURCE_DIR="$REPO_DIR/genome"
SKILLS_SOURCE="$REPO_DIR/organs"

echo "Installing Soma for $PLATFORM (OS: $DETECTED_OS, Kernel: $(uname -s))..."
echo "  Source: $(normalize_path "$SOURCE_DIR")"
echo "  Config: TEAM_SIZE=$TEAM_SIZE GIT_STRATEGY=$GIT_STRATEGY RULES_SUBSET=$RULES_SUBSET"
[ "$JIT_MODE" = "true" ] && echo "  Mode:   JIT (v0.23 — MCP-first, 1 meta-rule)"
[ "$DRY_RUN" = "true" ] && echo "  Mode:   DRY-RUN (no files will be modified)"
echo ""

BACKUP_TS=$(date -u +"%Y-%m-%dT%H-%M-%S")
BACKUP_DIR="$RESOLVED_HOME/.soma/backup/$BACKUP_TS"

if [ "$DRY_RUN" = "false" ]; then
  # Retain the most recent N generations. This used to `rm -rf` the whole
  # backup parent before creating the new stamped directory, so exactly one
  # generation survived — and after a second install that survivor was a copy
  # of Soma's own output, leaving the genuine pre-install state unrecoverable.
  BACKUP_ROOT="$RESOLVED_HOME/.soma/backup"
  BACKUP_KEEP="${SOMA_BACKUP_GENERATIONS:-5}"
  case "$BACKUP_KEEP" in
    ''|*[!0-9]*) BACKUP_KEEP=5 ;;
  esac
  mkdir -p "$BACKUP_ROOT"
  # Prune oldest-first, never the one we are about to write.
  find "$BACKUP_ROOT" -maxdepth 1 -mindepth 1 -type d 2>/dev/null \
    | sort -r \
    | awk -v k="$BACKUP_KEEP" 'NR>=k { print }' \
    | while IFS= read -r stale; do
        [ -n "$stale" ] || continue
        [ "$stale" = "$BACKUP_DIR" ] && continue
        rm -rf -- "$stale"
      done
  mkdir -p "$BACKUP_DIR"
  
  case "$PLATFORM" in
    gemini)
      if [ "$LOCAL_INSTALL" = "true" ]; then
        # Read the paths a local install actually writes (.soma/rules and
        # .soma/skills), not .soma/genome / .soma/organs which never exist.
        [ -d "$(pwd)/.soma/rules" ] && cp -r "$(pwd)/.soma/rules" "$BACKUP_DIR/genome"
        [ -d "$(pwd)/.soma/skills" ] && cp -r "$(pwd)/.soma/skills" "$BACKUP_DIR/organs"
        [ -d "$(pwd)/.soma/plugins/governance" ] && cp -r "$(pwd)/.soma/plugins/governance" "$BACKUP_DIR/governance"
        [ -d "$(pwd)/.soma/cells" ] && cp -r "$(pwd)/.soma/cells" "$BACKUP_DIR/cells"
      else
        [ -d "$RESOLVED_HOME/.gemini/config/rules" ] && cp -r "$RESOLVED_HOME/.gemini/config/rules" "$BACKUP_DIR/genome"
        [ -d "$RESOLVED_HOME/.gemini/config/skills" ] && cp -r "$RESOLVED_HOME/.gemini/config/skills" "$BACKUP_DIR/organs"
        [ -d "$RESOLVED_HOME/.gemini/config/plugins/governance" ] && cp -r "$RESOLVED_HOME/.gemini/config/plugins/governance" "$BACKUP_DIR/governance"
      fi
      ;;
    kiro)
      [ -d "$RESOLVED_HOME/.kiro/steering" ] && cp -r "$RESOLVED_HOME/.kiro/steering" "$BACKUP_DIR/genome"
      [ -d "$RESOLVED_HOME/.kiro/skills" ] && cp -r "$RESOLVED_HOME/.kiro/skills" "$BACKUP_DIR/organs"
      [ -d "$RESOLVED_HOME/.kiro/hooks" ] && cp -r "$RESOLVED_HOME/.kiro/hooks" "$BACKUP_DIR/hooks"
      ;;
    copilot)
      [ -f "$RESOLVED_HOME/copilot-instructions.md" ] && cp "$RESOLVED_HOME/copilot-instructions.md" "$BACKUP_DIR/"
      ;;
    claude)
      if [ "$LOCAL_INSTALL" = "true" ]; then
        [ -f "$(pwd)/CLAUDE.md" ] && cp "$(pwd)/CLAUDE.md" "$BACKUP_DIR/"
        [ -f "$(pwd)/.mcp.json" ] && cp "$(pwd)/.mcp.json" "$BACKUP_DIR/"
      else
        [ -f "$RESOLVED_HOME/.claude/CLAUDE.md" ] && cp "$RESOLVED_HOME/.claude/CLAUDE.md" "$BACKUP_DIR/"
      fi
      ;;
    mcp)
      [ -f "$(pwd)/.mcp.json" ] && cp "$(pwd)/.mcp.json" "$BACKUP_DIR/"
      ;;
  esac
fi

case "$PLATFORM" in
  gemini)
    if [ "$LOCAL_INSTALL" = "true" ]; then
      INSTALL_SCOPE="local"
      TARGET_RULES="$(pwd)/.soma/rules"
      TARGET_SKILLS="$(pwd)/.soma/skills"
      TARGET_HOOKS="$(pwd)/.soma/plugins/governance"
    else
      TARGET_RULES="$RESOLVED_HOME/.gemini/config/rules"
      TARGET_SKILLS="$RESOLVED_HOME/.gemini/config/skills"
      TARGET_HOOKS="$RESOLVED_HOME/.gemini/config/plugins/governance"
    fi
    [ "$DRY_RUN" = "true" ] || mkdir -p "$TARGET_RULES" "$TARGET_SKILLS"

    # Install rules
    count=0; skipped=0
    while IFS= read -r rule; do
      [ -n "$rule" ] || continue
      name="$(basename "$rule")"
      if ! should_install "$name"; then
        log_skip "$name (not in $RULES_SUBSET subset)"
        skipped=$((skipped + 1))
        continue
      fi
      if [ "$DRY_RUN" = "true" ]; then
        log_info "[dry-run] would install $name -> $(normalize_path "$TARGET_RULES/$name")"
      else
        rm -f "$TARGET_RULES/$name"  # Remove any existing symlink before copy
        cp -- "$rule" "$TARGET_RULES/$name"
        record_installed_file "$TARGET_RULES/$name"
        log_info "$name"
      fi
      count=$((count + 1))
    done <<< "$(find "$SOURCE_DIR" -type f -name "*.md" | sort)"

    # Install skills
    skill_count=0
    if [ -d "$SKILLS_SOURCE" ]; then
      for skill in "$SKILLS_SOURCE"/*/; do
        skill_name="$(basename "$skill")"
        if [ "$DRY_RUN" = "true" ]; then
          log_info "[dry-run] would install skill/$skill_name -> $(normalize_path "$TARGET_SKILLS/$skill_name")"
        else
          backup_dir "$TARGET_SKILLS/$skill_name"
          # Remove existing (file or dir) to prevent type conflicts
          rm -rf -- "$TARGET_SKILLS/$skill_name"
          cp -r -- "$skill" "$TARGET_SKILLS/$skill_name"
          record_installed_skill "$TARGET_SKILLS/$skill_name"
          log_info "skill/$skill_name"
        fi
        skill_count=$((skill_count + 1))
      done
    fi

    # Team overrides
    apply_team_overrides "$TARGET_RULES"

    # Hooks
    if [ "$ENABLE_HOOKS" = "true" ]; then
      if install_hooks "$REPO_DIR" "$TARGET_HOOKS"; then
        [ "$DRY_RUN" = "true" ] || [ ! -f "$TARGET_HOOKS/hooks.json" ] || \
          record_installed_hook "$TARGET_HOOKS/hooks.json"
      fi
    fi

    echo ""
    if [ "$DRY_RUN" = "true" ]; then
      echo "Dry-run complete. Would install $count rules, $skill_count skills to $(normalize_path "$TARGET_RULES")"
    else
      write_manifest
      echo "Done! Installed $count rules, $skill_count skills"
      if [ "$LOCAL_INSTALL" = "true" ]; then
        echo "Installed locally to $(pwd)/.soma/ — these rules apply only to this project."
      else
        echo "These will take effect on your next Gemini conversation."
      fi
    fi
    if [ "$skipped" -gt 0 ]; then
      echo "  ($skipped rules skipped — not in $RULES_SUBSET subset)"
    fi
    ;;

  kiro)
    TARGET_RULES="$RESOLVED_HOME/.kiro/steering"
    TARGET_SKILLS="$RESOLVED_HOME/.kiro/skills"
    TARGET_HOOKS="$RESOLVED_HOME/.kiro/hooks"
    [ "$DRY_RUN" = "true" ] || mkdir -p "$TARGET_RULES" "$TARGET_SKILLS"

    count=0; skipped=0
    while IFS= read -r rule; do
      [ -n "$rule" ] || continue
      name="$(basename "$rule")"
      if ! should_install "$name"; then
        log_skip "$name (not in $RULES_SUBSET subset)"
        skipped=$((skipped + 1))
        continue
      fi
      if [ "$DRY_RUN" = "true" ]; then
        log_info "[dry-run] would install $name (converted syntax) -> $(normalize_path "$TARGET_RULES/$name")"
      else
        backup_file "$TARGET_RULES/$name"
        # Convert trigger syntax to Kiro inclusion syntax
        sed -e 's/^trigger: always_on$/inclusion: always/' \
            -e 's/^trigger: model_decision$/inclusion: manual/' \
            "$rule" > "$TARGET_RULES/$name"
        record_installed_file "$TARGET_RULES/$name"
        log_info "$name"
      fi
      count=$((count + 1))
    done <<< "$(find "$SOURCE_DIR" -type f -name "*.md" | sort)"

    # Install skills (parity with Gemini)
    skill_count=0
    if [ -d "$SKILLS_SOURCE" ]; then
      for skill in "$SKILLS_SOURCE"/*/; do
        skill_name="$(basename "$skill")"
        if [ "$DRY_RUN" = "true" ]; then
          log_info "[dry-run] would install skill/$skill_name -> $(normalize_path "$TARGET_SKILLS/$skill_name")"
        else
          backup_dir "$TARGET_SKILLS/$skill_name"
          # Remove existing to prevent nesting
          [ -d "$TARGET_SKILLS/$skill_name" ] && rm -rf -- "$TARGET_SKILLS/$skill_name"
          cp -r -- "$skill" "$TARGET_SKILLS/$skill_name"
          record_installed_skill "$TARGET_SKILLS/$skill_name"
          log_info "skill/$skill_name"
        fi
        skill_count=$((skill_count + 1))
      done
    fi

    # Team overrides (parity with Gemini)
    apply_team_overrides "$TARGET_RULES"

    # Hooks (Kiro uses individual .kiro.hook files, not hooks.json)
    if [ "$ENABLE_HOOKS" = "true" ]; then
      if install_hooks "$REPO_DIR" "$TARGET_HOOKS"; then
        [ "$DRY_RUN" = "true" ] || [ ! -f "$TARGET_HOOKS/hooks.json" ] || \
          record_installed_hook "$TARGET_HOOKS/hooks.json"
      fi
    fi

    if [ "$LOCAL_INSTALL" = "true" ]; then
      KIRO_MCP_DIR="$(pwd)/.kiro/settings"
    else
      KIRO_MCP_DIR="$RESOLVED_HOME/.kiro/settings"
    fi
    # The settings file may be global, but the server always governs the
    # project from which the installer was invoked, never the source checkout
    # or the user's entire home directory.
    KIRO_ROOT="$(pwd)"
    [ "$DRY_RUN" = "true" ] || mkdir -p "$KIRO_MCP_DIR"
    KIRO_MCP_FILE="$KIRO_MCP_DIR/mcp.json"
    if [ "$DRY_RUN" = "true" ]; then
      log_info "[dry-run] would create/update mcp.json at $(normalize_path "$KIRO_MCP_FILE")"
    else
      backup_file "$KIRO_MCP_FILE"
      merge_mcp_config "$KIRO_MCP_FILE" "$KIRO_ROOT"
      record_mcp_config "$KIRO_MCP_FILE"
      log_info "merged soma into mcp.json"
    fi

    echo ""
    if [ "$DRY_RUN" = "true" ]; then
      echo "Dry-run complete. Would install $count rules, $skill_count skills to $(normalize_path "$TARGET_RULES")"
    else
      write_manifest
      echo "Done! Installed $count rules, $skill_count skills to $(normalize_path "$TARGET_RULES")"
      echo "Rules with 'inclusion: always' are active on every interaction."
      echo "Rules with 'inclusion: manual' can be referenced via #rulename."
    fi
    if [ "$skipped" -gt 0 ]; then
      echo "  ($skipped rules skipped — not in $RULES_SUBSET subset)"
    fi
    ;;

  copilot)
    if [ "$MODE" = "project" ]; then
      # Absolute: a relative path here put relative strings into a manifest
      # that uninstall may read from a different working directory.
      INSTALL_SCOPE="local"
      TARGET_DIR="$(pwd)/.github/instructions"
      echo "  Target: $(normalize_path "$TARGET_DIR")"
      [ "$DRY_RUN" = "true" ] || mkdir -p "$TARGET_DIR"

      count=0; skipped=0
      while IFS= read -r rule; do
        [ -n "$rule" ] || continue
        filename="$(basename "$rule")"
        if ! should_install "$filename"; then
          log_skip "$filename (not in $RULES_SUBSET subset)"
          skipped=$((skipped + 1))
          continue
        fi
        name="$(basename "$rule" .md)"
        target="$TARGET_DIR/${name}.instructions.md"
        if [ "$DRY_RUN" = "true" ]; then
          log_info "[dry-run] would install ${name}.instructions.md -> $(normalize_path "$target")"
        else
          backup_file "$target"
          strip_frontmatter < "$rule" > "$target"
          record_installed_file "$target"
          log_info "${name}.instructions.md"
        fi
        count=$((count + 1))
      done <<< "$(find "$SOURCE_DIR" -type f -name "*.md" | sort)"

      # Team overrides for Copilot project mode
      apply_team_overrides "$TARGET_DIR"

      echo ""
      if [ "$DRY_RUN" = "true" ]; then
        echo "Dry-run complete. Would install $count instruction files to $(normalize_path "$TARGET_DIR")"
      else
        write_manifest
        echo "Done! Installed $count instruction files to $(normalize_path "$TARGET_DIR")"
        echo "Commit .github/instructions/ to share with your team."
      fi
      if [ "$skipped" -gt 0 ]; then
        echo "  ($skipped rules skipped — not in $RULES_SUBSET subset)"
      fi

    elif [ "$MODE" = "global" ]; then
      TARGET_FILE="$RESOLVED_HOME/copilot-instructions.md"

      echo "  Target: $(normalize_path "$TARGET_FILE")"
      if [ "$DRY_RUN" = "false" ]; then
        backup_file "$TARGET_FILE"

        echo "# Copilot Global Instructions" > "$TARGET_FILE"
        echo "" >> "$TARGET_FILE"
        echo "> Auto-generated from soma. Do not edit directly." >> "$TARGET_FILE"
        echo "" >> "$TARGET_FILE"
        # A merged file, not a copy: uninstall strips our section rather than
        # deleting the file, so record it once here.
        record_installed_file "$TARGET_FILE"
      fi

      count=0; skipped=0
      while IFS= read -r rule; do
        [ -n "$rule" ] || continue
        filename="$(basename "$rule")"
        if ! should_install "$filename"; then
          log_skip "$filename (not in $RULES_SUBSET subset)"
          skipped=$((skipped + 1))
          continue
        fi
        if [ "$DRY_RUN" = "true" ]; then
          log_info "[dry-run] would merge $filename into $(normalize_path "$TARGET_FILE")"
        else
          echo "---" >> "$TARGET_FILE"
          echo "" >> "$TARGET_FILE"
          strip_frontmatter < "$rule" >> "$TARGET_FILE"
          echo "" >> "$TARGET_FILE"
          log_info "$filename"
        fi
        count=$((count + 1))
      done <<< "$(find "$SOURCE_DIR" -type f -name "*.md" | sort)"

      echo ""
      if [ "$DRY_RUN" = "true" ]; then
        echo "Dry-run complete. Would merge $count rules into $(normalize_path "$TARGET_FILE")"
      else
        write_manifest
        echo "Done! All rules merged into $(normalize_path "$TARGET_FILE")"
        echo "Enable 'Custom Instructions' in your IDE's Copilot settings."
      fi
      if [ "$skipped" -gt 0 ]; then
        echo "  ($skipped rules skipped — not in $RULES_SUBSET subset)"
      fi
    else
      log_error "Unknown mode: $MODE (expected: global|project)"
      exit 1
    fi
    ;;

  claude)
    if [ "$LOCAL_INSTALL" = "true" ]; then
      INSTALL_SCOPE="local"
      TARGET_DIR="$(pwd)"
      TARGET_FILE="$TARGET_DIR/CLAUDE.md"
      MCP_FILE="$TARGET_DIR/.mcp.json"
    else
      TARGET_DIR="$RESOLVED_HOME/.claude"
      TARGET_FILE="$TARGET_DIR/CLAUDE.md"
      [ "$DRY_RUN" = "true" ] || mkdir -p "$TARGET_DIR"
    fi

    echo "  Target: $(normalize_path "$TARGET_FILE")"
    if [ "$DRY_RUN" = "false" ]; then
      backup_file "$TARGET_FILE"
      echo "# Soma Governance Rules" > "$TARGET_FILE"
      echo "" >> "$TARGET_FILE"
      echo "> Auto-generated by Soma. Do not edit directly." >> "$TARGET_FILE"
      echo "" >> "$TARGET_FILE"
      # A merged file, not a copy: uninstall strips our section rather than
      # deleting the file. Recording it is what makes `uninstall.sh claude`
      # work at all — the old find-based manifest never listed CLAUDE.md.
      record_installed_file "$TARGET_FILE"
    fi

    count=0; skipped=0; skill_count=0
    while IFS= read -r rule; do
      [ -n "$rule" ] || continue
      filename="$(basename "$rule")"
      if ! should_install "$filename"; then
        log_skip "$filename (not in $RULES_SUBSET subset)"
        skipped=$((skipped + 1))
        continue
      fi
      if [ "$DRY_RUN" = "true" ]; then
        log_info "[dry-run] would merge $filename into $(normalize_path "$TARGET_FILE")"
      else
        echo "---" >> "$TARGET_FILE"
        echo "" >> "$TARGET_FILE"
        strip_frontmatter < "$rule" >> "$TARGET_FILE"
        echo "" >> "$TARGET_FILE"
        log_info "$filename"
      fi
      count=$((count + 1))
    done <<< "$(find "$SOURCE_DIR" -type f -name "*.md" | sort)"

    # Count skills for tracking purposes
    if [ -d "$SKILLS_SOURCE" ]; then
      for skill in "$SKILLS_SOURCE"/*/; do
        skill_count=$((skill_count + 1))
      done
    fi

    if [ "$LOCAL_INSTALL" = "true" ]; then
      if [ "$DRY_RUN" = "true" ]; then
        log_info "[dry-run] would create/update .mcp.json at $(normalize_path "$MCP_FILE")"
      else
        backup_file "$MCP_FILE"
        merge_mcp_config "$MCP_FILE" "$TARGET_DIR"
        record_mcp_config "$MCP_FILE"
        log_info "merged soma into .mcp.json"
      fi
    fi

    echo ""
    if [ "$DRY_RUN" = "true" ]; then
      echo "Dry-run complete. Would merge $count rules into $(normalize_path "$TARGET_FILE")"
    else
      write_manifest
      echo "Done! All rules merged into $(normalize_path "$TARGET_FILE") ($skill_count skills tracked)"
      if [ "$LOCAL_INSTALL" = "true" ]; then
        echo "Created .mcp.json for local MCP server."
      else
        echo "For global mode, run 'claude mcp add soma python3 -m soma_mcp' manually."
        echo "Note: Global hooks must be configured in ~/.claude/settings.json"
      fi
    fi
    if [ "$skipped" -gt 0 ]; then
      echo "  ($skipped rules skipped — not in $RULES_SUBSET subset)"
    fi
    ;;

  mcp)
    # Always project-scoped: .mcp.json is written into the current directory.
    INSTALL_SCOPE="local"
    TARGET_DIR="$(pwd)"
    MCP_FILE="$TARGET_DIR/.mcp.json"
    
    if [ "$DRY_RUN" = "true" ]; then
      log_info "[dry-run] would create/update .mcp.json at $(normalize_path "$MCP_FILE")"
    else
      backup_file "$MCP_FILE"
      merge_mcp_config "$MCP_FILE" "$TARGET_DIR"
      record_mcp_config "$MCP_FILE"
      log_info "merged soma into .mcp.json"
    fi

    echo ""
    if [ "$DRY_RUN" = "true" ]; then
      echo "Dry-run complete."
    else
      # The mcp platform previously wrote no manifest at all, so uninstall fell
      # back to pattern guessing and the platform-mismatch guard had nothing to
      # check against.
      write_manifest
      echo "Done! Created .mcp.json for local MCP server."
    fi
    ;;

  *)
    log_error "Unknown platform: $PLATFORM (expected: gemini|kiro|copilot|claude|mcp)"
    exit 1
    ;;
esac

if [ "${INSTALL_GIT_HOOKS:-false}" = "true" ]; then
  if [ -d ".git/hooks" ]; then
    if [ "$DRY_RUN" = "true" ]; then
      echo "[dry-run] would install git pre-commit hook."
    else
      cp "$REPO_DIR/install/hooks/pre-commit" ".git/hooks/pre-commit"
      chmod +x ".git/hooks/pre-commit"
      # Recorded so uninstall can remove it. It used to be installed and then
      # left behind forever, with zero references in uninstall.sh.
      record_installed_hook "$(pwd)/.git/hooks/pre-commit"
      write_manifest
      echo "Installed git pre-commit hook."
    fi
  else
    echo "No .git/hooks directory found, skipping pre-commit hook installation."
  fi
fi
