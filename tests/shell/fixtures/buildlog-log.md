---
type: buildlog
status: active
created: <% tp.date.now("YYYY-MM-DD") %>
project: "[[]]"
post: none
tags: []
---

%% ─────────────────────────────────────────────────────────────────────
BUILDLOG — the honest record, written DURING the work.

One file per buildlog. The plan lives in the project note's Next list; this
file records what actually happened, forward-chronological, newest at the
bottom, one entry per real step.

Never prefilled. If it hasn't happened, it doesn't get an entry. A log
written from memory three days later has already lost the exact thing it
exists to capture.

This file is the raw material for every technical post. What's missing here
can't be recovered later.

ENTRY FORMAT — when something went wrong:

## YYYY-MM-DD HH:MM CDT — short title
Saw:   the symptom, as it actually appeared on screen
Cause: why it happened
Fix:   what resolved it — and the real fix, if this one was a workaround
Prevent: what changes so it can't happen again — a test, a check, a hook, a rule

Saw comes first because it's the part that evaporates fastest and the part a
reader recognizes as their own bad afternoon. Paste the actual error or
output. Not a paraphrase, not a summary — the real text.

ENTRY FORMAT — when it just worked:

## YYYY-MM-DD HH:MM CDT — short title
what was done, the commands or config that mattered, and why this way and not
the other way.

[life] ENTRIES — the human parts. Shift ran long, ate standing up, 2am, hit a
wall, small win, kid interrupted. Same timestamp format, tagged [life]. These
are what make the finished post sound like a person wrote it, and they only
exist if they're caught while they're still true.

## YYYY-MM-DD HH:MM CDT — [life] short title
what was going on.

FRONTMATTER: `status` is active or done. `post` starts at none and is promoted
to candidate on purpose when the work turns out to have a story in it, then
drafted, then published.

WRAPPING UP: when the work ends, write one last entry — what shipped, what's
still broken, what you'd do differently. That entry is usually most of the
post's closing section.
───────────────────────────────────────────────────────────────────── %%

# Log

