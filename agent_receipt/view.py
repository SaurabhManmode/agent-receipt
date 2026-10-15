"""Turns one or more Sessions into a renderer-neutral receipt view."""
from __future__ import annotations

import hashlib
import os
from collections import Counter
from datetime import datetime

from . import pricing, risk
from .model import Session, Usage


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def fmt_usd(x) -> str:
    if x is None:
        return "n/a"
    if x < 0.01 and x > 0:
        return "<$0.01"
    return f"${x:,.2f}"


def fmt_duration(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _short_path(p: str, cwd: str) -> str:
    if cwd and p.startswith(cwd.rstrip("/") + "/"):
        return p[len(cwd.rstrip("/")) + 1:]
    home = os.path.expanduser("~")
    if p.startswith(home):
        return "~" + p[len(home):]
    return p


def _cmd_name(cmd: str) -> str:
    """'cd x && FOO=1 sudo npm test' -> 'npm'."""
    import re
    for seg in re.split(r"&&|\|\||;|\n", cmd):
        toks = seg.split()
        while toks and ("=" in toks[0] and not toks[0].startswith("-") or toks[0] in ("sudo", "time", "nohup", "exec")):
            toks.pop(0)
        if not toks or toks[0] in ("cd", "pushd", "popd", "export", "set", "source", "."):
            continue
        return toks[0].split("/")[-1]
    return "?"


def build(sessions: list, title: str = "") -> dict:
    """Aggregate sessions into a view dict. One session -> session receipt."""
    agg = Session(agent="", session_id="", path="")
    agents = Counter()
    for s in sessions:
        risk.analyze(s)
        agents[s.agent] += 1
        for model, u in s.models.items():
            agg.models.setdefault(model, Usage()).add(u)
        agg.actions.extend(s.actions)
        agg.flags.extend(s.flags)
        agg.prompts += s.prompts
        for t in (s.started, s.ended):
            if t and (agg.started is None or t < agg.started):
                agg.started = t
            if t and (agg.ended is None or t > agg.ended):
                agg.ended = t
    single = sessions[0] if len(sessions) == 1 else None
    if single:
        agg.cwd, agg.git_branch = single.cwd, single.git_branch

    total, per_model = pricing.session_cost(agg.models)
    points = risk.score(agg)
    usage = agg.usage
    cwd = single.cwd if single else ""

    cmd_counts = Counter(_cmd_name(a.target) for a in agg.commands if a.target)
    tool_counts = Counter(a.tool for a in agg.actions)
    written = agg.files_written
    duration = sum(s.duration_s for s in sessions)

    seed = "".join(s.session_id for s in sessions) or "agent-receipt"
    order_no = hashlib.sha1(seed.encode()).hexdigest()[:8].upper()

    return {
        "title": title or ("AGENT RECEIPT" if single else "AGENT STATEMENT"),
        "single": bool(single),
        "agent": " + ".join(agents) if agents else "Unknown agent",
        "session_count": len(sessions),
        "order_no": order_no,
        "session_id": single.session_id if single else "",
        "project": os.path.basename(cwd.rstrip("/")) if cwd else "",
        "cwd": cwd,
        "branch": agg.git_branch,
        "started": agg.started,
        "ended": agg.ended,
        "duration": fmt_duration(duration) if duration else "n/a",
        "first_prompt": single.first_prompt if single else "",
        "prompts": agg.prompts,
        "models": [
            {"name": m, "tokens": u.total, "cost": per_model.get(m)}
            for m, u in sorted(agg.models.items(), key=lambda kv: -kv[1].total)
            if u.total or len(agg.models) == 1
        ],
        "usage": usage,
        "cost": total,
        "cache_savings": pricing.cache_savings(agg.models),
        "cache_hit": (usage.cache_read / (usage.input + usage.cache_read + usage.cache_write))
        if (usage.input + usage.cache_read + usage.cache_write) else 0.0,
        "tool_calls": len(agg.actions),
        "tool_counts": tool_counts.most_common(8),
        "commands": len(agg.commands),
        "top_commands": cmd_counts.most_common(5),
        "files_written": [_short_path(p, cwd) for p in written],
        "files_read": len(agg.files_read),
        "web": len(agg.of_kind("web")),
        "failures": agg.failures,
        "flags": [{"severity": f.severity, "rule": f.rule, "detail": _short_path(f.detail, cwd)}
                  for f in agg.flags],
        "score": points,
        "grade": risk.grade(points),
        "verdict": risk.verdict(agg, points),
        "generated": datetime.now().astimezone(),
    }
