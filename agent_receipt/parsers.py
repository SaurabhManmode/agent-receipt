"""Parsers for Claude Code and OpenAI Codex CLI session logs.

Both tools write JSONL transcripts to the user's home directory:

* Claude Code: ~/.claude/projects/<escaped-cwd>/<session-id>.jsonl
* Codex CLI:   ~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<id>.jsonl

Formats evolve, so every field access here is defensive: unknown lines are
skipped rather than crashing the receipt.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shlex
from datetime import datetime
from typing import Iterator, Optional

from .model import Action, Session, Usage

CLAUDE_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
CLAUDE_READ_TOOLS = {"Read", "NotebookRead"}
CLAUDE_SEARCH_TOOLS = {"Grep", "Glob", "LS"}
CLAUDE_WEB_TOOLS = {"WebFetch", "WebSearch"}


def _ts(value) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _lines(path: str) -> Iterator[dict]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj


def _touch_time(s: Session, ts: Optional[datetime]) -> None:
    if ts is None:
        return
    if s.started is None or ts < s.started:
        s.started = ts
    if s.ended is None or ts > s.ended:
        s.ended = ts


def _prompt_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
    return ""


def _is_real_prompt(text: str) -> bool:
    t = text.strip()
    return bool(t) and not t.startswith("<") and not t.startswith("Caveat:")


# ---------------------------------------------------------------- Claude Code
def parse_claude(path: str) -> Session:
    s = Session(agent="Claude Code", session_id=os.path.basename(path)[:-6], path=path)
    seen_msgs = set()
    pending: dict = {}  # tool_use_id -> Action

    for d in _lines(path):
        ts = _ts(d.get("timestamp"))
        typ = d.get("type")
        if typ in ("user", "assistant"):
            _touch_time(s, ts)
        s.cwd = s.cwd or d.get("cwd") or ""
        s.git_branch = s.git_branch or d.get("gitBranch") or ""
        msg = d.get("message") if isinstance(d.get("message"), dict) else {}

        if typ == "user":
            content = msg.get("content")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        act = pending.get(b.get("tool_use_id"))
                        if act is not None and b.get("is_error"):
                            act.failed = True
            if not d.get("isSidechain") and not d.get("isMeta"):
                text = _prompt_text(content)
                if _is_real_prompt(text) and not (isinstance(content, list) and any(
                        isinstance(b, dict) and b.get("type") == "tool_result" for b in content)):
                    s.prompts += 1
                    if not s.first_prompt:
                        s.first_prompt = " ".join(text.split())[:160]

        elif typ == "assistant":
            model = msg.get("model") or "unknown"
            usage = msg.get("usage")
            mid = msg.get("id") or d.get("requestId")
            if isinstance(usage, dict) and model != "<synthetic>" and (mid is None or mid not in seen_msgs):
                if mid:
                    seen_msgs.add(mid)
                u = s.models.setdefault(model, Usage())
                u.add(Usage(
                    input=int(usage.get("input_tokens") or 0),
                    output=int(usage.get("output_tokens") or 0),
                    cache_write=int(usage.get("cache_creation_input_tokens") or 0),
                    cache_read=int(usage.get("cache_read_input_tokens") or 0),
                ))
            elif model not in ("unknown", "<synthetic>"):
                s.models.setdefault(model, Usage())

            for b in msg.get("content") or []:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                if b.get("id") and b["id"] in pending:
                    continue  # same message logged twice
                name = b.get("name", "")
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                act = _claude_action(name, inp, ts)
                if act:
                    s.actions.append(act)
                    if b.get("id"):
                        pending[b["id"]] = act
    return s


def _claude_action(name: str, inp: dict, ts) -> Optional[Action]:
    if name == "Bash":
        return Action("command", name, str(inp.get("command", "")).strip(), ts)
    if name in CLAUDE_WRITE_TOOLS:
        return Action("write", name, str(inp.get("file_path") or inp.get("notebook_path") or ""), ts)
    if name in CLAUDE_READ_TOOLS:
        return Action("read", name, str(inp.get("file_path") or inp.get("notebook_path") or ""), ts)
    if name in CLAUDE_SEARCH_TOOLS:
        return Action("search", name, str(inp.get("pattern") or inp.get("path") or ""), ts)
    if name in CLAUDE_WEB_TOOLS:
        return Action("web", name, str(inp.get("url") or inp.get("query") or ""), ts)
    if name:
        return Action("tool", name, "", ts)
    return None


# ---------------------------------------------------------------- Codex CLI
_PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.M)


def _codex_command(args) -> str:
    cmd = args.get("command") if isinstance(args, dict) else None
    if isinstance(cmd, list):
        # ["bash", "-lc", "real command"] -> "real command"
        if len(cmd) >= 3 and cmd[0] in ("bash", "sh", "zsh") and cmd[1] in ("-lc", "-c"):
            return str(cmd[2])
        return shlex.join(str(c) for c in cmd)
    if isinstance(cmd, str):
        return cmd
    return ""


def parse_codex(path: str) -> Session:
    s = Session(agent="Codex", session_id=os.path.basename(path)[:-6], path=path)
    last_total: Optional[Usage] = None
    model = "unknown"
    calls: dict = {}

    for d in _lines(path):
        ts = _ts(d.get("timestamp"))
        typ = d.get("type")
        p = d.get("payload") if isinstance(d.get("payload"), dict) else d

        if typ == "session_meta":
            s.session_id = p.get("id") or s.session_id
            s.cwd = p.get("cwd") or s.cwd
            git = p.get("git") if isinstance(p.get("git"), dict) else {}
            s.git_branch = git.get("branch") or s.git_branch
            continue
        if typ == "turn_context":
            model = p.get("model") or model
            s.cwd = s.cwd or p.get("cwd") or ""
            s.models.setdefault(model, Usage())
            continue
        if typ == "event_msg":
            if p.get("type") == "token_count":
                info = p.get("info") if isinstance(p.get("info"), dict) else {}
                tot = info.get("total_token_usage") if isinstance(info.get("total_token_usage"), dict) else None
                if tot:
                    cached = int(tot.get("cached_input_tokens") or 0)
                    last_total = Usage(
                        input=max(0, int(tot.get("input_tokens") or 0) - cached),
                        output=int(tot.get("output_tokens") or 0),
                        cache_read=cached,
                    )
            elif p.get("type") == "user_message":
                text = str(p.get("message") or "")
                if _is_real_prompt(text):
                    s.prompts += 1
                    s.first_prompt = s.first_prompt or " ".join(text.split())[:160]
                _touch_time(s, ts)
            continue

        ptype = p.get("type")
        if ptype in ("function_call", "local_shell_call", "custom_tool_call", "message"):
            _touch_time(s, ts)
        if ptype == "function_call":
            name = p.get("name", "")
            try:
                args = json.loads(p.get("arguments") or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            if name in ("shell", "container.exec", "shell_command", "exec_command"):
                act = Action("command", name, _codex_command(args) or str(args.get("cmd", "")), ts)
            elif name == "apply_patch":
                act = None
                for f in _PATCH_FILE.findall(str(args.get("input", ""))):
                    s.actions.append(Action("write", name, f.strip(), ts))
            else:
                act = Action("tool", name, "", ts)
            if act:
                s.actions.append(act)
                calls[p.get("call_id")] = act
        elif ptype == "local_shell_call":
            action = p.get("action") if isinstance(p.get("action"), dict) else {}
            act = Action("command", "local_shell", _codex_command(action), ts)
            s.actions.append(act)
            calls[p.get("call_id")] = act
        elif ptype == "custom_tool_call":
            name = p.get("name", "")
            if name == "apply_patch":
                for f in _PATCH_FILE.findall(str(p.get("input", ""))):
                    s.actions.append(Action("write", name, f.strip(), ts))
            else:
                s.actions.append(Action("tool", name, "", ts))
        elif ptype in ("function_call_output", "custom_tool_call_output"):
            act = calls.get(p.get("call_id"))
            out = p.get("output")
            if act is not None:
                code = None
                if isinstance(out, str):
                    try:
                        code = (json.loads(out).get("metadata") or {}).get("exit_code")
                    except (json.JSONDecodeError, AttributeError):
                        m = re.search(r"[Ee]xit code:? (\d+)", out)
                        code = int(m.group(1)) if m else None
                if code not in (None, 0):
                    act.failed = True
        elif ptype == "message" and p.get("role") == "user" and s.prompts == 0:
            # older Codex logs without user_message events
            text = _prompt_text(p.get("content"))
            if not text and isinstance(p.get("content"), list):
                for b in p["content"]:
                    if isinstance(b, dict) and b.get("type") == "input_text":
                        text = b.get("text", "")
                        break
            if _is_real_prompt(text) and "<environment_context>" not in text:
                s.first_prompt = " ".join(text.split())[:160]

    if last_total is not None:
        s.models = {model: last_total}
    return s


# ---------------------------------------------------------------- discovery
def claude_home() -> str:
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def codex_home() -> str:
    return os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")


def find_sessions(agent: str = "all") -> list:
    """Return [(mtime, agent, path)] newest first."""
    out = []
    if agent in ("all", "claude"):
        for p in glob.glob(os.path.join(claude_home(), "projects", "*", "*.jsonl")):
            out.append((os.path.getmtime(p), "claude", p))
    if agent in ("all", "codex"):
        for p in glob.glob(os.path.join(codex_home(), "sessions", "**", "*.jsonl"), recursive=True):
            out.append((os.path.getmtime(p), "codex", p))
    out.sort(reverse=True)
    return out


def detect_agent(path: str) -> str:
    for d in _lines(path):
        if d.get("type") in ("session_meta", "turn_context", "response_item", "event_msg"):
            return "codex"
        if d.get("type") in ("user", "assistant", "summary") or "sessionId" in d:
            return "claude"
    return "claude"


def parse(path: str, agent: Optional[str] = None) -> Session:
    agent = agent or detect_agent(path)
    return parse_codex(path) if agent == "codex" else parse_claude(path)
