"""Attribute Codex context tokens to the action that put them there.

Same method as claude_tokens.py: every item that enters a Codex conversation is
sized and counted against each later model call that re-sent it. Writes
cx_items.jsonl and cx_calls.jsonl.
"""

import json, glob, os, re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claude_tokens import bash_kind, area  # noqa: E402

ROOT = os.path.expanduser("~/.codex/sessions")
OUT = os.environ.get("TOKEN_USAGE_OUT", os.getcwd())
CPT_OUT = float(os.environ.get("CX_CPT_OUT", "3.7"))  # tool output, fitted 2026-10-01
CPT_TXT = float(os.environ.get("CX_CPT_TXT", "4.9"))  # instructions and messages, fitted 2026-10-01

STR_RE = r'"((?:[^"\\]|\\.)*)"'


def js_str(s):
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return s


def classify_cell(code):
    """Return (action, target, desc) for one exec cell, from its first real tool call."""
    tools = re.findall(r"tools\.(\w+)\(", code)
    if not tools:
        return ("exec: plain JS", "", code[:120])
    t = tools[0]
    if t == "exec_command":
        m = re.search(r"cmd\s*:\s*" + STR_RE, code) or re.search(
            r'"cmd"\s*:\s*' + STR_RE, code
        )
        cmd = js_str(m.group(1)) if m else ""
        w = re.search(r'workdir"?\s*:\s*' + STR_RE, code)
        if w and cmd:
            cmd = "cd " + js_str(w.group(1)) + " && " + cmd
        k, tg = bash_kind(cmd) if cmd else ("exec_command (cmd not parsed)", "")
        if len(tools) > 1 and len(set(tools)) > 1:
            k = k
        return ("shell: " + k, tg, cmd[:160])
    if t == "apply_patch":
        m = re.search(r'\*\*\* (?:Add|Update|Delete) File: ([^\\\n"]+)', code)
        return (
            "apply_patch",
            area(m.group(1)) if m else "",
            (m.group(1) if m else "")[:160],
        )
    if t == "write_stdin":
        empty = re.search(r'chars\s*:\s*""', code) is not None
        return (
            "write_stdin (poll)" if empty else "write_stdin (input)",
            "",
            code[:120],
        )
    if t.startswith("web__"):
        return ("web search/open", "", code[:160])
    if t.startswith("clock"):
        return ("get the time", "", "")
    if "goal" in t:
        return ("goal tools", "", "")
    if t.startswith("mcp__"):
        return ("MCP: " + t.split("__")[1], "", "")
    return ("other tool: " + t, "", code[:120])


def user_kind(text):
    s = text.lstrip()
    if s.startswith("<environment_context>"):
        return "environment context"
    if s.startswith("# AGENTS.md") or "AGENTS.md instructions" in s[:200]:
        return "AGENTS.md"
    if s.startswith("<user_instructions>"):
        return "AGENTS.md"
    if s.startswith("<skill>") or "SKILL.md" in s[:300]:
        return "skill text"
    if s.startswith("<turn_aborted>") or s.startswith("<user_shell_command>"):
        return "session notices"
    if (
        "Review" in s[:400]
        and ("diff" in s[:2000] or "commit" in s[:2000])
        and len(s) > 1500
    ):
        return "review prompt"
    return "prompt / goal text"


def main():
    files = sorted(glob.glob(ROOT + "/**/*.jsonl", recursive=True))
    io = open(os.path.join(OUT, "cx_items.jsonl"), "w")
    co = open(os.path.join(OUT, "cx_calls.jsonl"), "w")
    for f in files:
        sess = os.path.basename(f)
        stype = "?"
        live, pending, calls = [], [], 0
        callmap = {}

        def add(kind, action, target, chars, tok, ts, desc="", to=None):
            it = {
                "f": sess,
                "stype": stype,
                "kind": kind,
                "action": action,
                "target": target,
                "chars": chars,
                "tok": tok,
                "ts": ts,
                "rides": 0,
                "born": calls,
                "desc": desc,
            }
            (to if to is not None else live).append(it)
            return it

        def flush(reason):
            for it in live + pending:
                it["end"] = reason
                io.write(json.dumps(it) + "\n")
            live.clear()
            pending.clear()

        for line in open(f):
            d = json.loads(line)
            p = d.get("payload") or {}
            ts = d.get("timestamp", "")
            ty = d["type"]
            if ty == "session_meta":
                src = p.get("source")
                stype = (
                    "review run"
                    if isinstance(src, dict) and src.get("subagent") == "review"
                    else "one-off codex exec"
                    if src == "exec"
                    else "interactive build session"
                )
                continue
            if ty == "compacted":
                flush("compacted")
                hist = p.get("replacement_history") or []
                txt = json.dumps(hist)
                add(
                    "compaction summary",
                    "replacement history",
                    "",
                    len(txt),
                    len(txt) / CPT_TXT,
                    ts,
                )
                continue
            if ty == "token_usage_record":
                u = p.get("usage") or {}
                ctx = u.get("input_tokens", 0)
                for it in live:
                    it["rides"] += 1
                calls += 1
                out = u.get("output_tokens", 0)
                rs = u.get("reasoning_output_tokens", 0)
                vis = [it for it in pending if it["kind"] != "reasoning"]
                n = sum(it["chars"] for it in vis)
                for it in pending:
                    if it["kind"] == "reasoning":
                        it["tok"] = rs / max(1, len(pending) - len(vis))
                    else:
                        it["tok"] = max(out - rs, 0) * it["chars"] / n if n else 0
                if rs and not any(it["kind"] == "reasoning" for it in pending):
                    pending.append(
                        {
                            "f": sess,
                            "stype": stype,
                            "kind": "reasoning",
                            "action": "",
                            "target": "",
                            "chars": 0,
                            "tok": rs,
                            "ts": ts,
                            "rides": 0,
                            "born": calls,
                            "desc": "",
                        }
                    )
                for it in pending:
                    it["born"] = calls
                live.extend(pending)
                pending.clear()
                co.write(
                    json.dumps(
                        {
                            "f": sess,
                            "stype": stype,
                            "ts": ts,
                            "ctx": ctx,
                            "cached": u.get("cached_input_tokens", 0),
                            "out": out,
                            "rs": rs,
                            "est": sum(it["tok"] for it in live),
                        }
                    )
                    + "\n"
                )
                continue
            if ty != "response_item":
                continue
            t = p.get("type")
            if t == "message":
                txt = "\n".join(
                    c.get("text", "")
                    for c in p.get("content", [])
                    if isinstance(c, dict)
                )
                role = p.get("role")
                if role == "assistant":
                    add("Codex reply", "", "", len(txt), 0, ts, to=pending)
                elif role == "developer":
                    add(
                        "developer instructions",
                        "",
                        "",
                        len(txt),
                        len(txt) / CPT_TXT,
                        ts,
                    )
                else:
                    add(
                        "user-side text",
                        user_kind(txt),
                        "",
                        len(txt),
                        len(txt) / CPT_TXT,
                        ts,
                        txt[:120],
                    )
            elif t == "reasoning":
                add("reasoning", "", "", 0, 0, ts, to=pending)
            elif t in ("custom_tool_call", "function_call"):
                code = p.get("input") or p.get("arguments") or ""
                if p.get("name") == "exec":
                    a, tg, desc = classify_cell(code)
                elif p.get("name") == "wait":
                    a, tg, desc = "wait on running command", "", code[:80]
                else:
                    a, tg, desc = "other tool: " + str(p.get("name")), "", code[:80]
                callmap[p.get("call_id")] = (a, tg, desc)
                add("tool_input", a, tg, len(code), 0, ts, desc, to=pending)
            elif t in ("custom_tool_call_output", "function_call_output"):
                o = p.get("output")
                if isinstance(o, list):
                    txt = "\n".join(c.get("text", "") for c in o if isinstance(c, dict))
                else:
                    txt = str(o)
                a, tg, desc = callmap.get(p.get("call_id"), ("?", "", ""))
                add("tool_result", a, tg, len(txt), len(txt) / CPT_OUT, ts, desc)
        flush("end")
    io.close()
    co.close()


if __name__ == "__main__":
    main()
