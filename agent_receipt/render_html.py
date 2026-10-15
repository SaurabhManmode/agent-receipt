"""Self-contained, shareable HTML receipt (no external requests)."""
from __future__ import annotations

from html import escape

from .view import fmt_tokens, fmt_usd

CSS = """
:root{--bg:#e9e6df;--paper:#fffdf7;--ink:#1d1b18;--mute:#7a746a;--rule:#cfc8ba;
--high:#c0392b;--med:#b9770e;--low:#8a8478;--ok:#1e8449}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--paper:#f4f1e8;}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:var(--bg);display:flex;justify-content:center;
align-items:flex-start;padding:40px 16px;font:14px/1.45 ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;color:var(--ink)}
.receipt{width:100%;max-width:400px;background:var(--paper);padding:28px 26px 22px;position:relative;
box-shadow:0 1px 0 rgba(0,0,0,.04),0 18px 40px -18px rgba(0,0,0,.35);transform:rotate(-.6deg)}
.receipt:before,.receipt:after{content:"";position:absolute;left:0;right:0;height:12px;
background:linear-gradient(-45deg,transparent 8px,var(--paper) 0),linear-gradient(45deg,transparent 8px,var(--paper) 0);
background-size:16px 16px;background-repeat:repeat-x}
.receipt:before{top:-12px;transform:rotate(180deg)} .receipt:after{bottom:-12px}
h1{font-size:18px;letter-spacing:.18em;text-align:center;margin:0 0 4px}
.c{text-align:center}.m{color:var(--mute)}.s{font-size:12px}
hr{border:0;border-top:1px dashed var(--rule);margin:12px 0}
hr.solid{border-top:2px solid var(--ink)}
.row{display:flex;justify-content:space-between;gap:12px}.row span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row span:last-child{white-space:nowrap;text-align:right}
.ind{padding-left:14px}
.total{font-weight:700;font-size:17px}
.sec{font-weight:700;letter-spacing:.12em;font-size:12px;margin:2px 0 4px}
.quote{font-style:italic;color:var(--mute)}
.f{margin:4px 0}.f b{font-weight:700}.f .d{display:block;padding-left:22px;color:var(--mute);font-size:12px;word-break:break-all}
.high b{color:var(--high)}.medium b{color:var(--med)}.low b{color:var(--low)}
.ok{color:var(--ok)}
.grade{display:flex;align-items:center;justify-content:space-between;margin-top:6px}
.grade .g{font-size:40px;font-weight:800;line-height:1;border:3px solid currentColor;border-radius:8px;padding:6px 12px;transform:rotate(-6deg)}
.gA{color:var(--ok)}.gB,.gC{color:var(--med)}.gD,.gF{color:var(--high)}
.bar{display:flex;height:44px;justify-content:center;gap:1px;margin:14px 0 6px}
.bar i{display:block;background:var(--ink)}
.path{word-break:break-all;font-size:12px}
"""


def _row(left: str, right: str, cls: str = "") -> str:
    return f'<div class="row {cls}"><span>{escape(left)}</span><span>{escape(right)}</span></div>'


def _barcode(seed: str) -> str:
    out = []
    for ch in (seed * 8)[:56]:
        w = 1 + int(ch, 16) % 4
        out.append(f'<i style="width:{w}px"></i>' if int(ch, 16) % 3 else f'<i style="width:{w}px;background:transparent"></i>')
    return '<div class="bar">' + "".join(out) + "</div>"


def render(v: dict) -> str:
    h = []
    add = h.append
    add(f'<h1>{escape(v["title"])}</h1>')
    add(f'<div class="c">{escape(v["agent"])}</div>')
    if v["project"]:
        add(f'<div class="c m">project: {escape(v["project"])}' + (f' @ {escape(v["branch"])}' if v["branch"] else "") + "</div>")
    if v["started"]:
        when = v["started"].astimezone().strftime("%d %b %Y · %H:%M")
        if not v["single"]:
            when += " → " + v["ended"].astimezone().strftime("%d %b %H:%M")
        add(f'<div class="c m">{escape(when)}</div>')
    add(f'<div class="c m s">order #{v["order_no"]}' + ("" if v["single"] else f' · {v["session_count"]} sessions') + "</div>")
    add("<hr>")
    if v["first_prompt"]:
        add(f'<div class="quote">“{escape(v["first_prompt"])}”</div><hr>')

    add(_row("prompts", str(v["prompts"])))
    add(_row("duration", v["duration"]))
    add(_row("tool calls", str(v["tool_calls"])))
    add(_row("shell commands", str(v["commands"]), "ind"))
    add(_row("files edited", str(len(v["files_written"])), "ind"))
    add(_row("files read", str(v["files_read"]), "ind"))
    if v["web"]:
        add(_row("web lookups", str(v["web"]), "ind"))
    if v["failures"]:
        add(_row("failed calls", str(v["failures"]), "ind"))
    add("<hr>")
    for m in v["models"]:
        add(_row(m["name"], f'{fmt_tokens(m["tokens"])}   {fmt_usd(m["cost"])}'))
    u = v["usage"]
    add(_row("in / out", f"{fmt_tokens(u.input)} / {fmt_tokens(u.output)}", "ind m"))
    add(_row("cache read / write", f"{fmt_tokens(u.cache_read)} / {fmt_tokens(u.cache_write)}", "ind m"))
    if v["cache_hit"]:
        add(_row("cache hit rate", f'{v["cache_hit"] * 100:.0f}%', "ind m"))
    if v["cache_savings"] >= 0.01:
        add(_row("cache discount", "-" + fmt_usd(v["cache_savings"]), "ind ok"))
    add('<hr class="solid">')
    add(_row("TOTAL (est.)", fmt_usd(v["cost"]), "total"))
    add('<hr class="solid">')

    if v["files_written"]:
        add('<div class="sec">FILES CHANGED</div>')
        for p in v["files_written"][:12]:
            add(f'<div class="path">· {escape(p)}</div>')
        if len(v["files_written"]) > 12:
            add(f'<div class="m s">…and {len(v["files_written"]) - 12} more</div>')
        add("<hr>")
    if v["top_commands"]:
        add('<div class="sec">TOP COMMANDS</div>')
        for name, n in v["top_commands"]:
            add(_row(name, f"x{n}", "ind"))
        add("<hr>")

    add('<div class="sec">RED FLAGS</div>')
    if not v["flags"]:
        add('<div class="ok">✓ none. clean run.</div>')
    for f in v["flags"][:12]:
        tag = {"high": "!!", "medium": "!", "low": "·"}[f["severity"]]
        add(f'<div class="f {f["severity"]}"><b>{tag} {escape(f["rule"])}</b><span class="d">{escape(f["detail"])}</span></div>')
    if len(v["flags"]) > 12:
        add(f'<div class="m s">…and {len(v["flags"]) - 12} more</div>')
    add("<hr>")

    g = v["grade"]
    add(f'<div class="grade"><div><div class="sec">SAFETY GRADE</div><div>{v["score"]}/100</div>'
        f'<div class="m s">{escape(v["verdict"])}</div></div><div class="g g{g[0]}">{g}</div></div>')
    add(_barcode(v["order_no"]))
    add('<div class="c m s">thank you for coding with AI</div>')
    add('<div class="c m s">made with agent-receipt · github.com/SaurabhManmode/agent-receipt</div>')

    title = f'{v["title"].title()} · {v["project"] or v["agent"]}'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{escape(title)}</title><style>{CSS}</style></head>"
            f'<body><main class="receipt">{"".join(h)}</main></body></html>')
