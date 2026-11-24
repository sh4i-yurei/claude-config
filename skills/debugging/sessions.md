# Investigating an agent session

Use this when Mark wants to know why a Claude or Codex session went wrong: it repeated work,
ignored its handoff, stumbled, cost too much or took too long.

## Start with a problem statement

"It took too long" is a complaint, not a problem statement. Ask one question at a time until you
can write down which sessions, the turns or times if known, what Mark expected, what happened, and
the measure he cares about: time, tokens, a repeated action or one specific action. A request that
already names one event is its own problem statement. Don't read transcripts before this exists.

## Find the files

- Claude Code keeps main sessions at `~/.claude/projects/<project folder>/<session>.jsonl` and
  subagents at `<project folder>/<session>/subagents/agent-<id>.jsonl`, each with a `.meta.json`.
- Codex keeps sessions at `~/.codex/sessions/<year>/<month>/<day>/rollout-<time>-<uuid>.jsonl`.
  The first line is a `session_meta` record whose `payload.timestamp` is the start in UTC.
- A build session belongs to the handoff its first message names after "Follow the Request in"
  (codex-build-loop step 7).

These layouts were recorded as Facts in Token baseline and quick wins on 2026-11-21 and 2026-11-22.
Check again if a harness has been upgraded since. Confirm a past session by quoting its first
prompt's opening words and its start time, and list any candidates you rejected.

## Read safely

One transcript line can be over a megabyte, and printing it can flood your context.

1. Measure first: the file's lines and bytes, and which lines exceed 100,000 characters.
2. Never print whole records. Get line numbers and counts first, then small fields from specific
   lines with `jq` or `cut`.
3. If a command returns more than 500 characters for one record, narrow it.
4. Never modify, move or delete a session file.

Session files hold Mark's messages and every tool's output, which can include secrets. Quote as
little as a finding needs, and never copy transcript text into a public repository or a fixture
(Operating model decision 14; claude-config is public).

## What to look for

Only records Mark typed are his words. Hook output, system reminders and tool results are not. In a
subagent's or headless worker's file, "user" is the agent that started it.

- **Repeated work.** Group tool calls by tool and target: the file for reads and edits, the whole
  command for shell calls, the query for searches. Report reads or searches repeated three or more
  times, edits and shell commands repeated twice or more (status checks and test runs aside), and
  the same job started twice. Say what happened between repetitions: a re-read after an edit is
  fine, one after compaction is the compaction's, and one with nothing between is a finding. Also
  look for a conclusion reached twice, quoting both places.
- **Stumbles.** Failed calls and commands, retries after an error, reverted edits, "actually" or
  "that was wrong" in the agent's text, Mark correcting the last action, permission denials, hook
  failures, rate limits and compaction mid-task. Say what happened next for each.
- **Cost and time.** Use `claude-config/tools/token-usage/` with `--since` and `--until` rather
  than adding numbers by hand. Report the turns, tools and repeats that dominate, with numbers, and
  gaps of more than ten minutes between events.
- **Following the plan.** Compare what the session did with its handoff, queue row or spec, and say
  where it departed, especially after a compaction.

Independent angles can run as separate read-only `claude -p` jobs in labelled panes, each given
absolute file paths and one angle. A job's "current session" is its own, so never ask it to look at
"this session".

## Report

Every finding cites the absolute path and line with a short quote; a finding without one is dropped.
Every number comes from the transcript or a command you ran, never from memory. For a build item,
name each extra round's cause with the build loop's causes: spec gap, test case gap, builder error,
environment or process. The report goes in the project's buildlog. Report what happened; a change
to a rule, skill or the loop is a separate step through the owner of that text.

Adapted from the "diagnosing-superpowers" skill of the superpowers plugin 7.0.2, under the MIT
License. The full notice is in this folder's SKILL.md.
