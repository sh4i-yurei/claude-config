#!/bin/bash
# PostToolUse hook: auto-format files after Write/Edit, matched by extension.
input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')
[ -z "$file_path" ] && exit 0
[ -f "$file_path" ] || exit 0

case "$file_path" in
  *.py)  command -v ruff >/dev/null 2>&1 && ruff format --quiet "$file_path" 2>/dev/null ;;
  *.rs)  command -v rustfmt >/dev/null 2>&1 && rustfmt --edition 2021 "$file_path" 2>/dev/null ;;
  *.go)  command -v gofmt >/dev/null 2>&1 && gofmt -w "$file_path" 2>/dev/null ;;
esac
exit 0
