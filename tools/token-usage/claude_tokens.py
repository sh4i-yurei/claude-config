"""Attribute Claude Code context tokens to the action that put them there.

For every item that enters a conversation (tool output, tool input Claude wrote,
replies, thinking, skill text, reminders, Mark's messages) record its size and
how many later model calls re-sent it. Writes items.jsonl and calls.jsonl.
"""

import json, glob, os, re, sys, collections

ROOT = os.path.expanduser("~/.claude/projects")
OUT = os.environ.get("TOKEN_USAGE_OUT", os.getcwd())  # data files go where it is run, never in the repo
HOME = os.path.expanduser("~")
CPT = 3.05  # reminders, skill text and other injected text
CPT_TOOL = {"Bash": 2.65, "Read": 2.23, "MCP": 2.14}  # tool output, fitted against real context growth
CPT_TOOL_OTHER = 2.34
CPT_MARK = 2.88
FRAMING = 262  # tokens of message wrapping each model call adds


def area(path):
    """Classify a file path into a readable area."""
    if not path:
        return "?"
    p = path.replace(HOME, "~")
    m = re.search(r"Second_Brain/([^/]+)(?:/([^/]+))?", p)
    if m:
        top = m.group(1)
        if top in ("INDEX.md", "README.md"):
            return "vault:" + top
        if top == ".claude":
            return "vault:.claude (skills)"
        return "vault:" + top
    if "/.claude/projects/" in p and "/tool-results/" in p:
        return "claude:saved tool output"
    if "/.claude/projects/" in p:
        return "claude:session transcripts"
    if "/.claude/plugins/" in p:
        return "claude:plugins"
    if "Documents/claude-config" in p:
        return "repo:claude-config"
    if "Documents/codex-config" in p:
        return "repo:codex-config"
    if "/.claude/skills/" in p:
        return "claude:skills"
    if "/.claude/" in p:
        return "claude:config"
    if "/.codex/sessions" in p:
        return "codex:session files"
    if "/.codex/" in p:
        return "codex:config"
    if p.startswith("/tmp/") or p.startswith("/var/tmp"):
        return "tmp"
    m = re.match(r"~/Documents/([^/]+)", p)
    if m:
        return "repo:" + m.group(1)
    m = re.match(r"~/(\.[^/]+|[^/]+)", p)
    if m:
        return "home:" + m.group(1)
    if p.startswith("/etc") or p.startswith("/usr"):
        return "system files"
    return "other path"


PATH_RE = re.compile(
    r'(~/[^\s\'";|&>)]+|/(?:var|tmp|etc|usr|home)/[^\s\'";|&>)]+|(?:Documents|\.claude|\.codex)/[^\s\'";|&>)]+)'
)
READERS = {"cat", "sed", "head", "tail", "less", "awk", "nl", "jq", "bat"}
SEARCHERS = {"grep", "rg", "egrep", "ag"}
LISTERS = {"ls", "find", "tree", "du", "wc", "stat", "fd"}


SKIP = {"cd", "export", "set", "source", ".", "unset", "shopt", "trap", "{", "}", "(", ")", "then", "fi", "done", "else", "local"}


def bash_kind(cmd):
    """Classify a shell command into (verb, target), following cd and variables."""
    head = cmd.split("<<", 1)[0] if "<<" in cmd.split("\n", 1)[0] else "\n".join(cmd.split("\n")[:6])
    hd = "<<" in cmd.split("\n", 1)[0]
    vars_ = {"HOME": HOME}
    cwd = HOME
    segs = re.split(r"&&|\|\||;|\n|\bdo\b", head)
    chosen = None
    fallback = None
    for seg in segs:
        seg = seg.strip().lstrip("({ !").strip()
        if not seg:
            continue
        for k, v in vars_.items():
            seg = seg.replace("${" + k + "}", v).replace("$" + k, v)
        seg = re.sub(r"~(?=/|\s|$)", HOME, seg)
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|\S*)$", seg)
        if m:
            vars_[m.group(1)] = m.group(2).strip("\"'")
            continue
        seg = re.sub(r"^([A-Za-z_][A-Za-z0-9_]*=\S*\s+)+", "", seg)
        words = seg.split()
        if not words:
            continue
        if words[0] == "cd" and len(words) > 1:
            d = words[1].strip("\"'")
            cwd = d if d.startswith("/") else os.path.normpath(os.path.join(cwd, d))
            continue
        if words[0] in SKIP or words[0].startswith("#"):
            continue
        if words[0] in ("for", "while", "if", "until"):
            continue
        if words[0] in ("echo", "printf", "date", "true", "sleep", "exit") and fallback is None:
            fallback = seg
            continue
        if words[0] in ("echo", "printf", "date", "true", "sleep", "exit"):
            continue
        chosen = seg
        break
    if chosen is None:
        chosen = fallback
    if chosen is None:
        return ("cd/setup only", area(cwd))
    words = chosen.split()
    w0 = os.path.basename(words[0])
    if w0 in ("timeout", "time", "nice", "env", "command", "sudo", "flatpak-spawn", "stdbuf"):
        rest = [w for w in words[1:] if not w.startswith("-") and not re.match(r"^[0-9.]+[sm]?$", w) and "=" not in w]
        if rest:
            k, t = bash_kind(" ".join(words[words.index(rest[0]):]))
            return (k, t if t != "~" else area(cwd))
    def tgt_of(ws):
        for w in ws[1:]:
            w = w.strip("\"'")
            if w.startswith("-") or not w or w.startswith("$"):
                continue
            if "/" in w or "." in w:
                p = w if w.startswith("/") else os.path.join(cwd, w)
                return area(p)
        return area(cwd)
    tgt = tgt_of(words)
    if w0 in ("distrobox", "dev"):
        return ("dev container", tgt)
    if w0 in ("ssh", "scp", "rsync"):
        host, skip = "?", False
        for w in words[1:]:
            if skip:
                skip = False
                continue
            if w in ("-o", "-i", "-p", "-J", "-l", "-F", "-e"):
                skip = True
                continue
            if not w.startswith("-"):
                host = w
                break
        return ("ssh/" + w0, host.split("@")[-1].split(":")[0])
    if w0 in ("python3", "python", "uv", "node", "bash", "sh"):
        if hd:
            return ("inline script (" + w0 + " heredoc)", area(cwd))
        if re.search(r"\s-c\s", chosen):
            return ("inline one-liner (" + w0 + " -c)", area(cwd))
        script = next((w for w in words[1:] if not w.startswith("-")), "")
        if "query.py" in script or "sweep" in script or "vault" in script:
            return ("vault script", os.path.basename(script))
        if script.endswith(".py") or script.endswith(".sh"):
            return ("run script", os.path.basename(script))
        return ("run " + w0, area(cwd))
    if hd and (re.search(r"\bcat\s*>", chosen) or w0 == "tee"):
        m = re.search(r">+\s*(\S+)", chosen) if w0 != "tee" else None
        p = (m.group(1).strip("\"'") if m else (words[-1] if len(words) > 1 else "")).split("<<")[0]
        p = p if p.startswith("/") else os.path.join(cwd, p)
        return ("write file (heredoc)", area(p))
    if w0 in READERS:
        return ("read file (" + w0 + ")", tgt)
    if w0 in SEARCHERS:
        return ("search (" + w0 + ")", tgt)
    if w0 in LISTERS:
        return ("list/find (" + w0 + ")", tgt)
    if w0 in ("git", "gh"):
        sub = next((w for w in words[1:] if not w.startswith("-") and "/" not in w), "")
        return (w0 + " " + sub, area(cwd))
    if w0.startswith("ansible"):
        return ("ansible", w0)
    if w0 in ("vale", "ruff", "pytest", "mypy", "shellcheck", "markdownlint", "yamllint"):
        return ("lint/test (" + w0 + ")", tgt)
    if w0 in ("obsidian",):
        return ("obsidian cli", words[1] if len(words) > 1 else "")
    if w0 in ("codex", "claude"):
        return (w0 + " cli", words[1] if len(words) > 1 else "")
    if w0 in ("echo", "printf"):
        return ("echo/printf", area(cwd))
    if w0 in ("mkdir", "cp", "mv", "rm", "touch", "chmod", "ln", "tee", "date", "sleep", "true", "test", "[", "which", "type", "diff", "cmp", "sort", "uniq"):
        return ("small shell (" + w0 + ")", tgt)
    if w0.endswith(".py") or w0.endswith(".sh") or "/" in words[0]:
        if "lookup" in w0 or "research" in w0:
            return ("run script", w0)
        return ("run script", w0)
    return (w0, tgt)


def block_text(content):
    """Visible text of a tool_result content field."""
    if isinstance(content, str):
        return content, 0
    out, imgs = [], 0
    for b in content or []:
        if b.get("type") == "text":
            out.append(b.get("text", ""))
        elif b.get("type") == "image":
            imgs += 1
        elif b.get("type") == "tool_reference":
            out.append(b.get("tool_name", ""))
        else:
            out.append(json.dumps(b))
    return "\n".join(out), imgs


def flat(x):
    """Flatten rendered attachment content to text."""
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        if x.get("type") == "image":
            return "x" * int(1600 * CPT)
        return flat(x.get("content", x.get("text", "")))
    if isinstance(x, list):
        return "\n".join(flat(i) for i in x)
    return str(x)


def project_of(f):
    d = f.split("/")[0]
    if d.startswith("-tmp-research-check"):
        return "research harness (headless checks)"
    d = d.replace("-var-home-sh4i-yurei", "~").replace("-Documents-", "Documents/")
    return d or "~"


def main():
    files = glob.glob("**/*.jsonl", root_dir=ROOT, recursive=True)

    def first_ts(f):
        with open(os.path.join(ROOT, f)) as fh:
            for line in fh:
                if '"timestamp"' in line:
                    try:
                        return json.loads(line).get("timestamp") or ""
                    except Exception:
                        pass
        return ""

    files.sort(key=first_ts)
    seen_calls = set()
    items_out = open(os.path.join(OUT, "items.jsonl"), "w")
    calls_out = open(os.path.join(OUT, "calls.jsonl"), "w")
    for f in files:
        path = os.path.join(ROOT, f)
        is_sub = "/subagents/" in f
        agent = "main"
        if is_sub:
            try:
                agent = "subagent:" + json.load(
                    open(path.replace(".jsonl", ".meta.json"))
                ).get("agentType", "?")
            except Exception:
                agent = "subagent:?"
        proj = project_of(f)
        sess = f.split("/")[1].replace(".jsonl", "") if not is_sub else f.split("/")[1]
        live = []  # items currently in context
        tool_names = {}  # tool_use id -> (tool, kind, target, skill)
        cur_msg = None
        last_skill = None
        prev_ctx = None
        call_ix = 0

        def add(kind, tool, detail, target, chars, tok, ts, extra=None):
            it = {
                "f": f,
                "sess": sess,
                "proj": proj,
                "agent": agent,
                "kind": kind,
                "tool": tool,
                "detail": detail,
                "target": target,
                "chars": chars,
                "tok": tok,
                "ts": ts,
                "rides": 0,
                "born": call_ix,
            }
            if extra:
                it.update(extra)
            live.append(it)

        cur_blocks = []
        cur_out = {"rest": 0}

        def settle():
            """Give the message's exact output tokens to its blocks by size."""
            n = sum(b["chars"] for b in cur_blocks)
            for b in cur_blocks:
                b["tok"] = cur_out["rest"] * b["chars"] / n if n else 0
            cur_blocks.clear()

        def flush(reason):
            settle()
            for it in live:
                it["end"] = reason
                items_out.write(json.dumps(it) + "\n")
            live.clear()

        for line in open(path):
            try:
                d = json.loads(line)
            except Exception:
                continue
            t = d.get("type")
            ts = d.get("timestamp", "")
            if t == "system" and d.get("subtype") == "compact_boundary":
                flush("compacted")
                continue
            if t == "attachment":
                a = d.get("attachment", {})
                r = d.get("rendered")
                if not r:
                    continue
                txt = flat(r)
                at = a.get("type")
                detail = at
                if at == "hook_additional_context" or at == "hook_success":
                    detail = at + ":" + (a.get("hookName") or "?")
                if at == "queued_command":
                    add("Mark message", "", "queued while Claude worked", "", len(txt), len(txt) / CPT_MARK, ts)
                    continue
                if at == "invoked_skills":
                    add("skill text", "", "re-sent after compaction", "", len(txt), len(txt) / CPT, ts)
                    continue
                if at == "edited_text_file":
                    detail = at + ":" + area(a.get("filename"))
                add("reminder", "attachment", detail, "", len(txt), len(txt) / CPT, ts)
                continue
            if t == "user":
                msg = d.get("message", {})
                c = msg.get("content")
                origin = (d.get("origin") or {}).get("kind")
                if isinstance(c, str):
                    c = [{"type": "text", "text": c}]
                for b in c or []:
                    bt = b.get("type")
                    if bt == "tool_result":
                        txt, imgs = block_text(b.get("content"))
                        tn = tool_names.get(b.get("tool_use_id"), ("?", "", "", None, ""))
                        tok = len(txt) / CPT_TOOL.get(tn[0], CPT_TOOL_OTHER) + imgs * 1600
                        add(
                            "tool_result",
                            tn[0],
                            tn[1],
                            tn[2],
                            len(txt),
                            tok,
                            ts,
                            {"err": bool(b.get("is_error")), "skill": tn[3], "desc": tn[4]},
                        )
                    elif bt == "text":
                        txt = b.get("text", "")
                        if d.get("isCompactSummary"):
                            kind, detail = "compaction summary", ""
                        elif txt.startswith("Base directory for this skill:"):
                            m = re.search(r"skills/([^/\n]+)", txt)
                            kind, detail = "skill text", (m.group(1) if m else "?")
                            last_skill = detail
                        elif d.get("isMeta") and txt.startswith("# "):
                            kind, detail = "skill text", "built-in: " + txt[2:40].split("\n")[0]
                        elif "Stop hook is now active with condition" in txt:
                            kind, detail = "goal condition", ""
                        elif txt.startswith("Stop hook feedback"):
                            kind, detail = (
                                "hook feedback",
                                re.search(r"\[([^\]]+)\]", txt).group(1).split("/")[-1]
                                if "[" in txt
                                else "?",
                            )
                        elif "<command-name>" in txt or "<local-command" in txt:
                            m = re.search(r"<command-name>([^<]+)", txt)
                            kind, detail = (
                                "slash command",
                                (m.group(1) if m else "local output"),
                            )
                        elif txt.lstrip().startswith("<task-notification>"):
                            kind, detail = "background task notice", ""
                        elif (
                            origin == "peer"
                            or "Another Claude session sent a message" in txt
                        ):
                            kind, detail = "agent message", ""
                        elif origin == "human" or (
                            origin is None and not d.get("isMeta")
                        ):
                            kind, detail = (
                                "Mark message",
                                ("pasted" if "<pasted_content" in txt else ""),
                            )
                        else:
                            kind, detail = "system message", origin or ""
                        add(kind, "", detail, "", len(txt), len(txt) / (CPT_MARK if kind == "Mark message" else CPT), ts)
                    elif bt == "image":
                        add("Mark message", "", "image", "", 0, 1600, ts)
                continue
            if t == "assistant":
                msg = d.get("message", {})
                mid = msg.get("id")
                model = msg.get("model", "")
                if model == "<synthetic>":
                    continue
                u = msg.get("usage") or {}
                if mid != cur_msg:
                    cur_msg = mid
                    ctx = (
                        u.get("input_tokens", 0)
                        + u.get("cache_creation_input_tokens", 0)
                        + u.get("cache_read_input_tokens", 0)
                    )
                    key = (mid, d.get("requestId"))
                    new = key not in seen_calls
                    seen_calls.add(key)
                    est = sum(it["tok"] for it in live)
                    if new:
                        for it in live:
                            it["rides"] += 1
                        call_ix += 1
                    calls_out.write(
                        json.dumps(
                            {
                                "f": f,
                                "sess": sess,
                                "proj": proj,
                                "agent": agent,
                                "ts": ts,
                                "model": model,
                                "new": new,
                                "ctx": ctx,
                                "in": u.get("input_tokens", 0),
                                "cw": u.get("cache_creation_input_tokens", 0),
                                "cr": u.get("cache_read_input_tokens", 0),
                                "out": u.get("output_tokens", 0),
                                "think": (u.get("output_tokens_details") or {}).get(
                                    "thinking_tokens", 0
                                ),
                                "est_live": est,
                                "n_live": len(live),
                            }
                        )
                        + "\n"
                    )
                    # output tokens apportioned over this message's blocks below
                    out_tok = u.get("output_tokens", 0)
                    think_tok = (u.get("output_tokens_details") or {}).get(
                        "thinking_tokens", 0
                    )
                    settle()
                    if new:
                        add("message framing", "", "", "", 0, FRAMING, ts)
                    if think_tok:
                        add("thinking", "", "", "", 0, think_tok, ts)
                    cur_out["rest"] = 0.93 * max(out_tok - think_tok, 0)
                for b in msg.get("content", []):
                    bt = b.get("type")
                    if bt == "thinking":
                        continue
                    if bt == "text":
                        txt = b.get("text", "")
                        add("Claude reply", "", "", "", len(txt), len(txt) / CPT, ts)
                        cur_blocks.append(live[-1])
                    elif bt == "tool_use":
                        name = b.get("name", "?")
                        inp = b.get("input", {}) or {}
                        kind, target, skill = "", "", None
                        if name == "Bash":
                            kind, target = bash_kind(inp.get("command", ""))
                            if last_skill:
                                skill = last_skill
                        elif name in ("Read", "Write", "Edit", "NotebookEdit"):
                            kind, target = name, area(inp.get("file_path"))
                        elif name in ("Grep", "Glob"):
                            kind, target = name, area(inp.get("path") or "")
                        elif name == "Skill":
                            kind = inp.get("skill", "?")
                        elif name in ("Agent", "Task"):
                            kind = inp.get("subagent_type", "general-purpose")
                        elif name.startswith("mcp__"):
                            parts = name.split("__")
                            kind, target = parts[1], parts[-1]
                            name = "MCP"
                        desc = (inp.get("command") or inp.get("file_path") or inp.get("pattern")
                                or inp.get("skill") or inp.get("description") or inp.get("url")
                                or inp.get("query") or json.dumps(inp))[:160]
                        tool_names[b.get("id")] = (name, kind, target, skill, desc)
                        txt = json.dumps(inp)
                        add(
                            "tool_input",
                            name,
                            kind,
                            target,
                            len(txt),
                            len(txt) / CPT,
                            ts,
                            {"desc": desc},
                        )
                        cur_blocks.append(live[-1])
                continue
        flush("end")
    items_out.close()
    calls_out.close()


if __name__ == "__main__":
    main()
