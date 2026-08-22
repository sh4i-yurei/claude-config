---
name: vault-query
description: Answers questions about Mark's work by reading his Obsidian vault at ~/Documents/Second_Brain. Use this whenever he asks what he is working on, what is next, where something stands, what he did last week or yesterday, what is blocked, what is worth writing a blog post about, whether he already solved something before, or what he decided about anything — and use it before proposing work on any project, so you are arguing from what the project note already says instead of from scratch. Trigger it even when he does not mention the vault, Obsidian, or notes.
---

# Vault query

The vault holds the answer to most questions about Mark's work. Reading it first
is the difference between "here's what I'd suggest" and "here's what you already
decided, and here's what's actually next."

The failure this prevents is relitigating settled decisions. His project notes
carry numbered decisions with reasons — nginx over Caddy, the DO edge firewall
over `ufw`, ALTCHA over Turnstile. Proposing one of those afresh wastes his time
and signals you didn't look.

## Start with the script

```bash
python3 ~/.claude/skills/vault-query/scripts/query.py status
```

That gives active projects, paused ones, open buildlogs, anything marked worth
writing up, and what's sitting unfiled in the inbox. Other commands:

```bash
query.py projects --status active     # or idea | paused | done
query.py buildlogs --post candidate   # work with a story in it
query.py posts --status drafted
query.py recent --days 7              # what's been touched
query.py find nginx                   # filename / frontmatter match
```

It returns paths and frontmatter, never note bodies. That's deliberate — it keeps
the answer small so you can then read only the two or three notes that matter
rather than pulling the whole vault into context.

## Or ask Obsidian directly

When Obsidian is running, its CLI answers from the live index rather than from a
filesystem scan, which makes it the better tool for anything link-shaped:

```bash
obsidian backlinks file="keepbreath.ing"   # every note that links here
obsidian links     file="keepbreath.ing"   # what it links out to
obsidian search    query="ALTCHA" limit=5
obsidian search:context query="inode"      # matches with surrounding lines
```

Backlinks are the one worth reaching for. Project notes deliberately don't keep a
hand-maintained list of related notes — anything carrying
`project: "[[Some Project]]"` shows up as a backlink automatically, so asking for
backlinks is how you find everything attached to a project without trusting a list
that could be stale.

## Then read what's relevant

For "what should I work on" — read the project note's **Where it stands** and
**Next** sections. For "why is it like this" — read **Decisions**, which carries
the reasoning and the `[decided]` / `[tentative]` / `[superseded]` status. For
"what did I do" — read the buildlog, which is chronological and has the real
commands and errors in it.

## Answering well

Lead with the answer, then cite the note it came from so he can check you. If the
vault genuinely doesn't say, say that plainly rather than inferring — a confident
guess dressed as a lookup is worse than "the notes don't cover this."

If you notice the vault is *wrong* — the project note says active but the work
shipped, "Where it stands" describes a state that's moved on — say so. Notes drift,
and a stale answer delivered confidently is how a second brain stops being trusted.

## Where things live

`10_Projects` is the front door: what a thing is, why, scope, how it's built,
decisions, current state, next actions, risks. `20_Buildlogs` holds the history —
what actually happened, with the real error text. `30_Posts` is finished writing,
`40_Reference` is looked-up how-tos, `50_Personal` is everything else, and
`00_Inbox` is unfiled capture.

Full schema is in the vault's `INDEX.md` and each folder's `README.md`.
