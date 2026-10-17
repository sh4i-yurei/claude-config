# token-usage

Measures where Claude Code's and Codex's tokens go, from their own session files, and what
outsourcing a kind of work would have saved. I use it to size the local agent layer and to check
each change before and after.

Every model call re-sends the whole conversation so far. So the cost of anything that enters a
conversation (a file read, a command's output, a skill, Claude's own reasoning) is its size times
the number of later calls that carried it. These scripts record that for every item, fitted against
the real context sizes the API reported, and scaled so the parts add up to the exact totals.

## Running it

Run the scripts from an empty scratch folder. They write their data files into the folder they are
run from, or into `$TOKEN_USAGE_OUT`, never into this repository.

```bash
mkdir -p /tmp/token-usage && cd /tmp/token-usage
python3 ~/Documents/claude-config/tools/token-usage/claude_tokens.py   # reads ~/.claude/projects
python3 ~/Documents/claude-config/tools/token-usage/codex_tokens.py    # reads ~/.codex/sessions
python3 ~/Documents/claude-config/tools/token-usage/analyze_claude.py summary
python3 ~/Documents/claude-config/tools/token-usage/analyze_codex.py detail
python3 ~/Documents/claude-config/tools/token-usage/simulate.py claude
python3 ~/Documents/claude-config/tools/token-usage/simulate.py codex
```

- `claude_tokens.py` and `codex_tokens.py` parse the session files into `items.jsonl`,
  `calls.jsonl`, `cx_items.jsonl` and `cx_calls.jsonl`.
- `analyze_claude.py` ranks what put tokens into Claude's context. Its modes are `top`, `tools`,
  `inputs`, `injected`, `singles` and `summary`.
- `analyze_codex.py` does the same for Codex, with `detail` for the full tables.
- `simulate.py` replays the real conversations with one kind of work handed to a local helper and
  recomputes every later call. It reports two bounds: step by step, where each step's output is
  condensed and no calls disappear, and whole runs, where a run of steps becomes one request.

## Limits

- The characters-per-token rates were fitted on 2026-10-01 against Opus 5 and Codex's tokenizers.
  Refit them if a model changes: the regression is in the 2026-10-01 session record and the method
  is in the vault, in `00_Inbox/local-agent-layer-idea.md` under "What put the tokens there".
- Categories are good to about 10%. Totals are exact.
- Claude Code deletes session files after 30 days, so the window it can measure is the last month.
