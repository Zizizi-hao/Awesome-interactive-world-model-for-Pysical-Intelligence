"""Track possible gaps between validated arXiv Atom announcement snapshots."""

import json
import os
import tempfile
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path


def _category_key(categories: list[str]) -> str:
    return "+".join(sorted(set(categories)))


def _announcement_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid announcement date: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"Expected an announcement date in YYYY-MM-DD format: {value!r}")
    return parsed


def _validate_coverage(state: dict) -> None:
    if not isinstance(state, dict):
        raise ValueError("arXiv coverage must be a JSON object")
    for key, record in state.items():
        if not isinstance(record, dict) or not isinstance(record.get("pending"), list):
            raise ValueError(f"Invalid arXiv coverage record for {key!r}")
        last = _announcement_date(record.get("last_observed"))
        for value in record["pending"]:
            pending = _announcement_date(value)
            if pending >= last or pending.weekday() >= 5:
                raise ValueError(f"Invalid pending announcement date for {key!r}: {value}")


def read_coverage(path: Path) -> dict:
    """Load coverage, starting empty only when the state file is absent."""
    try:
        with path.open(encoding="utf-8") as stream:
            state = json.load(stream)
    except FileNotFoundError:
        return {}
    _validate_coverage(state)
    return state


def update_coverage(
    state: dict, categories: list[str], announcement_dates: Iterable[str]
) -> dict:
    """Return updated coverage for dates from nonempty, validated Atom feeds.

    Dates are the Eastern mailing dates of Atom entries. arXiv publishes on
    Sunday through Thursday evenings, while the Atom mailings fall on Monday
    through Friday. A missing weekday is only a possible gap, including on
    holidays. https://info.arxiv.org/help/availability.html#announcement-schedule
    """
    observed_dates = sorted({_announcement_date(value) for value in announcement_dates})
    if not observed_dates:
        return state.copy()

    key = _category_key(categories)
    record = state.get(key)
    last = _announcement_date(record["last_observed"]) if record else observed_dates[0]
    pending = {_announcement_date(value) for value in record["pending"]} if record else set()
    day = timedelta(days=1)
    for observed in observed_dates:
        pending.discard(observed)
        if observed <= last:
            continue
        possible = last + day
        while possible < observed:
            if possible.weekday() < 5:
                pending.add(possible)
            possible += day
        last = observed

    return {
        **state,
        key: {
            "last_observed": last.isoformat(),
            "pending": [value.isoformat() for value in sorted(pending)],
        },
    }


def pending_dates(state: dict, categories: list[str]) -> list[str]:
    """Return the unresolved dates for this exact category set."""
    return sorted(set(state.get(_category_key(categories), {}).get("pending", [])))


def mark_reviewed(state: dict, categories: list[str], dates: Iterable[str]) -> dict:
    """Clear existing gaps explicitly checked by an operator."""
    reviewed = {_announcement_date(value).isoformat() for value in dates}
    key = _category_key(categories)
    if key not in state:
        return state.copy()
    record = state[key]
    return {
        **state,
        key: {**record, "pending": sorted(set(record["pending"]) - reviewed)},
    }


def write_coverage(path: Path, state: dict) -> None:
    """Replace the coverage file atomically after writing a sibling file."""
    _validate_coverage(state)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(state, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
