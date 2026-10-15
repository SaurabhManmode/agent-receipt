"""Thermal-printer style receipt for the terminal."""
from __future__ import annotations

import os
import sys

from .view import fmt_tokens, fmt_usd

W = 46


class _C:
    def __init__(self, on: bool):
        self.on = on

    def __call__(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.on else text


def _use_color(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def _row(left: str, right: str, width: int = W) -> str:
    left = left if len(left) + len(right) + 1 <= width else left[: width - len(right) - 2] + "…"
    return left + " " * (width - len(left) - len(right)) + right


def _center(text: str) -> str:
    return text.center(W).rstrip()


def _trim(text: str, n: int = W - 4) -> str:
    return text if len(text) <= n else "…" + text[-(n - 1):]


def _barcode(seed: str) -> str:
    bars = "▌▍▎▏▋▊▉█ "
    return "".join(bars[int(c, 16) % len(bars)] for c in (seed * 6)[:W - 8])


def render(v: dict, color=None) -> str:
    c = _C(_use_color(sys.stdout) if color is None else color)
    dash, dot = "-" * W, "·" * W
    sev_color = {"high": "1;31", "medium": "33", "low": "2"}
    out = []
    add = out.append

    add("")
    add(c("1", _center(f"*** {v['title']} ***")))
    add(_center(v["agent"]))
    if v["project"]:
        add(_center(f"project: {v['project']}" + (f" @ {v['branch']}" if v["branch"] else "")))
    if v["started"]:
        add(_center(v["started"].astimezone().strftime("%d %b %Y  %H:%M")
                    + ("" if v["single"] else "  →  " + v["ended"].astimezone().strftime("%d %b %H:%M"))))
    add(_center(f"order #{v['order_no']}" + ("" if v["single"] else f"   {v['session_count']} sessions")))
    add(dash)
    if v["first_prompt"]:
        import textwrap
        lines = textwrap.wrap("“" + v["first_prompt"] + "”", W, max_lines=3, placeholder="…”")
        for line in lines:
            add(c("2", line))
        add(dot)

    add(_row("prompts", str(v["prompts"])))
    add(_row("duration", v["duration"]))
    add(_row("tool calls", str(v["tool_calls"])))
    add(_row("  shell commands", str(v["commands"])))
    add(_row("  files edited", str(len(v["files_written"]))))
    add(_row("  files read", str(v["files_read"])))
    if v["web"]:
        add(_row("  web lookups", str(v["web"])))
    if v["failures"]:
        add(_row("  failed calls", c("33", str(v["failures"])), W + (len(c("33", "")) if c.on else 0)))
    add(dot)

    for m in v["models"]:
        add(_row(_trim(m["name"], 28), f"{fmt_tokens(m['tokens']):>7}  {fmt_usd(m['cost']):>8}"))
    u = v["usage"]
    add(c("2", _row("  in / out", f"{fmt_tokens(u.input)} / {fmt_tokens(u.output)}")))
    add(c("2", _row("  cache read / write", f"{fmt_tokens(u.cache_read)} / {fmt_tokens(u.cache_write)}")))
    if v["cache_hit"]:
        add(c("2", _row("  cache hit rate", f"{v['cache_hit'] * 100:.0f}%")))
    if v["cache_savings"] >= 0.01:
        add(c("32", _row("  cache discount", "-" + fmt_usd(v["cache_savings"]))))
    add(dash)
    add(c("1", _row("TOTAL (est. API cost)", fmt_usd(v["cost"]))))
    add(dash)

    if v["files_written"]:
        add(c("1", "FILES CHANGED"))
        for p in v["files_written"][:8]:
            add("  " + _trim(p))
        if len(v["files_written"]) > 8:
            add(c("2", f"  …and {len(v['files_written']) - 8} more"))
        add(dot)
    if v["top_commands"]:
        add(c("1", "TOP COMMANDS"))
        for name, n in v["top_commands"]:
            add(_row("  " + name, f"x{n}"))
        add(dot)

    add(c("1", "RED FLAGS"))
    if not v["flags"]:
        add(c("32", "  none. clean run."))
    for f in v["flags"][:10]:
        tag = {"high": "!!", "medium": "! ", "low": "· "}[f["severity"]]
        add(c(sev_color[f["severity"]], f"  {tag} {f['rule']}"))
        d = f["detail"]
        add(c("2", "     " + (d if len(d) <= W - 6 else d[: W - 7] + "…")))
    if len(v["flags"]) > 10:
        add(c("2", f"  …and {len(v['flags']) - 10} more (use --json)"))
    add(dash)

    g = v["grade"]
    gcol = "1;32" if g.startswith("A") else "1;33" if g in ("B", "C") else "1;31"
    add(_row("SAFETY GRADE", c(gcol, f"{g}  ({v['score']}/100)"), W + (len(c(gcol, "")) if c.on else 0)))
    add(_center(v["verdict"]))
    add("")
    add(c("2", _center(_barcode(v["order_no"]))))
    add(c("2", _center("thank you for coding with AI")))
    add(c("2", _center("github.com/SaurabhManmode/agent-receipt")))
    add("")
    return "\n".join(out)
