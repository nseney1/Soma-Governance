#!/usr/bin/env bash
# escalation_sentinel.sh — Zero-token protocol escalation recommender (E14)
#
# Analyzes staged/unstaged git changes and recommends the minimum review
# protocol based on file sensitivity patterns and diff size.
#
# Usage:
#   ./escalation_sentinel.sh [--staged]    # Analyze staged changes
#   ./escalation_sentinel.sh [--all]       # Analyze all uncommitted changes
#   ./escalation_sentinel.sh [file...]     # Analyze specific files
#
# Output:
#   PROTOCOL=breeze|gale|trident|maelstrom|tempest
#   REASON=<why this level was selected>
#
# Exit codes:
#   0 = recommendation made
#   1 = no changes detected / error

set -euo pipefail

# ── Sensitivity Classification ────────────────────────────────────────

# HIGH: Security-sensitive, infrastructure, auth, config execution
HIGH_PATTERNS=(
  'enzymes/.*\.sh$'
  'install\.sh$'
  'Makefile$'
  'hooks\.json'
  '\.github/workflows/'
  'auth|credential|secret|token|password'
  'docker|Dockerfile'
  'requirements\.txt$|package\.json$|go\.mod$'
)

# MEDIUM: Rules, skills with semantic meaning, core logic
MEDIUM_PATTERNS=(
  'genome/.*\.md$'
  'organs/.*/SKILL\.md$'
  'steering\.conf'
  '\.py$|\.js$|\.ts$|\.go$'
)

# LOW: Documentation, pure markdown, README
LOW_PATTERNS=(
  '(^|/)docs/'
  'README\.md$'
  'LICENSE$'
  'CHANGELOG|EVOLUTION|METRICS|EXPERIMENTS'
  '\.txt$|\.csv$|\.json$'
)

# TEST: Test files (test-only changes cap at Gale)
TEST_PATTERNS=(
  '\.test\.'
  '_test\.'
)

# CRITICAL: Branch operations, force pushes, schema changes
# These are detected separately from file patterns

# ── Gather Changed Files ──────────────────────────────────────────────

gather_files() {
  local mode="${1:-all}"
  case "$mode" in
    --staged)
      git diff --cached --name-only 2>/dev/null
      ;;
    --all)
      git diff --name-only 2>/dev/null
      git diff --cached --name-only 2>/dev/null
      ;;
    *)
      # Treat remaining args as file paths
      shift 0
      printf '%s\n' "$@"
      ;;
  esac
}

# ── Classify Files ────────────────────────────────────────────────────

classify() {
  local file="$1"
  local pattern

  for pattern in "${HIGH_PATTERNS[@]}"; do
    if echo "$file" | grep -qE "$pattern"; then
      echo "HIGH"
      return
    fi
  done

  for pattern in "${MEDIUM_PATTERNS[@]}"; do
    if echo "$file" | grep -qE "$pattern"; then
      echo "MEDIUM"
      return
    fi
  done

  for pattern in "${LOW_PATTERNS[@]}"; do
    if echo "$file" | grep -qE "$pattern"; then
      echo "LOW"
      return
    fi
  done

  # Unknown files default to MEDIUM
  echo "MEDIUM"
}

# ── Check Test Files ──────────────────────────────────────────────────

is_test_file() {
  local file="$1"
  local pattern
  for pattern in "${TEST_PATTERNS[@]}"; do
    if echo "$file" | grep -qE "$pattern"; then
      return 0
    fi
  done
  return 1
}

# ── Diff Size Analysis ───────────────────────────────────────────────

get_diff_size() {
  local mode="${1:-all}"
  case "$mode" in
    --staged)
      git diff --cached --stat 2>/dev/null | tail -1 | grep -oE '[0-9]+' | head -1 || echo "0"
      ;;
    *)
      git diff --stat 2>/dev/null | tail -1 | grep -oE '[0-9]+' | head -1 || echo "0"
      ;;
  esac
}

# ── Branch Operation Detection ────────────────────────────────────────

detect_branch_ops() {
  # Check recent git operations for dangerous patterns
  # This is a heuristic — checks reflog for branch renames, force pushes
  local recent
  recent=$(git reflog --format='%gs' -5 2>/dev/null || echo "")

  if echo "$recent" | grep -qiE 'branch -[mMdD]|push.*force|rebase|reset.*hard'; then
    echo "CRITICAL"
    return
  fi
  echo "NONE"
}

# ── Main Logic ────────────────────────────────────────────────────────

main() {
  local mode="${1:---all}"
  local files
  local high_count=0 medium_count=0 low_count=0
  local high_files="" reasons=""

  # Gather and classify files
  files=$(gather_files "$mode" "$@" | sort -u)

  if [ -z "$files" ]; then
    echo "PROTOCOL=none"
    echo "REASON=No changes detected"
    exit 1
  fi

  local total_files
  total_files=$(echo "$files" | wc -l | tr -d ' ')
  local test_count=0

  while IFS= read -r file; do
    local level
    level=$(classify "$file")
    case "$level" in
      HIGH)
        high_count=$((high_count + 1))
        high_files="${high_files:+$high_files, }$file"
        ;;
      MEDIUM) medium_count=$((medium_count + 1)) ;;
      LOW)    low_count=$((low_count + 1)) ;;
    esac
    if is_test_file "$file"; then
      test_count=$((test_count + 1))
    fi
  done <<< "$files"

  # Check for branch operations
  local branch_ops
  branch_ops=$(detect_branch_ops)

  # Get diff size
  local diff_lines
  diff_lines=$(get_diff_size "$mode")

  # ── Decision Matrix ─────────────────────────────────────────────

  local protocol="breeze"
  reasons=""

  # Rule 1: Branch operations → minimum Trident
  if [ "$branch_ops" = "CRITICAL" ]; then
    protocol="maelstrom"
    reasons="Branch operation detected (rename/force-push/rebase)"
  fi

  # Rule 2: HIGH sensitivity files
  if [ "$high_count" -ge 3 ]; then
    protocol="maelstrom"
    reasons="${reasons:+$reasons; }${high_count} high-sensitivity files: ${high_files}"
  elif [ "$high_count" -ge 1 ]; then
    if [ "$protocol" != "maelstrom" ] && [ "$protocol" != "tempest" ]; then
      protocol="trident"
      reasons="${reasons:+$reasons; }High-sensitivity file(s): ${high_files}"
    fi
  fi

  # Rule 3: Security-sensitive paths → Maelstrom minimum
  if echo "$high_files" | grep -qiE 'auth|credential|secret|token|password'; then
    protocol="maelstrom"
    reasons="${reasons:+$reasons; }Security-sensitive path detected"
  fi

  # Rule 4: Large diffs → escalate one level
  if [ "${diff_lines:-0}" -gt 200 ]; then
    case "$protocol" in
      breeze)  protocol="gale";     reasons="${reasons:+$reasons; }Large diff (${diff_lines} lines)" ;;
      gale)    protocol="trident";  reasons="${reasons:+$reasons; }Large diff (${diff_lines} lines)" ;;
      trident) protocol="maelstrom"; reasons="${reasons:+$reasons; }Large diff (${diff_lines} lines)" ;;
    esac
  fi

  # Rule 5: Pure docs → Breeze (docs changes do not need multi-lens review)
  if [ "$high_count" -eq 0 ] && [ "$medium_count" -eq 0 ] && [ "$low_count" -gt 0 ]; then
    protocol="breeze"
    reasons="All changes are low-sensitivity (docs/README)"
  fi

  # Rule 5b: Test-only changes → Gale (test-only changes don't need Trident)
  if [ "$high_count" -eq 0 ] && [ "$test_count" -gt 0 ] && [ $((test_count + low_count)) -eq "$total_files" ]; then
    protocol="gale"
    reasons="Test-only changes (${test_count} test file(s); test changes do not need Trident)"
  fi

  # Rule 6: Single known-location fix → Breeze
  if [ "$total_files" -eq 1 ] && [ "$high_count" -eq 0 ] && [ "$test_count" -eq 0 ]; then
    protocol="breeze"
    reasons="Single file, non-infrastructure change"
  fi

  # ── Membrane Overrides ──────────────────────────────────────────
  for cell_dir in membranes walls; do
    if [ -d ".soma/cells/$cell_dir" ]; then
      for membrane in .soma/cells/$cell_dir/*.md; do
      [ -f "$membrane" ] || continue
      local mem_mode
      mem_mode=$(grep '^minimum_mode:' "$membrane" 2>/dev/null | awk '{print $2}' | tr -d '\r' || true)
      # Read target_paths from frontmatter (array or single value)
      local mem_paths
      mem_paths=$(awk '/^target_paths:/{found=1; next} found && /^  - /{gsub(/^  - /,""); print; next} found{exit}' "$membrane" 2>/dev/null || true)
      if [ -z "$mem_paths" ]; then
        # Try single-value form: target_paths: path/to/file
        mem_paths=$(grep '^target_paths:' "$membrane" 2>/dev/null | sed 's/^target_paths:[[:space:]]*//' | tr -d "\"'" || true)
      fi

      if [ -n "$mem_mode" ] && [ -n "$mem_paths" ]; then
        local path_matched=false
        while IFS= read -r mem_path; do
          [ -z "$mem_path" ] && continue
          if echo "$files" | grep -qF "$mem_path"; then
            path_matched=true
            break
          fi
        done <<< "$mem_paths"
        if [ "$path_matched" = true ]; then
          # Escalate if mem_mode > protocol
          local current_rank=1
          case "$protocol" in breeze) current_rank=1;; gale) current_rank=2;; trident) current_rank=3;; maelstrom) current_rank=4;; tempest) current_rank=5;; esac
          local mem_rank=1
          case "$mem_mode" in breeze) mem_rank=1;; gale) mem_rank=2;; trident) mem_rank=3;; maelstrom) mem_rank=4;; tempest) mem_rank=5;; esac

          if [ "$mem_rank" -gt "$current_rank" ]; then
            protocol="$mem_mode"
            reasons="Membrane escalation for $mem_path ($mem_mode)"
          fi
        fi
      fi
      done
    fi
  done

  # ── Output ──────────────────────────────────────────────────────

  echo "PROTOCOL=${protocol}"
  echo "REASON=${reasons:-Default classification}"
  echo "FILES_TOTAL=${total_files}"
  echo "FILES_HIGH=${high_count}"
  echo "FILES_MEDIUM=${medium_count}"
  echo "FILES_LOW=${low_count}"
  echo "FILES_TEST=${test_count}"
  echo "DIFF_LINES=${diff_lines:-0}"
  echo "BRANCH_OPS=${branch_ops}"

  # Human-readable summary to stderr
  >&2 echo "⚡ Escalation Sentinel: $(echo "$protocol" | tr '[:lower:]' '[:upper:]') recommended"
  >&2 echo "   ${reasons:-Default classification}"
  >&2 echo "   Files: ${total_files} (${high_count} high, ${medium_count} medium, ${low_count} low, ${test_count} test)"
}

main "$@"
