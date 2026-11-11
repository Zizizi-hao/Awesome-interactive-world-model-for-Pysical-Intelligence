"""Parse arXiv's daily Atom announcements for local candidate matching.

The daily feed covers the latest announcement only, not the API's lookback
window. Its published timestamp is an announcement date, not submission time.
See https://info.arxiv.org/help/atom_specifications.html and /help/rss.html.
"""

import datetime
import re
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET


ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"
FEED_LIMIT = 2000


def _text(element: ET.Element, tag: str) -> str:
    child = element.find(tag)
    return re.sub(r"\s+", " ", "".join(child.itertext()) if child is not None else "").strip()


def _date(value: str, label: str) -> str:
    try:
        stamp = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"arXiv feed has missing or invalid {label}: {value!r}") from exc
    if stamp.year < 1991 or stamp.tzinfo is None:
        raise ValueError(f"arXiv feed has invalid {label}: {value!r}")
    return stamp.date().isoformat()


def _arxiv_id(value: str) -> str:
    if value.startswith("oai:arXiv.org:"):
        value = value[len("oai:arXiv.org:"):]
    elif value.startswith(("https://arxiv.org/abs/", "http://arxiv.org/abs/")):
        value = urllib.parse.urlsplit(value).path[len("/abs/"):]
    value = re.sub(r"v\d+$", "", value)
    if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z][a-z.-]*/\d{7})", value):
        raise ValueError(f"arXiv feed contains an invalid paper id: {value!r}")
    return value


def parse_feed(xml_bytes: bytes) -> list[dict]:
    """Return validated daily announcements, with a distinct ``announced`` date.

    ``published`` is deliberately blank so consumers cannot accidentally label
    an announcement as its original submission. ``categories`` includes all
    listed categories; their ordering does not establish a primary category.
    A feed at the official 2,000-entry cap is rejected as possibly truncated.
    """
    root = ET.fromstring(xml_bytes)
    if root.tag != f"{ATOM}feed":
        raise ValueError("arXiv daily feed response is not an Atom feed")
    if not _text(root, f"{ATOM}id") or not _text(root, f"{ATOM}title"):
        raise ValueError("arXiv daily feed is missing its id or title")
    if _text(root, f"{ATOM}title").casefold() == "error":
        raise ValueError("arXiv returned an error feed")
    _date(_text(root, f"{ATOM}updated"), "feed generation timestamp")
    raw_entries = root.findall(f"{ATOM}entry")
    if len(raw_entries) >= FEED_LIMIT:
        raise ValueError(f"arXiv daily feed reached {FEED_LIMIT} entries and may be truncated")

    entries = []
    for entry in raw_entries:
        raw_id = _text(entry, f"{ATOM}id")
        title = _text(entry, f"{ATOM}title")
        summary = _text(entry, f"{ATOM}summary")
        if "/api/errors" in raw_id or title.casefold() == "error":
            raise ValueError(f"arXiv returned an error entry: {summary or raw_id}")
        paper_id = _arxiv_id(raw_id)
        if not title or not summary:
            raise ValueError(f"arXiv feed entry {paper_id} lacks title or abstract")
        announced = _date(_text(entry, f"{ATOM}published"), "announcement timestamp")
        summary = re.sub(
            r"^arXiv:\S+\s+Announce Type:\s*\S+\s+Abstract:\s*",
            "", summary, flags=re.IGNORECASE,
        )
        categories = [c.get("term", "") for c in entry.findall(f"{ATOM}category")]
        categories = [category for category in categories if category]
        if not categories:
            raise ValueError(f"arXiv feed entry {paper_id} has no categories")
        primary = entry.find(f"{ARXIV_NS}primary_category")
        authors = [_text(author, f"{ATOM}name") for author in entry.findall(f"{ATOM}author")]
        if not authors:
            # The official daily feed supplies a comma-separated dc:creator.
            authors = [name.strip() for name in _text(entry, f"{DC_NS}creator").split(",")]
        entries.append({
            "id": paper_id,
            "title": title,
            "abstract": summary,
            "published": "",
            "announced": announced,
            "date_label": "公告日期",
            "authors": [author for author in authors if author],
            "primary_category": primary.get("term", "") if primary is not None else "",
            "categories": categories,
            "announce_type": _text(entry, f"{ARXIV_NS}announce_type"),
            "source": "feed",
        })
    return entries


def _normalize(value: str) -> str:
    # Word separators make ASCII/Unicode hyphens and whitespace equivalent.
    return re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


def matches_query(entry: dict, query_config: dict) -> bool:
    """Match AND-of-OR ``feed_keywords`` phrases in title or abstract only.

    This is explicit local phrase matching, not an emulation of API ``all:``
    search. Plurals or other variants must appear in the configured OR group.
    """
    groups = query_config.get("feed_keywords")
    if not isinstance(groups, list) or not groups:
        raise ValueError("Each Atom query requires nonempty feed_keywords groups")
    fields = [f" {_normalize(entry.get(key, ''))} " for key in ("title", "abstract")]
    for group in groups:
        if not isinstance(group, list) or not group:
            raise ValueError("Each feed_keywords group must be a nonempty list of phrases")
        if any(not isinstance(phrase, str) or not _normalize(phrase) for phrase in group):
            raise ValueError("Each feed_keywords phrase must be a nonempty string")
    return all(
        any(f" {_normalize(phrase)} " in field for phrase in group for field in fields)
        for group in groups
    )
