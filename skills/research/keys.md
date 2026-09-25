# API keys — what to get, and where they live

Every key here is free. None needs a card. Each one turns a pathway from "sometimes
unavailable" into "usable", which is the point: a rate limit should mean switching sources,
and that only works if the alternatives are actually reachable.

## Where keys live

The same place every other secret does: Vaultwarden, read at run time with `bw get`. Never
in a file in a repository, never in an environment variable written to disk, never in a note.
This is the pattern `ansible/group_vars/all.yml` already uses for the sudo password.

Item naming, matching the existing convention of one item per thing with the name carrying
what it is for:

```
NVD API key
Semantic Scholar API key
GitHub read-only token
Bright Data zone password
AbuseIPDB API key
```

Matching the existing style in the vault, which is descriptive and unpunctuated —
`Cloudflare DNS token`, `control plane SSH key passphrase`.

**Load the session token before any `bw` call.** A Bash tool call does not inherit
`BW_SESSION`, so `bw` reports `locked` even when the vault is open. The token is on disk:

```bash
export BW_SESSION="$(cat "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/bw-session")"
bw get password 'NVD API key'
```

Only conclude the vault is locked if `bw status` still says so with the token loaded.

## Status

| Key | State | Notes |
|---|---|---|
| NVD | **Held**, in Vaultwarden as `NVD API key` | Verified 2026-09-24 by a live call. Sent as an `apiKey` header |
| Semantic Scholar | **Held**, in Vaultwarden as `Semantic Scholar API key` | Verified 2026-09-24: answers first time where the unkeyed pool took 65 seconds. Sent as an `x-api-key` header. Data is CC BY-NC and attribution is required |
| GitHub | **Held**, in Vaultwarden as `GitHub read-only token` | Fine-grained, public repositories read-only. Verified 2026-09-24: 5,000 an hour, reads public repos, 404 on private ones |
| CORE | **Held**, in Vaultwarden as `CORE API key` | Full text of open access papers. `Authorization: Bearer`. Academic tier via the Hinds address: 5,000 tokens a day, 10 a minute. Verified 2026-09-24 |
| OpenAlex | **Held**, in Vaultwarden as `OpenAlex API key` | Sent as `?api_key=` in the URL, not a header. $1 of usage a day, no payment method attached so it cannot overspend. Single lookups by DOI are free and unlimited |
| Bright Data | **Held**, in Vaultwarden as `Bright Data API key` | Zone `bright_data_agent`. Verified 2026-09-24: fetched a real page, exit was a datacenter rather than this connection. 5,000 free requests a month, $1.50 per thousand beyond that |

## Get these first — they unblock the most

| Key | Sign up at | Without it | With it |
|---|---|---|---|
| **NVD** | `nvd.nist.gov/developers/request-an-api-key` | 5 requests per 30 seconds | 50 per 30 seconds |
| **Semantic Scholar** | done — see Status above | shared pool, returns 429 quickly | 1 request per second, reliably |
| **GitHub token** | done — see Status above | 60 requests an hour | 5,000 an hour |
| **Bright Data** | done — see Status above | nothing | 5,000 requests a month |

The GitHub one matters more than it looks: 370 fetches in the recorded history were GitHub
pages, and the API is the sanctioned route for all of them.

## Worth having for security work

| Key | Sign up at | Free allowance |
|---|---|---|
| AbuseIPDB | `abuseipdb.com/register` | 1,000 checks a day |
| GreyNoise | `greynoise.io/viz/signup` | 1,000 a day registered, 50 without |
| Shodan | `account.shodan.io/register` | 100 results per search |
| VirusTotal | `virustotal.com/gui/join-us` | 500 lookups a day |
| Censys | `censys.io/register` | 250 queries a month |
| OpenAlex | done — see Status above | the polite-pool advice was stale; keys are required since Feb 2026 |

## Needs no key at all

Recorded so nobody goes looking for one: OSV, crt.sh, EPSS, `endoflife.date`, RDAP, arXiv,
Crossref, PyPI, npm, the Hugging Face Hub read endpoints, OpenRouter, Ollama, Stack Exchange,
MITRE ATT&CK, abuse.ch's feeds, and Have I Been Pwned's password endpoint.

`crates.io` needs no key but **does** require a `User-Agent` header naming a person and a
contact address, or it returns 403.

## When a key is missing

Say so and use the next source in the chain in `known-apis.md`. A missing key is a reason to
switch, never a reason to report the question unanswerable.
