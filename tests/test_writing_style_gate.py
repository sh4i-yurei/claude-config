import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks/writing-style-gate.py"
SPEC = importlib.util.spec_from_file_location("hooks.writing-style-gate", HOOK)
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)

FULL = (
    "Writing a vault note. Before this lands, read it as if you had never seen "
    "it: complete sentences rather than fragments, every piece of jargon "
    "explained the first time, one idea per sentence, the reason before the "
    "detail, and backticks only around real code identifiers. If a sentence only "
    "makes sense because you already know what you meant, rewrite it. Full "
    "directive: 40_Reference/writing-and-teaching-directive.md."
)
ALLOW_ONLY = {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
    }
}
ARROWS = "a -> b -> c"
MIDDOTS = "one · two"
BACKTICKS = "Run `alpha` then `beta` then `gamma` now ok"
ALL_HINTS = ARROWS + "\n" + MIDDOTS + "\n" + BACKTICKS
ARROW_HINT = "arrow chains standing in for sentences"
ALL_HINT_TEXT = (
    "arrow chains standing in for sentences, middots doing the job of grammar, "
    "a line that is mostly backticks with a few English words"
)


def allow_with(context):
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "additionalContext": context,
        }
    }


ALLOW_FULL = allow_with(FULL)


def repeat_hint(hints):
    return allow_with(
        "Writing a vault note: this draft appears to contain "
        + hints
        + ". Full directive: 40_Reference/writing-and-teaching-directive.md."
    )


MISSING = object()


def edit(path, text="Plain words in a sentence.", session="s1"):
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": str(path), "new_string": text},
    }
    if session is not MISSING:
        payload["session_id"] = session
    return payload


def write(path, text="Plain words in a sentence.", session="s1"):
    return {
        "session_id": session,
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": str(path), "content": text},
    }


def mode_of(path):
    return stat.S_IMODE(os.lstat(path).st_mode)


class GateTest(unittest.TestCase):
    def setUp(self):
        self.vault = self.temp_folder()
        self.runtime = self.temp_folder()
        self.cwd = self.temp_folder()
        self.elsewhere = self.temp_folder()
        previous = os.getcwd()
        os.chdir(self.cwd)
        self.addCleanup(os.chdir, previous)
        vault_patch = patch.object(GATE, "VAULT", self.vault)
        vault_patch.start()
        self.addCleanup(vault_patch.stop)
        env_patch = patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.runtime)})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.note = self.vault / "10_Projects" / "a.md"
        self.folder = self.runtime / "writing-style-gate"

    def temp_folder(self):
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        return Path(handle.name).resolve()

    def call(self, payload, umask=None):
        """Run the gate in-process on one payload; return its exit code and stdout."""
        text = payload if isinstance(payload, str) else json.dumps(payload)
        stdout = io.StringIO()
        previous = os.umask(umask) if umask is not None else None
        try:
            with (
                patch.object(sys, "stdin", io.StringIO(text)),
                contextlib.redirect_stdout(stdout),
            ):
                returned = GATE.main()
        finally:
            if previous is not None:
                os.umask(previous)
        return returned, stdout.getvalue()

    def assert_prints(self, payload, expected, umask=None):
        returned, output = self.call(payload, umask=umask)
        self.assertEqual(returned, 0)
        self.assertEqual(json.loads(output), expected)

    def assert_silent(self, payload):
        returned, output = self.call(payload)
        self.assertEqual(returned, 0)
        self.assertEqual(output, "")

    def assert_full_twice(self, payload):
        self.assert_prints(payload, ALLOW_FULL)
        self.assert_prints(payload, ALLOW_FULL)

    def record(self, session="s1"):
        return self.folder / session


class OncePerNotePerSession(GateTest):
    def test_second_edit_of_a_note_prints_only_the_allow_decision(self):
        self.assert_prints(edit(self.note), ALLOW_FULL)
        self.assert_prints(edit(self.note), ALLOW_ONLY)
        self.assertEqual(self.record().read_text(encoding="utf-8"), f"{self.note}\n")

    def test_another_note_in_the_same_session_gets_the_full_reminder(self):
        self.assert_prints(edit(self.note), ALLOW_FULL)
        self.assert_prints(edit(self.vault / "10_Projects" / "b.md"), ALLOW_FULL)

    def test_another_session_editing_the_same_note_gets_the_full_reminder(self):
        self.assert_prints(edit(self.note, session="s1"), ALLOW_FULL)
        self.assert_prints(edit(self.note, session="s2"), ALLOW_FULL)

    def test_write_after_edit_of_the_same_note_prints_only_the_allow_decision(self):
        self.assert_prints(edit(self.note), ALLOW_FULL)
        self.assert_prints(write(self.note), ALLOW_ONLY)

    def test_note_with_a_space_in_its_name_is_remembered(self):
        note = self.vault / "10_Projects" / "my note.md"
        self.assert_prints(edit(note), ALLOW_FULL)
        self.assert_prints(edit(note), ALLOW_ONLY)


class HintsOnRepeat(GateTest):
    def repeat_after_first_edit(self, text, hints):
        self.assert_prints(edit(self.note), ALLOW_FULL)
        self.assert_prints(edit(self.note, text), repeat_hint(hints))

    def test_arrow_chain_on_a_repeat(self):
        self.repeat_after_first_edit(ARROWS, ARROW_HINT)

    def test_middot_list_on_a_repeat(self):
        self.repeat_after_first_edit(MIDDOTS, "middots doing the job of grammar")

    def test_backtick_heavy_line_on_a_repeat(self):
        self.assertEqual(len(BACKTICKS), 43)
        self.repeat_after_first_edit(
            BACKTICKS, "a line that is mostly backticks with a few English words"
        )

    def test_all_three_hints_on_a_repeat(self):
        self.repeat_after_first_edit(ALL_HINTS, ALL_HINT_TEXT)

    def test_first_edit_with_an_arrow_chain_keeps_todays_output(self):
        self.assert_prints(
            edit(self.note, ARROWS),
            allow_with(
                FULL
                + " Specifically, this draft appears to contain "
                + ARROW_HINT
                + "."
            ),
        )

    def test_first_edit_with_all_three_hints_keeps_todays_output(self):
        self.assert_prints(
            edit(self.note, ALL_HINTS),
            allow_with(
                FULL
                + " Specifically, this draft appears to contain "
                + ALL_HINT_TEXT
                + "."
            ),
        )


class UnusableRuntimeFolder(GateTest):
    def assert_nothing_gained(self):
        self.assertEqual(list(self.runtime.iterdir()), [])
        self.assertEqual(list(self.cwd.iterdir()), [])

    def test_unset(self):
        with patch.dict(os.environ):
            del os.environ["XDG_RUNTIME_DIR"]
            self.assert_full_twice(edit(self.note))
        self.assert_nothing_gained()

    def test_empty(self):
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": ""}):
            self.assert_full_twice(edit(self.note))
        self.assert_nothing_gained()

    def test_relative(self):
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": "run"}):
            self.assert_full_twice(edit(self.note))
        self.assert_nothing_gained()

    def test_relative_path_to_an_existing_folder(self):
        (self.cwd / "run").mkdir()
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": "run"}):
            self.assert_full_twice(edit(self.note))
        self.assertEqual(list(self.cwd.iterdir()), [self.cwd / "run"])
        self.assertEqual(list((self.cwd / "run").iterdir()), [])
        self.assertEqual(list(self.runtime.iterdir()), [])

    def test_absolute_path_that_does_not_exist(self):
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.runtime / "missing")}):
            self.assert_full_twice(edit(self.note))
        self.assert_nothing_gained()


class UnusableSessionId(GateTest):
    def assert_unusable(self, session):
        self.assert_full_twice(edit(self.note, session=session))
        self.assertEqual(list(self.runtime.iterdir()), [])

    def test_missing(self):
        self.assert_unusable(MISSING)

    def test_empty(self):
        self.assert_unusable("")

    def test_parent_folder(self):
        self.assert_unusable("../x")

    def test_slash(self):
        self.assert_unusable("a/b")

    def test_dot(self):
        self.assert_unusable(".")

    def test_space(self):
        self.assert_unusable("s 1")

    def test_trailing_newline(self):
        self.assert_unusable("s1\n")

    def test_non_ascii(self):
        self.assert_unusable("sé")

    def test_number(self):
        self.assert_unusable(7)

    def test_null(self):
        self.assert_unusable(None)


class UnusableRecord(GateTest):
    def test_record_folder_is_a_plain_file(self):
        self.folder.write_text("not a folder\n", encoding="utf-8")
        self.assert_full_twice(edit(self.note))
        self.assertEqual(self.folder.read_text(encoding="utf-8"), "not a folder\n")

    def test_record_is_not_utf8_and_is_not_appended_to(self):
        self.folder.mkdir()
        self.record().write_bytes(b"\xff\xfe\n")
        self.assert_full_twice(edit(self.note))
        self.assertEqual(self.record().read_bytes(), b"\xff\xfe\n")

    def test_record_folder_is_a_link_to_a_real_folder(self):
        self.folder.symlink_to(self.elsewhere, target_is_directory=True)
        self.assert_full_twice(edit(self.note))
        self.assertEqual(list(self.elsewhere.iterdir()), [])

    def test_record_is_a_link(self):
        self.folder.mkdir()
        target = self.elsewhere / "target"
        target.write_text(f"{self.note}\n", encoding="utf-8")
        self.record().symlink_to(target)
        self.assert_full_twice(edit(self.note))
        self.assertEqual(target.read_text(encoding="utf-8"), f"{self.note}\n")
        self.assertEqual(list(self.elsewhere.iterdir()), [target])

    def test_record_that_cannot_be_created_still_gets_the_reminder(self):
        self.folder.mkdir(mode=0o500)
        self.addCleanup(os.chmod, self.folder, 0o700)
        self.assert_full_twice(edit(self.note))
        self.assertEqual(list(self.folder.iterdir()), [])


class RecordModes(GateTest):
    def test_folder_and_record_modes_under_a_strict_umask(self):
        self.assert_prints(edit(self.note), ALLOW_FULL, umask=0o177)
        self.assert_prints(edit(self.note), ALLOW_ONLY, umask=0o177)
        self.assert_prints(edit(self.note), ALLOW_ONLY, umask=0o177)
        self.assertTrue(self.record().is_file())
        self.assertEqual(mode_of(self.folder), 0o700)
        self.assertEqual(mode_of(self.record()), 0o600)
        self.assertEqual(self.record().read_text(encoding="utf-8"), f"{self.note}\n")

    def test_new_record_mode_under_an_open_umask(self):
        self.assert_prints(edit(self.note), ALLOW_FULL, umask=0)
        self.assertTrue(self.record().is_file())
        self.assertEqual(mode_of(self.record()), 0o600)

    def test_existing_folder_mode_is_left_alone(self):
        self.folder.mkdir()
        os.chmod(self.folder, 0o755)
        self.assert_prints(edit(self.note), ALLOW_FULL)
        self.assertEqual(mode_of(self.folder), 0o755)
        self.assert_prints(edit(self.note), ALLOW_ONLY)


class NoteWithANewline(GateTest):
    def test_never_recorded(self):
        note = self.vault / "10_Projects" / "a\nb.md"
        self.assert_full_twice(edit(note))
        record = self.record()
        self.assertFalse(
            record.exists() and str(note) in record.read_text(encoding="utf-8")
        )


class IgnoredInputs(GateTest):
    def assert_ignored(self, payload):
        self.assert_silent(payload)
        self.assertEqual(list(self.runtime.iterdir()), [])

    def test_readme(self):
        self.assert_ignored(edit(self.vault / "README.md"))

    def test_index(self):
        self.assert_ignored(edit(self.vault / "INDEX.md"))

    def test_template(self):
        self.assert_ignored(edit(self.vault / "_Templates" / "t.md"))

    def test_not_markdown(self):
        self.assert_ignored(edit(self.vault / "10_Projects" / "a.txt"))

    def test_outside_the_vault(self):
        self.assert_ignored(edit(self.elsewhere / "a.md"))

    def test_no_file_path(self):
        self.assert_ignored(
            {
                "session_id": "s1",
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {"new_string": "Plain words in a sentence."},
            }
        )

    def test_file_path_that_cannot_be_resolved(self):
        self.assert_ignored(edit("\u0000"))

    def test_input_that_is_not_json(self):
        self.assert_ignored("not json at all")


if __name__ == "__main__":
    unittest.main()
