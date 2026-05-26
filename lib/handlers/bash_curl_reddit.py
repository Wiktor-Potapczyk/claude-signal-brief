"""bash-curl-reddit handler.

Fetches Reddit subreddit top posts via the public JSON endpoint
(https://www.reddit.com/r/<sub>/top.json), filters by min_score, returns Item
list. Name is "bash-curl-reddit" for historical reasons (original design called
out to curl); implementation uses urllib for consistency with rss.py and to
avoid subprocess overhead.

Reddit blocks default urllib/python User-Agents — set a custom UA per their
API docs (https://github.com/reddit-archive/reddit/wiki/API).

Stdlib only.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import register, Item


HTTP_TIMEOUT_SEC = 15
USER_AGENT = "claude-signal-brief/0.1 (by /u/claude-signal-brief)"
DEFAULT_LIMIT = 25


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch(source_cfg: dict, state_cfg: dict) -> list[Item]:
    sub = source_cfg.get("sub")
    if not sub:
        return []
    window = source_cfg.get("window", "day")
    min_score = int(source_cfg.get("min_score", 0))
    limit = int(source_cfg.get("limit", DEFAULT_LIMIT))
    name = source_cfg.get("name", f"r/{sub}")

    url = f"https://www.reddit.com/r/{sub}/top.json?t={window}&limit={limit}"
    try:
        payload = _fetch_json(url)
    except urllib.error.HTTPError as e:
        # 429 = rate limit; 403 = UA block; return [] so other sources continue
        if e.code in (403, 429):
            return []
        raise

    children = (payload.get("data", {}) or {}).get("children", []) or []
    out: list[Item] = []

    for child in children:
        d = child.get("data", {}) or {}
        score = int(d.get("score", 0))
        if score < min_score:
            continue

        title = (d.get("title") or "").strip()
        if not title:
            continue

        # Skip stickied (mod announcements / megathreads) and over_18
        if d.get("stickied") or d.get("over_18"):
            continue

        permalink = d.get("permalink") or ""
        permalink_full = f"https://www.reddit.com{permalink}" if permalink else ""
        is_self = bool(d.get("is_self"))
        external_url = d.get("url") or ""

        # For self-posts the "url" is the permalink anyway; for link-posts we
        # want the external link as the primary URL and stash the discussion
        # URL in _extra.
        primary_url = permalink_full if is_self else (external_url or permalink_full)

        item: Item = {
            "title": title,
            "url": primary_url,
            "source": name,
            "summary": "",
            "_extra": {
                "score": score,
                "num_comments": int(d.get("num_comments", 0)),
                "subreddit": d.get("subreddit", sub),
                "permalink": permalink_full,
            },
        }

        selftext = (d.get("selftext") or "").strip()
        if selftext:
            item["_extra"]["selftext_preview"] = selftext[:300]

        out.append(item)

    return out


register("bash-curl-reddit", fetch)
