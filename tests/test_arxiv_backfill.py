import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from arxiv_backfill import fetch_backfill


def entry(paper_id, published="2026-11-02T23:59:55Z"):
    return f"""<entry>
      <id>http://arxiv.org/abs/{paper_id}</id>
      <title>Example dynamics</title><summary>Example abstract.</summary>
      <published>{published}</published><category term="cs.RO"/>
      <category term="cs.CV"/><author><name>Example Author</name></author>
    </entry>"""


def page(total, index, size, *entries):
    return f"""<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
      <opensearch:totalResults>{total}</opensearch:totalResults>
      <opensearch:startIndex>{index}</opensearch:startIndex>
      <opensearch:itemsPerPage>{size}</opensearch:itemsPerPage>
      {''.join(entries)}</feed>""".encode()


class BackfillTests(unittest.TestCase):
    def backfill(self, fetch, **kwargs):
        return fetch_backfill("all:robot OR all:physics", date(2026, 11, 1), date(2026, 11, 2),
                              fetch, page_size=2, **kwargs)

    def test_pages_are_fetched_in_order_and_normalized(self):
        fetch = Mock(side_effect=[page(3, 0, 2, entry("2611.00003v2"), entry("2611.00002v1")),
                                  page(3, 2, 1, entry("hep-ex/0307015v3"))])
        papers = self.backfill(fetch)
        self.assertEqual([p["id"] for p in papers], ["2611.00003", "2611.00002", "hep-ex/0307015"])
        self.assertEqual(papers[0]["categories"], ["cs.RO", "cs.CV"])
        self.assertEqual([c.args[1:] for c in fetch.call_args_list], [(0, 2), (2, 2)])
        self.assertEqual(fetch.call_args.args[0], "(all:robot OR all:physics) AND submittedDate:[202611010000 TO 202611022359]")

    def test_empty_query_completes(self):
        fetch = Mock(return_value=page(0, 0, 2))
        self.assertEqual(self.backfill(fetch), [])
        fetch.assert_called_once()

    def test_result_limit_stops_before_more_requests(self):
        fetch = Mock(return_value=page(3, 0, 2, entry("2611.00003"), entry("2611.00002")))
        with self.assertRaisesRegex(ValueError, "超过"):
            self.backfill(fetch, max_pages=1)
        fetch.assert_called_once()

    def test_incomplete_duplicate_or_out_of_window_results_raise(self):
        for responses in (
            [page(3, 0, 2, entry("2611.00003"))],
            [page(3, 0, 2, entry("2611.00003"), entry("2611.00002")), page(3, 2, 2, entry("2611.00003v2"))],
            [page(3, 0, 2, entry("2611.00003"), entry("2611.00002")), page(4, 2, 2, entry("2611.00001"), entry("2611.00004"))],
            [page(1, 0, 2, entry("2611.00003", "2026-11-03T00:00:00Z"))],
            [b'<feed xmlns="http://www.w3.org/2005/Atom"/>'],
        ):
            with self.subTest(responses=responses), self.assertRaises(ValueError):
                self.backfill(Mock(side_effect=responses))
