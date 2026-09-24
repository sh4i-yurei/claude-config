---
name: research
description: Use when a question needs sources rather than recall — investigating a tool, protocol, standard, vendor, library or design decision; when asked to look into, find out about, dig deeper on, compare, or research something; or when a previous answer turned out shallow and needs another pass.
---

# Research

Two required sections bracket the work. They are written into the files, not just said in
the reply, because a plan that leaves no trace is a plan nobody can check.

## Before the first query

Create `70_Research/<topic>/sources/<topic>-sources.md` and write this section first:

```markdown
## Search plan
- **Effort tier:** simple (3–10 calls) | comparison (10–15) | complex — say why
- **Budget:** N calls
- **Ideal source:** what the thing that actually answers this would be
- **Sub-questions:** the concepts this breaks into, named
- **Synonyms:** per concept — OR within a concept, AND across them
```

Filling it in afterwards defeats the point. Broad queries first, specific ones after.

Skip the last two and you get the signature failure: the same sub-question asked five times
in slightly different words.

## The ladder — use the cheapest rung that works

| Rung | Use it for |
|---|---|
| Local | Files on disk, `--help`, `man`, installed documentation, the vault |
| API or MCP | A documented API or an MCP tool. See `known-apis.md` |
| Paced fetch | One fetch to a site at a time, spaced per site — see below |
| Scraping service | Anti-bot walls, JavaScript-rendered pages, real volume |

**Check what this session actually has before assuming.** The tools available change between
sessions and between projects: connectors fail, need authentication, or are configured at a
scope that does not reach here. A specialised tool beats a generic search whenever one
exists, and reaching for one that is not loaded wastes the turn. `known-apis.md` lists open
endpoints that answer a precise question in one request, which is almost always better than
reading pages. If something that should be available is missing, say so rather than quietly
falling back to scraping.

Web fetches leave from the user's home connection. **Never fan out subagents to search in
parallel** — that is the pattern that gets an address flagged.

**Pacing is per site, not overall.** Four pages each from a hundred sites is reading; four
hundred pages from one site is hammering it. Before fetching a site again, wait roughly ten
times as long as the last fetch to that site took — floor one second, ceiling two minutes.
A slow response usually means a loaded server, so this backs off exactly when it matters. A
flat delay cannot, which is why there is no single number here.

One fetch to a site at a time. After five errors in a row from a site, leave it alone for
hours rather than minutes.

Respect `robots.txt`, and honour `Crawl-delay` by taking whichever is longer, it or the gap
above — it is good manners rather than a standard, since RFC 9309 deliberately left it out.

On a 429, back off; never retry straight into a limit. At most three attempts per request,
and retries stay under a tenth of all requests. Billable calls need a ceiling stated before
the first one.

**A limit on one source is not the end of the question.** Most questions have several
sources that answer them, and `known-apis.md` lists them as chains. Hitting a rate limit,
running out of credit, or meeting a bot wall means moving to the next source — not
abandoning the sub-question and not reporting it as unanswerable. Say which source actually
answered, since coverage differs between them.

Reasoning and sources in `70_Research/client-side-rate-limiting/`.

**A hook denial means the approach was wrong, not that the hook is in the way.** Step back
down the ladder. Never route around a block.

## Red flags — stop

- About to spawn subagents that will each search
- About to retry something that just returned 429
- About to fetch a domain listed in `known-apis.md`
- About to fetch a page already read this session, or written up in `70_Research/`
- About to report a number whose only source has a stake in it
- About to call it complete when what actually happened is the budget ran out
- About to work around a denial instead of stepping down a rung

## Before answering

The synthesis note ends with this section:

```markdown
## How far this went
- **Why I stopped:** saturation — a full round that added nothing new — or the cap. Say which.
- **Single-sourced:** the load-bearing claims with no second, independent source
- **Disagreement:** where it is; or that the only numbers are the vendor's or the inventor's
```

Presenting an early stop as a complete one is the failure this skill exists to prevent.

## Storage

Exactly two files:

```
70_Research/<topic>/<topic>.md                    the synthesis
70_Research/<topic>/sources/<topic>-sources.md    the sources
```

The sources file goes **inside** `sources/`, not beside the synthesis. Summarise with
attribution; never paste third-party text into the vault. Write findings down as they
arrive.

The sources file carries `## Search plan` above, then:

```markdown
## Queries run
| Date | Query | Tool | What it returned |
```

then a paragraph per source saying what it contributed and where it has an interest.

Deleting a note is allowed where that folder's README permits it, but say which note and
why, in the reply where it happens. Never silently.

`methodology.md` has the techniques: chaining, the unindexed layer, saturation, weighing
sources. `known-apis.md` has the fallback chains. `keys.md` says which keys exist, what each
one unlocks, and how to read it from the vault with `bw get`.
