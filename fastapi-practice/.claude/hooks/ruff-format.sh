#!/usr/bin/env bash
# PostToolUse hook: format the Python file Claude just edited with ruff.
# Never blocks Claude: any problem is reported on stderr and the hook exits 0.
set -u

if ! command -v jq >/dev/null 2>&1; then
  echo "ruff-format hook: jq not found, skipping" >&2
  exit 0
fi

file_path=$(jq -r '.tool_input.file_path // empty')

case "$file_path" in
  *.py | *.pyi) ;;
  *) exit 0 ;;
esac

[ -f "$file_path" ] || exit 0

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
uv run --quiet ruff format --quiet "$file_path" >&2 || echo "ruff-format hook: ruff format failed for $file_path" >&2
exit 0
