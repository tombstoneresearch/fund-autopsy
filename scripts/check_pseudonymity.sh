#!/usr/bin/env bash
# Identifier leak scanner.
#
# Scans every file that would be included in a git push against a
# locally-configured list of regex patterns. Exits nonzero on any hit
# so a git pre-push hook can block the push.
#
# Usage:
#   bash scripts/check_pseudonymity.sh
#
# Pattern source (first match wins):
#   1. $PSEUDONYMITY_PATTERNS_FILE (env var pointing at a patterns file)
#   2. scripts/.pseudonymity_patterns (gitignored; preferred)
#
# One ERE pattern per non-blank, non-comment line. Lines beginning with
# '#' and blank lines are ignored. See scripts/pseudonymity_patterns.example
# for the expected format and how to activate the scanner locally.
#
# Install as a pre-push hook:
#   ln -sf ../../scripts/check_pseudonymity.sh .git/hooks/pre-push
#   chmod +x .git/hooks/pre-push
#
# This script is intended as a local pre-push gate. It is deliberately
# not wired into CI: the patterns are never in the remote, so CI has
# no way to evaluate them without a secret store, and a secret store
# defeats the purpose of keeping the patterns off shared infrastructure.

set -u

# Resolve the repo root regardless of how this script is invoked.
# When run as a pre-push hook, $0 is .git/hooks/pre-push and naive
# relative-path math lands inside .git/.
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [[ -z "$REPO_ROOT" ]]; then
  echo "[pseudonymity] Not inside a git repository; skipping scan." >&2
  exit 2
fi
cd "$REPO_ROOT" || exit 2

# Locate the patterns file.
PATTERNS_FILE=""
if [[ -n "${PSEUDONYMITY_PATTERNS_FILE:-}" && -r "${PSEUDONYMITY_PATTERNS_FILE}" ]]; then
  PATTERNS_FILE="${PSEUDONYMITY_PATTERNS_FILE}"
elif [[ -r "scripts/.pseudonymity_patterns" ]]; then
  PATTERNS_FILE="scripts/.pseudonymity_patterns"
else
  cat >&2 <<'EOF'
[pseudonymity] No patterns file found. The scanner cannot run.

Expected one of:
  - $PSEUDONYMITY_PATTERNS_FILE (environment variable, readable file)
  - scripts/.pseudonymity_patterns (local, gitignored)

To set up:
  cp scripts/pseudonymity_patterns.example scripts/.pseudonymity_patterns
  # then edit scripts/.pseudonymity_patterns with your identifiers

The scanner is a local pre-push gate. It exits nonzero when no
patterns are configured so a pre-push hook will refuse the push
until setup is complete — silent passes would defeat the gate.
EOF
  exit 2
fi

# Load patterns: skip blank lines and lines starting with '#'.
FORBIDDEN_PATTERNS=()
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -z "${line// }" ]] && continue
  [[ "$line" =~ ^[[:space:]]*# ]] && continue
  FORBIDDEN_PATTERNS+=("$line")
done < "$PATTERNS_FILE"

if [[ ${#FORBIDDEN_PATTERNS[@]} -eq 0 ]]; then
  echo "[pseudonymity] Patterns file '$PATTERNS_FILE' is empty after stripping comments. Add at least one pattern or remove the file." >&2
  exit 2
fi

# File extensions to scan. Binaries and caches are excluded.
INCLUDE_EXTS='md|py|html|js|css|txt|yaml|yml|toml|cfg|json'

# Use git ls-files so we only check files git would actually ship.
# --cached covers tracked files; --others includes untracked but respects
# .gitignore; --exclude-standard filters .gitignore hits.
GIT_FILES=$(git ls-files --cached --others --exclude-standard 2>/dev/null)
if [[ -z "$GIT_FILES" ]]; then
  echo "[pseudonymity] No git-tracked files found; running outside a repo?" >&2
  exit 2
fi

HITS=0
HIT_REPORT=""

while IFS= read -r file; do
  # Skip if not an extension we care about.
  ext="${file##*.}"
  if ! [[ "$ext" =~ ^($INCLUDE_EXTS)$ ]]; then
    continue
  fi

  # Skip excluded paths (defense in depth; gitignore is the real gate).
  # pseudonymity_patterns.example is a pattern template; scanning it
  # against its own placeholder identifiers would produce false positives.
  case "$file" in
    Intelligence/*|.git/*|__pycache__/*|*.pyc|.pytest_cache/*|.venv/*|venv/*|node_modules/*|tests/fixtures/*|scripts/pseudonymity_patterns.example) continue ;;
  esac

  # Skip if file no longer exists (e.g., deleted but still in index).
  [[ -f "$file" ]] || continue

  for pattern in "${FORBIDDEN_PATTERNS[@]}"; do
    if grep -i -E -n "$pattern" "$file" >/dev/null 2>&1; then
      HITS=$((HITS + 1))
      match=$(grep -i -E -n "$pattern" "$file" | head -3)
      HIT_REPORT+=$'\n'"  $file  [pattern hit]"$'\n'"$match"$'\n'
    fi
  done
done <<< "$GIT_FILES"

if [[ $HITS -gt 0 ]]; then
  echo "================================================================"
  echo "  IDENTIFIER LEAK DETECTED — push blocked"
  echo "================================================================"
  echo "$HIT_REPORT"
  echo
  echo "Scrub the matches above or gitignore the files before pushing."
  echo "Re-run to verify:  bash scripts/check_pseudonymity.sh"
  exit 1
fi

echo "[pseudonymity] Clean. $(echo "$GIT_FILES" | wc -l | tr -d ' ') files scanned across ${#FORBIDDEN_PATTERNS[@]} patterns."
exit 0
