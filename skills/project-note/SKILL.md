---
name: project-note
description: Creates and updates project notes in ~/Documents/Second_Brain/10_Projects, the front door to every project Mark has. Use this when he starts a new project or has an idea for one, when a decision gets made that should be recorded, when work finishes or changes what is next, when he asks where something stands or what he decided, and after any substantial work session so the note reflects reality. Also use it when a project note has grown wrong — accumulating history, backlogs or how-to content that belongs in other folders. Trigger it even when he does not mention notes, projects folders, or the vault.
---

# Project notes

A project note answers "what is this, and where does it stand" for two readers:
Mark in six months who has forgotten the details, and you at the start of a session
who needs to come up to speed without reading a repo.

Everything about its shape serves one goal — stopping it from becoming the 28,000
character `ROADMAP.md` it replaced. That file failed not because it was long but
because it was six documents at once: status, backlog, a security plan, a phased
rollout, and a blog outline.

## Creating one

Start from `_Templates/project.md`. Name it as he'd say it out loud —
`keepbreath.ing`, `Dev server`, `Home lab - Pi cluster` — because the filename is
what `[[links]]` resolve against everywhere else.

Nine sections: **What it is**, **Why** (including what done looks like), **Scope**
(in and out), **How it's built**, **Decisions**, **Where it stands**, **Next**,
**Open questions**, **Risks**. An idea that hasn't started might only fill the
first three; delete the rest rather than leaving empty headings. A live project
fills all nine and that's fine — there is no length cap.

The **Out** half of Scope is the one people skip and the one that earns its place.
It's where you record the thing he keeps being tempted by, so next time it comes up
the note shows he already decided.

## Decisions are numbered, and superseded rather than deleted

```
1. nginx over Caddy `[decided]` — Caddy is easier and was half set up, but nginx
   is the tool used everywhere in security work and the point is to learn it.
2. Mail on its own droplet `[tentative]` — decide during the rebuild.
7. Time-trap bot defence `[superseded by 5]` — ALTCHA covers it cryptographically.
```

Numbering exists so a changed mind leaves a trace. Editing decision 5 in place
destroys the record of what was believed before and why it changed, which is
usually the more interesting half. When something is reversed, mark the old one
superseded and add a new one.

Record the honest reason, not the defensible one. "Because I want to know nginx"
is more useful to future-Mark than a performance justification he doesn't believe.

## Updating after work

**Where it stands** gets *rewritten*, never appended to. The moment it becomes a
running history it is a buildlog wearing the wrong hat, and that is exactly how the
old roadmap grew. What happened belongs in `20_Buildlogs`.

**Next** holds what he'd genuinely pick up if he sat down now. A list of thirty
items is a list of zero. Anything further out is either an open question or a
different project.

## What does not belong, and where it goes instead

History → `20_Buildlogs`. Step-by-step instructions → `40_Reference`. Draft prose →
`30_Posts`. Recording *that* the site runs nginx behind Cloudflare belongs here;
the procedure for issuing an origin certificate does not.

If a note is getting unwieldy, it is almost always holding one of those three. Move
the content out rather than trimming it — the size is a symptom, not the disease.

## Splitting

When a project note describes several genuinely separate efforts, each with its own
definition of done and its own eventual blog post, it is several projects. Split it
and cross-link with `[[wikilinks]]`. Don't maintain a list of related notes by hand
— anything carrying `project: "[[This Project]]"` in its frontmatter already shows
up in the backlinks pane, and a hand-kept list only goes stale.
