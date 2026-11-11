"""Offline regression tests: python -m unittest discover -s tests."""

import contextlib
import datetime
import email.utils
import http.client
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.error


SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("fetch_arxiv", SCRIPTS / "fetch_arxiv.py")
fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)


def http_error(code, retry_after=None):
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return urllib.error.HTTPError("https://example.invalid", code, "test", headers, None)


def paper(arxiv_id="2609.00001", **changes):
    result = {
        "id": arxiv_id,
        "title": "World model for driving robots and interactive video",
        "abstract": "A research paper.",
        "published": datetime.date.today().isoformat(),
        "authors": ["Test Author"],
        "primary_category": "cs.CV",
        "categories": ["cs.CV"],
    }
    result.update(changes)
    return result


class MainTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.temp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.config_path = self.temp / "config.yaml"
        self.coverage_path = self.temp / "coverage.json"
        self.output_path = self.temp / "output.txt"
        self.summary_path = self.temp / "summary.md"
        self.cfg = {
            "category_filter": ["cs.CV", "cs.RO"],
            "queries": [{"name": "Robotics", "search": "all:robot",
                         "feed_keywords": [["world model"], ["robot", "robots"]]}],
        }
        self.stack.enter_context(patch.object(fetch, "CONFIG_FILE", self.config_path))
        self.stack.enter_context(patch.object(fetch, "COVERAGE_FILE", self.coverage_path))
        self.stack.enter_context(patch.dict(os.environ, {
            "GITHUB_OUTPUT": str(self.output_path),
            "GITHUB_STEP_SUMMARY": str(self.summary_path),
        }))
        original_mkdtemp = tempfile.mkdtemp
        self.stack.enter_context(patch.object(fetch.tempfile, "mkdtemp", side_effect=lambda **kw: original_mkdtemp(dir=self.temp, **kw)))
        self.existing = self.stack.enter_context(patch.object(fetch, "existing_arxiv_ids", return_value=set()))
        self.seen = self.stack.enter_context(patch.object(fetch, "load_seen", return_value=set()))
        self.append_seen = self.stack.enter_context(patch.object(fetch, "append_seen"))
        self.api = self.stack.enter_context(patch.object(fetch, "fetch_query", side_effect=AssertionError("Daily scan used search API")))
        self.feed = self.stack.enter_context(patch.object(fetch, "fetch_url", return_value=b"feed"))
        self.parse_feed = self.stack.enter_context(patch.object(fetch, "parse_feed", return_value=[]))

    def run_main(self, *args):
        self.config_path.write_text(fetch.yaml.safe_dump(self.cfg), encoding="utf-8")
        stdout = io.StringIO()
        with patch.object(sys, "argv", ["fetch_arxiv.py", *args]), contextlib.redirect_stdout(stdout):
            try:
                fetch.main()
            except SystemExit as exc:
                code = exc.code or 0
            else:
                code = 0
        return code, stdout.getvalue()

    def output(self):
        return dict(line.split("=", 1) for line in self.output_path.read_text(encoding="utf-8").splitlines())

    def candidate(self, arxiv_id="2609.00001", **changes):
        result = paper(arxiv_id, published="", announced="2026-09-14", primary_category="",
                       categories=["cs.CV", "cs.RO"], date_label="公告日期")
        result.update(changes)
        return result

    def test_daily_uses_only_atom_and_deduplicates_categories_and_seen_ids(self):
        self.existing.return_value = {"2609.00002"}
        self.seen.return_value = {"2609.00003"}
        self.parse_feed.return_value = [self.candidate(), self.candidate("2609.00002"), self.candidate("2609.00003")]
        code, _ = self.run_main()
        self.assertEqual(code, 0)
        self.api.assert_not_called()
        self.assertEqual([call.args[0] for call in self.feed.call_args_list],
                         [fetch.FEED_URL + "cs.CV", fetch.FEED_URL + "cs.RO"])
        out = self.output()
        self.assertEqual(out["scan_status"], "success")
        self.assertEqual(out["candidate_count"], "1")
        self.assertEqual(set(p.name for p in Path(out["snapshot"]).iterdir()), {"cs.CV.xml", "cs.RO.xml"})
        self.assertEqual(fetch.read_coverage(self.coverage_path)["cs.CV"]["last_observed"], "2026-09-14")
        self.append_seen.assert_called_once_with({"2609.00001"})
        report = Path(out["report"]).read_text(encoding="utf-8")
        self.assertEqual(report.count("https://arxiv.org/abs/2609.00001"), 1)
        self.assertIn("公告日期", report)
        self.assertTrue(report.startswith(f"<!-- arxiv-scan:{out['batch']} -->"))

    def test_partial_atom_scan_keeps_successful_candidates_and_coverage(self):
        self.feed.side_effect = [b"feed", http_error(429)]
        self.parse_feed.return_value = [self.candidate(categories=["cs.CV"])]
        code, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(self.output()["scan_status"], "partial")
        self.assertEqual(self.output()["has_new"], "true")
        self.assertEqual(set(fetch.read_coverage(self.coverage_path)), {"cs.CV"})
        self.assertIn("HTTP Error 429", self.summary_path.read_text(encoding="utf-8"))

    def test_total_failure_does_not_advance_state_or_publish(self):
        self.feed.side_effect = fetch.RequestDeferred("Long server cooldown")
        code, _ = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(self.output()["scan_status"], "failed")
        self.assertEqual(self.output()["has_new"], "false")
        self.feed.assert_called_once()
        self.api.assert_not_called()
        self.append_seen.assert_not_called()
        self.assertFalse(self.coverage_path.exists())

    def test_empty_atom_is_partial_and_preserves_last_observed(self):
        old_state = fetch.update_coverage({}, ["cs.CV"], ["2026-09-11"])
        fetch.write_coverage(self.coverage_path, old_state)
        code, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(self.output()["scan_status"], "partial")
        self.assertEqual(fetch.read_coverage(self.coverage_path), old_state)
        self.append_seen.assert_not_called()

    def test_missing_announcement_is_saved_even_without_new_candidates(self):
        fetch.write_coverage(self.coverage_path, fetch.update_coverage({}, ["cs.CV"], ["2026-09-14"]))
        self.seen.return_value = {"2609.00001"}
        self.parse_feed.return_value = [self.candidate(announced="2026-09-16")]
        code, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(self.output()["scan_status"], "partial")
        self.assertEqual(self.output()["has_new"], "false")
        state = fetch.read_coverage(self.coverage_path)
        self.assertEqual(fetch.pending_dates(state, ["cs.CV"]), ["2026-09-15"])
        self.assertEqual(fetch.pending_dates(state, ["cs.RO"]), [])
        self.append_seen.assert_not_called()

    def test_replay_and_dry_run_do_not_write_state(self):
        self.parse_feed.return_value = [self.candidate()]
        snapshot = self.temp / "saved.xml"
        snapshot.write_bytes(b"saved")
        for args in (("--dry-run",), ("--replay", str(snapshot))):
            with self.subTest(args=args):
                self.feed.reset_mock()
                code, report = self.run_main(*args)
                self.assertEqual(code, 0)
                self.assertIn("https://arxiv.org/abs/2609.00001", report)
                if args[0] == "--replay":
                    self.feed.assert_not_called()
                self.append_seen.assert_not_called()
                self.assertFalse(self.coverage_path.exists())
                self.assertFalse(self.output_path.exists())
                self.assertFalse(self.summary_path.exists())

    def test_backfill_uses_submission_dates_without_resolving_atom_gaps(self):
        old_state = fetch.update_coverage({}, ["cs.CV"], ["2026-09-14", "2026-09-16"])
        fetch.write_coverage(self.coverage_path, old_state)
        with patch.object(fetch, "fetch_backfill", return_value=[paper()]) as backfill:
            code, _ = self.run_main("--backfill-from", "2026-09-11", "--backfill-to", "2026-09-15")
        self.assertEqual(code, 0)
        self.feed.assert_not_called()
        self.assertEqual(backfill.call_args.args[1:3], (datetime.date(2026, 9, 11), datetime.date(2026, 9, 15)))
        self.assertEqual(fetch.read_coverage(self.coverage_path), old_state)
        self.assertEqual(self.output()["scan_status"], "partial")

    def test_reviewed_date_resolves_only_a_confirmed_gap(self):
        fetch.write_coverage(self.coverage_path, fetch.update_coverage({}, ["cs.CV"], ["2026-09-14", "2026-09-16"]))
        self.parse_feed.return_value = [self.candidate(announced="2026-09-16")]
        code, _ = self.run_main("--reviewed-date", "2026-09-15")
        self.assertEqual(code, 0)
        self.assertEqual(self.output()["scan_status"], "success")
        self.assertEqual(fetch.pending_dates(fetch.read_coverage(self.coverage_path), ["cs.CV"]), [])

    def test_backfill_406_does_not_repeat_other_searches(self):
        self.cfg["queries"].append(dict(self.cfg["queries"][0], name="Driving"))
        self.api.side_effect = http_error(406)
        code, _ = self.run_main("--backfill-from", "2026-09-11", "--backfill-to", "2026-09-15")
        self.assertEqual(code, 1)
        self.api.assert_called_once()
        self.feed.assert_not_called()
        self.assertEqual(self.output()["scan_status"], "failed")
        self.assertFalse(self.coverage_path.exists())


class FetchUrlTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.now = 1000.0
        self.stack.enter_context(patch.object(fetch, "_next_request_at", 0.0))
        self.stack.enter_context(patch.object(fetch.time, "monotonic", side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(fetch.time, "time", side_effect=lambda: 1_800_000_000 + self.now))
        real_datetime = datetime.datetime
        fake_datetime = self.stack.enter_context(patch.object(fetch.datetime, "datetime", wraps=real_datetime))
        fake_datetime.now.side_effect = lambda tz=None: real_datetime.fromtimestamp(1_800_000_000 + self.now, tz)
        self.sleep = self.stack.enter_context(patch.object(fetch.time, "sleep", side_effect=self.advance))
        self.stack.enter_context(patch.object(fetch.random, "uniform", return_value=0))
        self.urlopen = self.stack.enter_context(patch.object(fetch.urllib.request, "urlopen"))
        self.response = MagicMock()
        self.response.__enter__.return_value.read.return_value = b"<feed />"

    def advance(self, seconds):
        self.now += seconds

    def test_transient_errors_retry_and_recover(self):
        errors = [http_error(code) for code in (408, 429, 500, 502, 503, 504)] + [
            urllib.error.URLError("offline"), TimeoutError("timed out"),
            ConnectionError("disconnected"), http.client.RemoteDisconnected("closed"),
        ]
        for error in errors:
            with self.subTest(error=repr(error)):
                fetch._next_request_at = 0
                self.urlopen.reset_mock()
                self.urlopen.side_effect = [error, self.response]
                result = fetch.fetch_url("https://example.invalid", retries=2, timeout=12, delay=5)
                self.assertEqual(result, b"<feed />")
                self.assertEqual(self.urlopen.call_count, 2)
                self.assertEqual(self.urlopen.call_args.kwargs["timeout"], 12)

    def test_http_400_is_not_retried(self):
        self.urlopen.side_effect = http_error(400)
        with self.assertRaises(urllib.error.HTTPError):
            fetch.fetch_url("https://example.invalid", retries=3)
        self.urlopen.assert_called_once()

    def test_retry_after_cooldown_is_shared_between_api_and_feed(self):
        for header in ("40", email.utils.formatdate(1_800_001_060, usegmt=True)):
            with self.subTest(retry_after=header):
                self.now = 1000.0
                fetch._next_request_at = 0
                self.urlopen.side_effect = [http_error(429, header), self.response]
                with self.assertRaises(urllib.error.HTTPError):
                    fetch.fetch_query("all:test", 10, retries=1)
                result = fetch.fetch_url("https://rss.arxiv.org/atom/cs.CV", retries=1)
                self.assertEqual(result, b"<feed />")
                self.assertGreaterEqual(self.now, 1040.0 if header == "40" else 1060.0)

    def test_long_retry_after_defers_without_another_request(self):
        self.urlopen.side_effect = http_error(429, "600")
        with self.assertRaises(fetch.RequestDeferred):
            fetch.fetch_url("https://example.invalid", retries=3)
        self.urlopen.assert_called_once()
        self.assertLessEqual(self.now - 1000.0, fetch.REQUEST_WAIT_BUDGET)
        with self.assertRaises(fetch.RequestDeferred):
            fetch.fetch_url("https://rss.arxiv.org/atom/cs.CV", retries=1)
        self.urlopen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
