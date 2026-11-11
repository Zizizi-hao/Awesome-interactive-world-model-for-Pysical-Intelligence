"""Bounded arXiv search API pagination for explicit UTC submission windows."""

import datetime
import xml.etree.ElementTree as ET

from arxiv_feed import ARXIV_NS, ATOM, _arxiv_id, _text


OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"


def parse_page(payload, offset, size, start, end):
    root = ET.fromstring(payload)
    if root.tag != f"{ATOM}feed" or _text(root, f"{ATOM}title").casefold() == "error":
        raise ValueError("arXiv search did not return a valid Atom feed")
    entries = root.findall(f"{ATOM}entry")
    for entry in entries:
        if "/api/errors" in _text(entry, f"{ATOM}id") or _text(entry, f"{ATOM}title").casefold() == "error":
            raise ValueError(_text(entry, f"{ATOM}summary") or "arXiv search returned an error")
    try:
        total, index, per_page = (int(_text(root, f"{OPENSEARCH}{tag}"))
                                  for tag in ("totalResults", "startIndex", "itemsPerPage"))
    except ValueError as exc:
        raise ValueError("arXiv search is missing valid pagination metadata") from exc
    if total < 0 or index != offset or per_page not in {size, len(entries)}:
        raise ValueError("arXiv search returned inconsistent pagination metadata")
    if len(entries) != min(size, max(0, total - offset)):
        raise ValueError("arXiv search returned an incomplete page")

    papers = []
    for entry in entries:
        paper_id = _arxiv_id(_text(entry, f"{ATOM}id"))
        title = _text(entry, f"{ATOM}title")
        abstract = _text(entry, f"{ATOM}summary")
        timestamp = datetime.datetime.fromisoformat(_text(entry, f"{ATOM}published").replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError(f"Missing timezone in arXiv submission date for {paper_id}")
        published = timestamp.astimezone(datetime.timezone.utc).date()
        if not start <= published <= end:
            raise ValueError(f"arXiv search returned {paper_id} outside the requested submission window")
        categories = [node.get("term") for node in entry.findall(f"{ATOM}category") if node.get("term")]
        primary = entry.find(f"{ARXIV_NS}primary_category")
        if not title or not abstract or not categories:
            raise ValueError(f"arXiv search returned incomplete metadata for {paper_id}")
        papers.append({
            "id": paper_id, "title": title, "abstract": abstract, "published": published.isoformat(),
            "authors": [_text(a, f"{ATOM}name") for a in entry.findall(f"{ATOM}author")],
            "categories": categories, "primary_category": primary.get("term", "") if primary is not None else "",
        })
    return total, papers


def fetch_backfill(search, start, end, fetch_page, *, page_size=100, max_pages=3):
    """Return the whole query or raise if any page is missing or inconsistent."""
    if start > end or not 1 <= page_size <= 2000 or max_pages < 1 or page_size * max_pages > 30000:
        raise ValueError("Invalid arXiv backfill dates or pagination limits")
    start_term = start.isoformat().replace("-", "") + "0000"
    end_term = end.isoformat().replace("-", "") + "2359"
    query = f"({search}) AND submittedDate:[{start_term} TO {end_term}]"
    papers = {}
    total = None
    for offset in range(0, page_size * max_pages, page_size):
        page_total, batch = parse_page(fetch_page(query, offset, page_size), offset, page_size, start, end)
        if total is None:
            total = page_total
            if total > page_size * max_pages:
                raise ValueError(f"API 补扫命中 {total} 条，超过 {max_pages} 页上限。请缩短日期区间。")
        elif page_total != total:
            raise ValueError("arXiv search result count changed during backfill")
        for paper in batch:
            paper_id = paper["id"]
            if paper_id in papers:
                raise ValueError(f"arXiv search returned duplicate ID {paper_id} during backfill")
            papers[paper_id] = paper
        if len(papers) == total:
            return list(papers.values())
    raise ValueError("arXiv backfill did not reach the reported total")
