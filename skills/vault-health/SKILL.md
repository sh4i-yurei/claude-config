---
name: vault-health
description: Checks Mark's Obsidian vault at ~/Documents/Second_Brain for broken links, duplicate basenames, missing or invalid frontmatter, forgotten inbox items, secrets accidentally pasted into notes, and drift between a project note and what actually happened. Use this when he asks whether the vault is healthy, tidy, consistent or drifting, after any batch of note edits or a migration, after renaming or moving notes, before adding a new convention, or whenever something in the vault seems off. Also use it periodically during long vault work — the cost of running it is seconds and the cost of silent drift is a knowledge base nobody trusts.
---

# Vault health

A second brain fails quietly. Nothing errors when a link breaks, a note loses its
frontmatter, or a reference doc goes stale — it just gradually stops being worth
consulting. This checks for that before it compounds.

## Run it

```bash
python3 ~/.claude/skills/vault-health/scripts/check.py
```

One script, standard library only. The same file runs from the pre-commit hook and
from CI on the vault repo, so a clean result here means a clean result there.

It covers three things.

**Conventions.** Duplicate basenames (which make `[[wikilinks]]` ambiguous), buildlogs
using bare `log.md` instead of `<slug>-log.md`, notes with no frontmatter or an unknown
`type`, `status`/`post`/`genre` values outside the allowed set, a `title:` field that
should not exist, reference notes not updated in six months, inbox items older than
three weeks, and anything resembling a key or token pasted into a note.

**Links.** Every `[[wikilink]]` and `![[embed]]` resolves to a real file. Comments,
fenced code and inline code are stripped first, because documentation *about* links is
not a link — and a check that cries wolf gets ignored within a week.

**Drift.** Where the documentation disagrees with what happened. Not staleness: a
correct note nobody edited for six months is fine. Drift is a gap between two things,
so it needs no "N days" threshold.

Each rule below is one function in the script, named so you can grep for it.

| Function | Catches |
|---|---|
| `check_links` | A `[[wikilink]]` or `![[embed]]` pointing at nothing |
| `check_drift` | Every task ticked but the status unchanged; a post that exists while its buildlog is still open; a buildlog for a project claiming `idea`; a project `done` with its buildlog still open |
| `check_index_coverage` | A procedure in the manual that its index does not list |
| `check_skills_map` | A skill missing from `INDEX.md`'s table, or a table entry with no skill behind it |
| `check_folder_readmes` | A note missing from the `Holds:` or `Currently:` list in its folder's README |
| `check_archive_leaks` | A dashboard query reading a folder without excluding its archive |
| `check_own_docs` | A rule in this script that this file does not describe |

Each was written against a real failure found on 2026-08-22 and verified by running
it against the commit before those failures were fixed by hand, or by injecting the
fault deliberately.

`check_archive_leaks` exists because this bit three times in one day. Dataview's
`FROM "folder"` recurses, so creating an archive subfolder silently widens every query
reading the parent — nothing errors, the query keeps returning rows, and finished work
starts appearing as live. A query is safe if it excludes the archive path or filters on
`status`, since archived notes carry `status: done`.

`check_own_docs` is self-referential on purpose. Every other rule compares notes to
notes, or a note to a folder — nothing compared code to the prose describing it, so
the tooling was the one part of the vault with no drift detection at all. That is a
poor place for a blind spot, since everything else depends on it. The checker is the
only thing positioned to notice that the checker has drifted.

The three coverage rules all have the same shape: a note that claims to describe a
set, drifting from the set. They only work because the lists use exact links —
aliased wikilinks like `[[homelab-node-provisioning|node provisioning]]` read as
prose and match exactly. Keep it that way; prose lists would need fuzzy matching,
and a check that cries wolf gets ignored within a week.

**Deeper, optional scan.** For orphan attachments, duplicate files by hash and
oversized files, which the script above does not cover:

```bash
cd ~/Documents/Second_Brain && npx --yes vault-inspector . --format json
```

That needs npm and a network, which is why it is not what CI runs.

## Reading the results

Both tools report; neither fixes. That's correct — most findings need a judgement
call, and a script that "tidies" a knowledge base unasked is how people lose notes.

Sort by what actually costs something:

**Fix now:** anything that looks like a leaked secret, duplicate basenames, and
broken links. These are correctness problems.

**Fix soon:** missing frontmatter (the note is invisible to every query), bare
`log.md` naming, invalid enum values.

**Judgement:** orphan attachments are usually screenshots staged but never embedded
— the fix is often to embed them with `![[filename.png]]` rather than delete them.
Stale reference notes need reading before acting; the fix might be updating the
content, or might be deleting a note that has outlived its subject. Low-usage tag
warnings are almost always noise in a personal vault; ignore them.

## Renaming and moving

Obsidian's own index answers link questions better than any filesystem scan, and
these are the fastest health check available:

```bash
obsidian unresolved   # links pointing at notes that don't exist — broken links
obsidian orphans      # files nothing links to, including unembedded images
obsidian deadends     # notes with no outgoing links
```

Run `unresolved` first. It is the authoritative broken-link check and it is instant.

**Moving and renaming.** Use the CLI rather than `mv` — it relocates the file *and*
rewrites every `[[wikilink]]` pointing at it, where `mv` silently orphans them and
the damage only surfaces later when something you needed fails to resolve.

This depends on **Settings → Files and links → Automatically update internal
links**, which is off in a default Obsidian install and is on in this vault
(`alwaysUpdateLinks: true` in `.obsidian/app.json`). If it ever gets turned off, a
move leaves every link pointing at the old name — the exact failure the CLI is
supposed to prevent. Verified both ways: with it off the link went stale, with it on
`[[move-target]]` became `[[move-target-renamed]]` automatically.

Run `obsidian unresolved` after any move regardless. It costs a second and it is the
only thing that actually proves nothing broke.

Arguments are `key=value`, not positional:

```bash
obsidian move   path="20_Buildlogs/old.md" to="30_Posts/old.md"
obsidian rename path="10_Projects/Old Name.md" name="New Name"
obsidian delete path="00_Inbox/dead.md"          # goes to trash, not permanent
```

Useful for diagnosis too, since these read Obsidian's own index rather than
guessing from the filesystem:

```bash
obsidian backlinks file="keepbreath.ing"   # who actually links here
obsidian links file="keepbreath.ing"       # what it links out to
obsidian search query="ALTCHA" limit=5
```

Requires Obsidian **running**, since the CLI drives the live app. If it isn't, the
command says so. Fall back to `mv` only if you must, and then check for links you
just orphaned:

```bash
grep -rn "\[\[old-note-name" ~/Documents/Second_Brain --include='*.md'
```

## After fixing

Re-run both checkers. A fix that introduces a new problem is common — renaming a
file to clear a duplicate basename breaks any link that pointed at the old name,
unless the rename went through Obsidian.
