---
name: research
description: Use when a question needs sources rather than recall — investigating a tool, protocol, standard, vendor, library or design decision; when asked to look into, find out about, dig deeper on, compare, or research something; or when a previous answer turned out shallow and needs another pass.
---

# Research

**MUST, MUST NOT and SHALL NOT are absolute here.** They are requirements, not advice, and no
judgement call overrides them. Text without those words is rationale. Rationale explains a
requirement and never weakens one. Where the two appear to conflict, the requirement wins.
The same applies to `known-apis.md`.

Two sections are mandatory and bracket the work. Both MUST be written into the files rather
than stated in the reply, because a plan that leaves no trace is a plan nobody can check.

## Before the first query

`known-apis.md` MUST be read in full before the search plan is written. This is unconditional.
It does not depend on whether an API will be called, on the subject of the question, or on
what the answer is expected to be.

**`known-apis.md` MUST be applied as it stood when the session began.** Edits made during the
session — to cells, rows, permissions, gating or the Local-first table — take effect from the
next session. The one exception: a row added this session for a provider that no pre-existing
row names MAY be used, but it SHALL NOT displace a pre-existing row that also covers the
sub-question. Rules that require an edit, such as adding a row, still apply; the edit simply
does not loosen anything until next time.

Create `70_Research/<topic>/sources/<topic>-sources.md`. This section MUST exist in it before
the first query, and every field MUST be filled:

```markdown
## Search plan
- **Effort tier:** simple (3–10 calls) | comparison (10–15) | complex — say why
- **Budget:** N calls. A call is any network operation made for this research, by this
  session or a subagent it starts: a search, a page read, or an API request. Each request
  counts, however many a single shell command makes. Local reads and reading a credential
  from the vault are not calls
- **Ideal source:** what the thing that actually answers this would be
- **Tools available:** every tool, built-in or MCP, that this session has and that searches,
  fetches, scrapes or reads web or research content, by its exact listed name and with its
  rung, whether or not it will be used, read from the session's own tool list, including deferred tools listed by name only; every
  connector
  the session reports as failed or unauthenticated, with that status; and any tool
  `known-apis.md` names that is missing
- **Sub-questions:** the concepts this breaks into, named
- **Synonyms:** per concept — OR within a concept, AND across them
- **Row match, per sub-question:** the row of `known-apis.md` whose subject covers it, named
  exactly as that file names it — or the literal words "no row matches"
- **Route, per sub-question:** the rung, and the source called first. Where a lower rung is
  not used, the checked fact that rules it out
- **Limits:** for each source in Route, its rate limit and its batching rule, copied from
  `known-apis.md` as written. Write "not documented" for either one that file omits, and for
  both where it states neither
```

**The plan is correctable and MUST be corrected when it turns out to be wrong.** A field is
revised by appending a line beginning `Revised:` giving the date, what changed and why. The
original text MUST remain. A plan known to be false SHALL NOT be left standing.

A `Revised:` line MUST be written when the route changes, not gathered up at the end.
Moving to the next source in a chain is such a change, and that source's limits MUST be
appended before it is called. **Revising is a record, not a permission.** A `Revised:` line
moving a route to a higher rung MUST state the failure, exhaustion, coverage gap or hook denial
that permits it under *Moving up a rung* below. Convenience SHALL NOT be a stated reason.

### Row matching

**Row matching MUST be mechanical rather than a judgement call.** Every sub-question MUST be
compared against every row of every source table in `known-apis.md`, not only the
fallback-chain table. A row covers a sub-question where that row's subject names the kind of
thing being asked for. Where it is arguable, the row MUST be treated as covering it. Where
more than one row covers it, the more specific MUST be used; where equally specific, the one
listed first. The matched row MUST be written in Row match.

Where no row covers it, the literal words "no row matches" MUST be written.

A provider's own documentation MUST be read before its first use where `known-apis.md` has no
row for it, and a row MUST then be added. **A row added during this session MUST NOT name a
scraping service as its first source.** An API SHALL NOT be probed to discover its limits;
limits are read from documentation.

Rationale: every row in that file was written after a mistake, and a pointer to a file is not
a reading of it. Omitting the sub-questions and synonyms produces the signature failure, which
is the same sub-question asked five times in slightly different words.

Where a sub-question is answered by searching, broad queries MUST precede specific ones.
A single lookup of a known identifier is not a search and needs no broad query first.

## The ladder

| Rung | Use it for |
|---|---|
| Local | Files on disk, `--help`, `man`, installed documentation, the vault |
| API or MCP | A documented API or an MCP tool |
| Paced fetch | One fetch to a site at a time, spaced as set out below |
| Scraping service | Anti-bot walls, JavaScript-rendered pages, real volume |

**Cheapest means lowest in this table.** It is rung order and nothing else — not money, not
latency, not the number of calls, not convenience. The lowest rung that can answer the
sub-question MUST be used.

**Rung MUST be assigned by what a tool is, not by how it is reached.** Firecrawl and Bright
Data, and every tool either exposes — including their paper-search and research tools — MUST
be recorded as the scraping-service rung however they are called, whether through MCP, an SDK
or a plain URL. Any other provider whose product is fetching or extracting pages on your
behalf MUST be recorded the same way. Reaching a scraper through MCP SHALL NOT be treated as
the API-or-MCP rung.

**Web search finds addresses; it does not answer.** `WebSearch`, and any other tool that
returns a list of results rather than a page or a record, MUST be recorded on the API-or-MCP
rung, and each search is a call. A result's snippet SHALL NOT be cited as answering a
sub-question; the page or record it points to is what answers, reached by the rules below. A
scraping service's own search tool SHALL NOT be used as a web search. Where the Row match is
`Arbitrary web content` or "no row matches", a web search whose results do not themselves
answer the sub-question counts as a coverage gap for *Reading a page*, and an address it
returned MAY be written in Route as the page to read.

**Rungs three and four are both "read a web page", and their order is inverted on purpose.**
Where a sub-question can only be answered by reading a page, a scraping service MUST be used
in preference to a paced fetch. This is the sole exception to the rung order, it applies
between these two rungs only, and it MUST NOT be read as licensing either in place of the
API-or-MCP rung. That a page must be read is a claim that MUST rest on named sources that were
called and what they did not return.

Rationale: a paced fetch leaves from the user's home connection and a scraping service leaves
from its own, and a flagged home address is the problem this skill exists to prevent.

What this session actually has MUST be checked rather than assumed, because connectors fail,
need authentication, or are scoped elsewhere. The check MUST be recorded in the plan's Tools
available field, and that record is the evidence cited when a tool is exhausted as absent. Where a specialised tool on the API-or-MCP rung
exists for the question, it MUST be preferred over a generic search. Where an expected tool is missing, that
MUST be said in the reply rather than covered by quietly falling back to scraping.

## Moving up a rung

**This section is the only thing that permits a higher rung. Nothing elsewhere grants it.**

Apart from the documentation read in *Reading a page*, a higher rung MUST NOT be used for a
sub-question until all three hold, and each MUST be
recorded in the plan or the queries table:

1. **Row matching is done**, as above. Calling the matched row's own first source is not
   moving up a rung; the conditions govern what comes after it.
2. **Every callable source in the matched row's chain has been called for this sub-question**,
   and each has failed, been exhausted, or returned a coverage gap, as defined below.
3. **Every lower rung has been called for this sub-question, or ruled out by a checked fact.**
   Within condition 3, the one standing exception is the paced-fetch rung: where the inversion in *The ladder*
   applies, that rung is ruled out by the inversion itself and MUST NOT be called. This is the
   only rule outside this section that discharges a condition, and it discharges only this one.
   A call made for a different sub-question does not count. Reading `known-apis.md`, which
   every run requires, SHALL NOT be counted as having called the Local rung. "There is
   probably no API for this" is a prediction and SHALL NOT be written; a checked fact names
   what was checked and what came back.

**Where the matched row's own first source is a scraping service** — true of `Arbitrary web
content`, and of any row whose first cell names one — condition 2 is replaced, not waived.
The API-or-MCP rung MUST first be attempted for that sub-question to the same standard:
called, and failed, exhausted, or returned a coverage gap, as defined below. The source attempted MUST be one that
plausibly covers the sub-question's subject. Calling an unrelated endpoint, or one chosen
because it is keyless and convenient, SHALL NOT satisfy this. Only then may the scraper be used, and
Route MUST record both. The same applies where Row match is "no row matches". These are one
condition under two names: no row named a real source for the subject.

Neither "no row matches" nor "no subject row names an endpoint for this" is a checked fact
that rules out the API-or-MCP rung. Both state the condition that obliges the attempt, and
they cannot also excuse it.

**A callable source** is a cell naming an endpoint or a tool. Cells reading `—`, "single
source, say so", or a caveat about which source not to use are not sources and MUST NOT be
called. Where a cell says a named source is wrong for this case, it MUST be skipped. A cell
that can only be read as a page — a scraper, "paced direct fetch", "the project's own docs" —
is not a callable source for condition 2. It is what *Reading a page* below reaches. Where a
project's docs are published in a GitHub repository, the GitHub contents API, or GraphQL for
several files at once, is the callable source for them and MUST be called before any page of
those docs is read.

The chain MUST be walked only when escalating: where the first source answers the
sub-question, nothing further is called. Chain calls MUST count against Budget, and where
walking a chain would exceed it, Budget MUST be revised rather than quietly overrun.

### Failure

**Failure MUST mean exactly one of two things**, and nothing else counts:

- an HTTP status of 4xx or 5xx, other than 429 and other than a 404 that counts as a coverage gap
  below, from a request whose shape follows the guidance for that source in
  `known-apis.md`. A 500 caused by a shape that file warns against is a malformed request and
  SHALL NOT be recorded as a failure;
- a response that is an anti-automation challenge, whatever status it carries, including a
  challenge page served with HTTP 200.

A failure MUST be observed in this session and quoted in the queries table. A failure recorded
in `known-apis.md` is not one that counts here. Where that file records a source as gated
against automation, that source MUST be skipped rather than called. The skip counts as
exhaustion only where the row was in the file before this session began, recorded by citing
it. A gated row added during this session counts only where it quotes a challenge observed in
this session, which is already a failure.

**A coverage gap is not a failure.** Where a source answers correctly that it does not hold
what was asked — a 404, or zero results, under the conditions below — that is a coverage gap,
whatever the response shape and whatever endpoint was used. A coverage gap MUST be recorded as
one, and it moves the chain on to the next callable source exactly as a failure does. It
SHALL NOT be recorded as a failure.

A record returned without the field asked for — an empty `fullText`, or `is_oa: false` — is a
coverage gap. A 404 counts as a coverage gap only for an identifier in the form the source's
documentation, or its row in `known-apis.md`, says it takes, cited in the queries table. Zero results count only for a query that used the plan's synonyms for that concept. Results
none of which concern the subject asked about count the same way as zero results, under the same
synonym condition, and only with the returned titles quoted in the queries table as the evidence. A
gap produced by a wrong identifier or a narrow query is a malformed request, and SHALL NOT be
recorded as a gap.

A 429 or any other rate-limit response is **NOT** a failure. It is a pacing signal. Slow
responses, partial results and merely unhelpful results are NOT failures and SHALL NOT be
recorded as such.

### Reading a page

Where every callable source for the sub-question — the matched row's chain, or the plausibly
covering API attempts of the replacement rule — has been called and each ended in failure,
exhaustion or a coverage gap, that record is the checked fact that the answer lives only on a
page. A page MAY then be read, and only then, apart from the documentation read below:

- the page MUST be a specific one, its address written in Route before it is read. A scraping
  service SHALL NOT be used to search;
- the inversion in *The ladder* decides the rung: a scraping service, not a paced fetch.

**A provider's own API documentation is the one page that may be read before its API is
called**, because the API cannot be called correctly without it. It MUST first be sought
locally or through an API where it is published there, such as a repository read through the
GitHub contents API. Where it is not, one named documentation page MAY be read through a
scraping service without conditions 2 and 3, before the first call to that API, and for no
other purpose. That read is allowed only where the provider has no row in `known-apis.md`, its
API is already named in Route for a sub-question, and the local or API search for its
documentation is recorded in the queries table. The page SHALL NOT be cited as answering any
sub-question; it tells you how to call the API, and the API call is what answers.

### Exhaustion

**Exhausted is not failed, and both let the chain move on.** A source is exhausted where it
returns 429 after its documented wait has been honoured, where its allowance for the period is
spent, where it needs a credential that is not held, or where it is a tool absent from this
session, checked against the session's own tool list. Which of the four MUST be recorded,
and each MUST carry evidence quoted in the queries table rather than asserted: the 429 and its
timing, the response that states the allowance is spent, or the failed attempt to read the
credential from the vault, or the tool list that lacks it. Where `known-apis.md` records a key as held, "credential not held"
SHALL NOT be written without that attempt.

**A self-set ceiling is not exhaustion.** Where a stated ceiling binds, it MUST be revised in
the plan or the sub-question stops there, and it SHALL NOT be used to unlock a higher rung.

Where a source documents no wait, the pacing rule below supplies one.

**Where a limb's evidence cannot be obtained** — an allowance with no header that reports it,
a credential whose name is unknown — the source MUST be called and whatever it returns
recorded as failure or pacing under the definitions above. The sub-question is not blocked,
and a limb MUST NOT be asserted in place of the call.

A scraping service MUST NOT be used as a general-purpose substitute for a source that answers
the question in one request.

## Pacing

Every number is exact and matches the hook's constants. Prose and code MUST agree, so neither
is changed without the other.

**The hook is a backstop, not the rule.** It inspects only `WebFetch` and Firecrawl's scrape
tool. For those it enforces the per-site gap, one fetch in flight and the error cooldown. It also
stops a site at 300 fetches, but through a defect it never resets that count by date, so a site
that reaches 300 stays locked. Its redirect — first direct fetch allowed, a second within six
hours denied — fires only for rows of `known-apis.md` whose first cell's first backticked domain is a
registered domain, which at present means `github.com`, `arxiv.org` and `dblp.org`; every other listed
host is compared wrongly and never matches. It does not see searches, `curl` or any
other shell command, other MCP tools, or pages already read, and whether its check for subagents
works is unverified: it looks for payload keys no main-session call carries, and no subagent
fetch has been recorded to show what a subagent's call carries. Every rule in this file MUST therefore be followed whether or not the hook
would catch a breach of it. Where the hook allows something this file forbids, this file
governs, and a call SHALL NOT be treated as permitted because the hook let it through.

Searches have no site to pace against, so the hook cannot govern them. Each search MUST count
against Budget and searches MUST be made one at a time. The same query, compared after
lowercasing and collapsing whitespace, SHALL NOT be sent to the same tool twice in a session,
except as a retry the pacing rules permit, which takes its own row. A further query to the same tool
for the same sub-question, other than a permitted retry, MUST add or drop a plan synonym or concept, named in its row.

- Subagents SHALL NOT be spawned to search in parallel. That is the pattern that flags an
  address.
- Pacing MUST be measured per site, not across the session.
- Before fetching a site again, the wait MUST be **ten times the duration of the last fetch to
  that site**, floor **1 second**, ceiling **120 seconds**. Rationale: a slow response usually
  means a loaded server, so this backs off when it matters, which a flat delay cannot.
- At most **one** fetch to a site SHALL be in flight at a time.
- After **5 consecutive errors** from a site, it SHALL NOT be fetched again for **4 hours**.
- At most **300** fetches to one site in a day; a 301st SHALL NOT be made.
- At most **3** attempts per request; a 4th SHALL NOT be made. Retries MUST stay below a tenth
  of all requests.
- On HTTP 429 the request SHALL NOT be retried immediately.
- Switching endpoint on a provider does not reset its rate limit and SHALL NOT be used to get
  around one. Where a provider states a per-second limit across all endpoints, different
  endpoints draw on the same allowance.
- Where a batch endpoint exists, identifiers SHALL NOT be fetched one at a time in a loop.
- `robots.txt` MUST be respected, and where `Crawl-delay` is present the longer of it and the
  gap above MUST be used. Rationale: RFC 9309 left `Crawl-delay` out, so it is a convention
  rather than a standard. That does not make it optional here.
- Billable calls MUST have a ceiling stated before the first one.

A rate limit, spent credit or bot wall on one source SHALL NOT end the sub-question. The next
callable source in the chain MUST be tried, and the source that actually answered MUST be named,
because coverage differs between them.

An HTTP status SHALL NOT be used to infer the state of an account. Where the state of a key
matters, it MUST be tested directly.

A hook denial means the approach was wrong, not that the hook is in the way. It MUST be
answered by stepping back down the ladder. A block SHALL NOT be routed around.

Reasoning and sources in `70_Research/client-side-rate-limiting/`.

## Red flags — stop

**Each line below is a stop condition. Where one is true, the action SHALL NOT be taken until
the reason it is true has been resolved.**

- About to spawn subagents that will each search
- About to retry something that just returned 429
- About to fetch a domain that the *Fetch these a different way* table redirects, other than a
  read its row explicitly permits
- About to fetch a page already read this session, or written up in `70_Research/`, other than
  one re-read per page, recorded in Route with what the earlier summary lacks
- About to report a number whose only source has a stake in it
- About to call it complete when what actually happened is the budget ran out
- About to call an API whose limits are not written in the search plan
- About to loop over identifiers one at a time where a batch endpoint exists
- About to explain a 429 by guessing at the account rather than reading the documented limit
- About to probe an API to find out what its limits are
- About to use a scraping service before conditions 1 to 3 above are all recorded, other than
  the one documentation read *Reading a page* permits
- About to reach a scraper because the matched row happens to name one first
- About to add a row whose first source is a scraper
- About to treat a row match of "no row matches" as permission rather than an obligation
- About to revise a Route upward because the planned rung was awkward
- About to record zero results or a 404 for an item not held as a failure
- About to use a scraping service to search rather than to read one named page
- About to assert exhaustion without quoting the evidence
- About to work around a denial instead of stepping down a rung

## Before answering

The synthesis note MUST end with this section, and every field MUST be filled:

```markdown
## How far this went
- **Calls:** how many were made against the Budget, counted from the queries table
- **Why I stopped:** the question was answered; or saturation, meaning a full round that added
  nothing new; or the cap. Say which. Where it was none of those, say what it actually was
  rather than choosing the nearest.
- **Rungs used:** which rungs answered which sub-questions, and anything routed above the
  lowest rung that could have answered it
- **Single-sourced:** the load-bearing claims with no second, independent source
- **Disagreement:** where it is; or that the only numbers are the vendor's or the inventor's
```

An early stop SHALL NOT be presented as a complete one. That is the failure this skill exists
to prevent.

## Storage

Exactly two files:

```
70_Research/<topic>/<topic>.md                    the synthesis
70_Research/<topic>/sources/<topic>-sources.md    the sources
```

The sources file MUST go inside `sources/`. Sources MUST be summarised with attribution.
Third-party text SHALL NOT be pasted into the vault. Findings MUST be written as they arrive.

The sources file carries `## Search plan`, then:

```markdown
## Queries run
| Date | Sub-question | Query | Rung | Tool | What it returned |
```

A row MUST be appended immediately after each call, not gathered up afterwards. A single
command that makes several requests MUST take one row, appended when it returns, and that row
MUST state how many requests it made; that number counts against Budget and in Calls. Sub-question
MUST name the sub-question from the plan, or several where one call served more than one, in
which case the call counts for each of those sub-questions but once against Budget.
Rung MUST record the rung actually used, so Route
and reality can be compared line by line. Where they differ, Route MUST carry a `Revised:`
line. Then a paragraph per source saying what it contributed and where it has an interest.

A note MAY be deleted where that folder's README permits it. The note and the reason MUST be
named in the reply where it happens. A deletion SHALL NOT be silent.

`methodology.md` has the techniques: chaining, the unindexed layer, saturation, weighing
sources. `known-apis.md` has the chains and the per-provider limits. `keys.md` says which keys
exist, what each unlocks, and how to read it from the vault with `bw get`.
