"""Build the Data Nerd news feed: data and AI industry updates, Inshorts-style.

Reads the official RSS/Atom feeds in news/sources.yaml and Hacker News's
official search API, keeps the publisher's own headline and excerpt (never the
article body), and links every item to the original story. Each request is
checked against the site's robots.txt first.

Writes <out>/news.json. Usage: python tools/news/fetch_news.py [--out docs]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "news" / "sources.yaml"
USER_AGENT = "DataNerdNewsBot/1.0 (+https://github.com/bprashant001/data-nerd-jobs)"
BOT = USER_AGENT.split("/")[0]
MAX_AGE_DAYS = 10
PER_SOURCE = 8
MAX_ITEMS = 120
EXCERPT_WORDS = 45

# ---------------------------------------------------------------- fetching


def fetch(url: str, timeout: float = 30) -> bytes | None:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, application/json, */*",
        "Accept-Encoding": "gzip",
    })
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read(10_000_000)
                if resp.headers.get("Content-Encoding") == "gzip" or body[:2] == b"\x1f\x8b":
                    body = gzip.decompress(body)
                return body
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt == 0:
                time.sleep(3)
                continue
            return None
        except Exception:
            if attempt == 0:
                time.sleep(2)
                continue
            return None
    return None


@lru_cache(maxsize=None)
def _robots(host: str) -> urllib.robotparser.RobotFileParser | None:
    body = fetch(f"{host}/robots.txt", timeout=15)
    if body is None:
        return None  # no robots.txt: nothing is disallowed
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(body.decode("utf-8", "replace").splitlines())
    return rp


def allowed(url: str) -> bool:
    p = urlparse(url)
    rp = _robots(f"{p.scheme}://{p.netloc}")
    return rp is None or rp.can_fetch(BOT, url)


# ---------------------------------------------------------------- text

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def plain(raw: str | None) -> str:
    if not raw:
        return ""
    text = html.unescape(_TAG.sub(" ", html.unescape(raw)))
    return _WS.sub(" ", text).strip()


def excerpt(text: str, words: int = EXCERPT_WORDS) -> str:
    """The publisher's own summary, cut to about [words] words at a sentence end if possible."""
    text = re.sub(r"\s*(The post .* appeared first on .*|Continue reading.*|Read more.*)$", "", text, flags=re.I)
    parts = text.split()
    if len(parts) <= words:
        return text
    cut = " ".join(parts[:words])
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end > len(cut) * 0.5:
        return cut[: end + 1]
    return cut.rstrip(",;:") + "…"


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- topics

_DATA = re.compile(
    r"\b(data|database|warehouse|lakehouse|lake|etl|elt|pipeline|sql|spark|kafka|flink|airflow|dbt|iceberg|delta lake|"
    r"parquet|snowflake|databricks|bigquery|redshift|synapse|fabric|postgres|duckdb|analytics|streaming|cdc|"
    r"governance|catalog)\b",
    re.I,
)
_AI = re.compile(
    r"\b(ai|a\.i\.|llms?|gpt[-\w]*|openai|anthropic|claude|gemini|llama|mistral|deepmind|machine learning|ml|"
    r"neural|model|models|agents?|agentic|rag|embedding|transformer|diffusion|chatbot|inference|fine-tun\w*)\b",
    re.I,
)
TAGS = {
    "databricks": r"databricks", "snowflake": r"snowflake", "dbt": r"\bdbt\b", "spark": r"\bspark\b",
    "kafka": r"\bkafka\b|confluent", "airflow": r"\bairflow\b", "iceberg": r"\biceberg\b", "aws": r"\baws\b|amazon",
    "azure": r"\bazure\b|microsoft fabric", "gcp": r"google cloud|bigquery|\bgcp\b", "postgres": r"postgres",
    "llm": r"\bllms?\b|\bgpt|claude|gemini|llama|mistral", "agents": r"\bagents?\b|agentic",
}
_TAG_RES = {k: re.compile(v, re.I) for k, v in TAGS.items()}


def topics_for(text: str, default: str) -> list[str]:
    out = {default}
    if _DATA.search(text):
        out.add("data")
    if _AI.search(text):
        out.add("ai")
    return sorted(out)


def relevant(text: str) -> bool:
    return bool(_DATA.search(text) or _AI.search(text))


# ---------------------------------------------------------------- sources


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def parse_feed(body: bytes) -> list[dict]:
    """RSS 2.0 or Atom → [{title, link, summary, published}]."""
    root = ET.fromstring(body)
    atom = "{http://www.w3.org/2005/Atom}"
    content_ns = "{http://purl.org/rss/1.0/modules/content/}"
    items = []
    for it in root.iter("item"):
        items.append({
            "title": plain(_text(it.find("title"))),
            "link": _text(it.find("link")),
            "summary": plain(_text(it.find("description")) or _text(it.find(f"{content_ns}encoded"))),
            "published": parse_date(_text(it.find("pubDate")) or _text(it.find("{http://purl.org/dc/elements/1.1/}date"))),
        })
    for e in root.iter(f"{atom}entry"):
        link = ""
        for l in e.findall(f"{atom}link"):
            if l.get("rel", "alternate") == "alternate":
                link = l.get("href", "")
                break
        items.append({
            "title": plain(_text(e.find(f"{atom}title"))),
            "link": link,
            "summary": plain(_text(e.find(f"{atom}summary")) or _text(e.find(f"{atom}content"))),
            "published": parse_date(_text(e.find(f"{atom}published")) or _text(e.find(f"{atom}updated"))),
        })
    return items


def from_feed(src: dict) -> list[dict]:
    url = src["url"]
    if not allowed(url):
        print(f"  ! {src['name']}: robots.txt disallows the feed", file=sys.stderr)
        return []
    body = fetch(url)
    if body is None:
        print(f"  ! {src['name']}: feed unavailable", file=sys.stderr)
        return []
    try:
        return parse_feed(body)
    except ET.ParseError as e:
        print(f"  ! {src['name']}: bad feed ({e})", file=sys.stderr)
        return []


def from_hackernews(_: dict) -> list[dict]:
    """Front-page stories with real traction, via HN's official Algolia API."""
    url = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=60"
    body = fetch(url)
    if body is None:
        return []
    out = []
    for h in json.loads(body).get("hits", []):
        if (h.get("points") or 0) < 150 or not h.get("url"):
            continue
        out.append({
            "title": h.get("title", ""),
            "link": h["url"],
            "summary": f"Trending on Hacker News with {h.get('points')} points and {h.get('num_comments', 0)} comments.",
            "published": datetime.fromtimestamp(h["created_at_i"], tz=timezone.utc),
        })
    return out


KINDS = {"feed": from_feed, "hackernews": from_hackernews}


def collect(src: dict, now: datetime) -> list[dict]:
    raw = KINDS[src.get("kind", "feed")](src)
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    items = []
    for r in raw:
        if not r["title"] or not r["link"].startswith("http") or not r["published"] or r["published"] < cutoff:
            continue
        blob = f"{r['title']} {r['summary']}"
        if src.get("filter") and not relevant(blob):
            continue
        items.append({
            "id": hashlib.sha1(r["link"].encode()).hexdigest()[:12],
            "title": r["title"],
            "excerpt": excerpt(r["summary"]) if r["summary"] else "",
            "url": r["link"],
            "source": src["name"],
            "publishedAt": r["published"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "topics": topics_for(blob, src["topic"]),
            "tags": [k for k, rx in _TAG_RES.items() if rx.search(blob)][:4],
        })
    items.sort(key=lambda i: i["publishedAt"], reverse=True)
    return items[:PER_SOURCE]


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())[:60]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "build" / "site"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)

    sources = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))["sources"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        batches = list(pool.map(lambda s: collect(s, now), sources))

    seen: set[str] = set()
    items = []
    for item in sorted((i for b in batches for i in b), key=lambda i: i["publishedAt"], reverse=True):
        key = _norm_title(item["title"])
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    items = items[:MAX_ITEMS]

    used = {i["source"] for i in items}
    payload = {
        "version": 1,
        "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": [
            {"name": s["name"], "url": s.get("url") or "https://news.ycombinator.com"}
            for s in sources if s["name"] in used
        ],
        "items": items,
    }
    (out / "news.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    counts = {s["name"]: len(b) for s, b in zip(sources, batches)}
    print(f"{len(items)} news items")
    print(f"  per source: {counts}")


if __name__ == "__main__":
    main()
