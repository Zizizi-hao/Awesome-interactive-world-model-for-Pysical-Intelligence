# Contributing

[简体中文](CONTRIBUTING.md) | **English**

Thanks for contributing! This repository keeps data separate from presentation:

- [`data.yaml`](data.yaml) contains metadata and category definitions, and references category files through `includes`.
- [`data/`](data/) stores paper entries by category (`driving.yaml`, `embodied.yaml`, and `general.yaml`).
- [`README.md`](README.md) and [`README.en.md`](README.en.md) are the Chinese and English homepages. Both are generated automatically; **do not edit them manually**.

## Adding or editing entries

1. Edit the appropriate `data/<category>.yaml` file (for example, `data/driving.yaml` for autonomous driving) and add an entry to its `papers` list:

```yaml
- title: "Full paper title"     # Required
  short: Acronym               # Optional; displayed in bold in the table
  org: Organization name       # Optional; Chinese or English
  org_en: Organization name    # Required if org contains Chinese; otherwise optional
  year: 2025                   # Required; year of first publication, displayed as (year)
  venue: Conference or journal # Required; use arXiv if unpublished; omit the year
  category: driving            # Required; see category IDs below
  links:
    arxiv: "2501.00000"         # arXiv ID, without the domain
    project: "https://..."      # Optional project page
    code: "https://..."         # Optional code repository
    demo: "https://..."         # Optional online demo
  features:                    # Use verified capabilities; may be empty {}
    action: true               # Action-conditioned generation
    realtime: true             # Real-time inference
    closedloop: true           # Closed-loop support
    longhorizon: true          # Long-horizon consistency
  tags: [tag1, tag2]            # Optional free-form keywords
  note: "Chinese summary"      # Required; describe the contribution and interactivity in Chinese
  note_en: "English summary"   # Required; preserve the same facts, numbers, and qualifications
```

2. Set `meta.updated` in `data.yaml` to today's date. The README's last-updated date comes from this field, rather than the Git commit date.

3. Regenerate both READMEs locally:

```bash
pip install pyyaml
python scripts/generate_readme.py
```

4. Include the changed `data/*.yaml`, `data.yaml`, `README.md`, and `README.en.md` in your pull request. CI checks both READMEs against the data. If an English summary or organization translation is missing, the generator identifies the affected entry.

English homepage text is stored in `meta.subtitle_en` and `meta.description_en` in `data.yaml`; category names use `name_en`. Update the corresponding translation whenever the source text changes.

To update both monthly paper-count charts, run:

```bash
pip install matplotlib
python scripts/generate_monthly_chart.py
```

Months are taken from arXiv IDs, with the cutoff month determined by `meta.updated`. Commit both generated `assets/monthly-paper-counts*.png` files.

## Maintaining the automatic scan

The daily scan reads each configured arXiv category's Atom feed in turn. A feed at the 2,000-entry cap is flagged as incomplete. The scanner matches `feed_keywords` locally against full titles and abstracts, using OR within groups and AND between groups, and includes cross-listings. Requests run serially at least five seconds apart and respect `Retry-After`. [Scan configuration](scripts/arxiv_config.yaml) · [arXiv feeds](https://info.arxiv.org/help/rss.html) · [Rate limits](https://info.arxiv.org/help/api/tou.html#rate-limits)

Each run uploads the valid raw category XML files in an `arxiv-atom-snapshot-${{ github.run_attempt }}` artifact for 90 days. Coverage is stored separately for each category, starts with its first valid nonempty snapshot, and tracks possible gaps on Monday through Friday in US Eastern time. Empty or stale feeds leave the coverage date unchanged. Holidays may also appear as gaps to review. [Coverage state](data/arxiv_scan_coverage.json) · [Atom date fields](https://info.arxiv.org/help/atom_specifications.html#atom-entry-elements)

The run summary reports scan coverage and publication outcomes separately. The workflow can publish candidates from a partial scan. A total fetch failure or a failure to archive snapshots, publish candidates, or save scan state marks the run as failed.

Use `--dry-run` to preview results without writing scan state. Use `--replay PATH` to replay saved raw Atom XML offline in read-only mode. Repeat the flag to replay snapshots from multiple categories together. When changing keywords, keep `feed_keywords` and the `search` conditions for manual API backfills in sync. Run the tests and replay a snapshot to verify changes.

```bash
python3 -m unittest discover -s tests
python3 -u scripts/fetch_arxiv.py --replay /path/to/atom.xml
python3 -u scripts/fetch_arxiv.py --dry-run
```

For a manual backfill, supply both `--backfill-from YYYY-MM-DD` and `--backfill-to YYYY-MM-DD`. The paginated API uses UTC submission dates, includes both endpoints, and covers at most 14 days. A Monday announcement may include submissions from the preceding Thursday and Friday, so choose the submission window accordingly. Announcement gaps still require independent review after backfill. Use `--reviewed-date YYYY-MM-DD` after independently checking all pending categories for that date or confirming a holiday. The flag applies to every pending category on that date. Repeat it for multiple dates. [arXiv announcement schedule](https://info.arxiv.org/help/availability.html#announcement-schedule)

After pushing an update, start a new run via **Actions → Daily arXiv scan → Run workflow → main**. For manual backfill, fill in `backfill_from` and `backfill_to`. Enter reviewed dates in `reviewed_dates`, separated by spaces. Re-running an old job uses its original commit. The fetch step prints the actual commit hash.

## Inclusion criteria

- Work should predict or generate the world using a **learnable dynamics model** and serve autonomous driving or embodied AI.
- Prefer work supporting **action conditioning** or **interactive control**. For pure video prediction, explain its relationship to interactivity in both summaries.
- Ensure arXiv IDs and publication metadata are accurate. Omit uncertain information rather than guess.

## Categories

| Category ID | Scope |
| :--- | :--- |
| `driving` | World models for autonomous driving: data engines, neural simulation, prediction, and planning |
| `embodied` | World models for robots and embodied agents |
| `general` | General world models, world foundation models, neural game engines, and related work |
