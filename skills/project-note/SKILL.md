---
name: project-note
description: Creates and updates project notes in ~/Documents/Second_Brain/10_Projects, grouped into domain subfolders (11_Infrastructure, 12_Web, 13_Mail, 14_Security, 15_Code, 16_Tooling) with finished work in 19_Archive. A project note is the specification for the project and the front door to it: it must be fully decided and research-backed before a buildlog opens. Use this when he starts a new project or has an idea for one, when a decision gets made that should be recorded, when work finishes or changes what is next, when he asks where something stands or what he decided, and after any substantial work session so the note reflects reality. Also use it for program charters, the notes that group related projects under one goal, and before working on any project whose note names a program. Also use it when a project note has grown wrong — accumulating history, backlogs or how-to content that belongs in other folders. Trigger it even when he does not mention notes, projects folders, or the vault.
---

# Project notes

**The project note is where the project is going. The buildlog is where it has been.**

It is the specification, not a status page. It answers "what is this, what are we
building, what has been decided and why" for two readers: Mark in six months who has
forgotten the details, and you at the start of a session who needs to come up to speed
without reading a repo.

Everything about its shape serves one goal — stopping it from becoming the 28,000
character `ROADMAP.md` it replaced. That file failed not because it was long but
because it was six documents at once: status, backlog, a security plan, a phased
rollout, and a blog outline. Length is not the problem; a real project's note is long.

## Sizing the design

`00_Inbox/README.md` is the authority for deciding how much design an item needs. Ask three
questions: Is it a new system or service? Does it touch authentication, secrets or how data is
stored? Does it need a data migration or a schema change? Any yes makes it architecture. If the
size is unclear, call it a feature.

A fix gets a sentence in its issue naming the problem and the change. A feature gets a short
design in the project note or issue: the problem, approach, affected interfaces or data, test
plan, and failure modes. Architecture gets that design plus at least two options compared with
the reasons the other options lost. Ask Codex to critique the architecture before the build
handoff.

## Fully decided before the buildlog opens

Before any building starts, the note carries the research, every design question the
build depends on, answered, and a scope bounded concretely enough to build from. A
buildlog should not open on a project whose note still has open design questions.

**Why this rule is stricter than the usual advice.** Fowler on evolutionary design, DORA
on change approval and the academic work on infrastructure-as-code defects all say a
heavyweight up-front spec is not what prevents defects. That research is about human
teams. A human holding a half-formed design keeps it in their head, notices when a new
decision contradicts an old one, and asks when something is ambiguous. You do not. With a
vague scope you will assume, forget the assumption, and later contradict it with equal
confidence — which is exactly what happened to the Ansible baseline role between 15 and 19
September 2026, five reversals mid-build.

So: research first, decisions recorded, then build. If a question surfaces mid-build that
was missed, stop and settle it in the note rather than deciding it in passing.

## Where it goes

Projects live in a domain subfolder, not at the top of `10_Projects`:

| No. | Folder | Holds |
|---|---|---|
| 11 | Infrastructure | Servers, home lab, the things that run other things |
| 12 | Web | The public site and what ships on it |
| 13 | Mail | Sending and receiving as `@keepbreath.ing` |
| 14 | Security | Hardening, and security work that is its own project |
| 15 | Code | Learning to program by building things worth finishing |
| 16 | Tooling | Things built to make the other work faster |
| 19 | Archive | Finished. Moved here, never deleted. |

## Programs

Some projects belong to a **program**: a group of projects run toward one shared goal and
built on one shared design. The program's **charter** (`type: program`) sits in the same
domain folder as its projects and holds what belongs to none of them alone: the goal, the
reference architecture, the order the projects get built in, and the decisions that apply to
all of them. The full rules are in the "Program charters" section of `10_Projects/README.md`.

- **A project names its program** with `program: "[[Charter Name]]"` in its frontmatter.
  That field is the only membership record. The charter's member table is a Dataview query
  over it, so never hand-maintain a list of members.
- **Before working on a project that names a program, read the charter first.** Its decisions
  bind every member. A project decision that contradicts one is relitigating it, and has to
  be raised with Mark rather than recorded.
- **Put each decision where it applies.** If it affects one project, it goes in that project's
  note. If it affects several, it goes in the charter, and the projects link to it rather
  than copying it.
- **A charter never holds build steps and never gets a buildlog.** Its roadmap orders the
  projects. Each project's own Next orders that project's work. The vault check warns when a
  buildlog points at a charter.
- **A charter closes when its last project does** and nothing more is planned. The vault check
  refuses a `done` charter with an unfinished member.

Start a charter from `_Templates/program-charter.md`.

## The five states

`status` has five values, because "not being worked on" has more than one cause:

- **`idea`** — a notion. Might never happen.
- **`active`** — he would genuinely pick this up today.
- **`simmering`** — real and intended, but not now.
- **`paused`** — started, then stopped. Different from simmering, which never began.
- **`done`** — finished, and moved to `19_Archive`.

**Status leads; the folder follows.** A note reaches `19_Archive` because its status
is `done`, never the reverse. Encoding state as location is what makes archives rot.

Before archiving, check for unfinished tasks in the note. Archiving is not deleting,
but a live task inside an archived note is functionally deleted, because nothing
looks there again — move it to `00_Inbox` first.

## Creating one

Start from `_Templates/project.md`. Name it as he'd say it out loud —
`keepbreath.ing`, `Dev server`, `Home lab - Pi cluster` — because the filename is
what `[[links]]` resolve against everywhere else.

Nine sections: **What it is**, **Why** (including what done looks like), **Scope**
(in and out), **How it's built**, **Decisions**, **Where it stands**, **Next**,
**Open questions**, **Risks**. An idea that hasn't started might only fill the
first three; delete the rest rather than leaving empty headings. A live project
fills all nine and that's fine — there is no length cap.

The **In** half of Scope has to be concrete enough to build from. "The baseline every
box shares" is not; a list of what the baseline actually does is. If you cannot write a
task list from the In section, it is not finished.

The **Out** half is the one people skip and the one that earns its place. It's where you
record the thing he keeps being tempted by, so next time it comes up the note shows he
already decided. Each item says where it belongs instead.

**How it's built** carries the shape of the thing, not only the stack: how the pieces fit,
what order things happen in, and anything about the environment the build depends on. When
a fact was read off a real machine rather than assumed, say so and date it. Estates drift
and notes go stale quietly — the Ansible project believed its droplets were AlmaLinux 10
for four days because nobody had looked.

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

**Record what was rejected, and why.** A decision with no alternatives listed gets
relitigated the first time somebody thinks of one. The rejected option and its cost are
half the value of writing it down.

**Back decisions with research or with the machine.** Where a decision came out of a
research pass, the write-up goes in `70_Research/<topic>/` and the decision links to it.
Where it came out of checking a real machine, paste the line the machine printed. A
decision whose stated reason turns out to be false gets marked `[withdrawn]` with the
correction, not quietly edited — that happened on 2026-09-18 when "Ansible cannot produce
a yescrypt hash" turned out to be untested and wrong.

## Updating after work

**Where it stands** gets *rewritten*, never appended to. The moment it becomes a
running history it is a buildlog wearing the wrong hat, and that is exactly how the
old roadmap grew. What happened belongs in `20_Buildlogs`.

**Next** is the build order, not a wish list: the sequence he would actually work
through, grouped when it is long, with each item pointing at the decision it implements.
Everything in it must be buildable from what is already decided above. If an item needs a
decision nobody has made, it is not Next yet — it is an open question.

**Open questions** should hold only what genuinely cannot be answered yet, each with what
would answer it, and it should say plainly that nothing there blocks the build. If
something there does block the build, the build should not have started. Keep answered
ones struck through, pointing at the decision that settled them.

## Risks and known limits

A risk is something that might go wrong. A known limit is a deliberate shortcut that is already
true. Both go under **Risks**, but a known limit is named plainly, with the reason it was accepted
and what remains incomplete, so a conscious trade-off doesn't turn into an invisible assumption.
If the project has a repository, mirror it as a `tech-debt` issue labelled `debt:deliberate`: the
note keeps the reason, and the issue keeps the work visible where changes are made.

**A shortcut only counts as deliberate if the record shows someone chose it.** Search the
buildlog, the decisions, the reviews and the session transcripts for the moment it was weighed. If
nobody ever chose it, it isn't a known limit with a reason to record. It's accidental debt:
`debt:accidental`, a gap found after the fact. Never ask Mark to remember a reason the record
doesn't hold. The `node_exporter` firewall rules were first written up as deliberate and turned
out to be accidental (Development workflow decision 45).

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

When the separate efforts all serve one goal and share one design, the original note
becomes their **program charter** instead. The shared goal, architecture and cross-cutting
decisions stay in it. Each effort moves out to its own project note carrying
`program: "[[Original Name]]"`, taking its build steps and project-specific decisions with
it.
