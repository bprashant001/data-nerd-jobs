"""Find which public applicant-tracking-system (ATS) job board each company uses.

Reads jobs/companies_source.csv (country, company, category), tries likely
board slugs on the ATS vendors that publish an official, unauthenticated job
board API, and writes jobs/companies.yaml. Review that file by hand: it is the
curated list the daily fetcher reads, so wrong matches should be deleted and
missing boards can be added manually.

Vendors probed (all documented public endpoints meant for career sites):
  greenhouse       https://boards-api.greenhouse.io/v1/boards/{slug}
  lever            https://api.lever.co/v0/postings/{slug}?mode=json
  ashby            https://api.ashbyhq.com/posting-api/job-board/{slug}
  smartrecruiters  https://api.smartrecruiters.com/v1/companies/{slug}/postings
  workable         https://apply.workable.com/api/v1/widget/accounts/{slug}

Usage: python tools/jobs/discover_ats.py [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from http_util import get_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "jobs" / "companies_source.csv"
OUT = ROOT / "jobs" / "companies.yaml"

_SUFFIXES = re.compile(
    r"\b(inc|ltd|limited|llc|plc|gmbh|ag|sa|nv|bv|corp|corporation|co|company|group|technologies|"
    r"technology|labs|software|india|holdings)\b\.?",
    re.I,
)


def slug_candidates(name: str) -> list[str]:
    base = re.sub(r"\(.*?\)", "", name)
    base = base.replace("&", "and")
    words = re.findall(r"[a-z0-9]+", base.lower())
    stripped = re.findall(r"[a-z0-9]+", _SUFFIXES.sub(" ", base.lower()))
    out: list[str] = []
    for ws in (words, stripped):
        if not ws:
            continue
        for s in ("".join(ws), "-".join(ws)):
            if s and s not in out:
                out.append(s)
    return out


def _similar(a: str, b: str) -> float:
    norm = lambda s: re.sub(r"[^a-z0-9]", "", _SUFFIXES.sub("", s.lower()))
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def probe(slug: str) -> list[dict]:
    """All vendors where `slug` is a live board with at least one job."""
    hits = []

    gh = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}")
    if isinstance(gh, dict) and gh.get("name"):
        jobs = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
        n = len(jobs.get("jobs", [])) if isinstance(jobs, dict) else 0
        if n:
            hits.append({"ats": "greenhouse", "slug": slug, "board_name": gh["name"], "jobs": n})

    lv = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if isinstance(lv, list) and lv:
        hits.append({"ats": "lever", "slug": slug, "board_name": None, "jobs": len(lv)})

    ab = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if isinstance(ab, dict) and ab.get("jobs"):
        hits.append({"ats": "ashby", "slug": slug, "board_name": None, "jobs": len(ab["jobs"])})

    sr = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1")
    if isinstance(sr, dict) and sr.get("totalFound", 0) > 0:
        content = sr.get("content") or [{}]
        name = (content[0].get("company") or {}).get("name")
        hits.append({"ats": "smartrecruiters", "slug": slug, "board_name": name, "jobs": sr["totalFound"]})

    wk = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    if isinstance(wk, dict) and wk.get("jobs"):
        hits.append({"ats": "workable", "slug": slug, "board_name": wk.get("name"), "jobs": len(wk["jobs"])})

    return hits


def discover(name: str) -> list[dict]:
    found = []
    for slug in slug_candidates(name):
        for hit in probe(slug):
            if hit["board_name"]:
                score = _similar(name, hit["board_name"])
                if score < 0.75:
                    continue
                hit["verified"] = True
            else:
                # Lever and Ashby don't return a company name. Short slugs are
                # likely to belong to some other company, so flag them.
                hit["verified"] = len(slug) >= 6
            found.append(hit)
        if found:
            break
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    countries: dict[str, set[str]] = defaultdict(set)
    categories: dict[str, str] = {}
    with SOURCE.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            countries[row["company"]].add(row["country"])
            categories.setdefault(row["company"], row["category"])
    names = sorted(countries)
    if args.limit:
        names = names[: args.limit]

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = dict(zip(names, pool.map(discover, names)))

    companies = []
    for name in names:
        for hit in results[name]:
            entry = {"name": name, "ats": hit["ats"], "slug": hit["slug"]}
            if not hit["verified"]:
                entry["check"] = True
            entry["listed_in"] = sorted(countries[name])
            companies.append(entry)

    header = (
        "# Companies whose public ATS job board the daily fetcher reads.\n"
        "# Generated by tools/jobs/discover_ats.py, then curated by hand.\n"
        "# `check: true` means the board name couldn't be confirmed automatically.\n"
        "# Add a company by hand: name, ats (greenhouse|lever|ashby|smartrecruiters|workable), slug.\n"
    )
    OUT.write_text(header + yaml.safe_dump({"companies": companies}, sort_keys=False, allow_unicode=True), encoding="utf-8")

    matched = {c["name"] for c in companies}
    by_ats = defaultdict(int)
    for c in companies:
        by_ats[c["ats"]] += 1
    print(f"{len(matched)}/{len(names)} companies have a public board: {dict(by_ats)}")
    print(f"{sum(1 for c in companies if c.get('check'))} need a manual check. Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
