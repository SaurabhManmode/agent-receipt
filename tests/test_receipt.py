import io
import json
import os
import unittest
from contextlib import redirect_stdout

from agent_receipt import cli, parsers, pricing, render_html, render_term, risk, view
from agent_receipt.model import Action, Session, Usage

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
CLAUDE = os.path.join(FIX, "claude_session.jsonl")
CODEX = os.path.join(FIX, "codex_session.jsonl")


def rules(s):
    return {f.rule for f in risk.analyze(s)}


class ClaudeParser(unittest.TestCase):
    def setUp(self):
        self.s = parsers.parse(CLAUDE)

    def test_detects_agent(self):
        self.assertEqual(self.s.agent, "Claude Code")
        self.assertEqual(self.s.cwd, "/Users/dev/shopfront")
        self.assertEqual(self.s.git_branch, "fix/flaky-checkout")

    def test_prompts_exclude_tool_results(self):
        self.assertEqual(self.s.prompts, 2)
        self.assertTrue(self.s.first_prompt.startswith("the checkout e2e test"))

    def test_usage_not_double_counted(self):
        u = self.s.models["claude-sonnet-4-5"]
        self.assertEqual(u.output, 410 + 520 + 300 + 2210 + 140 + 1880 + 90 + 120 + 80 + 640 + 160)
        self.assertIn("claude-haiku-4-5", self.s.models)

    def test_actions(self):
        self.assertEqual(len(self.s.commands), 7)
        self.assertIn("/Users/dev/shopfront/.github/workflows/ci.yml", self.s.files_written)
        self.assertEqual(len(self.s.files_written), 4)
        self.assertEqual(self.s.failures, 1)
        self.assertEqual(self.s.duration_s, 436)

    def test_flags(self):
        r = rules(self.s)
        for expected in ("force push", "read a secrets file", "edited CI pipeline",
                         "skips git hooks", "recursive force delete"):
            self.assertIn(expected, r)


class CodexParser(unittest.TestCase):
    def setUp(self):
        self.s = parsers.parse(CODEX)

    def test_meta(self):
        self.assertEqual(self.s.agent, "Codex")
        self.assertEqual(self.s.session_id, "0199e1c2-codex-demo")
        self.assertEqual(self.s.cwd, "/home/dev/api")
        self.assertEqual(self.s.prompts, 1)

    def test_usage_uses_last_cumulative_total(self):
        u = self.s.models["gpt-5-codex"]
        self.assertEqual((u.input, u.cache_read, u.output), (25000, 95000, 6500))

    def test_actions_and_failures(self):
        self.assertEqual([a.target for a in self.s.commands][:2], ["rg -n 'login' src", "cat .env"])
        self.assertEqual(self.s.files_written, ["src/routes/auth.ts", "src/middleware/rateLimit.ts"])
        self.assertEqual(self.s.failures, 1)

    def test_flags(self):
        r = rules(self.s)
        self.assertIn("pipe remote script to shell", r)
        self.assertIn("read a secrets file", r)


class Risk(unittest.TestCase):
    def cmd(self, c):
        s = Session("x", "x", "x", cwd="/p")
        s.actions.append(Action("command", "Bash", c))
        return rules(s)

    def test_positive(self):
        self.assertIn("recursive force delete", self.cmd("rm -rf build"))
        self.assertIn("recursive force delete", self.cmd("rm -fr /tmp/x"))
        self.assertIn("hard reset / clean", self.cmd("git reset --hard HEAD~3"))
        self.assertIn("database destroy", self.cmd("psql -c 'DROP TABLE users'"))
        self.assertIn("secret in command line", self.cmd("export OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz123"))
        self.assertIn("sudo", self.cmd("sudo apt install jq"))
        self.assertIn("package publish", self.cmd("npm publish --access public"))

    def test_negative(self):
        self.assertEqual(self.cmd("rm build.log"), set())
        self.assertEqual(self.cmd("ls -la && npm test"), set())
        self.assertEqual(self.cmd("git status"), set())
        self.assertEqual(self.cmd("cat README.md"), set())

    def test_write_outside_project(self):
        s = Session("x", "x", "x", cwd="/p")
        s.actions.append(Action("write", "Write", "/etc/hosts"))
        self.assertIn("wrote outside project", rules(s))

    def test_grade_bounds(self):
        self.assertEqual(risk.grade(100), "A+")
        self.assertEqual(risk.grade(0), "F")


class Pricing(unittest.TestCase):
    def test_known_and_unknown(self):
        self.assertAlmostEqual(pricing.cost("claude-sonnet-4-5", Usage(input=1_000_000)), 3.0)
        self.assertAlmostEqual(pricing.cost("claude-sonnet-4-5", Usage(cache_read=1_000_000)), 0.3)
        self.assertIsNone(pricing.cost("mystery-model", Usage(input=5)))
        self.assertEqual(pricing.rates_for("gpt-5-mini")["input"], 0.25)


class Rendering(unittest.TestCase):
    def test_term_and_html(self):
        v = view.build([parsers.parse(CLAUDE)])
        text = render_term.render(v, color=False)
        self.assertIn("AGENT RECEIPT", text)
        self.assertIn("force push", text)
        html = render_html.render(v)
        self.assertIn("<!doctype html>", html)
        self.assertNotIn("http://", html.split("</style>")[0])  # no external assets

    def test_statement_combines_sessions(self):
        v = view.build([parsers.parse(CLAUDE), parsers.parse(CODEX)])
        self.assertEqual(v["title"], "AGENT STATEMENT")
        self.assertEqual(v["session_count"], 2)
        self.assertEqual(v["agent"], "Claude Code + Codex")

    def test_html_escapes(self):
        s = parsers.parse(CLAUDE)
        s.first_prompt = "<script>alert(1)</script>"
        self.assertNotIn("<script>alert", render_html.render(view.build([s])))


class CLI(unittest.TestCase):
    def run_cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(list(args))
        return code, buf.getvalue()

    def test_json(self):
        code, out = self.run_cli(CLAUDE, "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertGreater(data["usage"]["total"], 0)
        self.assertEqual(data["grade"], "F")

    def test_fail_on(self):
        self.assertEqual(self.run_cli(CLAUDE, "--fail-on", "high", "--no-color")[0], 1)

    def test_html_file(self):
        out = os.path.join(FIX, "_tmp.html")
        try:
            code, _ = self.run_cli(CODEX, "--html", out, "--no-open")
            self.assertEqual(code, 0)
            self.assertTrue(os.path.getsize(out) > 1000)
        finally:
            if os.path.exists(out):
                os.remove(out)


if __name__ == "__main__":
    unittest.main()
