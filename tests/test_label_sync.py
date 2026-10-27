import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/label_sync"
WORKFLOW = ROOT / "tools/workflow"
OWNER = "sh4i-yurei"
INFRA = f"{OWNER}/keepbreathing-infra"
CLAUDE = f"{OWNER}/claude-config"


class LabelSync(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workflow = self.root / "workflow"
        shutil.copytree(WORKFLOW, self.workflow)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "gh"
        shutil.copy(FIXTURES / "fake_gh.py", fake)
        fake.chmod(0o755)
        self.env = dict(
            os.environ,
            PATH=f"{bin_dir}:{os.environ['PATH']}",
            FAKE_GH_STATE=str(self.root / "state.json"),
            FAKE_GH_CALLS=str(self.root / "calls.jsonl"),
            PYTHONDONTWRITEBYTECODE="1",
        )
        self.state = {
            "repos": json.loads((FIXTURES / "repos.json").read_text()),
            "labels": {
                f"{OWNER}/{file.stem}": json.loads(file.read_text())
                for file in FIXTURES.glob("*.json")
                if file.name != "repos.json"
            },
            "issues": {},
        }
        self.save()

    def save(self):
        Path(self.env["FAKE_GH_STATE"]).write_text(json.dumps(self.state))

    def run_sync(self, *args):
        result = subprocess.run(
            [sys.executable, self.workflow / "sync_labels.py", *args],
            text=True,
            capture_output=True,
            env=self.env,
            cwd=self.root,
        )
        self.state = json.loads(Path(self.env["FAKE_GH_STATE"]).read_text())
        return result

    def calls(self):
        path = Path(self.env["FAKE_GH_CALLS"])
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def test_dry_run_reports_exact_actions_and_makes_no_changes(self):
        before = json.dumps(self.state, sort_keys=True)
        result = self.run_sync("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.dumps(self.state, sort_keys=True), before)
        self.assertIn(f"{OWNER}/.github\n  create debt:code\n", result.stdout)
        self.assertIn("  delete bug\n", result.stdout)
        self.assertIn(f"{INFRA}\n  create debt:code\n", result.stdout)
        self.assertNotIn("  delete scope:hub\n", result.stdout)
        self.assertFalse(
            any(
                call[:2] in (["label", "create"], ["label", "delete"])
                for call in self.calls()
            )
        )

    def test_archived_and_exception_repositories_are_named_and_skipped(self):
        result = self.run_sync("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"skip {OWNER}/3ngram: archived\n", result.stdout)
        self.assertIn(f"skip {OWNER}/second-brain: exception\n", result.stdout)
        self.assertFalse(
            any(
                any("second-brain" in arg or "3ngram" in arg for arg in call)
                for call in self.calls()
            )
        )

    def test_new_repository_receives_all_global_labels(self):
        repo = f"{OWNER}/new-repo"
        self.state["repos"].append({"nameWithOwner": repo, "isArchived": False})
        self.state["labels"][repo] = []
        self.save()
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        labels = {item["name"] for item in self.state["labels"][repo]}
        self.assertEqual(
            labels,
            {
                "type:chore",
                "type:docs",
                "type:feature",
                "type:fix",
                "deferred",
                "workflow-exception",
                "tech-debt",
                "debt:accidental",
                "debt:bit-rot",
                "debt:deliberate",
                "debt:code",
                "debt:design",
                "debt:test",
                "debt:docs",
                "debt:infra",
                "dependencies",
                "github_actions",
            },
        )

    def test_unused_extra_label_is_deleted_with_yes(self):
        self.state["labels"][INFRA].append(
            {
                "name": "stray",
                "color": "ffffff",
                "description": "unused",
                "isDefault": False,
            }
        )
        self.save()
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(
            "stray", {label["name"] for label in self.state["labels"][INFRA]}
        )
        self.assertIn(
            ["label", "delete", "stray", "--repo", INFRA, "--yes"], self.calls()
        )

    def test_used_extra_label_blocks_exit_but_other_repositories_continue(self):
        self.state["labels"][INFRA].append(
            {
                "name": "stray",
                "color": "ffffff",
                "description": "used",
                "isDefault": False,
            }
        )
        self.state["issues"][INFRA] = {"stray": [14, 2]}
        self.save()
        result = self.run_sync()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(f"keep {INFRA} stray: open issues #2, #14\n", result.stdout)
        self.assertIn("stray", {label["name"] for label in self.state["labels"][INFRA]})
        self.assertTrue(
            any(
                call[:2] == ["label", "create"] and CLAUDE in call
                for call in self.calls()
            )
        )

    def test_open_pull_request_keeps_undefined_label_and_continues(self):
        self.state["labels"][INFRA].append(
            {
                "name": "stray",
                "color": "ffffff",
                "description": "used",
                "isDefault": False,
            }
        )
        self.state["pull_requests"] = {INFRA: {"stray": [29, 26]}}
        self.save()
        result = self.run_sync()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(
            f"keep {INFRA} stray: open pull requests #26, #29\n", result.stdout
        )
        self.assertIn("stray", {label["name"] for label in self.state["labels"][INFRA]})
        self.assertNotIn(
            ["label", "delete", "stray", "--repo", INFRA, "--yes"], self.calls()
        )
        self.assertTrue(
            any(
                call[:2] == ["label", "create"] and CLAUDE in call
                for call in self.calls()
            )
        )

    def test_changed_color_or_description_updates_with_force(self):
        target = next(
            item for item in self.state["labels"][INFRA] if item["name"] == "type:fix"
        )
        target.update(color="ffffff", description="wrong")
        self.save()
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            [
                "label",
                "create",
                "type:fix",
                "--repo",
                INFRA,
                "--color",
                "D73A4A",
                "--description",
                "Something broken",
                "--force",
            ],
            self.calls(),
        )

    def test_scope_label_stays_in_its_repository(self):
        self.state["labels"][INFRA] = [
            label
            for label in self.state["labels"][INFRA]
            if label["name"] != "scope:hub"
        ]
        self.save()
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "scope:hub", {label["name"] for label in self.state["labels"][INFRA]}
        )
        self.assertNotIn(
            "scope:hub", {label["name"] for label in self.state["labels"][CLAUDE]}
        )

    def test_second_application_has_no_actions(self):
        first = self.run_sync()
        self.assertEqual(first.returncode, 0, first.stderr)
        Path(self.env["FAKE_GH_CALLS"]).write_text("")
        second = self.run_sync()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertFalse(
            any(
                call[:2] in (["label", "create"], ["label", "delete"])
                for call in self.calls()
            )
        )
        self.assertNotIn("  create ", second.stdout)
        self.assertNotIn("  update ", second.stdout)
        self.assertNotIn("  delete ", second.stdout)

    def test_gh_failure_names_repo_label_and_own_error(self):
        self.state["failure"] = {
            "command": ["label", "create", "debt:code"],
            "message": "gh: permission denied",
        }
        self.save()
        result = self.run_sync()
        self.assertEqual(result.returncode, 2)
        self.assertIn(
            f"{OWNER}/.github debt:code: gh: permission denied", result.stderr
        )

    def test_invalid_configuration_exits_before_gh(self):
        for filename, content, expected in (
            ("labels.toml", None, "labels.toml: missing"),
            ("workflow.toml", "[", "workflow.toml: malformed"),
            (
                "labels.toml",
                "[global.missing]\ndescription = 'x'\n",
                "labels.toml: missing color",
            ),
        ):
            with self.subTest(filename=filename, content=content):
                path = self.workflow / filename
                original = path.read_text()
                if content is None:
                    path.unlink()
                else:
                    path.write_text(content)
                Path(self.env["FAKE_GH_CALLS"]).write_text("")
                try:
                    result = self.run_sync()
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(expected, result.stderr)
                    self.assertEqual(self.calls(), [])
                finally:
                    path.write_text(original)


if __name__ == "__main__":
    unittest.main()
