"""Tiny HTTP helpers for the jobs pipeline (standard library only)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

USER_AGENT = "DataNerdJobsBot/1.0 (+https://github.com/bprashant001/data-nerd-jobs)"


def get_json(url: str, *, timeout: float = 20, retries: int = 2, headers: dict | None = None):
    """GET a URL and parse JSON. Returns None on 4xx, or after retries fail."""
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError, OSError):
            time.sleep(1 + attempt)
    return None


def get_text(url: str, *, timeout: float = 20, max_bytes: int = 5_000_000) -> tuple[int, str]:
    """GET a URL as text. Returns (status, body); status 0 on network errors."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xml,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(max_bytes).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return 0, ""


def post_json(url: str, body: dict, *, timeout: float = 30, retries: int = 1):
    """POST JSON and parse the JSON reply. Returns None on errors."""
    data = json.dumps(body).encode()
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "application/json"}
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(3 * (attempt + 1))
                continue
            return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError, OSError):
            time.sleep(1 + attempt)
    return None
