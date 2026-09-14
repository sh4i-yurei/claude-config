#!/usr/bin/env bash
# Scaffold a new buildlog from the vault templates.
#
#   new-buildlog.sh <slug> [project-note-name]
#
# Creates 20_Buildlogs/<slug>/ containing <slug>-log.md and
# images/, with the date and project link already filled in. Refuses to touch an
# existing buildlog so a re-run can never clobber a log that's mid-flight.

set -euo pipefail

VAULT="${SECOND_BRAIN:-$HOME/Documents/Second_Brain}"
TPL="$VAULT/_Templates"
LOGS="$VAULT/20_Buildlogs"

slug="${1:-}"
project="${2:-}"

if [ -z "$slug" ]; then
  echo "usage: new-buildlog.sh <slug> [project-note-name]" >&2
  exit 2
fi

# Slugs become folder names and link targets, so keep them boring.
if ! printf '%s' "$slug" | grep -qE '^[a-z0-9]+(-[a-z0-9]+)*$'; then
  echo "error: slug must be lowercase words separated by hyphens (got '$slug')" >&2
  exit 2
fi

for f in "$TPL/buildlog-log.md"; do
  [ -f "$f" ] || { echo "error: missing template $f" >&2; exit 1; }
done

dir="$LOGS/$slug"
if [ -e "$dir" ]; then
  echo "error: $dir already exists — append to it instead of scaffolding over it" >&2
  exit 1
fi

today="$(TZ=America/Chicago date '+%Y-%m-%d')"

mkdir -p "$dir/images"

# Templates carry Templater syntax, which Templater expands when Obsidian
# creates the file in a mapped folder. This script writes them directly,
# bypassing that, so substitute here instead. Both paths must stay in step.
sed -e "s|<% tp.date.now(\"YYYY-MM-DD\") %>|$today|g" \
    -e "s|^project: \"\[\[\]\]\"|project: \"[[${project}]]\"|" \
    "$TPL/buildlog-log.md" > "$dir/$slug-log.md"

echo "created:"
echo "  $dir/$slug-log.md"
echo "  $dir/images/"
[ -n "$project" ] && echo "linked to project: [[$project]]" || \
  echo "note: no project given — set 'project:' in the log frontmatter"
