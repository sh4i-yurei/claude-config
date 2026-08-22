---
name: vault-health
description: Checks Mark's Obsidian vault at ~/Documents/Second_Brain for broken links, orphan attachments, duplicate basenames, missing or invalid frontmatter, stale reference notes, forgotten inbox items, and secrets accidentally pasted into notes. Use this when he asks whether the vault is healthy, tidy, consistent or drifting, after any batch of note edits or a migration, after renaming or moving notes, before adding a new convention, or whenever something in the vault seems off. Also use it periodically during long vault work — the cost of running it is seconds and the cost of silent drift is a knowledge base nobody trusts.
---

# Vault health

A second brain fails quietly. Nothing errors when a link breaks, a note loses its
frontmatter, or a reference doc goes stale — it just gradually stops being worth
consulting. This checks for that before it compounds.

## Run both checkers

They cover different ground and neither replaces the other.

**Conventions specific to this vault:**

```bash
python3 ~/.claude/skills/vault-health/scripts/check.py
```

Catches duplicate basenames (which make `[[wikilinks]]` ambiguous), buildlogs using
bare `log.md` instead of `<slug>-log.md`, notes with no frontmatter or an unknown
`type`, `status`/`post`/`genre` values outside the allowed set, a `title:` field
that shouldn't exist, reference notes not updated in six months, inbox items older
than three weeks, and anything that looks like a key, token, or certificate pasted
into a note.

**Generic vault problems:**

```bash
cd ~/Documents/Second_Brain && npx --yes vault-inspector . --format json
```

Catches broken links and embeds, orphan attachments, empty notes, duplicate files
by hash, frontmatter type inconsistencies, and oversized files. First run downloads
the package; after that it's fast.

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
