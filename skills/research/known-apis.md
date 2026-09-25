# Known APIs and local sources

**MUST, MUST NOT and SHALL NOT in this file are absolute, exactly as they are in `SKILL.md`.**
Everything else here is rationale or reference, and rationale never weakens a requirement.

## Hitting a limit is not a reason to stop

Most questions have several sources that can answer them. When one rate-limits, returns 429,
or runs out of credit, **move down its chain and keep going**. Say in the write-up which
source actually answered, because they differ in coverage.

| The question | First | Then | Then |
|---|---|---|---|
| Vulnerabilities in a package | OSV (no key, no limit) | NVD (5/30s, 50 with key) | GitHub advisories (60/hr, 5,000 with token) |
| Will this CVE be exploited | EPSS (no key) | — | single source, say so |
| Certificates for a domain | crt.sh (no key, no limit) | Censys (250/month, key) | — |
| Is this address hostile | Shodan InternetDB (no key) | GreyNoise (50/day) | AbuseIPDB (1,000/day, key) |
| Papers on a topic | arXiv (no key, 1 per 3s) | Semantic Scholar (key, 1/s) | OpenAlex, then Crossref |
| Who cites this paper | Semantic Scholar (key) | OpenCitations, then Crossref | **Not OpenAlex for arXiv preprints — see below** |
| Can I actually read this paper | `openAccessPdf` from Semantic Scholar | Unpaywall (email only) | CORE, which already holds the text, then the arXiv version |
| What is being read now | HF `daily_papers` (no key) | HF models by trending | — |
| Package facts | The registry itself | OSV for its vulnerabilities | jsDelivr for its contents |
| Support lifetime | `endoflife.date` (no key) | — | single source, say so |
| How do I use this thing | `context7`, once fixed | Stack Exchange API (no key) | the project's own docs |
| **Arbitrary web content** | **Firecrawl (credits)** | **Bright Data free tier (5,000/month)** | **paced direct fetch** |

**The last row is the fallback of last resort and MUST NOT be matched first.** It is reachable
only for a sub-question that none of the rows above it covers. Matching it to a question that
a subject-specific row already answers turns it into a standing exemption from the ladder,
which is exactly how ten scraper calls got made on a question about academic papers.

Within that row, the ordering is deliberate and is the one case where the scraping rung is
preferred to a direct fetch: a direct fetch leaves from the home connection and a scraping
service does not. It used to be the row that ended a research pass. Its cells are page reads, so they are
reached through *Reading a page* in `SKILL.md`, never by walking the chain, and the paced
direct fetch in it SHALL NOT be used while a scraping service is available.

**A key is a pathway, not an optimisation.** An unkeyed NVD gives 5 requests per 30 seconds
and a free key gives 50. That is the difference between a question being answerable and not.

A growing cache, not a fixed list. When you discover that a site has a documented API or
that its content ships locally, add a row. The pacing hook reads this file live to redirect
fetches, so a redirect row added here takes effect in the hook at once. That only ever makes
the rules stricter. For everything else, `SKILL.md` applies the file as it stood when the
session began.

Seeded 2026-09-24 from the domains most fetched across past sessions.

## Fetch these a different way

**A domain in this table SHALL NOT be fetched directly. The route in "Use instead" MUST be
taken,** except where the row's Notes name a permitted read through *Reading a page* in
`SKILL.md`, and then only that read. A permission counts only where it was in the row before
this session began.

| Domain | Use instead | Notes |
|---|---|---|
| `github.com` | The GitHub REST API at `api.github.com`, authenticated, or for several files or repositories at once, GraphQL at `api.github.com/graphql` | 254 fetches in past sessions. `gh` is **not** installed (checked 2026-09-24), so use `curl`. Authenticate with the research token — see below |
| `docs.github.com` | The same API, for anything about the API itself | 87 fetches |
| `raw.githubusercontent.com` | `api.github.com/repos/{owner}/{repo}/contents/{path}`, or for several files at once, GraphQL at `api.github.com/graphql` | 29 fetches. Read it through the contents API rather than fetching the raw file directly |
| `docs.ansible.com` | `ansible-doc <module>` in the dev container | 81 fetches for documentation already on disk |
| `docs.digitalocean.com` | DigitalOcean API, token in the lockbox | 80 fetches |
| `arxiv.org` | arXiv API at `export.arxiv.org/api/query` | No key needed. The API carries no body text. Where full text is needed and every other source is spent, one read of `arxiv.org/pdf/<id>` through *Reading a page* in `SKILL.md` is permitted |
| `api.semanticscholar.org` | Same endpoint, authenticated | Send the key: `bw get password 'Semantic Scholar API key'`, as an `x-api-key` header |
| `developer.hashicorp.com` | `terraform -help`, `packer -help` for installed versions | 40 fetches |
| `en.wikipedia.org` | Wikipedia API at `/w/api.php` | Returns clean extracts |
| npm package contents | `data.jsdelivr.com/v1/packages/npm/<pkg>@<version>?structure=flat` | Lists what is actually *inside* a published package. Browsing the repository cannot answer this, because built output is usually not committed. Added 2026-09-24 |

## Local first — no network at all

**Where a question appears in this table, the local route MUST be used first, and no network
call SHALL be made for what it answers.** Where it does not answer — a second pass on a topic
researched before, or an estate fact the vault does not hold — the ladder continues upward.

| Looking for | Where it already is |
|---|---|
| Ansible module behaviour | `ansible-doc <module>` |
| Command flags and options | `<cmd> --help`, `man <cmd>` |
| systemd unit directives | `man systemd.unit`, `man systemd.service` |
| Anything researched before | `70_Research/` in the vault, and past session transcripts |
| Estate facts — what a machine runs, what was decided | The vault. Read it before asking the internet |

That last row is the one most often skipped. Questions about this estate are answered by
the project notes and the operational manual, not by a search engine.

## Open APIs worth reaching for directly

All of these were called from this machine on 2026-09-24 and returned real data with no key,
unless a key is noted. They are a better first move than a search, because they answer a
precise question in one request instead of returning pages to read.

**Security and the estate**

| What you want | Endpoint | Notes |
|---|---|---|
| Every TLS certificate issued for a domain | `crt.sh/?q=<domain>&output=json` | No key, no limits. Verified: 90 records for `keepbreath.ing` |
| Vulnerabilities in a package | `api.osv.dev/v1/query`, POST a package and ecosystem | No key. Covers PyPI, npm, Go, Rust and more |
| One CVE, or CVEs by product | `services.nvd.nist.gov/rest/json/cves/2.0` | No key at 5 requests per 30s; a free key raises it to 50 |
| Likelihood a CVE gets exploited | EPSS, from FIRST | No key, updated daily |
| Whether an address is mass-scanning or targeting you | GreyNoise | 50 a day without a key |
| Address reputation | AbuseIPDB | 1,000 a day, free key |
| Ports and known issues for an address | Shodan InternetDB | No key, no limits |
| Domain registration facts | RDAP | No key. The JSON replacement for WHOIS |
| Adversary techniques | MITRE ATT&CK, full dataset on GitHub | No key |

**Papers, for the masters**

| What you want | Endpoint | Notes |
|---|---|---|
| New preprints in a category | `export.arxiv.org/api/query` over **HTTPS** | No key, one request per three seconds. `http://` returns a 301. `search_query=cat:cs.CR+AND+cat:cs.LG` is the security-and-machine-learning overlap |
| Citation counts, references, who cites what | `api.semanticscholar.org/graph/v1/...` | **Key held** — `bw get password 'Semantic Scholar API key'`, sent as `x-api-key`. One request a second. The `openAccessPdf` field says whether a paper is readable before a fetch is spent finding out |
| An open catalogue of works and citations | `api.openalex.org/...?api_key=` | Key held: `bw get password 'OpenAlex API key'`. **A URL parameter, not a header.** $1 a day; lookups by DOI free and unlimited, filters $0.0001, searches $0.001. Spend comes back in `x-ratelimit-remaining-usd` |
| Metadata for anything with a DOI | `api.crossref.org` | No key, around 180 million works |
| A free legal copy of a paywalled paper | `api.unpaywall.org/v2/<doi>?email=<you>` | No key, just an email in the query. Returns the best open-access location if one exists |
| How many times a paper has been cited, openly | `opencitations.net/index/api/v1/citation-count/<doi>` | No key. An open citation graph, independent of the commercial ones |
| Internet standards and drafts: status, abstract, working group | `datatracker.ietf.org/api/v1/doc/document/?format=json&<field>__<lookup>=` | No key. Read-only tastypie API; one document is `/api/v1/doc/document/<draft-name>/`. Documentation is `ietf/templates/api/index.html` in `ietf-tools/datatracker`, read through GitHub. No rate limit documented, so the skill's default pacing applies. Added 2026-09-25 |
| Datasets and software, not just papers | `api.datacite.org/dois?query=` | No key. Where a dataset or a code release with a DOI lives |
| **What a paper actually says**, not what its abstract claims | `api.core.ac.uk/v3/search/works/` | Key held: `bw get password 'CORE API key'`, `Authorization: Bearer`. Full body text in the `fullText` field. See the notes below |
| Which author is which | `pub.orcid.org/v3.0/expanded-search/?q=` | No key, send `Accept: application/json`. Disambiguates people with the same name |

**OpenAlex is priced per operation** and a key is required since February 2026. A free key
gives $1 of usage a day with no payment method: unlimited single lookups by DOI, 10,000
list-and-filter calls, or 1,000 searches. Prefer a single lookup where one will do, because
those are free and unlimited. Usage comes back in a remaining-budget response header.

**Both header names are real, read off a live response on 2026-09-25.** `x-ratelimit-remaining`
is a count of calls left (9989 of a `x-ratelimit-limit` of 10000) and `x-ratelimit-remaining-usd`
is the dollar balance left (0.9989 of 1). `x-ratelimit-cost-usd` gives the cost of that one call,
and `x-ratelimit-reset` the seconds until the daily reset. Quote `x-ratelimit-remaining-usd` as the
evidence that the allowance is spent.

**Semantic Scholar efficiency, which still applies with the key.** Their documentation states
that an individual key "automatically gives a user a 1 request per second rate **across all
endpoints**", and that some users may be granted slightly more. Two things follow. The second
of a pair of back-to-back calls fails whatever it asks for, and **switching endpoint does not
buy a fresh allowance** — a metadata lookup and a citations lookup draw on the same one per
second. So the shape of the request matters more than the rate:

- **Batch instead of looping.** `POST /graph/v1/paper/batch` takes a list of identifiers and
  returns them all in one response, mixing `arXiv:1611.01236` and `DOI:10.1145/...` freely. It also
  accepts `citations`, `references` and `authors` as fields, so one batch request can chain from
  many papers at once.
- **Exponential backoff is required, not optional.** Their API release notes (`allenai/s2-folks`,
  `API_RELEASE_NOTES.md`, from March 2024 onwards): "we now require the use of exponential backoff
  strategies for API requests. When a request fails, particularly due to rate limiting, ...
  systematically increasing the delay before retrying." A fixed retry delay does not comply. New
  keys get 1 RPS on all endpoints. Abstracts of Springer papers are withheld by agreement, and
  holding multiple keys is discouraged. Read 2026-09-25.
- **Bulk instead of relevance search.** `/paper/search/bulk` returns far more per response
  than `/paper/search`.
- **Ask for fewer fields.** More fields means a slower response.
- **If the rate is ever the binding constraint**, their documented answer is to download the
  dataset through their Datasets API and query it locally rather than to keep calling.

Source: their API tutorial at <https://www.semanticscholar.org/product/api/tutorial>, section
"How to make requests faster and more efficiently". Read 2026-09-24.

**Observed 2026-09-25, not explained.** The first two Semantic Scholar requests of a session,
both `POST /graph/v1/paper/batch` with 20 ids and more than a minute apart, returned `429` with
`x-amzn-errortype: TooManyRequestsException` and no `Retry-After`, while the key was confirmed
present (44 characters, vault unlocked). Under the skill that is exhaustion. What caused it is
unknown: the batch endpoint's documented limits need reading, and the key's state testing
with a single `GET`, before anyone concludes either.

**Key tested 2026-09-25, later the same day:** a single `GET /graph/v1/paper/{id}` with the same key
returned `200` in 0.34s. The key works. Whatever produced the 429s was specific to the batch
endpoint or to that moment, and the batch endpoint's own limits are still unread.

**How to tell the three failures apart, measured 2026-09-24.** An invalid key returns `403`.
No key at all returns `429`, because unauthenticated traffic shares one key with everybody and
that pool is saturated. A working key returns `200`. The three are distinguishable in one
test, so **never infer the state of the account from a `429`** — check it. A `429` while
sending a valid key usually means the calls were too close together, except as observed below.

`openAccessPdf` MUST be checked before fetching a paper — or, where Semantic Scholar is recorded as failed, exhausted or as a coverage gap, Unpaywall's open-access result instead; where both are recorded as failed, exhausted or as a coverage gap, that record discharges the check — so a fetch is never spent discovering that it
is paywalled.

**Attribution.** The data is CC BY-NC, so non-commercial, and anything published from it must
credit Semantic Scholar.

**CORE is the only source here that returns the body of a paper.** Everything else gives
metadata and a link. That makes it the answer to questions about method rather than topic —
searching abstracts finds papers *about* a technique, searching full text finds papers that
*used* one.

```bash
export BW_SESSION="$(cat "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/bw-session")"
KEY=$(bw get password 'CORE API key')
curl -sL -H "Authorization: Bearer $KEY" -G \
  --data-urlencode "q=adversarial examples neural networks" --data-urlencode "limit=3" \
  "https://api.core.ac.uk/v3/search/works/"
```

Three things learned the hard way on 2026-09-24:

- **It is a GET with a trailing slash.** Without the slash you get a 301; as a POST with a
  JSON body you get a 500. POST is only for aggregations.
- **Some query shapes return 500, including CORE's own documented `arxivId` example.** Plain
  keywords and simple field queries work. Build up from something simple rather than
  starting with a complex boolean.
- **Failed calls do not consume tokens**, so a 500 costs nothing but time.

The academic tier gives 5,000 tokens a day at 10 a minute; a simple query is one token, and
bulk or scroll queries three to five. Not every result carries text — check the `fullText`
field is non-empty before relying on it. They ask to be cited in published work.

**OpenAlex behaves differently from the other keys in two ways worth remembering.**

It goes in the URL as `?api_key=`, not in a header, so it ends up in shell history and in
server logs. A command containing it SHALL NOT be pasted anywhere that gets kept.

And it is priced per operation rather than rate limited, so the cheap path matters:

```bash
# free and unlimited — a single record by identifier
curl "https://api.openalex.org/works/doi:10.1145/3128572.3140448?api_key=$KEY"

# $0.001 each — a search. 1,000 a day inside the free dollar
curl "https://api.openalex.org/works?filter=title.search:...&api_key=$KEY"
```

Reach for the lookup whenever an identifier is already known. Every response carries
`x-ratelimit-remaining-usd`, so the budget can be read without a separate call.

**The whole corpus is also public on S3**, which is why paying for the API is not lock-in. It
is far too large for this estate; the reasoning is in `70_Research/research-apis/`.

**Models and datasets**

| What you want | Endpoint | Notes |
|---|---|---|
| What models exist, by name or task | `huggingface.co/api/models?search=` | No key |
| What datasets exist | `huggingface.co/api/datasets?search=` | No key |
| What the community is reading now | `huggingface.co/api/daily_papers` | No key. This is the trending digest, as data rather than a page to scrape |
| Which models are servable, and their pricing | `openrouter.ai/api/v1/models` | No key |
| Which models run locally in one command | `ollama.com/api/tags` | No key |

**Packages, docs and operations**

| What you want | Endpoint | Notes |
|---|---|---|
| Everything about a Python package | `pypi.org/pypi/<pkg>/json` | No key |
| Everything about an npm package | `registry.npmjs.org/<pkg>/latest` | No key |
| Everything about a Rust crate | `crates.io/api/v1/crates/<name>` | **Requires a `User-Agent` header** naming you and a contact address. Returns 403 without one |
| Questions and answers on a technology | `api.stackexchange.com/2.3/` | No key. Works even though the site will not accept a new account from this address |
| When software stops being supported | `endoflife.date/api/<product>.json` | No key. Answers the question for every product on the estate — AlmaLinux 10 ends 2035-05-31 |
| Advisories by ecosystem | `api.github.com/advisories` | Works unauthenticated, but send the research token anyway for the higher limit |
| Odds a CVE gets exploited | `api.first.org/data/v1/epss?cve=<id>` | No key |
| Who registered a domain | `rdap.org/domain/<domain>` | No key, but returns a 302 — follow redirects |

**Bright Data, the third rung for web content.** When Firecrawl credits are gone or a page
defeats it, this reads the page from Bright Data's infrastructure rather than this
connection — verified, the exit was a datacenter ASN.

```bash
export BW_SESSION="$(cat "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/bw-session")"
TOKEN=$(bw get password 'Bright Data API key')
curl https://api.brightdata.com/request \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"zone":"bright_data_agent","url":"<the page>","format":"raw"}'
```

The zone name `bright_data_agent` is required in every request body. 5,000 requests a month
are free; past that the plan bills at $1.50 per thousand, so the free allowance is worth
about $7.50. It MUST be treated as the scarce rung: it is for pages the cheaper routes could not get, and
it SHALL NOT be used as a default.

**Authenticating to GitHub.** Always use the research token:

```bash
export BW_SESSION="$(cat "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/bw-session")"
TOKEN=$(bw get password 'GitHub read-only token')
curl -H "Authorization: Bearer $TOKEN" https://api.github.com/repos/OWNER/REPO
```

**GraphQL is GitHub's batch endpoint.** One `POST https://api.github.com/graphql` with the
research token can fetch several repositories' README text, directory trees and named files by
aliasing `repository(owner:,name:){ object(expression:"HEAD:path"){... on Blob{text}} }`. On
2026-09-25, eleven repositories' READMEs and trees cost 1 point of 5,000, and so did a request for
six files across three repositories. A guessed path returns `null`, which is a malformed request,
not a coverage gap. Use it instead of fetching files one at a time.

It raises the limit from 60 requests an hour to 5,000, and it can only read public data —
verified on 2026-09-24 as returning 404 on a private repository.

**The master API token SHALL NOT be used for research.** It exists for deployment and infrastructure
and is scoped for that on purpose. Research touches more third-party surface than anything
else here, so it is the activity most likely to expose a credential; the one it exposes
should be the one that can only read public repositories.

**Detection content is repositories, not APIs.** SigmaHQ carries over 3,000 peer-reviewed
detection rules, and MITRE publishes the Cyber Analytics Repository and the ATT&CK dataset.
These change daily, so cloning once beats fetching repeatedly.

## Gated against automation

Recorded so time is not wasted rediscovering it. **A source in this table MUST be skipped
rather than called, and the skip counts as exhaustion only as the *Failure* section of `SKILL.md` allows.**

| Source | Problem | Use instead |
|---|---|---|
| `lore.kernel.org` | Anubis proof-of-work challenge, will not load | LWN mirrors the netdev cover letters |
| `dblp.org` API | Returns a bot challenge page with HTTP 200, even with a `User-Agent` identifying us. Tested 2026-09-24 | Their bulk XML dump for automated use; OpenAlex or Crossref for one-off lookups |
| OpenAlex, for citation chaining on arXiv preprints | Returned the record with a correct title and date but `referenced_works` empty and `cited_by_count` zero, on three 2025–2026 preprints. For one of them Semantic Scholar returned 25 parsed references for the same paper, so the gap is OpenAlex's rather than the papers'. Observed 2026-09-24; not checked against OpenAlex's own documentation, so treat it as an observation rather than their stated behaviour | Semantic Scholar for citation links. OpenAlex is still right for metadata lookup by DOI, which is its free unlimited case |

## Adding a row

When a fetch would have been avoidable, a row MUST be added before moving on. The point of the file
is that the next session does not repeat the fetch, and which domains matter changes with
whatever is being built that month.
