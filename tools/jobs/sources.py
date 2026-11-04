"""One fetcher per job source. Each yields raw postings as plain dicts:

    {source, source_id, title, company, location, country_codes, remote_hint,
     posted_at (datetime, UTC), url, text}

Only official public APIs are used. Titles are filtered *before* fetching
per-posting details, so detail calls are made only for data engineering roles.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Iterator
from urllib.parse import unquote

from http_util import USER_AGENT, get_json, get_text, post_json
from taxonomy import is_data_engineering, plain_text

Raw = dict


def _iso(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        secs = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(secs, tz=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- ATS boards

def greenhouse(company: str, slug: str) -> Iterator[Raw]:
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    for j in (data or {}).get("jobs", []):
        if not is_data_engineering(j.get("title", "")):
            continue
        offices = [o.get("location") or o.get("name") or "" for o in j.get("offices", [])]
        location = (j.get("location") or {}).get("name", "")
        yield {
            "source": "greenhouse", "source_id": f"{slug}-{j['id']}", "title": j["title"],
            "company": company, "location": location, "extra_locations": offices,
            "country_codes": [], "remote_hint": False,
            "posted_at": _iso(j.get("first_published") or j.get("updated_at")),
            "url": j.get("absolute_url"), "text": plain_text(j.get("content")),
        }


def lever(company: str, slug: str) -> Iterator[Raw]:
    data = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    for j in data or []:
        if not is_data_engineering(j.get("text", "")):
            continue
        cats = j.get("categories") or {}
        text = " ".join([j.get("descriptionPlain") or "", *[plain_text(l.get("content")) for l in j.get("lists", [])]])
        yield {
            "source": "lever", "source_id": f"{slug}-{j['id']}", "title": j["text"],
            "company": company, "location": cats.get("location") or "",
            "extra_locations": cats.get("allLocations") or [],
            "country_codes": [j.get("country")] if j.get("country") else [],
            "remote_hint": j.get("workplaceType") == "remote",
            "posted_at": _iso(j.get("createdAt")), "url": j.get("hostedUrl"), "text": text,
        }


def ashby(company: str, slug: str) -> Iterator[Raw]:
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    for j in (data or {}).get("jobs", []):
        if not is_data_engineering(j.get("title", "")) or j.get("isListed") is False:
            continue
        address = ((j.get("address") or {}).get("postalAddress") or {})
        yield {
            "source": "ashby", "source_id": f"{slug}-{j['id']}", "title": j["title"],
            "company": company, "location": j.get("location") or "",
            "extra_locations": [s.get("location", "") for s in j.get("secondaryLocations") or []],
            "country_codes": [address.get("addressCountry")] if address.get("addressCountry") else [],
            "remote_hint": bool(j.get("isRemote")) or j.get("workplaceType") == "Remote",
            "posted_at": _iso(j.get("publishedAt")), "url": j.get("jobUrl"),
            "text": j.get("descriptionPlain") or plain_text(j.get("descriptionHtml")),
        }


def smartrecruiters(company: str, slug: str) -> Iterator[Raw]:
    offset = 0
    while True:
        page = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}")
        content = (page or {}).get("content") or []
        for j in content:
            if not is_data_engineering(j.get("name", "")):
                continue
            loc = j.get("location") or {}
            detail = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{j['id']}") or {}
            sections = ((detail.get("jobAd") or {}).get("sections") or {})
            text = " ".join(plain_text((sections.get(k) or {}).get("text")) for k in
                            ("jobDescription", "qualifications", "additionalInformation"))
            yield {
                "source": "smartrecruiters", "source_id": f"{slug}-{j['id']}", "title": j["name"],
                "company": company,
                "location": loc.get("fullLocation") or ", ".join(x for x in (loc.get("city"), loc.get("country")) if x),
                "extra_locations": [], "country_codes": [loc.get("country")] if loc.get("country") else [],
                "remote_hint": bool(loc.get("remote")),
                "posted_at": _iso(j.get("releasedDate")),
                "url": detail.get("postingUrl") or f"https://jobs.smartrecruiters.com/{slug}/{j['id']}",
                "text": text,
            }
        offset += len(content)
        if not content or offset >= (page or {}).get("totalFound", 0) or offset >= 1000:
            break


def workable(company: str, slug: str) -> Iterator[Raw]:
    data = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
    for j in (data or {}).get("jobs", []):
        if not is_data_engineering(j.get("title", "")):
            continue
        locs = j.get("locations") or [{"city": j.get("city"), "country": j.get("country")}]
        names = [", ".join(x for x in (l.get("city"), l.get("region"), l.get("country")) if x) for l in locs]
        yield {
            "source": "workable", "source_id": f"{slug}-{j.get('shortcode')}", "title": j["title"],
            "company": company, "location": names[0] if names else "", "extra_locations": names[1:],
            "country_codes": [l.get("countryCode") for l in locs if l.get("countryCode")],
            "remote_hint": bool(j.get("telecommuting")),
            "posted_at": _iso(j.get("published_on") or j.get("created_at")),
            "url": j.get("url") or j.get("application_url"), "text": plain_text(j.get("description")),
        }


# ---------------------------------------------------------------- Workday
# Workday career sites publish robots.txt and a sitemap of postings for
# crawlers, and each job page embeds schema.org JobPosting data for search
# engines. We read only those, obey robots.txt, fetch detail pages only for
# data engineering titles, and pause between requests.

_BOT_NAME = USER_AGENT.split("/")[0]


@lru_cache(maxsize=None)
def _robots(host: str) -> urllib.robotparser.RobotFileParser | None:
    status, body = get_text(f"{host}/robots.txt")
    if status != 200:
        return None
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(body.splitlines())
    return rp


def _allowed(host: str, url: str) -> bool:
    rp = _robots(host)
    return rp is not None and rp.can_fetch(_BOT_NAME, url)


def _title_from_job_url(url: str) -> str:
    # .../job/<Location>/<Title-Words>_<ReqId>
    last = unquote(url.rstrip("/").rsplit("/", 1)[-1])
    return re.sub(r"_[A-Za-z0-9-]+$", "", last).replace("--", " - ").replace("-", " ").strip()


def _job_posting(html: str) -> dict | None:
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def _ld_locations(posting: dict) -> list[str]:
    locs = posting.get("jobLocation") or []
    out = []
    for loc in locs if isinstance(locs, list) else [locs]:
        addr = (loc or {}).get("address") or {}
        if isinstance(addr, dict):
            parts = [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")]
            text = ", ".join(str(p) for p in parts if p and not isinstance(p, dict))
            if text:
                out.append(text)
    return out


_POSTED_RE = re.compile(r"posted\s+(today|yesterday|(\d+)\+?\s+days?\s+ago)", re.I)


def _posted_on(text: str | None) -> datetime | None:
    """Workday shows "Posted Today", "Posted Yesterday", "Posted 8 Days Ago", "Posted 30+ Days Ago"."""
    m = _POSTED_RE.search(text or "")
    if not m:
        return None
    days = 0 if m.group(1).lower() == "today" else 1 if m.group(1).lower() == "yesterday" else int(m.group(2))
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)


def _workday_search(host: str, tenant: str, site: str, offset: int) -> dict | None:
    url = f"{host}/wday/cxs/{tenant}/{site}/jobs"
    if not _allowed(host, url):
        return None
    body = {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": "data engineer"}
    return post_json(url, body)


def workday(company: str, slug: str, max_pages: int = 5, max_details: int = 15) -> Iterator[Raw]:
    """One "data engineer" search per career site via the endpoint its own
    search page uses, then JobPosting data for a few matching roles."""
    tenant, dc, site = slug.split("/", 2)
    host = f"https://{tenant}.{dc}.myworkdayjobs.com"
    details = 0
    for page in range(max_pages):
        data = _workday_search(host, tenant, site, page * 20)
        postings = (data or {}).get("jobPostings") or []
        for j in postings:
            title = j.get("title", "")
            path = j.get("externalPath") or ""
            if not path or not is_data_engineering(title):
                continue
            url = f"{host}/{site}{path}"
            location = j.get("locationsText") or next(
                (b for b in j.get("bulletFields") or [] if b and not re.search(r"\d{4,}", b)), "")
            posted = _posted_on(j.get("postedOn"))
            text, locations, remote = "", [location], False
            if details < max_details and _allowed(host, url):
                details += 1
                time.sleep(0.5)  # polite pacing on detail pages
                status, html = get_text(url)
                posting = _job_posting(html) if status == 200 else None
                if posting:
                    text = plain_text(posting.get("description"))
                    locations = _ld_locations(posting) or locations
                    remote = "TELECOMMUTE" in str(posting.get("jobLocationType", "")).upper()
                    posted = _iso(posting.get("datePosted")) or posted
            yield {
                "source": "workday", "source_id": f"{tenant}-{path.rsplit('_', 1)[-1]}", "title": title,
                "company": company, "location": locations[0] or location, "extra_locations": locations[1:],
                "country_codes": [], "remote_hint": remote, "posted_at": posted, "url": url, "text": text,
            }
        if len(postings) < 20 or (page + 1) * 20 >= (data or {}).get("total", 0):
            break
        time.sleep(0.5)


ATS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "smartrecruiters": smartrecruiters,
    "workable": workable,
    "workday": workday,
}

# ---------------------------------------------------------------- job boards

def arbeitnow(max_pages: int = 8) -> Iterator[Raw]:
    """Europe-focused board (mostly Germany)."""
    for page in range(1, max_pages + 1):
        data = get_json(f"https://www.arbeitnow.com/api/job-board-api?page={page}")
        rows = (data or {}).get("data") or []
        for j in rows:
            if not is_data_engineering(j.get("title", "")):
                continue
            location = j.get("location") or ""
            yield {
                "source": "arbeitnow", "source_id": j["slug"], "title": j["title"],
                "company": j.get("company_name", ""), "location": location, "extra_locations": [],
                # Arbeitnow lists European jobs; bare city names still count as Europe.
                "country_codes": ["DE"] if location and "," not in location else [],
                "remote_hint": bool(j.get("remote")),
                "posted_at": _iso(j.get("created_at")), "url": j.get("url"),
                "text": plain_text(j.get("description")),
            }
        if not rows or not (data or {}).get("links", {}).get("next"):
            break


ADZUNA_COUNTRIES = ["us", "ca", "gb", "de", "fr", "nl", "pl", "es", "it", "at", "ch", "be", "in"]


def adzuna(pages: int = 3) -> Iterator[Raw]:
    """Broad coverage, including India. Needs ADZUNA_APP_ID / ADZUNA_APP_KEY."""
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        return
    for country in ADZUNA_COUNTRIES:
        for page in range(1, pages + 1):
            data = get_json(
                f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}?app_id={app_id}&app_key={app_key}"
                "&results_per_page=50&what=data%20engineer&max_days_old=30&content-type=application/json"
            )
            rows = (data or {}).get("results") or []
            for j in rows:
                if not is_data_engineering(j.get("title", "")):
                    continue
                yield {
                    "source": "adzuna", "source_id": f"{country}-{j['id']}", "title": plain_text(j["title"]),
                    "company": (j.get("company") or {}).get("display_name", ""),
                    "location": (j.get("location") or {}).get("display_name", ""), "extra_locations": [],
                    "country_codes": [country.upper()], "remote_hint": False,
                    "posted_at": _iso(j.get("created")), "url": j.get("redirect_url"),
                    "text": plain_text(j.get("description")),
                }
            if len(rows) < 50:
                break


BOARDS = {
    "arbeitnow": ("Arbeitnow", "https://www.arbeitnow.com", arbeitnow),
    "adzuna": ("Adzuna", "https://www.adzuna.com", adzuna),
}
