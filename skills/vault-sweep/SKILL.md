---
name: vault-sweep
description: Runs one bounded iteration of the vault sweep over Mark's Obsidian vault at ~/Documents/Second_Brain — checks everything, fixes the highest-priority batch, records what changed, and either schedules the next tick or ends the loop when a whole pass comes back clean. Use it when Mark runs /vault-sweep or /loop /vault-sweep, asks to bring the vault up to date, or asks whether the sweep is finished. Each tick is small on purpose so the diff stays reviewable.
---

# Vault sweep

One iteration. The loop calls this repeatedly; the checker decides when it is done.
The plan this implements is at `~/.claude/plans/ok-lets-get-a-sunny-origami.md`.

## 1. Check

```bash
python3 ~/.claude/skills/vault-sweep/scripts/sweep-check.py --summary
```

If it prints `Sweep check: clean.`, go to **Finish**. Otherwise read the first
non-empty section in full:

```bash
python3 ~/.claude/skills/vault-sweep/scripts/sweep-check.py --section <name> --limit 40
```

The sections come out in priority order: correctness first, then drift, then the
manual, then scaffolds, then style, then the ledger. Work them in that order. Do
not start on a lower section while a higher one has findings, with one exception:
style and ledger findings for the same note are fixed together, because the full
review is what clears both.

## 2. Fix one batch

**Bounded.** At most eight notes, or one folder of the operational manual, per
tick. A tick that touches thirty files produces a diff nobody reads.

Use the existing skills rather than improvising:

| Finding | Skill or tool |
|---|---|
| status, "Where it stands", archiving a project | `project-note`; moves go through `obsidian move` so links follow |
| inbox triage | `vault-file` — file it, archive it to `09_Archive` with a "where this went" line, or delete it |
| prose | `humanizer`, then `40_Reference/writing-and-teaching-directive.md`, then `vale --config ~/Documents/claude-config/vale/vale-sweep.ini <note>` from the vault's root |
| the record of the sweep itself | `buildlog`, into `20_Buildlogs/vault-system/vault-system-log.md` |

**Manual commands that run as the wrong user.** `ssh web` and `ssh mail` land as
`keepbreath0`, an ordinary account with sudo. The three shapes, from
`60_Operational_Manual/62_Machines/bastion-access.md`:

```
ssh -t web 'sudo <cmd>'                                    # as root
ssh -t web 'sudo -iu keepbreath1 <cmd>'                    # as the container user
ssh -t web 'sudo systemctl --user -M keepbreath1@ <verb> <unit>'   # that user's systemd
```

`-t` because sudo needs a terminal to ask for the password. `server-bootstrap`'s
`ssh root@<new-ip>` is correct and stays: a fresh droplet has no other account yet.

**Scaffolds.** Remove the `%%…%%` comment blocks the templates leave behind. The
frontmatter and the real content stay. The `[todo]` tags in the two old-format
buildlogs stay too: `20_Buildlogs/README.md` says they are left as they are.

**The full review of a note** (what clears `style` and `ledger` for it):

1. Read the whole note, not the flagged lines.
2. Apply the humanizer and the directive. In buildlogs, pasted commands, error
   text and command output are evidence: never rewrite them. Only the prose
   around them.
3. Run Vale on the result and fix what it finds.
4. Only then record it: `sweep-check.py --mark <note>`.

Vault notes are Mark's, in first person. "I" means Mark. No dialogue, no Claude
as narrator. Check every rewritten paragraph for this before saving.

**Published posts are out of scope.** The notes in `30_Posts` are live pages and
they stay as published. Mark decided this on 2026-09-12; do not rewrite them and
do not ask again. The checker skips them for style and the ledger, and only reads
their `status` field for the drift check.

## 3. Record

After the batch, re-run the summary and append one entry to
`20_Buildlogs/vault-system/vault-system-log.md`: what was fixed, the count before
and after, anything found that the checker did not predict. Timestamp in Central
time. First person, Mark's voice.

## 4. Next tick, or finish

If findings remain, schedule the next iteration — the loop is self-paced, so a
short delay is fine; there is nothing external to wait for. Pass the same
`/vault-sweep` prompt back so it re-enters this skill.

**Finish** only when `sweep-check.py` prints `Sweep check: clean.` with Vale
included, and nothing was changed between that run and the previous batch. Then:

1. Run the rest of the verification from the plan: `check.py` at zero errors,
   `obsidian unresolved` empty.
2. Write the closing entry in the `vault-system` buildlog with the starting and
   ending counts.
3. Update `10_Projects/16_Tooling/Vault system.md`'s "Where it stands".
4. End the loop.
