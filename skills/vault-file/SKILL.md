---
name: vault-file
description: Captures a note into Mark's Obsidian vault at ~/Documents/Second_Brain, and files items out of 00_Inbox into their proper home. Use this whenever he says to write something down, remember this, capture that idea, park it for later, add it to the vault, or make a note — and when he asks to clear, process, empty or triage the inbox. Also use it when an idea worth keeping surfaces mid-conversation and would otherwise be lost when the session ends. Trigger it even when he does not name the vault, Obsidian, or a folder.
---

# Filing into the vault

Two jobs that pull in opposite directions: capturing fast enough that ideas don't
evaporate, and filing carefully enough that the vault stays navigable. Doing both
at the moment of capture is what kills capture, so they're separated on purpose.

## Capturing

If he knows where it goes, put it there and use the template. If he doesn't, or
the conversation is mid-flow and stopping to decide would break it, drop it in
`00_Inbox` and move on. An inbox item needs no frontmatter and no naming
convention — anything that gets it captured is correct.

Capture what he actually said, in his framing. A captured idea that's been
rewritten into your words has lost the thing that made it worth keeping.

## Filing out of the inbox

Read the item first, then decide what it *is* — that determines everything else:

**A project or an idea for one** → `10_Projects`, named as he'd say it out loud
(`Dev server`, `keepbreath.ing`), because that filename is what `[[links]]` resolve
against. Use the `project-note` skill; it has nine sections and specific rules.

**A durable how-to** → `40_Reference`, named as what you'd search for
(`nginx-security-headers.md`). Needs `updated:` in frontmatter.

**Something personal** → `50_Personal`. No naming convention; imposing one here
only makes the folder get avoided.

**Work about to happen** → a buildlog. Use the `buildlog` skill.

**Finished writing** → `30_Posts`.

Then: rename to that folder's convention, add the frontmatter (no `title:` field —
the filename is the identity), link it to whatever project it belongs to with
`project: "[[Project Name]]"`, and move it with the Obsidian CLI rather than `mv`,
so any wikilink pointing at the note follows it:

```bash
obsidian move   path="00_Inbox/thing.md" to="40_Reference/nginx-headers.md"
obsidian rename path="00_Inbox/thing.md" name="nginx-headers"
```

Arguments are `key=value`, and Obsidian must be running. If you fall back to `mv`,
grep for `[[old-name` afterwards to catch links you just orphaned.

## When an inbox item is really several things

Common, and the reason inboxes clog. A note that's part project, part how-to, and
part half-written prose can't be filed as any one of them. Split it — that's the
same "one note, one job" rule the whole vault runs on, applied at the moment it
first gets tested.

## When to delete instead

Not everything captured deserves a home. An idea that's been sitting for three
weeks and still doesn't connect to anything is usually telling you something.
Say so and offer to drop it rather than filing it somewhere it will never be read.

## Before writing

Read the destination folder's `README.md` — it states what belongs, what doesn't,
the naming convention, and the exact frontmatter. Those files are the authority;
this skill is the procedure.
