#!/usr/bin/env bash
set -euo pipefail

# Configuration
BRAIN_DIR="${HOME}/.gemini/antigravity/brain"
REPO_DIR="${HOME}/.gemini/antigravity/scratch/ai-conversation-logs"
MIN_STEPS=50

echo "=== Conversation Log Export ==="
echo "Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"

cd "$REPO_DIR"

# Non-blocking lock — skip if another export is already running
LOCK_DIR="$REPO_DIR/.export.lock.d"
if command -v flock &>/dev/null; then
    exec 200>"$REPO_DIR/.export.lock"
    flock -n 200 || { echo "Export already running. Skipping."; exit 0; }
else
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
        echo "Export already running. Skipping."; exit 0
    fi
    trap 'rm -rf "$LOCK_DIR"' EXIT
fi

# Find all conversations with transcripts
find "$BRAIN_DIR" -maxdepth 5 -name "transcript.jsonl" -path "*/.system_generated/logs/*" 2>/dev/null | while read -r transcript; do
    rel="${transcript#"$BRAIN_DIR"/}"
    conv_id="${rel%%/*}"
    step_count=$(wc -l < "$transcript" | tr -d ' ')

    # Skip tiny conversations
    if [ "$step_count" -lt "$MIN_STEPS" ]; then
        continue
    fi

    # Detect primary vs subagent (primary has USER_INPUT steps)
    is_primary=$(head -20 "$transcript" | grep -c '"type":"USER_INPUT"' || true)

    # Create conversation directory
    conv_dir="$REPO_DIR/conversations/$conv_id"
    mkdir -p "$conv_dir"

    # Copy-time secret scrubbing into temp file
    sed \
        -e 's/GEMINI_API_KEY=[^ ]*/GEMINI_API_KEY=REDACTED/g' \
        -e 's/AIzaSy[a-zA-Z0-9_-]\{33\}/AIzaSy_REDACTED/g' \
        -e 's/sk-[a-zA-Z0-9]\{20,\}/sk-REDACTED/g' \
        -e 's/ghp_[a-zA-Z0-9]\{36\}/ghp_REDACTED/g' \
        -e 's/github_pat_[a-zA-Z0-9_]\{20,\}/github_pat_REDACTED/g' \
        -e 's/Bearer [a-zA-Z0-9._-]\{20,\}/Bearer REDACTED/g' \
        "$transcript" > "$conv_dir/transcript.jsonl.tmp"

    if ! cmp -s "$conv_dir/transcript.jsonl.tmp" "$conv_dir/transcript.jsonl" 2>/dev/null \
       || [ ! -f "$conv_dir/metadata.json" ]; then
        mv "$conv_dir/transcript.jsonl.tmp" "$conv_dir/transcript.jsonl"
        echo "Updated: $conv_id ($step_count steps, primary=$is_primary)"

        # Generate metadata only on actual change
        cat > "$conv_dir/metadata.json" << EOF
{
    "conversation_id": "$conv_id",
    "step_count": $step_count,
    "is_primary": $([ "$is_primary" -gt 0 ] && echo "true" || echo "false"),
    "last_exported": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
    "transcript_bytes": $(wc -c < "$transcript")
}
EOF
    else
        rm -f "$conv_dir/transcript.jsonl.tmp"
    fi
done

# Generate index
echo "[" > "$REPO_DIR/conversations/index.json"
first=true
for meta in "$REPO_DIR"/conversations/*/metadata.json; do
    [ -f "$meta" ] || continue
    if [ "$first" = true ]; then
        first=false
    else
        echo "," >> "$REPO_DIR/conversations/index.json"
    fi
    cat "$meta" >> "$REPO_DIR/conversations/index.json"
done
echo "]" >> "$REPO_DIR/conversations/index.json"

# Secret scrubbing now happens at copy-time above (P5/S1 fix).
# This block is intentionally removed to avoid double-processing.

# Git commit and push if changes
if [ -n "$(git status --porcelain conversations/ governance/ 2>/dev/null)" ]; then
    git add conversations/ governance/
    git commit -m "Log export: $(date -u +"%Y-%m-%dT%H:%M:%SZ") | $(find conversations -name 'metadata.json' | wc -l) conversations"
    git push origin "$(git symbolic-ref --short -q HEAD 2>/dev/null || echo main)"
    echo "Pushed to GitHub."
else
    echo "No changes to push."
fi

echo "Export complete."
