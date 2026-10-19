import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from opswatch import cli, state
from opswatch.checks import REGISTRY
from opswatch.config import ConfigError, parse
from opswatch.models import CheckResult, CheckSpec, Settings, Status
from opswatch.notify import build_email, notify_all
from opswatch.report import overall, render_html, render_json, render_markdown, render_text, summary
from opswatch.runner import run_all, run_one

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def result(name, status, message="m"):
    return CheckResult(name, "http", status, message)


class ConfigTests(unittest.TestCase):
    def good(self):
        return {"checks": [{"name": "a", "type": "tcp", "host": "h", "port": 1}]}

    def test_valid(self):
        config = parse(self.good())
        self.assertEqual(config.checks[0].options, {"host": "h", "port": 1})
        self.assertEqual(config.settings, Settings())

    def test_requires_checks(self):
        with self.assertRaisesRegex(ConfigError, "no .*checks"):
            parse({})

    def test_unknown_type(self):
        data = {"checks": [{"name": "a", "type": "ping"}]}
        with self.assertRaisesRegex(ConfigError, "unknown type"):
            parse(data)

    def test_missing_and_unknown_options(self):
        with self.assertRaisesRegex(ConfigError, "missing port"):
            parse({"checks": [{"name": "a", "type": "tcp", "host": "h"}]})
        with self.assertRaisesRegex(ConfigError, "unknown option"):
            parse({"checks": [{"name": "a", "type": "tcp", "host": "h", "port": 1, "colour": 1}]})

    def test_duplicate_names(self):
        data = self.good()
        data["checks"].append(dict(data["checks"][0]))
        with self.assertRaisesRegex(ConfigError, "duplicate"):
            parse(data)

    def test_bad_settings(self):
        data = self.good()
        data["settings"] = {"workers": 0}
        with self.assertRaisesRegex(ConfigError, "workers"):
            parse(data)
        data["settings"] = {"nope": 1}
        with self.assertRaisesRegex(ConfigError, "unknown option"):
            parse(data)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.calls = 0
        self.original = dict(REGISTRY)

    def tearDown(self):
        REGISTRY.clear()
        REGISTRY.update(self.original)

    def test_retries_until_success(self):
        def flaky(options, timeout):
            self.calls += 1
            return (Status.OK, "up") if self.calls == 3 else (Status.FAIL, "down")

        REGISTRY["flaky"] = flaky
        slept = []
        res = run_one(CheckSpec("f", "flaky"), Settings(retries=2, retry_delay=1), sleep=slept.append)
        self.assertEqual((res.status, res.attempts), (Status.OK, 3))
        self.assertEqual(slept, [1, 2])  # linear back-off

    def test_gives_up_and_reports_failure(self):
        REGISTRY["down"] = lambda options, timeout: (Status.FAIL, "down")
        res = run_one(CheckSpec("d", "down"), Settings(retries=1), sleep=lambda s: None)
        self.assertEqual((res.status, res.attempts), (Status.FAIL, 2))

    def test_warn_is_not_retried(self):
        def slow(options, timeout):
            self.calls += 1
            return Status.WARN, "slow"

        REGISTRY["slow"] = slow
        run_one(CheckSpec("s", "slow"), Settings(retries=3), sleep=lambda s: None)
        self.assertEqual(self.calls, 1)

    def test_exception_becomes_failure(self):
        def boom(options, timeout):
            raise RuntimeError("kaput")

        REGISTRY["boom"] = boom
        res = run_one(CheckSpec("b", "boom"), Settings(retries=0))
        self.assertEqual(res.status, Status.FAIL)
        self.assertIn("RuntimeError: kaput", res.message)

    def test_run_all_keeps_config_order(self):
        REGISTRY["ok"] = lambda options, timeout: (Status.OK, options["n"])
        specs = [CheckSpec(f"c{i}", "ok", {"n": str(i)}) for i in range(10)]
        names = [r.name for r in run_all(specs, Settings(workers=4))]
        self.assertEqual(names, [f"c{i}" for i in range(10)])


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.results = [
            result("Web", Status.OK, "HTTP 200"),
            result("Disk", Status.WARN, "80% used"),
            result("DB | main", Status.FAIL, "refused"),
        ]

    def test_overall_and_summary(self):
        self.assertEqual(overall(self.results), Status.FAIL)
        self.assertEqual(overall([]), Status.OK)
        self.assertEqual(summary(self.results), {"overall": "FAIL", "total": 3, "OK": 1, "WARN": 1, "FAIL": 1})

    def test_text(self):
        text = render_text(self.results, NOW)
        self.assertIn("[FAIL] DB | main", text)
        self.assertIn("2026-01-01 12:00:00 UTC", text)
        self.assertIn("FAIL: 1 ok, 1 warning, 1 failing of 3", text)

    def test_json_round_trip(self):
        data = json.loads(render_json(self.results, NOW))
        self.assertEqual(data["summary"]["overall"], "FAIL")
        self.assertEqual(data["results"][1]["status"], "WARN")

    def test_markdown_escapes_pipes(self):
        md = render_markdown([result("x", Status.FAIL, "a | b")], NOW)
        self.assertIn("a \\| b", md)

    def test_html_escapes(self):
        page = render_html([result("<b>x</b>", Status.OK, "<script>")], NOW)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)


class StateTests(unittest.TestCase):
    def test_should_notify(self):
        self.assertFalse(state.should_notify({}, {}))
        self.assertTrue(state.should_notify({}, {"a": "FAIL"}))
        self.assertFalse(state.should_notify({"a": "FAIL"}, {"a": "FAIL"}))
        self.assertTrue(state.should_notify({"a": "WARN"}, {"a": "FAIL"}))
        self.assertTrue(state.should_notify({"a": "FAIL"}, {}))  # recovery

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            self.assertEqual(state.load(path), {})
            state.save(path, {"a": "FAIL"})
            self.assertEqual(state.load(path), {"a": "FAIL"})
            path.write_text("not json")
            self.assertEqual(state.load(path), {})

    def test_problems(self):
        res = [result("a", Status.OK), result("b", Status.WARN), result("c", Status.FAIL)]
        self.assertEqual(state.problems(res), {"b": "WARN", "c": "FAIL"})


class NotifyTests(unittest.TestCase):
    def test_build_email(self):
        msg = build_email({"from": "a@x.io", "to": ["b@x.io", "c@x.io"]}, "subj", "body")
        self.assertEqual(msg["To"], "b@x.io, c@x.io")
        self.assertEqual(msg["Subject"], "subj")

    def test_errors_are_returned_not_raised(self):
        cfg = {"webhook": {"url": "http://127.0.0.1:9/none"}}
        errors = notify_all(cfg, "s", "b")
        self.assertEqual(len(errors), 1)
        self.assertIn("webhook failed", errors[0])


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def write(self, tmp, body):
        path = Path(tmp) / "c.toml"
        path.write_text(body, encoding="utf-8")
        return str(path)

    def test_init_prints_valid_example(self):
        code, out, _ = self.run_cli("init")
        self.assertEqual(code, 0)
        self.assertIn("[[checks]]", out)
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = self.run_cli("validate", "-c", self.write(tmp, out))
            self.assertEqual(code, 0)
            self.assertIn("OK: 4 check(s)", out)

    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = self.write(tmp, f'[[checks]]\nname="d"\ntype="disk"\npath="{Path(tmp).as_posix()}"\nmax_used_percent=100\nwarn_used_percent=100\n')
            code, out, _ = self.run_cli("run", "-c", ok)
            self.assertEqual(code, 0)
            self.assertIn("OK:", out)

            bad = self.write(tmp, f'[settings]\nretries=0\n[[checks]]\nname="d"\ntype="disk"\npath="{Path(tmp).as_posix()}"\nmax_used_percent=0\n')
            code, out, _ = self.run_cli("run", "-c", bad, "-f", "json")
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["summary"]["overall"], "FAIL")

    def test_config_with_utf8_bom_loads(self):
        body = '[[checks]]\nname="t"\ntype="tcp"\nhost="h"\nport=1\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bom.toml"
            path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
            code, out, _ = self.run_cli("validate", "-c", str(path))
            self.assertEqual(code, 0)
            self.assertIn("OK: 1 check(s)", out)

    def test_config_errors_exit_3(self):
        code, _, err = self.run_cli("validate", "-c", "does-not-exist.toml")
        self.assertEqual(code, 3)
        self.assertIn("config error", err)

    def test_notifies_only_on_change_with_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = self.write(tmp, f'[settings]\nretries=0\n[[checks]]\nname="d"\ntype="disk"\npath="{Path(tmp).as_posix()}"\nmax_used_percent=0\n')
            state_file = str(Path(tmp) / "state.json")
            with mock.patch.object(cli, "notify_all", return_value=[]) as sender:
                self.run_cli("run", "-c", bad, "--notify", "--state-file", state_file)
                self.run_cli("run", "-c", bad, "--notify", "--state-file", state_file)
                self.assertEqual(sender.call_count, 1)  # second run: nothing changed

    def test_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self.write(tmp, f'[[checks]]\nname="d"\ntype="disk"\npath="{Path(tmp).as_posix()}"\nmax_used_percent=100\nwarn_used_percent=100\n')
            target = Path(tmp) / "report.html"
            code, out, _ = self.run_cli("run", "-c", cfg, "-f", "html", "-o", str(target))
            self.assertEqual((code, out), (0, ""))
            self.assertIn("<title>opswatch report</title>", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
