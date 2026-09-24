# Known APIs and local sources

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
| Who cites this paper | Semantic Scholar (key) | OpenAlex (no key) | Crossref (no key) |
| What is being read now | HF `daily_papers` (no key) | HF models by trending | — |
| Package facts | The registry itself | OSV for its vulnerabilities | jsDelivr for its contents |
| Support lifetime | `endoflife.date` (no key) | — | single source, say so |
| How do I use this thing | `context7`, once fixed | Stack Exchange API (no key) | the project's own docs |
| **Arbitrary web content** | **Firecrawl (credits)** | **Bright Data free tier (5,000/month)** | **paced direct fetch** |

The last row is the one that used to end a research pass. It should not: there are three
independent ways to read a page, and exhausting one moves to the next.

**A key is a pathway, not an optimisation.** An unkeyed NVD gives 5 requests per 30 seconds
and a free key gives 50. That is the difference between a question being answerable and not.

A growing cache, not a fixed list. When you discover that a site has a documented API or
that its content ships locally, add a row. The pacing hook reads this file to redirect
fetches, so a row added here changes behaviour everywhere.

Seeded 2026-09-24 from the domains most fetched across past sessions.

## Fetch these a different way

| Domain | Use instead | Notes |
|---|---|---|
| `github.com` | The GitHub REST API at `api.github.com`, authenticated | 254 fetches in past sessions. `gh` is **not** installed (checked 2026-09-24), so use `curl`. Authenticate with the research token — see below |
| `docs.github.com` | The same API, for anything about the API itself | 87 fetches |
| `raw.githubusercontent.com` | `api.github.com/repos/{owner}/{repo}/contents/{path}` | 29 fetches. Fetching the raw file directly is also fine — it is one request and no scraping |
| `docs.ansible.com` | `ansible-doc <module>` in the dev container | 81 fetches for documentation already on disk |
| `docs.digitalocean.com` | DigitalOcean API, token in the lockbox | 80 fetches |
| `arxiv.org` | arXiv API at `export.arxiv.org/api/query` | No key needed |
| `api.semanticscholar.org` | Same endpoint, authenticated | Send the key: `bw get password 'Semantic Scholar API key'`, as an `x-api-key` header |
| `developer.hashicorp.com` | `terraform -help`, `packer -help` for installed versions | 40 fetches |
| `en.wikipedia.org` | Wikipedia API at `/w/api.php` | Returns clean extracts |
| npm package contents | `data.jsdelivr.com/v1/packages/npm/<pkg>@<version>?structure=flat` | Lists what is actually *inside* a published package. Browsing the repository cannot answer this, because built output is usually not committed. Added 2026-09-24 |

## Local first — no network at all

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
| An open catalogue of works and citations | `api.openalex.org` | Returned data with no key when tested. See the caveat below |
| Metadata for anything with a DOI | `api.crossref.org` | No key, around 180 million works |

**Contested:** one source says OpenAlex began requiring keys and pricing usage above a daily
allowance in February 2026, and two others say it is free. A direct call with no key worked
on 2026-09-24. Treat the free tier as real but not guaranteed, and get a key before
depending on it.

**Semantic Scholar efficiency, which still applies with the key.** One request per second is
yours alone, but it is still one per second, so the shape of the request matters more than
the rate:

- **Batch instead of looping.** `POST /graph/v1/paper/batch` takes a list of identifiers and
  returns them all in one response, mixing `arXiv:1611.01236` and `DOI:10.1145/...` freely.
- **Bulk instead of relevance search.** `/paper/search/bulk` returns far more per response
  than `/paper/search`.
- **Ask for fewer fields.** More fields means a slower response.
- **If the rate is ever the binding constraint**, their documented answer is to download the
  dataset and query it locally rather than to keep calling.

Check `openAccessPdf` before fetching a paper, so a fetch is never spent discovering that it
is paywalled.

**Attribution.** The data is CC BY-NC, so non-commercial, and anything published from it must
credit Semantic Scholar.

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
about $7.50. Treat it as the scarce rung: it is for pages the cheaper routes could not get,
not a default.

**Authenticating to GitHub.** Always use the research token:

```bash
export BW_SESSION="$(cat "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/bw-session")"
TOKEN=$(bw get password 'GitHub read-only token')
curl -H "Authorization: Bearer $TOKEN" https://api.github.com/repos/OWNER/REPO
```

It raises the limit from 60 requests an hour to 5,000, and it can only read public data —
verified on 2026-09-24 as returning 404 on a private repository.

**Never use the master API token for research.** It exists for deployment and infrastructure
and is scoped for that on purpose. Research touches more third-party surface than anything
else here, so it is the activity most likely to expose a credential; the one it exposes
should be the one that can only read public repositories.

**Detection content is repositories, not APIs.** SigmaHQ carries over 3,000 peer-reviewed
detection rules, and MITRE publishes the Cyber Analytics Repository and the ATT&CK dataset.
These change daily, so cloning once beats fetching repeatedly.

## Gated against automation

Recorded so time is not wasted rediscovering it.

| Source | Problem | Use instead |
|---|---|---|
| `lore.kernel.org` | Anubis proof-of-work challenge, will not load | LWN mirrors the netdev cover letters |

## Adding a row

When a fetch would have been avoidable, add the row before moving on. The point of the file
is that the next session does not repeat the fetch, and which domains matter changes with
whatever is being built that month.
