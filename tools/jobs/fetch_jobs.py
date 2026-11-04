"""Fetch data engineering jobs and publish jobs.json for the app.

Reads the curated boards in jobs/companies.yaml plus the public job boards in
sources.BOARDS, keeps data engineering roles in North America, Europe and India
(and remote roles open worldwide), tags level and skills, removes duplicates and
writes:

  <out>/jobs.json                  everything the app downloads
  <out>/history/<yyyy-mm-dd>.json  today's skill shares, for week-on-week trends

Usage: python tools/jobs/fetch_jobs.py [--out build/jobs] [--max-age-days 180] [--board-max-age-days 45] [--only N]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sources  # noqa: E402
from taxonomy import (  # noqa: E402
    REGIONS,
    classify_location,
    level_of,
    min_years,
    names_other_country,
    skills_in,
    summary,
)

ROOT = Path(__file__).resolve().parents[2]
COMPANIES = ROOT / "jobs" / "companies.yaml"
SCHEMA_VERSION = 1

# Lower number wins when the same job appears in several sources.
_SOURCE_RANK = {name: 0 for name in sources.ATS} | {"arbeitnow": 1, "adzuna": 2}


def _fetch_company(entry: dict) -> list[dict]:
    fn = sources.ATS.get(entry["ats"])
    if fn is None:
        return []
    try:
        return list(fn(entry["name"], entry["slug"]))
    except Exception as e:  # one broken board must not stop the run
        print(f"  ! {entry['name']} ({entry['ats']}): {e}", file=sys.stderr)
        return []


def _fetch_board(key: str) -> list[dict]:
    try:
        return list(sources.BOARDS[key][2]())
    except Exception as e:
        print(f"  ! board {key}: {e}", file=sys.stderr)
        return []


def normalise(raw: dict) -> dict | None:
    locations = [raw["location"], *raw.get("extra_locations", [])]
    regions: set[str] = set()
    remote = raw.get("remote_hint", False)
    for i, loc in enumerate(locations):
        r, rem = classify_location(loc, remote_hint=False, country_codes=raw.get("country_codes") if i == 0 else None)
        regions.update(r)
        remote = remote or rem
    # A remote job with no region named is open worldwide, unless it names a
    # country outside our regions ("Remote, Brazil").
    if not regions and (not remote or any(names_other_country(loc) for loc in locations)):
        return None
    text = raw.get("text") or ""
    blob = f"{raw['title']} {text}"
    key = f"{raw['source']}:{raw['source_id']}"
    return {
        "id": hashlib.sha1(key.encode()).hexdigest()[:12],
        "title": raw["title"].strip(),
        "company": raw["company"].strip(),
        "location": (raw["location"] or ("Remote" if remote else "")).strip(),
        "regions": [r for r in REGIONS if r in regions],
        "remote": remote,
        "level": level_of(raw["title"]),
        "minYears": min_years(text),
        "skills": skills_in(blob),
        "postedAt": raw["posted_at"].strftime("%Y-%m-%dT%H:%M:%SZ") if raw.get("posted_at") else None,
        "url": raw["url"],
        "source": raw["source"],
        "summary": summary(text),
    }


def _dedupe_key(job: dict) -> str:
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    return f"{norm(job['company'])}|{norm(job['title'])}|{norm(job['location'])[:20]}"


def skill_shares(jobs: list[dict]) -> dict[str, float]:
    if not jobs:
        return {}
    counts = Counter(s for j in jobs for s in j["skills"])
    return {s: round(n / len(jobs), 4) for s, n in counts.most_common()}


def trends(today: dict[str, float], history_dir: Path, now: datetime) -> list[dict]:
    """Compare with the snapshot closest to 7 days ago (within 5–10 days)."""
    previous: dict[str, float] = {}
    for days in (7, 6, 8, 5, 9, 10):
        f = history_dir / f"{(now - timedelta(days=days)).date().isoformat()}.json"
        if f.exists():
            previous = json.loads(f.read_text(encoding="utf-8")).get("skillShares", {})
            break
    return [
        {"skill": s, "share": share, **({"prevShare": previous[s]} if s in previous else {})}
        for s, share in today.items()
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "build" / "jobs"))
    parser.add_argument("--max-age-days", type=int, default=180,
                        help="for company boards; a posting still on a board is an open role")
    parser.add_argument("--board-max-age-days", type=int, default=45, help="for job-board listings")
    parser.add_argument("--only", type=int, default=0, help="read only the first N company boards (testing)")
    args = parser.parse_args()

    out = Path(args.out)
    history = out / "history"
    history.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    started = time.time()

    companies = yaml.safe_load(COMPANIES.read_text(encoding="utf-8"))["companies"]
    companies = [c for c in companies if not c.get("disabled")]
    if args.only:
        companies = companies[: args.only]

    raw: list[dict] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        for rows in pool.map(_fetch_company, companies):
            raw.extend(rows)
        for rows in pool.map(_fetch_board, list(sources.BOARDS)):
            raw.extend(rows)

    cutoffs = {name: now - timedelta(days=args.max_age_days) for name in sources.ATS} | {
        name: now - timedelta(days=args.board_max_age_days) for name in sources.BOARDS
    }
    best: dict[str, dict] = {}
    dropped = Counter()
    for r in raw:
        if not r.get("url"):
            dropped["no url"] += 1
            continue
        if r.get("posted_at") and r["posted_at"] < cutoffs[r["source"]]:
            dropped["too old"] += 1
            continue
        job = normalise(r)
        if job is None:
            dropped["outside regions"] += 1
            continue
        key = _dedupe_key(job)
        kept = best.get(key)
        if kept is None or _SOURCE_RANK[job["source"]] < _SOURCE_RANK[kept["source"]]:
            if kept is not None:
                dropped["duplicate"] += 1
            best[key] = job
        else:
            dropped["duplicate"] += 1

    jobs = sorted(best.values(), key=lambda j: j["postedAt"] or "", reverse=True)
    shares = skill_shares(jobs)
    (history / f"{now.date().isoformat()}.json").write_text(
        json.dumps({"date": now.date().isoformat(), "jobs": len(jobs), "skillShares": shares}), encoding="utf-8"
    )
    used_boards = sorted({j["source"] for j in jobs} & set(sources.BOARDS))
    payload = {
        "version": SCHEMA_VERSION,
        "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "attribution": [
            {"id": k, "name": sources.BOARDS[k][0], "url": sources.BOARDS[k][1]} for k in used_boards
        ],
        "skillTrends": trends(shares, history, now),
        "jobs": jobs,
    }
    (out / "jobs.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    by_region = Counter(r for j in jobs for r in j["regions"])
    print(f"{len(jobs)} jobs from {len(raw)} matching postings in {time.time() - started:.0f}s")
    print(f"  regions: {dict(by_region)}, remote: {sum(j['remote'] for j in jobs)}")
    print(f"  sources: {dict(Counter(j['source'] for j in jobs))}")
    print(f"  dropped: {dict(dropped)}")
    print(f"  top skills: {list(shares.items())[:8]}")


if __name__ == "__main__":
    main()
