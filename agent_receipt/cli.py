"""agent-receipt: print a receipt for what your AI coding agent just did."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import webbrowser
from datetime import datetime

from . import __version__, parsers, render_html, render_term, view


def _since(text: str) -> float:
    m = re.fullmatch(r"(\d+)\s*([hdw])", text.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError("use e.g. 12h, 7d, 2w")
    n, unit = int(m.group(1)), m.group(2)
    return time.time() - n * {"h": 3600, "d": 86400, "w": 604800}[unit]


def _same_project(path: str, agent: str, cwd: str) -> bool:
    if agent == "claude":
        # Claude Code escapes the cwd into the folder name: /a/b.c -> -a-b-c
        return os.path.basename(os.path.dirname(path)) == re.sub(r"[^A-Za-z0-9]", "-", cwd)
    try:
        return parsers.parse_codex(path).cwd == cwd
    except OSError:
        return False


def _jsonable(v: dict) -> dict:
    out = dict(v)
    u = out.pop("usage")
    out["usage"] = {"input": u.input, "output": u.output, "cache_write": u.cache_write,
                    "cache_read": u.cache_read, "total": u.total}
    for k in ("started", "ended", "generated"):
        out[k] = out[k].isoformat() if out[k] else None
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="agent-receipt",
        description="Print a receipt for what your AI coding agent did: cost, files, commands, red flags.",
    )
    ap.add_argument("session", nargs="?", help="session id or path to a .jsonl log (default: latest)")
    ap.add_argument("-a", "--agent", choices=["all", "claude", "codex"], default="all",
                    help="which agent's logs to look at (default: all)")
    ap.add_argument("--here", action="store_true", help="only sessions started in the current directory")
    ap.add_argument("--since", type=_since, metavar="7d",
                    help="combine every session in a window into one statement (e.g. 24h, 7d, 4w)")
    ap.add_argument("--html", nargs="?", const="", metavar="FILE",
                    help="write a shareable HTML receipt (and open it)")
    ap.add_argument("--no-open", action="store_true", help="with --html, don't open the browser")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--list", action="store_true", help="list recent sessions and exit")
    ap.add_argument("--fail-on", choices=["high", "medium", "low"],
                    help="exit 1 if any flag at or above this severity (for hooks / CI)")
    ap.add_argument("--hook", action="store_true",
                    help="read a Claude Code hook payload from stdin and receipt that session")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("-V", "--version", action="version", version=f"agent-receipt {__version__}")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    found = parsers.find_sessions(args.agent)
    cwd = os.getcwd()
    if args.here:
        found = [f for f in found if _same_project(f[2], f[1], cwd)]

    if args.list:
        if not found:
            print("No sessions found in ~/.claude/projects or ~/.codex/sessions.")
            return 1
        for mtime, agent, path in found[:25]:
            s = parsers.parse(path, agent)
            when = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            print(f"{when}  {s.agent:<11}  {s.session_id[:12]:<12}  {(s.first_prompt or '-')[:60]}")
        return 0

    if args.hook:
        try:
            payload = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            payload = {}
        args.session = os.path.expanduser(payload.get("transcript_path") or "") or args.session
        if args.html == "":
            folder = os.path.expanduser("~/.agent-receipts")
            os.makedirs(folder, exist_ok=True)
            args.html = os.path.join(folder, f"{datetime.now():%Y%m%d-%H%M%S}.html")

    if args.session:
        if os.path.exists(args.session):
            paths = [(None, None, args.session)]
        else:
            paths = [f for f in found if args.session in os.path.basename(f[2])][:1]
            if not paths:
                print(f"agent-receipt: no session matching '{args.session}'", file=sys.stderr)
                return 1
    elif args.since:
        paths = [f for f in found if f[0] >= args.since]
    else:
        paths = found[:1]

    if not paths:
        where = " for this directory" if args.here else ""
        print(f"agent-receipt: no Claude Code or Codex sessions found{where}.\n"
              "Looked in ~/.claude/projects and ~/.codex/sessions "
              "(override with CLAUDE_CONFIG_DIR / CODEX_HOME).", file=sys.stderr)
        return 1

    sessions = [parsers.parse(p, a) for _, a, p in paths]
    sessions = [s for s in sessions if s.actions or s.prompts or s.models] or sessions
    v = view.build(sessions)

    if args.json:
        print(json.dumps(_jsonable(v), indent=2, default=str))
    elif args.html is not None:
        out = args.html or f"agent-receipt-{v['order_no'].lower()}.html"
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(render_html.render(v))
        print(f"receipt written to {out}")
        if not args.no_open:
            webbrowser.open("file://" + os.path.abspath(out))
    else:
        print(render_term.render(v, color=False if args.no_color else None))

    if args.fail_on:
        rank = {"low": 0, "medium": 1, "high": 2}
        if any(rank[f["severity"]] >= rank[args.fail_on] for f in v["flags"]):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
