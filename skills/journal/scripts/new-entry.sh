#!/usr/bin/env bash
# Create today's journal entry from the vault template.
#
#   new-entry.sh [YYYY-MM-DD]
#
# Writes 50_Personal/51_Journal/<year>/<date>.md, creating the year folder if it
# does not exist. Refuses to touch an entry that already exists, so a re-run can
# never overwrite a day that is already written.
#
# Date-first filenames mean chronological and alphabetical order are the same
# thing, which is the one naming rule every archival guide agrees on.

set -euo pipefail

VAULT="${SECOND_BRAIN:-$HOME/Documents/Second_Brain}"
TPL="$VAULT/_Templates/journal.md"

date_arg="${1:-$(TZ=America/Chicago date '+%Y-%m-%d')}"

if ! printf '%s' "$date_arg" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'; then
  echo "error: date must be YYYY-MM-DD (got '$date_arg')" >&2
  exit 2
fi

[ -f "$TPL" ] || { echo "error: missing template $TPL" >&2; exit 1; }

year="${date_arg%%-*}"
dir="$VAULT/50_Personal/51_Journal/$year"
out="$dir/$date_arg.md"

if [ -e "$out" ]; then
  echo "error: $out already exists — append to it instead of scaffolding over it" >&2
  exit 1
fi

mkdir -p "$dir"

# Templates carry Templater syntax, which Templater expands when Obsidian
# creates the file in a mapped folder. This script writes the file directly,
# bypassing that, so substitute here instead. Both paths must stay in step.
sed "s|<% tp.date.now(\"YYYY-MM-DD\") %>|$date_arg|g" "$TPL" > "$out"

echo "created: $out"
