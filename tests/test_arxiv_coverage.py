import tempfile
import unittest
from pathlib import Path

from scripts.arxiv_coverage import mark_reviewed, pending_dates, read_coverage, update_coverage, write_coverage


class CoverageTests(unittest.TestCase):
    def test_out_of_order_snapshot_fills_gap_without_moving_latest_date(self):
        state = update_coverage({}, ["cs.CV"], ["2026-11-06"])
        state = update_coverage(state, ["cs.CV"], ["2026-11-10"])
        self.assertEqual(pending_dates(state, ["cs.CV"]), ["2026-11-09"])
        self.assertEqual(pending_dates(state, ["cs.RO"]), [])
        recovered = update_coverage(state, ["cs.CV"], ["2026-11-09"])
        self.assertEqual(pending_dates(recovered, ["cs.CV"]), [])
        self.assertEqual(recovered["cs.CV"]["last_observed"], "2026-11-10")

    def test_long_interruption_keeps_gaps_until_observed_or_reviewed(self):
        state = update_coverage({}, ["cs.RO"], ["2026-11-02", "2026-11-16"])
        self.assertEqual(len(pending_dates(state, ["cs.RO"])), 9)
        state = mark_reviewed(state, ["cs.RO"], ["2026-11-11"])
        state = update_coverage(state, ["cs.RO"], ["2026-11-17"])
        self.assertEqual(len(pending_dates(state, ["cs.RO"])), 8)
        self.assertNotIn("2026-11-11", pending_dates(state, ["cs.RO"]))

    def test_saved_coverage_round_trips_and_invalid_state_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coverage.json"
            self.assertEqual(read_coverage(path), {})
            state = update_coverage({}, ["cs.CV"], ["2026-11-10"])
            write_coverage(path, state)
            self.assertEqual(read_coverage(path), state)
            path.write_text('{"cs.CV": {"pending": ["2026-11-09"]}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                read_coverage(path)
