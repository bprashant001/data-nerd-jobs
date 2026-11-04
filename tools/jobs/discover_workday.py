"""Find Workday career sites for companies in jobs/companies_source.csv.

Workday career sites live at https://<tenant>.wd<N>.myworkdayjobs.com/<site>.
Each tenant publishes a robots.txt naming the sites crawlers may visit and
their sitemaps, so we probe likely tenant names on the common data centres and
keep the ones whose robots.txt lists a sitemap. Results are merged into
jobs/companies.yaml as `ats: workday` entries for manual review.

Usage: python tools/jobs/discover_workday.py [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover_ats import _SUFFIXES  # noqa: E402
from http_util import USER_AGENT  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "jobs" / "companies_source.csv"
OUT = ROOT / "jobs" / "companies.yaml"
DATA_CENTRES = [5, 1, 3, 12, 10, 103, 108, 501, 503]


def get_text(url: str, timeout: float = 15) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def tenant_candidates(name: str) -> list[str]:
    base = re.sub(r"\(.*?\)", "", name).replace("&", "and").lower()
    words = re.findall(r"[a-z0-9]+", base)
    stripped = re.findall(r"[a-z0-9]+", _SUFFIXES.sub(" ", base))
    out: list[str] = []
    # Whole names only: a first word alone ("american") matches other tenants.
    for c in ("".join(words), "".join(stripped)):
        if len(c) >= 3 and c not in out:
            out.append(c)
    return out


def sitemaps_in(robots: str) -> list[str]:
    return re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots)


# Sites that aren't the main public listing for experienced hires: campus and
# intern boards, private or internal sites, and feeds pushed to other job
# boards (they duplicate the main site).
_SKIP_SITE = re.compile(
    r"intern|private|confidential|campus|graduate|student|apprentice|early|university|^uni$|contractor|agency|"
    r"linkedin|naukri|glassdoor|stepstone|seek|pracuj|equest|broadbean|instagram|indeed|efinancial|"
    r"brightnetwork|tanitjob|^rav$|talent|fair|give_away|consent|manual|offline|casual|store_staff|campaign|"
    r"conversion|noexternal|fasttrack|proactive|avature|ryc|futureforce|summer|leadership|executive|\d{4}",
    re.I,
)
MAX_SITES = 3


def keep_site(site: str) -> bool:
    return not _SKIP_SITE.search(site)


def probe(name: str) -> list[dict]:
    for tenant in tenant_candidates(name):
        for dc in DATA_CENTRES:
            host = f"https://{tenant}.wd{dc}.myworkdayjobs.com"
            status, body = get_text(f"{host}/robots.txt")
            if status != 200:
                continue
            sites = []
            for sm in sitemaps_in(body):
                m = re.match(rf"{re.escape(host)}/([^/]+)/siteMap\.xml", sm, re.I)
                if m:
                    sites.append(m.group(1))
            if sites:
                return [{"tenant": tenant, "dc": dc, "site": s} for s in sites]
    return []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    countries: dict[str, set[str]] = defaultdict(set)
    with SOURCE.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            countries[row["company"]].add(row["country"])

    text = OUT.read_text(encoding="utf-8")
    header = "".join(line for line in text.splitlines(True) if line.startswith("#"))
    companies = yaml.safe_load(text)["companies"]
    have = {c["name"] for c in companies}
    names = sorted(n for n in countries if n not in have)
    if args.limit:
        names = names[: args.limit]

    with ThreadPoolExecutor(max_workers=8) as pool:
        found = dict(zip(names, pool.map(probe, names)))

    added = 0
    seen = {c["slug"] for c in companies if c["ats"] == "workday"}
    for name in names:
        kept = 0
        for hit in found[name]:
            if kept >= MAX_SITES:
                break
            slug = f"{hit['tenant']}/wd{hit['dc']}/{hit['site']}"
            if slug in seen:
                continue
            seen.add(slug)
            kept += 1
            if not keep_site(hit["site"]):
                continue
            companies.append({
                "name": name, "ats": "workday", "slug": slug,
                "listed_in": sorted(countries[name]),
            })
            added += 1
    OUT.write_text(header + yaml.safe_dump({"companies": companies}, sort_keys=False, allow_unicode=True),
                   encoding="utf-8")
    print(f"{sum(1 for n in names if found[n])}/{len(names)} companies have a Workday site; added {added} boards")


if __name__ == "__main__":
    main()
