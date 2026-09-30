"""Offline checks for lookup core and local kinds."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lookup


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def response(
        self,
        source,
        url,
        payload,
        *,
        status=200,
        cached=False,
        name="response.json",
    ):
        path = self.root / name
        envelope = {
            "url": url,
            "requested_at": "2026-09-26T12:00:00Z",
            "status": status,
            "body": json.dumps(payload),
        }
        return lookup.RemoteResponse(source, url, path, envelope, cached)

    def test_archive_path_slug_month_and_run_location(self):
        at = datetime(2026, 9, 25, 15, 4, 5, tzinfo=timezone.utc)
        default = lookup.archive_path(
            "eol", ["AlmaLinux", "10 / stable"], root=self.root, at=at, run=""
        )
        self.assertEqual(
            default.relative_to(self.root).as_posix(),
            "70_Research/_lookups/2026-09/eol/almalinux-10-stable--20260925T150405.json",
        )
        run = lookup.archive_path(
            "page", ["Example"], root=self.root, at=at, run="topic-name"
        )
        self.assertEqual(
            run.relative_to(self.root).as_posix(),
            "70_Research/topic-name/sources/raw/page-example--20260925T150405.json",
        )
        with self.assertRaises(lookup.BadArguments):
            lookup.archive_path("page", ["x"], root=self.root, at=at, run="../outside")

    def test_docs_search_and_library_context_normalize_snippets(self):
        payload = {
            "codeSnippets": [
                {
                    "libraryId": "/vercel/next.js",
                    "codeTitle": "Stream a response",
                    "codeList": [{"code": "return stream"}],
                }
            ],
            "infoSnippets": [
                {
                    "libraryId": "/openai/openai-python",
                    "title": "Streaming",
                    "content": "Use the streaming interface.",
                }
            ],
        }
        response = self.response(
            "Context7 search",
            "https://context7.com/api/v3/search?query=stream&type=json",
            payload,
        )
        with mock.patch.object(
            lookup, "gateway_response", return_value=response
        ) as gateway:
            outcome = lookup.docs_lookup(["stream"], root=self.root)
        self.assertEqual(outcome["status"], "found")
        self.assertEqual(
            outcome["answer"]["library_ids"],
            ["/vercel/next.js", "/openai/openai-python"],
        )
        self.assertEqual(
            [snippet["library_id"] for snippet in outcome["answer"]["snippets"]],
            ["/vercel/next.js", "/openai/openai-python"],
        )
        self.assertIn("query=stream", gateway.call_args.args[3])

        context = self.response(
            "Context7 context",
            "https://context7.com/api/v2/context",
            {"infoSnippets": [{"content": "Use app routes."}]},
            name="context.json",
        )
        with mock.patch.object(
            lookup, "gateway_response", return_value=context
        ) as gateway:
            outcome = lookup.docs_lookup(
                ["/vercel/next.js", "app routes"], root=self.root
            )
        self.assertEqual(
            outcome["answer"]["snippets"][0]["library_id"], "/vercel/next.js"
        )
        self.assertIn("libraryId=%2Fvercel%2Fnext.js", gateway.call_args.args[3])

    def test_docs_no_documentation_404_is_not_found(self):
        response = self.response(
            "Context7 search",
            "https://context7.com/api/v3/search?query=missing&type=json",
            {"error": "no_documentation_found"},
            status=404,
        )
        with mock.patch.object(lookup, "gateway_response", return_value=response):
            outcome = lookup.docs_lookup(["missing"], root=self.root)
        self.assertEqual(outcome["status"], "not found")
        self.assertIsNone(outcome["answer"])
        self.assertEqual(outcome["tried"][0]["http"], 404)

    def test_cache_returns_newest_unexpired_matching_envelope(self):
        old = lookup.archive_path(
            "eol",
            ["almalinux", "10"],
            root=self.root,
            at=datetime(2026, 9, 20, tzinfo=timezone.utc),
            run="",
        )
        new = lookup.archive_path(
            "eol",
            ["almalinux", "10"],
            root=self.root,
            at=datetime(2026, 9, 25, tzinfo=timezone.utc),
            run="",
        )
        for path, requested in (
            (old, "2026-09-20T00:00:00Z"),
            (new, "2026-09-25T00:00:00Z"),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "requested_at": requested,
                        "status": 200,
                        "lookup": lookup.lookup_identity("eol", ["AlmaLinux", "10"]),
                    }
                )
            )
        cached = lookup.newest_cached_envelope(
            "eol",
            ["AlmaLinux", "10"],
            7,
            root=self.root,
            now=datetime(2026, 9, 26, tzinfo=timezone.utc),
        )
        self.assertIsNotNone(cached)
        self.assertEqual(cached[0], new)

    def test_cache_includes_current_research_run(self):
        at = datetime(2026, 9, 25, tzinfo=timezone.utc)
        path = lookup.archive_path(
            "page", ["Example"], root=self.root, at=at, run="test-b4"
        )
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "requested_at": "2026-09-25T00:00:00Z",
                    "status": 200,
                    "lookup": lookup.lookup_identity("page", ["Example"]),
                }
            )
        )
        with mock.patch.dict(os.environ, {"RESEARCH_RUN": "test-b4"}):
            cached = lookup.newest_cached_envelope(
                "page",
                ["Example"],
                7,
                root=self.root,
                now=datetime(2026, 9, 26, tzinfo=timezone.utc),
            )
        self.assertIsNotNone(cached)
        self.assertEqual(cached[0], path)

    def test_research_run_cache_excludes_shared_lookup_tree(self):
        path = lookup.archive_path(
            "page",
            ["Example"],
            root=self.root,
            at=datetime(2026, 9, 25, tzinfo=timezone.utc),
            run="",
        )
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "requested_at": "2026-09-25T00:00:00Z",
                    "status": 200,
                    "lookup": lookup.lookup_identity("page", ["Example"]),
                }
            )
        )
        with mock.patch.dict(os.environ, {"RESEARCH_RUN": "test-b4"}):
            cached = lookup.newest_cached_envelope(
                "page",
                ["Example"],
                7,
                root=self.root,
                now=datetime(2026, 9, 26, tzinfo=timezone.utc),
            )
        self.assertIsNone(cached)

    def test_cache_excludes_transient_429_envelope(self):
        url = "https://endoflife.date/api/almalinux.json"
        path = lookup.archive_path(
            "eol",
            ["almalinux", "10"],
            root=self.root,
            at=datetime(2026, 9, 26, 12, tzinfo=timezone.utc),
            run="",
        )
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "url": url,
                    "requested_at": "2026-09-26T12:00:00Z",
                    "status": 429,
                    "body": "{}",
                    "lookup": lookup.lookup_identity("eol", ["almalinux", "10"]),
                }
            )
        )
        cached = lookup.newest_cached_envelope(
            "eol",
            ["almalinux", "10"],
            7,
            root=self.root,
            now=datetime(2026, 9, 26, 13, tzinfo=timezone.utc),
            url=url,
        )
        self.assertIsNone(cached)

    def test_gateway_response_reuses_matching_cache_without_running_gateway(self):
        url = "https://endoflife.date/api/almalinux.json"
        path = lookup.archive_path(
            "eol",
            ["almalinux", "10"],
            root=self.root,
            at=datetime(2026, 9, 26, 12, tzinfo=timezone.utc),
            run="",
        )
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "url": url,
                    "requested_at": "2026-09-26T12:00:00Z",
                    "status": 200,
                    "body": "[]",
                    "lookup": lookup.lookup_identity("eol", ["almalinux", "10"]),
                }
            )
        )
        with (
            mock.patch.object(
                lookup,
                "utc_now",
                return_value=datetime(2026, 9, 26, 13, tzinfo=timezone.utc),
            ),
            mock.patch.object(lookup, "append_log") as append,
            mock.patch.object(lookup.subprocess, "run") as run,
        ):
            response = lookup.gateway_response(
                "eol",
                ["almalinux", "10"],
                "endoflife.date",
                url,
                root=self.root,
            )
        self.assertTrue(response.cached)
        self.assertEqual(response.path, path)
        run.assert_not_called()
        self.assertEqual(append.call_args.args[0]["via"], "lookup")
        self.assertEqual(
            append.call_args.args[0]["archive"], str(path.relative_to(self.root))
        )

    def test_cache_identity_rejects_different_queries_with_the_same_slug_and_url(self):
        first_parts = ["https://example.test/" + "a" * 80]
        second_parts = ["https://example.test/" + "a" * 79 + "b"]
        self.assertEqual(
            lookup.lookup_key(first_parts), lookup.lookup_key(second_parts)
        )
        path = lookup.archive_path(
            "page",
            first_parts,
            root=self.root,
            at=datetime(2026, 9, 26, 12, tzinfo=timezone.utc),
            run="",
        )
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "url": "https://api.firecrawl.dev/v2/scrape",
                    "requested_at": "2026-09-26T12:00:00Z",
                    "status": 200,
                    "body": "{}",
                    "lookup": lookup.lookup_identity("page", first_parts),
                }
            )
        )
        cached = lookup.newest_cached_envelope(
            "page",
            second_parts,
            7,
            root=self.root,
            now=datetime(2026, 9, 26, 13, tzinfo=timezone.utc),
            url="https://api.firecrawl.dev/v2/scrape",
        )
        self.assertIsNone(cached)

    def test_gateway_response_invokes_only_gw_script(self):
        url = "https://endoflife.date/api/almalinux.json"

        def write_envelope(command, **_kwargs):
            path = Path(command[2])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "url": url,
                        "requested_at": "2026-09-26T12:00:00Z",
                        "status": 200,
                        "body": "[]",
                    }
                )
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with mock.patch.object(
            lookup.subprocess, "run", side_effect=write_envelope
        ) as run:
            response = lookup.gateway_response(
                "eol",
                ["almalinux", "10"],
                "endoflife.date",
                url,
                fresh=True,
                root=self.root,
            )
        command = run.call_args.args[0]
        self.assertEqual(Path(command[1]).name, "gw.py")
        self.assertEqual(command[3:5], ["--", url])
        self.assertFalse(response.cached)

    def test_archive_reservations_are_unique_before_either_request_finishes(self):
        at = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
        first = lookup.reserve_archive_path(
            "eol", ["almalinux", "10"], root=self.root, at=at
        )
        second = lookup.reserve_archive_path(
            "eol", ["almalinux", "10"], root=self.root, at=at
        )
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())

    def test_archived_429_keeps_gateway_refusal_status(self):
        url = "https://endoflife.date/api/almalinux.json"

        def refused(command, **_kwargs):
            path = Path(command[2])
            path.write_text(
                json.dumps(
                    {
                        "url": url,
                        "requested_at": "2026-09-26T12:00:00Z",
                        "status": 429,
                        "body": "{}",
                    }
                )
            )
            return subprocess.CompletedProcess(command, 4, stdout="", stderr="")

        with mock.patch.object(lookup.subprocess, "run", side_effect=refused):
            response = lookup.gateway_response(
                "eol",
                ["almalinux", "10"],
                "endoflife.date",
                url,
                fresh=True,
                root=self.root,
            )
        _payload, attempt = lookup.remote_json(response)
        self.assertEqual(
            attempt,
            {
                "source": "endoflife.date",
                "status": "refused",
                "http": 429,
                "archive": str(response.path),
            },
        )

    def test_eol_normalizes_cycle_and_cache_state(self):
        url = "https://endoflife.date/api/almalinux.json"
        response = self.response(
            "endoflife.date",
            url,
            [
                {
                    "cycle": "10",
                    "releaseDate": "2025-05-27",
                    "support": "2030-05-31",
                    "eol": "2035-05-31",
                    "latest": "10.0",
                }
            ],
            cached=True,
        )
        with mock.patch.object(lookup, "gateway_response", return_value=response):
            outcome = lookup.eol_lookup(["almalinux", "10"], root=self.root)
        self.assertEqual(outcome["answer"]["eol"], "2035-05-31")
        self.assertTrue(outcome["cached"])

    def test_package_parsers_cover_each_registry(self):
        pypi = lookup.package_answer(
            "pypi",
            {
                "info": {
                    "name": "demo",
                    "version": "1.0",
                    "license": "MIT",
                    "home_page": "https://example.test",
                    "project_urls": {"Repository": "https://git.test/demo"},
                },
                "releases": {"1.0": [{"upload_time_iso_8601": "2026-01-01Z"}]},
            },
            None,
        )
        npm = lookup.package_answer(
            "npm",
            {
                "dist-tags": {"latest": "2.0"},
                "versions": {
                    "2.0": {
                        "name": "demo",
                        "license": "ISC",
                        "repository": {"url": "git+https://git.test/demo"},
                    }
                },
                "time": {"2.0": "2026-02-02Z"},
            },
            None,
        )
        crates = lookup.package_answer(
            "crates",
            {
                "crate": {
                    "name": "demo",
                    "newest_version": "3.0",
                    "repository": "https://git.test/demo",
                },
                "versions": [
                    {"num": "3.0", "created_at": "2026-03-03Z", "license": "MIT"}
                ],
            },
            None,
        )
        self.assertEqual(
            [pypi["version"], npm["version"], crates["version"]],
            ["1.0", "2.0", "3.0"],
        )

    def test_vulnerability_uses_osv_then_github(self):
        osv = self.response("OSV", "https://api.osv.dev/v1/query", {"vulns": []})
        github_url = (
            "https://api.github.com/advisories?ecosystem=pip&per_page=100&affects=demo"
        )
        github = self.response(
            "GitHub advisories",
            github_url,
            [
                {
                    "ghsa_id": "GHSA-test",
                    "summary": "Test advisory",
                    "severity": "high",
                    "vulnerabilities": [],
                }
            ],
            name="github.json",
        )
        with mock.patch.object(
            lookup, "gateway_response", side_effect=[osv, github]
        ) as gateway:
            outcome = lookup.vuln_lookup(["PyPI", "demo"], root=self.root)
        self.assertEqual(outcome["answer"]["advisories"][0]["id"], "GHSA-test")
        self.assertEqual(
            [attempt["status"] for attempt in outcome["tried"]],
            ["not found", "found"],
        )
        self.assertEqual(gateway.call_count, 2)

    def test_cve_adds_epss_to_nvd_result(self):
        nvd_url = "https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2026-1234"
        nvd = self.response(
            "NVD",
            nvd_url,
            {
                "vulnerabilities": [
                    {
                        "cve": {
                            "id": "CVE-2026-1234",
                            "descriptions": [{"lang": "en", "value": "Example"}],
                            "metrics": {
                                "cvssMetricV31": [
                                    {
                                        "cvssData": {
                                            "baseScore": 8.1,
                                            "baseSeverity": "HIGH",
                                        }
                                    }
                                ]
                            },
                            "references": [{"url": "https://example.test/cve"}],
                        }
                    }
                ]
            },
        )
        epss_url = "https://api.first.org/data/v1/epss?cve=CVE-2026-1234"
        epss = self.response(
            "FIRST EPSS",
            epss_url,
            {"data": [{"epss": "0.42", "percentile": "0.91"}]},
            name="epss.json",
        )
        with mock.patch.object(lookup, "gateway_response", side_effect=[nvd, epss]):
            outcome = lookup.cve_lookup(["cve-2026-1234"], root=self.root)
        self.assertEqual(outcome["answer"]["score"], 8.1)
        self.assertEqual(outcome["answer"]["epss"], "0.42")
        self.assertEqual(len(outcome["tried"]), 2)

    def test_cve_not_found_is_not_cached_when_osv_was_fresh(self):
        nvd = self.response(
            "NVD",
            "https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2026-1234",
            {"vulnerabilities": []},
            cached=True,
        )
        osv = self.response(
            "OSV",
            "https://api.osv.dev/v1/vulns/CVE-2026-1234",
            {},
            cached=False,
            name="osv.json",
        )
        with mock.patch.object(lookup, "gateway_response", side_effect=[nvd, osv]):
            outcome = lookup.cve_lookup(["CVE-2026-1234"], root=self.root)
        self.assertEqual(outcome["status"], "not found")
        self.assertFalse(outcome["cached"])

    def test_repo_and_rfc_normalize_their_api_responses(self):
        repo = self.response(
            "GitHub GraphQL",
            "https://api.github.com/graphql",
            {
                "data": {
                    "repository": {
                        "nameWithOwner": "owner/repo",
                        "description": "Example",
                        "url": "https://github.com/owner/repo",
                        "latestRelease": {"tagName": "v1"},
                        "readme": {"text": "readme"},
                        "target": {"entries": [{"name": "src", "type": "tree"}]},
                    }
                }
            },
        )
        rfc_url = (
            "https://datatracker.ietf.org/api/v1/doc/document/"
            "?format=json&name__iexact=rfc9000"
        )
        rfc = self.response(
            "IETF Datatracker",
            rfc_url,
            {
                "objects": [
                    {
                        "name": "rfc9000",
                        "title": "QUIC",
                        "states": ["/api/v1/doc/state/1/"],
                        "abstract": "A transport protocol.",
                        "rev": "00",
                        "group": "/api/v1/group/group/1074/",
                    }
                ]
            },
            name="rfc.json",
        )
        state = self.response(
            "IETF Datatracker state",
            "https://datatracker.ietf.org/api/v1/doc/state/1/",
            {"desc": "Proposed Standard", "slug": "ps"},
            name="state.json",
        )
        group = self.response(
            "IETF Datatracker group",
            "https://datatracker.ietf.org/api/v1/group/group/1074/",
            {"acronym": "quic", "name": "QUIC Working Group"},
            name="group.json",
        )
        with mock.patch.object(
            lookup, "gateway_response", side_effect=[repo, rfc, state, group]
        ):
            repo_outcome = lookup.repo_lookup(["owner/repo"], root=self.root)
            rfc_outcome = lookup.rfc_lookup(["rfc9000"], root=self.root)
        self.assertEqual(repo_outcome["answer"]["repository"], "owner/repo")
        self.assertEqual(rfc_outcome["answer"]["title"], "QUIC")
        self.assertEqual(rfc_outcome["answer"]["status"], ["Proposed Standard"])
        self.assertEqual(rfc_outcome["answer"]["working_group"], "quic")

    def test_paper_identifier_accepts_doi_and_arxiv(self):
        self.assertEqual(
            lookup.paper_identifier("https://doi.org/10.1000/Test"),
            ("doi", "10.1000/test", "DOI:10.1000/test"),
        )
        self.assertEqual(
            lookup.paper_identifier("arXiv:2506.08837"),
            ("arxiv", "2506.08837", "arXiv:2506.08837"),
        )
        self.assertEqual(
            lookup.paper_identifier("arXiv:hep-th/9901001"),
            ("arxiv", "hep-th/9901001", "arXiv:hep-th/9901001"),
        )
        with self.assertRaises(lookup.BadArguments):
            lookup.paper_identifier("not-an-id")

    def test_paper_normalizes_semantic_scholar_metadata(self):
        semantic = self.response(
            "Semantic Scholar",
            "https://api.semanticscholar.org/paper",
            {
                "title": "A Paper",
                "year": 2026,
                "venue": "A Venue",
                "authors": [{"name": "A. Author"}],
                "abstract": "An abstract.",
                "externalIds": {"DOI": "10.1000/test"},
                "openAccessPdf": {"url": "https://example.test/paper.pdf"},
                "citationCount": 4,
            },
        )
        with mock.patch.object(lookup, "gateway_response", return_value=semantic):
            outcome = lookup.paper_lookup(["10.1000/test"], root=self.root)
        self.assertEqual(outcome["answer"]["title"], "A Paper")
        self.assertEqual(outcome["answer"]["authors"], ["A. Author"])
        self.assertEqual(outcome["answer"]["citations"], 4)

    def test_paper_arxiv_fallback_parses_atom(self):
        semantic = self.response(
            "Semantic Scholar",
            "https://api.semanticscholar.org/paper",
            {},
            status=404,
        )
        atom = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>https://arxiv.org/abs/2506.08837</id><title> Example Paper </title>
<published>2025-06-10T00:00:00Z</published><summary> Example abstract. </summary>
<author><name>Example Author</name></author>
<link href="https://arxiv.org/pdf/2506.08837" type="application/pdf" />
</entry></feed>"""
        arxiv = lookup.RemoteResponse(
            "arXiv API",
            "https://export.arxiv.org/api/query?id_list=2506.08837",
            self.root / "arxiv.json",
            {
                "url": "https://export.arxiv.org/api/query?id_list=2506.08837",
                "requested_at": "2026-09-26T12:00:00Z",
                "status": 200,
                "body": atom,
            },
            False,
        )
        with mock.patch.object(
            lookup, "gateway_response", side_effect=[semantic, arxiv]
        ):
            outcome = lookup.paper_lookup(["arXiv:2506.08837"], root=self.root)
        self.assertEqual(outcome["answer"]["title"], "Example Paper")
        self.assertEqual(outcome["answer"]["venue"], "arXiv")
        legacy = lookup.arxiv_paper(atom.replace("2506.08837", "hep-th/9901001"))
        self.assertEqual(legacy["identifiers"]["ArXiv"], "hep-th/9901001")

    def test_cites_honors_refs_and_normalizes_papers(self):
        semantic = self.response(
            "Semantic Scholar",
            "https://api.semanticscholar.org/references",
            {
                "data": [
                    {
                        "citedPaper": {
                            "paperId": "paper-1",
                            "title": "Referenced paper",
                            "externalIds": {"DOI": "10.1000/ref"},
                        }
                    }
                ]
            },
        )
        with mock.patch.object(
            lookup, "gateway_response", return_value=semantic
        ) as gateway:
            outcome = lookup.cites_lookup(
                ["arXiv:2506.08837"], references=True, root=self.root
            )
        self.assertEqual(outcome["answer"]["papers"][0]["title"], "Referenced paper")
        self.assertIn("/references?", gateway.call_args.args[3])

    def test_fulltext_arxiv_skips_unpaywall_and_lists_every_rung(self):
        semantic = self.response(
            "Semantic Scholar open-access link",
            "https://api.semanticscholar.org/paper",
            {
                "title": "Example Paper",
                "externalIds": {"ArXiv": "2506.08837"},
                "openAccessPdf": None,
            },
        )
        core_doi = self.response(
            "CORE (DOI)",
            "https://api.core.ac.uk/v3/search/works/",
            {"results": []},
            name="core-doi.json",
        )
        core_title = self.response(
            "CORE (exact title)",
            "https://api.core.ac.uk/v3/search/works/",
            {"results": []},
            name="core-title.json",
        )
        page = {
            "kind": "page",
            "query": {"url": "https://arxiv.org/pdf/2506.08837"},
            "status": "not found",
            "cached": False,
            "answer": None,
            "source": None,
            "tried": [
                {"source": "Firecrawl scrape", "status": "not found", "http": 200}
            ],
        }
        with (
            mock.patch.object(
                lookup, "gateway_response", side_effect=[semantic, core_doi, core_title]
            ) as gateway,
            mock.patch.object(lookup, "page_lookup", return_value=page),
        ):
            outcome = lookup.fulltext_lookup(["arXiv:2506.08837"], root=self.root)
        self.assertEqual(
            [attempt["source"] for attempt in outcome["tried"]],
            [
                "Semantic Scholar open-access link",
                "Unpaywall",
                "CORE (DOI)",
                "CORE (exact title)",
                "Firecrawl scrape",
            ],
        )
        unpaywall = outcome["tried"][1]
        self.assertEqual(unpaywall["status"], "skipped")
        self.assertIn("arXiv DOI", unpaywall["reason"])
        self.assertFalse(
            any("unpaywall.org" in call.args[3] for call in gateway.call_args_list)
        )

    def test_fulltext_preserves_input_doi_and_core_can_match_title(self):
        semantic = self.response(
            "Semantic Scholar open-access link",
            "https://api.semanticscholar.org/paper",
            {
                "title": "Exact Paper Title",
                "externalIds": {},
                "openAccessPdf": None,
            },
        )
        unpaywall = self.response(
            "Unpaywall",
            "https://api.unpaywall.org/v2/10.1000%2Ftest",
            {"best_oa_location": {"url": "https://publisher.test/landing"}},
            name="unpaywall.json",
        )
        core_doi = self.response(
            "CORE (DOI)",
            "https://api.core.ac.uk/v3/search/works/",
            {"results": []},
            name="core-doi.json",
        )
        core_title = self.response(
            "CORE (exact title)",
            "https://api.core.ac.uk/v3/search/works/",
            {
                "results": [
                    {
                        "title": "Exact Paper Title",
                        "doi": None,
                        "fullText": "The complete paper body.",
                    }
                ]
            },
            name="core-title.json",
        )
        with mock.patch.object(
            lookup,
            "gateway_response",
            side_effect=[semantic, unpaywall, core_doi, core_title],
        ) as gateway:
            outcome = lookup.fulltext_lookup(["10.1000/test"], root=self.root)
        self.assertEqual(outcome["status"], "found")
        self.assertEqual(outcome["answer"]["length"], len("The complete paper body."))
        urls = [call.args[3] for call in gateway.call_args_list]
        self.assertTrue(any("unpaywall.org/v2/10.1000%2Ftest" in url for url in urls))
        self.assertFalse(any("publisher.test/landing" in url for url in urls))

    def test_fulltext_open_pdf_uses_page_routing_instead_of_direct_gateway(self):
        semantic = self.response(
            "Semantic Scholar open-access link",
            "https://api.semanticscholar.org/paper",
            {
                "title": "Example Paper",
                "externalIds": {"ArXiv": "2506.08837"},
                "openAccessPdf": {"url": "https://arxiv.org/pdf/2506.08837"},
            },
        )
        page = {
            "kind": "page",
            "query": {"url": "https://arxiv.org/pdf/2506.08837"},
            "status": "found",
            "cached": False,
            "answer": {"length": 1200, "archive": "70_Research/raw.json"},
            "source": {"name": "Firecrawl scrape", "archive": "70_Research/raw.json"},
            "tried": [{"source": "Firecrawl scrape", "status": "found", "http": 200}],
        }
        with (
            mock.patch.object(
                lookup, "gateway_response", return_value=semantic
            ) as gateway,
            mock.patch.object(lookup, "page_lookup", return_value=page) as page_call,
        ):
            outcome = lookup.fulltext_lookup(["arXiv:2506.08837"], root=self.root)
        self.assertEqual(outcome["answer"]["length"], 1200)
        self.assertEqual(gateway.call_count, 1)
        page_call.assert_called_once_with(
            ["https://arxiv.org/pdf/2506.08837"],
            fresh=False,
            root=self.root,
            allow_arxiv_pdf=True,
            cache_kind="fulltext",
            subject="arXiv:2506.08837",
        )

    def test_fulltext_does_not_retry_semantic_scholar_arxiv_pdf(self):
        semantic = self.response(
            "Semantic Scholar open-access link",
            "https://api.semanticscholar.org/paper",
            {
                "title": None,
                "externalIds": {"ArXiv": "2506.08837"},
                "openAccessPdf": {"url": "https://arxiv.org/pdf/2506.08837v1"},
            },
        )
        page = {
            "status": "not found",
            "cached": False,
            "tried": [
                {"source": "Firecrawl scrape", "status": "not found", "http": 404}
            ],
        }
        with (
            mock.patch.object(lookup, "gateway_response", return_value=semantic),
            mock.patch.object(lookup, "page_lookup", return_value=page) as page_call,
        ):
            outcome = lookup.fulltext_lookup(["arXiv:2506.08837"], root=self.root)
        self.assertEqual(outcome["status"], "not found")
        page_call.assert_called_once()

    def test_page_refuses_github_and_names_repo(self):
        with (
            mock.patch.object(lookup, "gateway_response") as gateway,
            mock.patch.object(lookup, "log_local") as log,
            mock.patch("builtins.print") as output,
        ):
            code = lookup.main(["page", "https://github.com/x/y"])
        self.assertEqual(code, 4)
        rendered = json.loads(output.call_args.args[0])
        self.assertEqual(rendered["status"], "refused")
        self.assertEqual(rendered["answer"]["use"], "repo")
        gateway.assert_not_called()
        log.assert_called_once()
        self.assertEqual(log.call_args.args[1], "https://github.com/x/y")

    def test_firecrawl_search_and_page_normalize_credits(self):
        search = self.response(
            "Firecrawl search",
            "https://api.firecrawl.dev/v2/search",
            {
                "success": True,
                "data": [
                    {
                        "title": "Example",
                        "url": "https://example.com",
                        "description": "Example result",
                    }
                ],
                "creditsUsed": 2,
            },
        )
        page = self.response(
            "Firecrawl scrape",
            "https://api.firecrawl.dev/v2/scrape",
            {
                "success": True,
                "data": {
                    "markdown": "# Example Domain",
                    "metadata": {"title": "Example Domain", "creditsUsed": 1},
                },
            },
            name="page.json",
        )
        with (
            mock.patch.object(lookup, "gateway_response", side_effect=[search, page]),
            mock.patch.object(lookup, "public_address", return_value="93.184.216.34"),
        ):
            search_outcome = lookup.search_lookup(["example"], root=self.root)
            page_outcome = lookup.page_lookup(["https://example.com"], root=self.root)
        self.assertEqual(search_outcome["answer"]["credits_used"], 2)
        self.assertEqual(page_outcome["answer"]["credits_used"], 1)
        self.assertEqual(page_outcome["answer"]["title"], "Example Domain")

    def test_firecrawl_v2_search_reads_results_under_data_web(self):
        search = self.response(
            "Firecrawl search",
            "https://api.firecrawl.dev/v2/search",
            {
                "success": True,
                "data": {
                    "web": [
                        {
                            "title": "Example",
                            "url": "https://example.com",
                            "description": "Example result",
                        },
                        {"title": "No address"},
                    ]
                },
                "creditsUsed": 2,
                "id": "search-id",
            },
        )
        with mock.patch.object(lookup, "gateway_response", return_value=search):
            outcome = lookup.search_lookup(["example"], root=self.root)
        self.assertEqual(outcome["status"], "found")
        self.assertEqual(
            outcome["answer"]["results"],
            [
                {
                    "title": "Example",
                    "url": "https://example.com",
                    "description": "Example result",
                }
            ],
        )
        self.assertEqual(outcome["answer"]["credits_used"], 2)
        self.assertTrue(lookup.firecrawl_search_cacheable(search.envelope))

    def test_firecrawl_v2_search_with_no_web_results_is_not_found(self):
        empty = self.response(
            "Firecrawl search",
            "https://api.firecrawl.dev/v2/search",
            {"success": True, "data": {"web": []}, "creditsUsed": 2},
        )
        with mock.patch.object(lookup, "gateway_response", return_value=empty):
            outcome = lookup.search_lookup(["example"], root=self.root)
        self.assertEqual(outcome["status"], "not found")
        self.assertTrue(lookup.firecrawl_search_cacheable(empty.envelope))

    def test_firecrawl_search_without_web_list_is_not_cacheable(self):
        odd = self.response(
            "Firecrawl search",
            "https://api.firecrawl.dev/v2/search",
            {"success": True, "data": {"news": []}},
        )
        self.assertFalse(lookup.firecrawl_search_cacheable(odd.envelope))

    def test_search_malformed_json_shape_returns_structured_error(self):
        malformed = self.response(
            "Firecrawl search", "https://api.firecrawl.dev/v2/search", []
        )
        with mock.patch.object(lookup, "gateway_response", return_value=malformed):
            outcome = lookup.search_lookup(["example"], root=self.root)
        self.assertEqual(outcome["status"], "error")
        self.assertFalse(lookup.firecrawl_search_cacheable(malformed.envelope))

    def test_arxiv_page_can_use_fulltext_cache_kind(self):
        page = self.response(
            "Firecrawl scrape",
            "https://api.firecrawl.dev/v2/scrape",
            {
                "success": True,
                "data": {"markdown": "paper text", "metadata": {"creditsUsed": 1}},
            },
        )
        with (
            mock.patch.object(lookup, "gateway_response", return_value=page) as gateway,
            mock.patch.object(lookup, "public_address", return_value="151.101.3.42"),
        ):
            outcome = lookup.page_lookup(
                ["https://arxiv.org/pdf/2506.08837"],
                root=self.root,
                allow_arxiv_pdf=True,
                cache_kind="fulltext",
            )
        self.assertEqual(outcome["status"], "found")
        self.assertEqual(gateway.call_args.args[0], "fulltext")

    def test_cert_returns_each_certificate_with_names_and_validity(self):
        response = self.response(
            "crt.sh",
            "https://crt.sh/?q=keepbreath.ing&output=json",
            [
                {
                    "id": 42,
                    "issuer_name": "Example CA",
                    "name_value": "keepbreath.ing\nwww.keepbreath.ing",
                    "not_before": "2026-01-01T00:00:00",
                    "not_after": "2026-04-01T00:00:00",
                    "serial_number": "abc",
                }
            ],
            cached=True,
        )
        with mock.patch.object(lookup, "gateway_response", return_value=response):
            outcome = lookup.cert_lookup(["KEEPBREATH.ING."], root=self.root)
        certificate = outcome["answer"]["certificates"][0]
        self.assertEqual(certificate["issuer"], "Example CA")
        self.assertEqual(certificate["names"], ["keepbreath.ing", "www.keepbreath.ing"])
        self.assertEqual(certificate["not_after"], "2026-04-01T00:00:00")
        self.assertTrue(outcome["cached"])

    def test_ip_combines_shodan_and_greynoise_and_refuses_private_addresses(self):
        shodan = self.response(
            "Shodan InternetDB",
            "https://internetdb.shodan.io/8.8.8.8",
            {"ports": [53], "vulns": ["CVE-TEST"], "hostnames": ["dns.google"]},
        )
        greynoise = self.response(
            "GreyNoise community",
            "https://api.greynoise.io/v3/community/8.8.8.8",
            {"noise": False, "riot": True, "classification": "benign"},
            name="greynoise.json",
        )
        with mock.patch.object(
            lookup, "gateway_response", side_effect=[shodan, greynoise]
        ) as gateway:
            outcome = lookup.ip_lookup(["8.8.8.8"], root=self.root)
        self.assertEqual(outcome["answer"]["open_ports"], [53])
        self.assertEqual(outcome["answer"]["known_issues"], ["CVE-TEST"])
        self.assertEqual(outcome["answer"]["scanning"]["classification"], "benign")
        self.assertEqual(gateway.call_count, 2)
        with self.assertRaises(lookup.BadArguments):
            lookup.ip_lookup(["127.0.0.1"], root=self.root)
        with self.assertRaises(lookup.BadArguments):
            lookup.ip_lookup(["224.0.0.1"], root=self.root)

    def test_security_cache_validators_reject_malformed_successes(self):
        malformed = {"status": 200, "body": "<html>temporary error</html>"}
        wrong_shape = {"status": 200, "body": json.dumps({"detail": "error"})}
        self.assertFalse(lookup.cert_cacheable(malformed))
        self.assertFalse(lookup.shodan_cacheable(wrong_shape))
        self.assertFalse(lookup.greynoise_cacheable(wrong_shape))
        self.assertFalse(
            lookup.cert_cacheable(
                {"status": 200, "body": json.dumps([{"name_value": None}])}
            )
        )
        self.assertFalse(
            lookup.shodan_cacheable(
                {"status": 200, "body": json.dumps({"ports": "error"})}
            )
        )
        self.assertFalse(
            lookup.greynoise_cacheable(
                {
                    "status": 200,
                    "body": json.dumps(
                        {"noise": False, "riot": False, "classification": []}
                    ),
                }
            )
        )
        self.assertTrue(lookup.cert_cacheable({"status": 200, "body": json.dumps([])}))
        self.assertTrue(
            lookup.shodan_cacheable({"status": 200, "body": json.dumps({"ports": []})})
        )
        self.assertTrue(
            lookup.greynoise_cacheable(
                {
                    "status": 200,
                    "body": json.dumps({"noise": False, "riot": False}),
                }
            )
        )

    def test_domain_follows_one_validated_rdap_redirect_and_normalizes_fields(self):
        bootstrap = self.response(
            "RDAP bootstrap",
            "https://rdap.org/domain/example.com",
            {},
            status=302,
        )
        bootstrap.envelope["headers"] = {
            "Location": "https://rdap.example/domain/example.com"
        }
        rdap = self.response(
            "RDAP",
            "https://rdap.example/domain/example.com",
            {
                "ldhName": "EXAMPLE.COM",
                "status": ["active"],
                "events": [
                    {
                        "eventAction": "registration",
                        "eventDate": "1995-08-14T04:00:00Z",
                    }
                ],
                "nameservers": [{"ldhName": "A.IANA-SERVERS.NET"}],
                "entities": [
                    {
                        "roles": ["registrar"],
                        "vcardArray": [
                            "vcard",
                            [["fn", {}, "text", "Example Registrar"]],
                        ],
                    }
                ],
            },
            name="rdap.json",
        )
        with (
            mock.patch.object(lookup, "newest_cached_envelope", return_value=None),
            mock.patch.object(
                lookup, "gateway_response", side_effect=[bootstrap, rdap]
            ) as gateway,
            mock.patch.object(
                lookup, "public_address", return_value="203.0.113.10"
            ) as public,
        ):
            outcome = lookup.domain_lookup(["example.com"], root=self.root)
        self.assertEqual(outcome["answer"]["registrar"], "Example Registrar")
        self.assertEqual(outcome["answer"]["name_servers"], ["A.IANA-SERVERS.NET"])
        self.assertEqual(outcome["tried"][0]["status"], "redirected")
        self.assertEqual(
            gateway.call_args.args[3], "https://rdap.example/domain/example.com"
        )
        public.assert_called_once_with("rdap.example")

    def test_domain_refuses_an_unsafe_rdap_redirect_without_following_it(self):
        bootstrap = self.response(
            "RDAP bootstrap",
            "https://rdap.org/domain/example.com",
            {},
            status=302,
        )
        bootstrap.envelope["headers"] = {
            "Location": "https://internal.example/domain/example.com"
        }
        with (
            mock.patch.object(lookup, "newest_cached_envelope", return_value=None),
            mock.patch.object(
                lookup, "gateway_response", return_value=bootstrap
            ) as gateway,
            mock.patch.object(
                lookup, "public_address", side_effect=ValueError("private address")
            ),
        ):
            outcome = lookup.domain_lookup(["example.com"], root=self.root)
        self.assertEqual(outcome["status"], "refused")
        self.assertEqual(outcome["tried"][-1]["source"], "RDAP redirect")
        self.assertEqual(gateway.call_count, 1)

    def test_domain_reuses_authoritative_rdap_cache_without_bootstrap_request(self):
        path = self.root / "rdap.json"
        envelope = {
            "url": "https://rdap.example/domain/example.com",
            "requested_at": "2026-09-26T12:00:00Z",
            "status": 200,
            "body": json.dumps({"ldhName": "EXAMPLE.COM", "status": ["active"]}),
        }
        path.write_text(json.dumps(envelope))
        with (
            mock.patch.object(
                lookup, "newest_cached_envelope", return_value=(path, envelope)
            ),
            mock.patch.object(lookup, "gateway_response") as gateway,
            mock.patch.object(lookup, "append_log") as append,
        ):
            outcome = lookup.domain_lookup(["example.com"], root=self.root)
        gateway.assert_not_called()
        append.assert_called_once()
        self.assertEqual(append.call_args.args[0]["via"], "lookup")
        self.assertTrue(outcome["cached"])
        self.assertEqual(outcome["answer"]["status"], ["active"])

    def test_gateway_response_reports_missing_contact_as_not_configured(self):
        completed = subprocess.CompletedProcess(
            [], 2, stdout="", stderr="[gw] REFUSED: contact email is not configured"
        )
        with mock.patch.object(lookup.subprocess, "run", return_value=completed):
            response = lookup.gateway_response(
                "paper",
                ["10.1000/example"],
                "Unpaywall",
                "https://api.unpaywall.org/v2/10.1000%2Fexample",
                fresh=True,
                root=self.root,
            )
        self.assertEqual(response.failure, "not configured")
        self.assertIsNone(response.path)
        self.assertEqual(list(self.root.rglob("*.json")), [])

    def test_main_reports_missing_session_reason_in_tried_entry(self):
        message = (
            "[gw] REFUSED api.github.com: Vaultwarden session unavailable; run vu\n"
        )
        completed = subprocess.CompletedProcess([], 2, stdout="", stderr=message)
        with (
            mock.patch.object(lookup.subprocess, "run", return_value=completed),
            mock.patch.object(lookup, "vault_root", return_value=self.root),
            mock.patch.object(
                lookup,
                "load_config",
                return_value={"lookup": {"max_output_chars": 8_000}},
            ),
            mock.patch.object(lookup, "log_local"),
            mock.patch("builtins.print") as output,
        ):
            self.assertEqual(lookup.main(["--fresh", "repo", "restic/restic"]), 1)
        rendered = json.loads(output.call_args.args[0])
        self.assertEqual(rendered["status"], "error")
        self.assertEqual(
            rendered["tried"],
            [
                {
                    "source": "GitHub GraphQL",
                    "status": "not configured",
                    "http": None,
                    "reason": "REFUSED api.github.com: "
                    "Vaultwarden session unavailable; run vu",
                }
            ],
        )
        self.assertEqual(list(self.root.rglob("*.json")), [])

    def test_vault_requires_every_word_and_limits_results(self):
        research = self.root / "70_Research"
        research.mkdir()
        (research / "one.md").write_text("Alpha appears here.\nBeta appears later.\n")
        (research / "two.md").write_text("Only alpha appears.\n")
        outcome = lookup.vault_lookup(["alpha", "beta"], root=self.root)
        self.assertEqual(outcome["status"], "found")
        self.assertEqual(len(outcome["answer"]["matches"]), 1)
        self.assertEqual(outcome["answer"]["matches"][0]["file"], "70_Research/one.md")
        self.assertIn("line", outcome["answer"]["matches"][0])
        self.assertIn("snippet", outcome["answer"]["matches"][0])

    def test_ansible_lists_normalized_options(self):
        payload = {
            "ansible.builtin.user": {
                "doc": {
                    "options": {
                        "name": {
                            "type": "str",
                            "required": True,
                            "description": ["Name of the user."],
                        },
                        "state": {
                            "type": "str",
                            "default": "present",
                            "description": ["Whether the account exists."],
                        },
                    }
                }
            }
        }
        completed = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(payload), stderr=""
        )
        with mock.patch.object(lookup.subprocess, "run", return_value=completed):
            outcome = lookup.ansible_lookup(["ansible.builtin.user"])
        self.assertEqual(outcome["status"], "found")
        self.assertEqual(
            outcome["answer"]["options"],
            [
                {
                    "name": "name",
                    "type": "str",
                    "default": None,
                    "required": True,
                    "description": "Name of the user.",
                },
                {
                    "name": "state",
                    "type": "str",
                    "default": "present",
                    "required": False,
                    "description": "Whether the account exists.",
                },
            ],
        )

    def test_ansible_treats_non_object_json_as_malformed(self):
        completed = subprocess.CompletedProcess([], 0, stdout="[]", stderr="")
        with mock.patch.object(lookup.subprocess, "run", return_value=completed):
            outcome = lookup.ansible_lookup(["ansible.builtin.user"])
        self.assertEqual(outcome["status"], "error")

    def test_help_rejects_arguments_and_falls_back_to_dash_help(self):
        man = subprocess.CompletedProcess([], 1, stdout="", stderr="missing")
        help_result = subprocess.CompletedProcess(
            [], 0, stdout="line 1\nline 2\n", stderr=""
        )
        with (
            mock.patch.object(lookup.shutil, "which", return_value="/usr/bin/tool"),
            mock.patch.object(
                lookup.subprocess, "run", side_effect=[man, help_result]
            ) as run,
        ):
            outcome = lookup.help_lookup(["tool"])
        self.assertEqual(outcome["answer"]["lines"], ["line 1", "line 2"])
        self.assertEqual(run.call_args_list[1].args[0], ["/usr/bin/tool", "--help"])
        with self.assertRaises(lookup.BadArguments):
            lookup.help_lookup(["tool", "extra"])
        with self.assertRaises(lookup.BadArguments):
            lookup.help_lookup(["../tool"])

    def test_help_falls_back_when_man_is_not_installed(self):
        help_result = subprocess.CompletedProcess(
            [], 0, stdout="fallback help\n", stderr=""
        )
        with (
            mock.patch.object(lookup.shutil, "which", return_value="/usr/bin/tool"),
            mock.patch.object(
                lookup.subprocess,
                "run",
                side_effect=[FileNotFoundError, help_result],
            ),
        ):
            outcome = lookup.help_lookup(["tool"])
        self.assertEqual(outcome["status"], "found")
        self.assertEqual(outcome["answer"]["lines"], ["fallback help"])

    def test_doctor_reports_every_configured_key_without_values(self):
        config = {
            "providers": {
                "one": {"key_item": "First key"},
                "two": {"key_item": "Second key"},
                "again": {"key_item": "First key"},
            }
        }

        def bitwarden(command, **_kwargs):
            if command == ["bw", "status"]:
                return subprocess.CompletedProcess(
                    command, 0, stdout=json.dumps({"status": "unlocked"}), stderr=""
                )
            if command[:4] == ["bw", "list", "items", "--search"]:
                name = command[4]
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps([{"id": f"id-{name}", "name": name}]),
                    stderr="",
                )
            return subprocess.CompletedProcess(command, 0, stdout="secret\n", stderr="")

        with (
            mock.patch.dict(os.environ, {"BW_SESSION": "session"}, clear=False),
            mock.patch.object(lookup, "load_config", return_value=config),
            mock.patch.object(lookup.shutil, "which", return_value="/bin/tool"),
            mock.patch.object(lookup.subprocess, "run", side_effect=bitwarden),
        ):
            outcome = lookup.doctor_lookup([], root=self.root)
        self.assertEqual(set(outcome["answer"]["keys"]), {"First key", "Second key"})
        self.assertTrue(outcome["answer"]["vaultwarden_session"]["available"])
        self.assertNotIn("secret", json.dumps(outcome))

    def test_doctor_reports_missing_bw_and_invalid_session(self):
        config = {"providers": {"one": {"key_item": "First key"}}}
        which = lambda name: None if name == "bw" else "/bin/tool"
        with (
            mock.patch.object(lookup, "load_config", return_value=config),
            mock.patch.object(lookup.shutil, "which", side_effect=which),
        ):
            missing = lookup.doctor_lookup([], root=self.root)
        self.assertFalse(missing["answer"]["tools"]["bw"]["available"])
        self.assertFalse(missing["answer"]["vaultwarden_session"]["available"])
        self.assertEqual(
            missing["answer"]["keys"]["First key"]["reason"], "bw unavailable"
        )

        locked = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({"status": "locked"}), stderr=""
        )
        with (
            mock.patch.dict(os.environ, {"BW_SESSION": "expired"}, clear=False),
            mock.patch.object(lookup, "load_config", return_value=config),
            mock.patch.object(lookup.shutil, "which", return_value="/bin/tool"),
            mock.patch.object(lookup.subprocess, "run", return_value=locked) as run,
        ):
            invalid = lookup.doctor_lookup([], root=self.root)
        self.assertFalse(invalid["answer"]["vaultwarden_session"]["available"])
        self.assertFalse(invalid["answer"]["keys"]["First key"]["available"])
        run.assert_called_once()

        malformed = subprocess.CompletedProcess([], 0, stdout="[]", stderr="")
        with (
            mock.patch.dict(os.environ, {"BW_SESSION": "session"}, clear=False),
            mock.patch.object(lookup, "load_config", return_value=config),
            mock.patch.object(lookup.shutil, "which", return_value="/bin/tool"),
            mock.patch.object(lookup.subprocess, "run", return_value=malformed),
        ):
            invalid_shape = lookup.doctor_lookup([], root=self.root)
        self.assertFalse(invalid_shape["answer"]["vaultwarden_session"]["available"])

    def test_parser_errors_are_json_with_exit_two(self):
        with mock.patch("builtins.print") as output:
            self.assertEqual(lookup.main([]), 2)
        self.assertEqual(
            json.loads(output.call_args.args[0])["status"], "bad arguments"
        )

    def test_research_run_refuses_local_kind_before_dispatch(self):
        with (
            mock.patch.dict(os.environ, {"RESEARCH_RUN": "test-topic"}),
            mock.patch.object(lookup, "dispatch") as dispatch,
            mock.patch("builtins.print") as output,
        ):
            self.assertEqual(lookup.main(["vault", "private-note"]), 2)
        dispatch.assert_not_called()
        self.assertIn(
            "unavailable inside a research gather run", output.call_args.args[0]
        )

    def test_fulltext_page_archive_carries_originating_identifier(self):
        page_outcome = {
            "status": "found",
            "answer": {"length": 10, "archive": "raw/page.json"},
            "source": {},
            "tried": [],
            "cached": False,
        }
        semantic = {
            "title": "Paper",
            "externalIds": {"DOI": "10.1145/example"},
            "openAccessPdf": {"url": "https://dl.acm.org/paper.pdf"},
        }
        with (
            mock.patch.object(lookup, "gateway_response") as gateway,
            mock.patch.object(lookup, "remote_json", return_value=(semantic, {})),
            mock.patch.object(lookup, "page_lookup", return_value=page_outcome) as page,
        ):
            response = lookup.fulltext_lookup(["10.1145/example"], root=self.root)
        self.assertEqual(response["status"], "found")
        self.assertEqual(page.call_args.kwargs["subject"], "10.1145/example")
        gateway.assert_called_once()

    def test_main_logs_local_lookup_and_uses_status_exit_codes(self):
        found = lookup.result(
            "doctor", {}, "found", {}, lookup.source("machine", "machine:doctor"), []
        )
        with (
            mock.patch.object(
                lookup, "dispatch", return_value=(found, "machine:doctor")
            ) as dispatch,
            mock.patch.object(lookup, "log_local") as log,
            mock.patch("builtins.print") as output,
        ):
            self.assertEqual(lookup.main(["doctor"]), 0)
        log.assert_called_once_with(found, "machine:doctor")
        dispatch.assert_called_once_with("doctor", [], fresh=False, references=False)
        rendered = json.loads(output.call_args.args[0])
        self.assertEqual(rendered["cached"], False)

    def test_main_bounds_large_json_and_leaves_full_archive(self):
        full_body = "archive-body-" + "z" * 2000

        def write_envelope(command, **_kwargs):
            archive = Path(command[2])
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_text(
                json.dumps(
                    {
                        "url": "https://api.github.com/graphql",
                        "requested_at": "2026-09-28T06:00:00Z",
                        "status": 200,
                        "body": full_body,
                    }
                )
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with (
            mock.patch.object(lookup.subprocess, "run", side_effect=write_envelope),
            mock.patch.object(lookup, "vault_root", return_value=self.root),
        ):
            response = lookup.gateway_response(
                "repo",
                ["example/large"],
                "GitHub GraphQL",
                "https://api.github.com/graphql",
                fresh=True,
                root=self.root,
            )
            source_value = lookup.source_from_response(response)
        outcome = lookup.result(
            "repo",
            {"repository": "example/large"},
            "found",
            {"text": "opening-" + "x" * 2000},
            source_value,
            [],
        )
        full_json = json.dumps(outcome, ensure_ascii=False)
        with (
            mock.patch.object(
                lookup, "dispatch", return_value=(outcome, "lookup:repo")
            ),
            mock.patch.object(
                lookup,
                "load_config",
                return_value={"lookup": {"max_output_chars": 500}},
            ),
            mock.patch("builtins.print") as output,
        ):
            self.assertEqual(lookup.main(["repo", "example/large"]), 0)
        printed = output.call_args.args[0]
        self.assertLessEqual(len(printed) + 1, 500)
        rendered = json.loads(printed)
        self.assertEqual(rendered["status"], "found")
        self.assertEqual(rendered["source"], outcome["source"])
        self.assertFalse(rendered["cached"])
        self.assertEqual(rendered["archive"], outcome["source"]["archive"])
        self.assertTrue(rendered["cut"])
        self.assertEqual(rendered["full_size"], len(full_json))
        self.assertTrue(rendered["answer"].startswith('{"text": "opening-'))
        self.assertEqual(json.loads(response.path.read_text())["body"], full_body)

    def test_main_leaves_under_limit_json_unchanged(self):
        outcome = lookup.result(
            "repo",
            {"repository": "example/small"},
            "found",
            {"text": "small"},
            lookup.source(
                "GitHub",
                "https://api.github.com/repos/example/small",
                archive="70_Research/_lookups/repo-small.json",
            ),
            [],
            cached=True,
        )
        expected = json.dumps(outcome, ensure_ascii=False)
        with (
            mock.patch.object(
                lookup, "dispatch", return_value=(outcome, "lookup:repo")
            ),
            mock.patch.object(
                lookup,
                "load_config",
                return_value={"lookup": {"max_output_chars": len(expected) + 1}},
            ),
            mock.patch.object(lookup, "log_local"),
            mock.patch("builtins.print") as output,
        ):
            self.assertEqual(lookup.main(["repo", "example/small"]), 0)
        self.assertEqual(output.call_args.args[0], expected)
        self.assertEqual(len(output.call_args.args[0]) + 1, len(expected) + 1)

    def test_cut_multi_response_names_every_recoverable_archive(self):
        shodan = self.response(
            "Shodan InternetDB",
            "https://internetdb.shodan.io/8.8.8.8",
            {"ports": list(range(1000)), "vulns": [], "hostnames": []},
            name="shodan.json",
        )
        greynoise = self.response(
            "GreyNoise community",
            "https://api.greynoise.io/v3/community/8.8.8.8",
            {"noise": False, "riot": True, "classification": "benign"},
            name="greynoise.json",
        )
        for response in (shodan, greynoise):
            response.path.write_text(json.dumps(response.envelope))
        with mock.patch.object(
            lookup, "gateway_response", side_effect=[shodan, greynoise]
        ):
            outcome = lookup.ip_lookup(["8.8.8.8"], root=self.root)

        rendered = json.loads(lookup.json_output(outcome, 700))
        expected = [str(shodan.path), str(greynoise.path)]
        self.assertTrue(rendered["cut"])
        self.assertEqual(rendered["archive"], expected[0])
        self.assertEqual(rendered["archives"], expected)
        for response in (shodan, greynoise):
            self.assertEqual(
                json.loads(response.path.read_text())["body"],
                response.envelope["body"],
            )

    def test_main_does_not_cut_unarchived_local_output(self):
        outcome = lookup.result(
            "ansible",
            {"module": "ansible.builtin.user"},
            "found",
            {"options": "x" * 2000},
            lookup.source("ansible-doc", "ansible-doc:ansible.builtin.user"),
            [{"source": "ansible-doc", "status": "found", "http": None}],
        )
        expected = json.dumps(outcome, ensure_ascii=False)
        with (
            mock.patch.object(
                lookup,
                "dispatch",
                return_value=(outcome, "ansible-doc:ansible.builtin.user"),
            ),
            mock.patch.object(
                lookup,
                "load_config",
                return_value={"lookup": {"max_output_chars": 300}},
            ),
            mock.patch.object(lookup, "log_local"),
            mock.patch("builtins.print") as output,
        ):
            self.assertEqual(lookup.main(["ansible", "ansible.builtin.user"]), 0)
        self.assertEqual(output.call_args.args[0], expected)
        self.assertNotIn("cut", json.loads(output.call_args.args[0]))

    def test_main_reports_output_configuration_errors_as_json(self):
        outcome = lookup.result(
            "repo",
            {"repository": "example/large"},
            "found",
            {"text": "x" * 2000},
            lookup.source(
                "GitHub",
                "https://api.github.com/graphql",
                archive="70_Research/_lookups/repo-large.json",
            ),
            [],
        )
        for config in ({}, {"lookup": {"max_output_chars": 10}}):
            with (
                self.subTest(config=config),
                mock.patch.object(
                    lookup, "dispatch", return_value=(outcome, "lookup:repo")
                ),
                mock.patch.object(lookup, "load_config", return_value=config),
                mock.patch("builtins.print") as output,
            ):
                self.assertEqual(lookup.main(["repo", "example/large"]), 1)
                self.assertEqual(
                    json.loads(output.call_args.args[0])["status"], "error"
                )

    def test_repo_path_preview_puts_requested_content_before_readme(self):
        response = self.response(
            "GitHub GraphQL",
            "https://api.github.com/graphql",
            {
                "data": {
                    "repository": {
                        "nameWithOwner": "owner/repo",
                        "description": "Example",
                        "url": "https://github.com/owner/repo",
                        "latestRelease": None,
                        "readme": {"text": "r" * 2000},
                        "target": {"text": "requested-file"},
                    }
                }
            },
        )
        with mock.patch.object(lookup, "gateway_response", return_value=response):
            outcome = lookup.repo_lookup(["owner/repo", "doc/file.md"], root=self.root)
        preview = json.loads(lookup.json_output(outcome, 500))["answer"]
        self.assertIn("requested-file", preview)
        self.assertNotIn('"readme"', preview)

    def test_cached_main_call_appends_real_lookup_log_without_gateway(self):
        url = "https://endoflife.date/api/almalinux.json"
        envelope = lookup.archive_path(
            "eol",
            ["almalinux", "10"],
            root=self.root,
            at=datetime(2026, 9, 26, 12, tzinfo=timezone.utc),
            run="",
        )
        envelope.parent.mkdir(parents=True)
        envelope.write_text(
            json.dumps(
                {
                    "url": url,
                    "requested_at": "2026-09-26T12:00:00Z",
                    "status": 200,
                    "body": json.dumps(
                        [
                            {
                                "cycle": "10",
                                "releaseDate": "2025-05-27",
                                "support": "2030-05-31",
                                "eol": "2035-05-31",
                                "latest": "10.0",
                            }
                        ]
                    ),
                    "lookup": lookup.lookup_identity("eol", ["almalinux", "10"]),
                }
            )
        )
        log_path = self.root / "lookup.jsonl"
        lock_path = self.root / "lookup.lock"
        real_append = lookup.append_log

        def append(entry):
            return real_append(entry, path=log_path, lock_path=lock_path)

        with (
            mock.patch.object(lookup, "vault_root", return_value=self.root),
            mock.patch.object(
                lookup,
                "utc_now",
                return_value=datetime(2026, 9, 26, 13, tzinfo=timezone.utc),
            ),
            mock.patch.object(lookup, "append_log", side_effect=append),
            mock.patch.object(lookup.subprocess, "run") as run,
            mock.patch("builtins.print") as output,
        ):
            self.assertEqual(lookup.main(["eol", "almalinux", "10"]), 0)
        run.assert_not_called()
        rendered = json.loads(output.call_args.args[0])
        self.assertTrue(rendered["cached"])
        lines = [json.loads(line) for line in log_path.read_text().splitlines()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["via"], "lookup")
        self.assertEqual(lines[0]["archive"], str(envelope.relative_to(self.root)))
        self.assertFalse(any(line["via"] == "gw" for line in lines))


if __name__ == "__main__":
    unittest.main()
