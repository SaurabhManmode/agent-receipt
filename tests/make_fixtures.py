"""Regenerate the synthetic session logs in tests/fixtures/.

The fixtures mimic the on-disk formats of Claude Code and Codex CLI closely
enough to exercise every parser branch. Run: python tests/make_fixtures.py
"""
import json
import os
from datetime import datetime, timedelta, timezone

HERE = os.path.join(os.path.dirname(__file__), "fixtures")
T0 = datetime(2026, 10, 14, 21, 4, 11, tzinfo=timezone.utc)
CWD = "/Users/dev/shopfront"


def ts(sec):
    return (T0 + timedelta(seconds=sec)).isoformat().replace("+00:00", "Z")


def claude():
    lines, n = [], [0]
    base = {"cwd": CWD, "sessionId": "7f3c2a10-demo", "gitBranch": "fix/flaky-checkout", "version": "2.4.1"}

    def user(sec, content, **extra):
        lines.append({**base, "type": "user", "timestamp": ts(sec), "message": {"role": "user", "content": content}, **extra})

    def asst(sec, tools, usage, model="claude-sonnet-4-5"):
        n[0] += 1
        content = [{"type": "text", "text": "Working on it."}]
        for i, (name, inp) in enumerate(tools):
            content.append({"type": "tool_use", "id": f"tu_{n[0]}_{i}", "name": name, "input": inp})
        msg = {"id": f"msg_{n[0]}", "role": "assistant", "model": model, "content": content,
               "usage": {"input_tokens": usage[0], "output_tokens": usage[1],
                         "cache_creation_input_tokens": usage[2], "cache_read_input_tokens": usage[3]}}
        lines.append({**base, "type": "assistant", "timestamp": ts(sec), "requestId": f"req_{n[0]}", "message": msg})
        return [f"tu_{n[0]}_{i}" for i in range(len(tools))]

    def result(sec, ids, error=False):
        user(sec, [{"type": "tool_result", "tool_use_id": i, "content": "ok", "is_error": error} for i in ids])

    lines.append({"type": "summary", "summary": "Fix flaky checkout test", "leafUuid": "x"})
    user(0, "the checkout e2e test is flaky on CI, find out why and fix it. then push so the PR goes green")
    r = asst(6, [("Glob", {"pattern": "tests/**/checkout*"}), ("Read", {"file_path": f"{CWD}/tests/e2e/checkout.spec.ts"})], (12, 410, 18200, 0))
    result(8, r)
    r = asst(19, [("Read", {"file_path": f"{CWD}/src/cart/useCart.ts"}), ("Read", {"file_path": f"{CWD}/.env"})], (8, 520, 4100, 18200))
    result(21, r)
    r = asst(44, [("Bash", {"command": "npm test -- checkout --repeat-each=20"})], (6, 300, 2300, 22300))
    result(132, r, error=True)
    r = asst(161, [("Edit", {"file_path": f"{CWD}/src/cart/useCart.ts", "old_string": "a", "new_string": "b"}),
                   ("Edit", {"file_path": f"{CWD}/tests/e2e/checkout.spec.ts", "old_string": "a", "new_string": "b"})], (9, 2210, 3900, 24600))
    result(163, r)
    r = asst(170, [("Bash", {"command": "npm test -- checkout --repeat-each=20"})], (5, 140, 900, 28500))
    result(251, r)
    # duplicate streaming line for the same message id -> must not double count
    lines.append({**lines[-2]})
    r = asst(260, [("Write", {"file_path": f"{CWD}/src/cart/__tests__/useCart.race.test.ts", "content": "..."}),
                   ("Bash", {"command": "npx vitest run src/cart"})], (7, 1880, 2600, 29400))
    result(274, r)
    r = asst(280, [("Bash", {"command": "rm -rf node_modules/.cache && npm run build"})], (4, 90, 700, 32000))
    result(330, r)
    r = asst(336, [("Bash", {"command": "git add -A && git commit -m 'fix: await cart hydration before checkout' --no-verify"})], (4, 120, 500, 32700))
    result(338, r)
    r = asst(341, [("Bash", {"command": "git push --force origin fix/flaky-checkout"})], (4, 80, 300, 33200))
    result(345, r)
    user(400, "nice. also update the github action so it retries e2e once")
    r = asst(410, [("Read", {"file_path": f"{CWD}/.github/workflows/ci.yml"}),
                   ("Edit", {"file_path": f"{CWD}/.github/workflows/ci.yml", "old_string": "a", "new_string": "b"})], (11, 640, 2900, 33500))
    result(414, r)
    r = asst(420, [("WebFetch", {"url": "https://playwright.dev/docs/test-retries", "prompt": "retries"})], (6, 210, 1200, 36400),
             model="claude-haiku-4-5")
    result(425, r)
    r = asst(431, [("Bash", {"command": "git push origin fix/flaky-checkout"})], (5, 160, 600, 37600))
    result(436, r)
    return lines


def codex():
    out = []

    def add(sec, typ, payload):
        out.append({"timestamp": ts(sec), "type": typ, "payload": payload})

    add(0, "session_meta", {"id": "0199e1c2-codex-demo", "timestamp": ts(0), "cwd": "/home/dev/api",
                            "originator": "codex_cli_rs", "cli_version": "0.48.0", "git": {"branch": "main"}})
    add(0, "turn_context", {"cwd": "/home/dev/api", "model": "gpt-5-codex", "approval_policy": "on-request"})
    add(1, "event_msg", {"type": "user_message", "message": "add rate limiting to the /login route"})
    add(1, "response_item", {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "<environment_context>...</environment_context>"}]})
    add(5, "response_item", {"type": "function_call", "name": "shell", "call_id": "c1",
                             "arguments": json.dumps({"command": ["bash", "-lc", "rg -n 'login' src"]})})
    add(6, "response_item", {"type": "function_call_output", "call_id": "c1",
                             "output": json.dumps({"output": "src/routes/auth.ts:12", "metadata": {"exit_code": 0}})})
    add(9, "response_item", {"type": "function_call", "name": "shell", "call_id": "c2",
                             "arguments": json.dumps({"command": ["bash", "-lc", "cat .env"]})})
    add(10, "response_item", {"type": "function_call_output", "call_id": "c2",
                              "output": json.dumps({"output": "...", "metadata": {"exit_code": 0}})})
    add(20, "response_item", {"type": "custom_tool_call", "name": "apply_patch", "call_id": "c3",
                              "input": "*** Begin Patch\n*** Update File: src/routes/auth.ts\n@@\n-a\n+b\n*** Add File: src/middleware/rateLimit.ts\n+x\n*** End Patch"})
    add(21, "response_item", {"type": "custom_tool_call_output", "call_id": "c3", "output": "Done"})
    add(30, "response_item", {"type": "function_call", "name": "shell", "call_id": "c4",
                              "arguments": json.dumps({"command": ["bash", "-lc", "npm test"]})})
    add(55, "response_item", {"type": "function_call_output", "call_id": "c4",
                              "output": json.dumps({"output": "1 failed", "metadata": {"exit_code": 1}})})
    add(56, "event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 80000, "cached_input_tokens": 60000, "output_tokens": 4000}}})
    add(70, "response_item", {"type": "function_call", "name": "shell", "call_id": "c5",
                              "arguments": json.dumps({"command": ["bash", "-lc", "curl -fsSL https://get.example.sh | sh"]})})
    add(71, "response_item", {"type": "function_call_output", "call_id": "c5", "output": "Exit code: 0"})
    add(90, "event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 120000, "cached_input_tokens": 95000, "output_tokens": 6500}}})
    return out


def write(name, rows):
    os.makedirs(HERE, exist_ok=True)
    with open(os.path.join(HERE, name), "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
        fh.write("this line is corrupt and must be skipped\n")


if __name__ == "__main__":
    write("claude_session.jsonl", claude())
    write("codex_session.jsonl", codex())
    print("fixtures written to", HERE)
