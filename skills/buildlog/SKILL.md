---
name: buildlog
description: Keeps a live record of real work in Mark's Obsidian vault at ~/Documents/Second_Brain/20_Buildlogs. Use this whenever working on something substantial — a deploy, a migration, a config change, a feature, a long debugging session — and especially the moment something breaks, produces an error, or behaves unexpectedly, because that is the material his blog posts are made of and it is lost if not captured live. Also use it when starting such work (scaffold the buildlog first), when the user mentions a late night, a work shift, or anything about how the session is going (those become [life] entries), and at the end of any working session to sweep up unlogged work. Trigger it even when the user does not mention logging, notes, Obsidian, or the vault at all.
---

# Buildlog

Mark's technical blog posts are built almost entirely out of things that went
wrong — the specific symptom, the specific cause, the specific fix. The buildlog
is where that raw material gets captured while it's still true. A week later he
remembers *that* he fixed the HSTS problem; he does not remember that `curl`
kept showing `max-age=300` while `nginx -s reload` exited clean. That detail is
what makes a reader recognize their own bad afternoon, and it only exists if
someone wrote it down at the time.

That's the whole reason this exists. Everything below serves it.

## Layout

```
~/Documents/Second_Brain/20_Buildlogs/<slug>/
    <slug>-outline.md   the plan, written before the work
    <slug>-log.md       the record, written during the work
    images/             screenshot staging
```

Files carry the slug in their name rather than being bare `log.md`. Obsidian
resolves `[[wikilinks]]` on filename alone, so bare names collide across
buildlogs and every link then needs a full path.

Read `~/Documents/Second_Brain/20_Buildlogs/README.md` for the full convention if
anything here is ambiguous — that file is the authority, this skill is the
working procedure.

## Starting a buildlog

When work begins on something worth remembering — a deploy, a migration, a
feature, a debugging session that's clearly going to take a while — scaffold it
before the work starts, not after:

```bash
~/.claude/skills/buildlog/scripts/new-buildlog.sh <slug> "<Project Note Name>"
```

The slug is lowercase words joined by hyphens, no dates: `droplet-rebuild`,
`contact-form`, `vlan-segmentation`. The project name must match a note in
`10_Projects` exactly, since it becomes a `[[link]]` — check what's there rather
than guessing at the name.

Then fill in the outline: what you're about to do, why now, the approach
including any rollback path, and what "done" looks like stated so it can be
checked rather than felt. That last one is worth real thought — "the site works"
is not checkable, "curl from outside the box returns the new header and the
origin refuses a direct connection" is.

**Not every task needs a buildlog.** A one-line config tweak or a quick question
doesn't. The test is whether you'd want the record in a month, or whether
anything in it might become a post. When unsure, ask rather than either
scaffolding clutter or losing the material.

## Writing entries

Entries go in `<slug>-log.md`, forward-chronological, newest at the bottom.
Timestamps are Central time:

```bash
TZ=America/Chicago date '+%Y-%m-%d %H:%M %Z'
```

### When something went wrong

```
## 2026-08-04 14:22 CDT — HSTS raise didn't take
Saw:   curl -I still returned max-age=300; nginx -s reload exited clean
Cause: git pull replaced nginx.conf (new inode); the bind mount was pinned to the old one
Fix:   docker restart — real fix is mounting the directory, not the file
```

`Saw` comes first deliberately. It's the part that evaporates fastest and the
part a reader recognizes. **Paste the actual error text and the actual command
output** — not a paraphrase, not a summary. If the terminal said
`Permission denied (publickey)`, write that, not "auth failed."

If the fix was a workaround, say so and name the real fix. Future-Mark will hit
this again and the note should tell him whether he's looking at a patch or a
solution.

### When it just worked

```
## 2026-08-04 15:10 CDT — DO Cloud Firewall applied
Pulled Cloudflare's published ranges from their API and wrote an inbound rule
allowing 80/443 only from those. Left SSH open. Chose the DO edge firewall over
ufw because Docker writes its own iptables rules that bypass ufw entirely.
```

Include the commands and config that mattered, and **why this way and not the
obvious other way**. The reasoning is usually more valuable later than the
command, because the command can be re-derived and the reasoning can't.

### `[life]` entries

```
## 2026-08-09 23:40 CDT — [life] pushing before the semester starts
Past midnight, classes start Monday. Want the site mostly done before the
semester eats my evenings.
```

These are what make the finished writing sound like a person wrote it rather
than a changelog. Capture them when the user mentions the time, a work shift,
being tired, being interrupted, getting stuck, or a small win — they're only
true in the moment and cannot be reconstructed afterward.

Don't invent them and don't fish for them. Write down what he actually said.

### Screenshots

When something on screen is worth a picture — a passing test, a dashboard, a
before/after — say `📸 capture X now` in the conversation and tick it off the
outline's checklist. He takes the shot; it gets staged in `images/` and redacted
before publishing (crop chrome, bar out IPs, emails, and secrets).

## Never prefill, never backfill

If it hasn't happened, it doesn't get an entry. A log written from memory days
later has already lost the exact thing it exists to capture, and worse, it reads
as though it were written live when it wasn't.

Writing entries at the **end of the same session** is fine and often better than
interrupting the work — the session transcript still holds the real error text
and the real commands, so that's working from the record, not from recollection.
The line is the session boundary, not the moment.

## Promoting to a post

The outline's frontmatter carries `post: none | candidate | drafted | published`.
It starts at `none`. Change it to `candidate` when the work turns out to have a
story in it — a failure with a named cause, a wrong assumption corrected, a trap
someone else would fall into.

Promote deliberately, not by default. The whole value of the field is that
searching for `post: candidate` returns the handful of things worth writing up.
If everything is a candidate, the search returns everything and the field means
nothing.

## Wrapping up

When the work ends, write a final entry: what shipped, what's still broken, what
you'd do differently. That entry is usually most of the eventual post's closing
section, and it's the cheapest one to write because it's all still in your head.

Then check whether the project note in `10_Projects` needs updating — its
"Where it stands" section should be rewritten to match reality, and its "Next"
list probably changed. The project note describes the present; the buildlog holds
the history. Keeping that boundary is what stops project notes from growing into
unreadable roadmaps.
