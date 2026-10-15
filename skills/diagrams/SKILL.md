---
name: diagrams
description: Adds and maintains Mermaid diagrams in Mark's vault notes and repositories, and checks every diagram by rendering it before he sees it. Use this whenever you write or change something that describes a system — a project note's "How it's built", a README, a decision record, a reference note, an infrastructure or network layout, a request flow, a deploy pipeline — and whenever he asks for a diagram, a picture, a map or a visual of anything. Also use it when a description of how pieces connect runs past a paragraph with no picture. Trigger it even when he does not say diagram or Mermaid.
---

# Diagrams

Mark reviews diagrams; he does not draw them. Every diagram is Mermaid text written
into the file it belongs to, and it is rendered and looked at before he sees it.
The project behind this is [[Diagram workflow]] in the vault.

## When a diagram earns its place

Add one when the text describes things that connect: machines and the paths between
them, services and who calls whom, steps that happen in order, states something moves
through. Don't add one to a note that's a list or an argument — a picture of a list
is decoration.

When you change a note that already has a diagram, check whether the change made the
diagram wrong, and fix it in the same edit. A stale diagram is worse than none.

## Which kind

| What it shows | Mermaid type |
|---|---|
| Machines, networks, how the estate fits together | C4 (`C4Context`, `C4Container`), or `flowchart` grouped with `subgraph` |
| A request or a login moving between parts, in time order | `sequenceDiagram` |
| A process or decision with branches | `flowchart` |
| Something moving through states | `stateDiagram-v2` |
| Data and how tables relate | `erDiagram` |

**C4 for architecture.** C4 is the standard set of zoom levels: context (the whole
system and who uses it), containers (the apps, databases and services inside it),
components (the parts inside one container). Pick one level per diagram and say which
in the sentence above it. Never mix levels in one picture.

If a C4 diagram comes out cramped (Mermaid's C4 support is experimental), redraw it as
a `flowchart` with one `subgraph` per C4 boundary.

## Writing it

- Put it in a fenced `mermaid` block in the file it describes, right after the
  paragraph it illustrates. Obsidian and GitHub both draw it from there.
- Write one plain sentence above it saying what it shows.
- Label every arrow with what travels along it (`HTTPS`, `Tailscale SSH`, `SMTP 587`).
- Use the real names: `web`, `control`, `hub`. Never invent a machine or a link — if
  you're not sure a connection exists, check the note or the machine, or leave it out.
- Draw the real route, hop by hop. If traffic goes through a jump host, a subnet router
  or a proxy, the arrow goes through that box, not straight past it. When one machine
  reaches another two different ways (a private scrape and a public check, say), draw
  both, because the difference is usually the point.
- Before drawing an arrow, find the sentence in the project note that says how that
  traffic travels. Knowing that two machines talk is not enough.
- **One story per diagram.** "How the public reaches the site" and "how I reach and
  watch the estate" are two diagrams, not one. Keep to about ten boxes and eight
  arrows. When arrows have to cross between several groups, the layout loops wires
  around the whole picture; that is the signal to split.
- When two sources both point at the same pair of boxes, put the pair in a `subgraph`
  and point at the subgraph. Four crossing arrows become two straight ones.
- Give boxes colour with `classDef`, one class per group (Mark's devices, DigitalOcean
  servers, the house, outside services), with a dark fill and white text so they read
  in both themes. Never force a text colour on a `subgraph` label; let the theme pick
  it, or it vanishes in one of the two themes.
- A long chain reads better top to bottom (`flowchart TB`) than as one thin strip
  left to right, which shrinks to nothing at note width.

## Check it before he sees it

Render it in the `dev` container twice, once in each theme, because Mark's Obsidian
is dark and GitHub is usually light:

```bash
distrobox enter dev -- mmdc -i <scratchpad>/d.mmd -o <scratchpad>/d-dark.png -t dark -b '#1e1e1e'
distrobox enter dev -- mmdc -i <scratchpad>/d.mmd -o <scratchpad>/d-light.png -t default
```

Then Read both PNGs. "It rendered and the paths can be followed" is not a pass. The
first estate diagram met that bar and still looked awful in Obsidian. Fix and
re-render if any of these are true:

- it failed to render;
- boxes, groups and labels are close enough in colour that nothing stands out;
- any label overlaps something or disappears in one theme;
- any wire loops around the outside of the picture, or two wires cross;
- a box has nothing connected to it and no reason to be there;
- it is much wider than tall, so the text would be tiny at note width;
- something in the picture disagrees with the text it sits under.

Would Mark look at it and think it was drawn on purpose? If not, it is not done.

The images are throwaway and go in the scratchpad, never in the vault or a repo. The
Mermaid text is the source of truth.

## Polish for an audience

For a blog post or portfolio piece, the Mermaid source becomes a finished picture
through Claude Design. Which route — a canvas made directly, or a prompt Mark pastes
— is decision 5 in [[Diagram workflow]], and it's still being settled. Read that
decision before doing either.
