### What are you trying to do, and what stops you today?

Some Claude seats should start without particular MCP servers while keeping the rest. Our case is the claude.ai connectors: a team's seats shouldn't load the productivity connectors (mail, calendar, documents), but they keep a research connector and their plugin servers. Each connected server also adds startup context. One claude.ai connector with 19 tools added about 13,900 input tokens to every session start.

A rig spec can't express "this seat without server X" today:

- `claude_mcp: none` drops every MCP server, not just the unwanted ones.
- `claude_permissions.deny` with `mcp__<server>` hides that server's tools, but the server still connects and its server instructions still enter the prompt. In a test, a deny rule on that connector cut the cost from about 13,900 to about 1,600 tokens, and the instructions block was still there.
- `ENABLE_CLAUDEAI_MCP_SERVERS=false` in `env`, or the `disableClaudeAiConnectors` setting, turns off every claude.ai connector at once.
- Claude Code's per-folder `disabledMcpServers` in `~/.claude.json` works. But a new seat's folder starts without it, and writing that shared file at launch races every other Claude session that rewrites it.

### What would you like OpenRig to do?

A per-seat list of MCP servers to block, on rig spec members and in `rig seat set-permissions` like the other permission fields. For example:

```yaml
claude_denied_mcp_servers: ["claude.ai Gmail", "claude.ai Google Calendar"]
```

OpenRig already writes each Claude seat's `--settings` file, so it could put these names into that file's `deniedMcpServers`:

```json
{"deniedMcpServers": [{"serverName": "claude.ai Gmail"}, {"serverName": "claude.ai Google Calendar"}]}
```

I checked that this works for a single session on Claude Code 2.1.331. With `claude -p --settings '{"deniedMcpServers":[{"serverName":"claude.ai Firecrawl"}]}'`, that connector was absent from the startup event's `mcp_servers` and tools, and input tokens fell from 56,356 to 42,802, the same as a session without it. A run without the setting listed it as connected with its 19 tools. Claude Code's settings schema says `deniedMcpServers` merges from all sources, so users can deny servers for themselves.

Like `claude_mcp`, the field should carry through fresh, resume and fork launches, restores, handovers and exports.

### How do you handle it now?

Every Claude member in our rig specs denies the unwanted connectors' tools with `claude_permissions.deny`, and the existing folders carry `disabledMcpServers`. New seats get the tool-level deny only, so the connector still connects and its instructions still load.

### OpenRig version

0.7.19 (Claude Code 2.1.331, Linux)
