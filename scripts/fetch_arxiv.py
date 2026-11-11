#!/usr/bin/env python3
"""Read the latest arXiv Atom announcements, or search a bounded backfill window."""

import argparse
import datetime
import hashlib
import http.client
import os
import random
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from email.utils import parsedate_to_datetime

from arxiv_backfill import fetch_backfill
from arxiv_coverage import mark_reviewed, pending_dates, read_coverage, update_coverage, write_coverage
from arxiv_feed import matches_query, parse_feed

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pip install pyyaml")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = Path(__file__).resolve().parent / "arxiv_config.yaml"
DATA_FILE = ROOT / "data.yaml"
SEEN_FILE = ROOT / "data" / "seen_arxiv_ids.txt"
COVERAGE_FILE = ROOT / "data" / "arxiv_scan_coverage.json"

API_URL = "https://export.arxiv.org/api/query"
FEED_URL = "https://rss.arxiv.org/atom/"
USER_AGENT = "awesome-interactive-world-models/1.0 (https://github.com/Zizizi-hao/Awesome-interactive-world-model-for-Pysical-Intelligence)"
REQUEST_WAIT_BUDGET = 300
MAX_BACKFILL_DAYS = 14
_next_request_at = 0.0
NETWORK_ERRORS = (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException)


class RequestDeferred(RuntimeError):
    """服务端要求的冷却时间超出本轮预算；本轮不再请求其他来源。"""


def retry_after_seconds(value: str) -> float:
    if not value:
        return 0
    try:
        return max(0, int(value.strip()))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=datetime.timezone.utc)
            return max(0, (date - datetime.datetime.now(datetime.timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 0


def is_transient(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code in {408, 429, 500, 502, 503, 504}
    return isinstance(error, NETWORK_ERRORS)


def fetch_url(url: str, retries: int = 3, timeout: int = 60, delay: float = 5) -> bytes:
    """所有来源共享请求间隔和 Retry-After；retries 为总尝试次数。"""
    global _next_request_at
    if retries < 1 or timeout <= 0:
        raise ValueError("retry_attempts 和 timeout_seconds 必须大于 0")
    delay = max(5, delay)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, retries + 1):
        wait = max(0, _next_request_at - time.monotonic())
        if wait > REQUEST_WAIT_BUDGET:
            raise RequestDeferred(f"服务端冷却还需 {wait:.0f}s，超过本轮等待预算；停止所有后续请求")
        if wait:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = resp.read()
            _next_request_at = time.monotonic() + delay
            return result
        except NETWORK_ERRORS as error:
            retry_after = retry_after_seconds(error.headers.get("Retry-After")) if isinstance(error, urllib.error.HTTPError) and error.headers else 0
            wait = max(delay, retry_after)
            if is_transient(error):
                wait = max(wait, min(90, 15 * 2 ** (attempt - 1))) + random.uniform(0, 3)
            # 最后一次失败也保留冷却期，切换来源不能绕过 Retry-After。
            _next_request_at = time.monotonic() + wait
            if wait > REQUEST_WAIT_BUDGET:
                raise RequestDeferred(f"服务端要求等待 {wait:.0f}s，停止本轮所有后续请求") from error
            if attempt == retries or not is_transient(error):
                raise
            print(f"请求失败（{error}），{wait:.0f}s 后重试（{attempt}/{retries - 1}）...", flush=True)


def strip_version(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", str(arxiv_id).strip())


def fetch_query(search: str, max_results: int, retries: int = 3, timeout: int = 60, delay: float = 5, *, start: int = 0) -> bytes:
    params = urllib.parse.urlencode({
        "search_query": search,
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    return fetch_url(f"{API_URL}?{params}", retries=retries, timeout=timeout, delay=delay)


def existing_arxiv_ids() -> set:
    ids = set()
    data = yaml.safe_load(DATA_FILE.read_text(encoding="utf-8")) or {}
    files = [DATA_FILE] + [ROOT / rel for rel in data.get("includes") or []]
    for f in files:
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for p in d.get("papers") or []:
            aid = (p.get("links") or {}).get("arxiv")
            if aid:
                ids.add(strip_version(aid))
    return ids


def load_seen() -> set:
    if not SEEN_FILE.is_file():
        return set()
    return {
        strip_version(line)
        for line in SEEN_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def append_seen(new_ids) -> None:
    if SEEN_FILE.is_file():
        lines = SEEN_FILE.read_text(encoding="utf-8").splitlines()
    else:
        lines = ["# 已由 scripts/fetch_arxiv.py 报告过的 arXiv id，自动维护，勿手动编辑"]
    lines.extend(sorted(new_ids))
    SEEN_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def format_authors(authors: list, limit: int = 6) -> str:
    if len(authors) > limit:
        return ", ".join(authors[:limit]) + f" 等（共 {len(authors)} 人）"
    return ", ".join(authors)


def render_report(groups: dict, cfg: dict, coverage: list[str]) -> str:
    total = sum(len(v) for v in groups.values())
    max_chars = cfg.get("abstract_chars", 400)
    lines = [f"发现 **{total}** 篇新候选论文（由 `scripts/fetch_arxiv.py` 自动生成）。", "", *coverage, ""]
    for name, entries in groups.items():
        if not entries:
            continue
        lines += [f"## {name}", ""]
        for e in entries:
            abstract = e["abstract"]
            if len(abstract) > max_chars:
                abstract = abstract[:max_chars] + "..."
            date_text = f"提交日期: {e['published']}"
            category_text = "分类（含交叉分类）: " + ", ".join(e["categories"])
            if e.get("date_label") == "公告日期":
                date_text = f"公告日期: {e['announced']}"
            lines += [
                f"### {e['title']}",
                f"- arXiv: https://arxiv.org/abs/{e['id']}",
                f"- {date_text} ｜ {category_text}",
                f"- 作者: {format_authors(e['authors'])}",
                f"- 摘要: {abstract}",
                "",
            ]
    lines += [
        "---",
        "收录流程：将候选条目写入 `data/<category>.yaml`（字段规范见 CONTRIBUTING.md），"
        "然后运行 `python3 scripts/generate_readme.py` 重新生成 README。",
    ]
    return "\n".join(lines)


def scan_announcements(categories, options, state, snapshots):
    entries, failures, empty = [], {}, []
    for index, category in enumerate(categories):
        try:
            payload = fetch_url(FEED_URL + category, **options)
            batch = parse_feed(payload)
            if batch and any(category not in paper["categories"] for paper in batch):
                raise ValueError("公告含不属于此分类的条目")
        except (RequestDeferred, *NETWORK_ERRORS, ET.ParseError, ValueError) as error:
            failures[category] = str(error)
            if isinstance(error, RequestDeferred) or is_transient(error):
                failures.update({pending: "订阅源暂不可用，本轮未请求" for pending in categories[index + 1:]})
                break
            continue
        snapshots[category] = payload
        if not batch:
            empty.append(category)
            continue
        state = update_coverage(state, [category], {paper["announced"] for paper in batch})
        entries.extend(batch)
    return entries, state, failures, empty


def scan_backfill(queries, start, end, cfg, options):
    results, failures = {}, {}

    def fetch_page(search, offset, size):
        return fetch_query(search, size, start=offset, **options)

    for index, query in enumerate(queries):
        name = query["name"]
        try:
            results[name] = fetch_backfill(
                query["search"], start, end, fetch_page,
                page_size=cfg.get("backfill_page_size", 100),
                max_pages=cfg.get("backfill_max_pages", 3),
            )
        except (RequestDeferred, *NETWORK_ERRORS, ET.ParseError, ValueError) as error:
            failures[name] = str(error)
            rejected = isinstance(error, urllib.error.HTTPError) and error.code == 406
            if isinstance(error, RequestDeferred) or is_transient(error) or rejected:
                failures.update({q["name"]: "搜索 API 暂不可用，本轮未请求" for q in queries[index + 1:]})
                break
    return results, failures


def pick_candidates(results, categories):
    blocked = existing_arxiv_ids() | load_seen()
    reported = set()
    groups = {}
    for name, entries in results.items():
        groups[name] = []
        for paper in entries:
            paper_id = paper["id"]
            if paper_id in blocked or paper_id in reported:
                continue
            if categories and not set(categories).intersection(paper["categories"]):
                continue
            groups[name].append(paper)
            reported.add(paper_id)
    return groups, reported


def date_arg(value):
    try:
        date = datetime.date.fromisoformat(value)
        if date.isoformat() != value:
            raise ValueError
        return date
    except ValueError:
        raise argparse.ArgumentTypeError("日期须为 YYYY-MM-DD") from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="打印候选和覆盖情况，不写入状态")
    parser.add_argument("--replay", type=Path, action="append", help="离线读取已保存的 Atom XML，可重复使用")
    parser.add_argument("--backfill-from", type=date_arg, help="API 补扫起始提交日期（UTC，含当天）")
    parser.add_argument("--backfill-to", type=date_arg, help="API 补扫结束提交日期（UTC，含当天）")
    parser.add_argument("--reviewed-date", type=date_arg, action="append", default=[], help="已人工核对的待查公告日期，可重复使用")
    args = parser.parse_args()
    start, end = args.backfill_from, args.backfill_to
    if bool(start) != bool(end):
        parser.error("补扫须同时提供 --backfill-from 和 --backfill-to")
    if start and not 0 <= (end - start).days < MAX_BACKFILL_DAYS:
        parser.error(f"补扫须按日期顺序且最多覆盖 {MAX_BACKFILL_DAYS} 天")
    if args.replay and (start or args.reviewed_date):
        parser.error("--replay 仅用于离线查看候选，不能与补扫或复审参数组合")

    cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    categories = sorted(set(cfg.get("category_filter") or []))
    queries = cfg.get("queries") or []
    if not queries or (not categories and not (start or args.replay)):
        parser.error("须配置 queries，日常扫描还需配置 category_filter")
    if any(not re.fullmatch(r"[a-z-]+\.[A-Za-z]+", category) for category in categories):
        parser.error("category_filter 须逐项指定分类，如 cs.RO")
    options = {"retries": cfg.get("retry_attempts", 3), "timeout": cfg.get("timeout_seconds", 60),
               "delay": cfg.get("delay_seconds", 5)}
    state = read_coverage(COVERAGE_FILE)
    reviewed = {date.isoformat() for date in args.reviewed_date}
    if reviewed:
        pending = {date for cat in categories for date in pending_dates(state, [cat])}
        if unknown_dates := reviewed - pending:
            parser.error("以下日期不在待核查记录中 " + "、".join(sorted(unknown_dates)))
    snapshots = {}
    empty = []
    failures = {}
    if start:
        results, failures = scan_backfill(queries, start, end, cfg, options)
        valid = len(results)
        coverage = [f"- API 补扫提交日期（UTC）**{start} 至 {end}**，完成 **{valid}/{len(queries)}** 组查询。",
                    "- 提交日期与公告日期口径不同。请按实际公告核对历史缺期。"]
    else:
        if args.replay:
            entries = []
            valid = 0
            for path in args.replay:
                try:
                    entries.extend(parse_feed(path.read_bytes()))
                    valid += 1
                except (OSError, ET.ParseError, ValueError) as error:
                    failures[path.name] = str(error)
            coverage = [f"- 离线重跑 **{valid}/{len(args.replay)}** 个 Atom 快照。"]
        else:
            entries, state, failures, empty = scan_announcements(categories, options, state, snapshots)
            valid = len(snapshots)
            coverage = [f"- Atom 公告抓取 **{valid}/{len(categories)}** 个分类。匹配使用标题、摘要及交叉分类。"]
            if empty:
                coverage.append("- 本次公告内容为空，待核查 " + "、".join(empty) + "。")
        dates = sorted({paper["announced"] for paper in entries})
        if dates:
            coverage.append("- 本次获得公告日期 " + "、".join(dates) + "。")
        results = {q["name"]: [paper for paper in entries if matches_query(paper, q)] for q in queries}

    if reviewed and valid:
        for category in categories:
            state = mark_reviewed(state, [category], reviewed)
        coverage.append("- 人工确认已核查公告日期 " + "、".join(sorted(reviewed)) + "。")
    gaps = {cat: pending_dates(state, [cat]) for cat in categories}
    observed = [f"{cat} {state[cat]['last_observed']}" for cat in categories if cat in state]
    if observed:
        coverage.append("- 各分类最近确认公告 " + "、".join(observed) + "。")
    coverage.extend(f"- {cat} 可能缺失的公告日期 " + "、".join(dates) + "。" for cat, dates in gaps.items() if dates)
    coverage.extend(f"- {name} 获取失败 · {error}" for name, error in failures.items())
    status = "failed" if not valid else "partial" if failures or empty or any(gaps.values()) else "success"
    labels = {"success": "本轮抓取成功", "partial": "部分覆盖，仍有待核查项", "failed": "本轮抓取失败"}
    coverage.insert(0, f"**扫描覆盖 · {labels[status]}**")
    groups, reported = pick_candidates(results, categories)
    report = render_report(groups, cfg, coverage)
    print(report, flush=True)
    if args.dry_run or args.replay:
        if not valid:
            raise SystemExit(1)
        return

    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as file:
            file.write("\n".join(coverage) + f"\n- 新候选数 **{len(reported)}**。\n")
    output = {"has_new": str(bool(reported)).lower(), "scan_status": status, "candidate_count": len(reported)}
    if snapshots or reported:
        directory = Path(tempfile.mkdtemp(prefix="arxiv-scan-"))
        if snapshots:
            snapshot_dir = directory / "atom"
            snapshot_dir.mkdir()
            for category, payload in snapshots.items():
                (snapshot_dir / f"{category}.xml").write_bytes(payload)
            output["snapshot"] = snapshot_dir
            print(f"Atom 快照已保存到 {snapshot_dir}")
        if reported:
            report_path = directory / "arxiv_report.md"
            batch = hashlib.sha256("\n".join(sorted(reported)).encode()).hexdigest()
            report_path.write_text(f"<!-- arxiv-scan:{batch} -->\n{report}", encoding="utf-8")
            output["report"] = report_path
            output["batch"] = batch
            append_seen(reported)
            print(f"候选报告已保存到 {report_path}")
    if valid:
        write_coverage(COVERAGE_FILE, state)
    if target := os.environ.get("GITHUB_OUTPUT"):
        with open(target, "a", encoding="utf-8") as file:
            for key, value in output.items():
                file.write(f"{key}={value}\n")
    if not valid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
