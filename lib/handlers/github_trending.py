"""github-mcp-trending handler.

Direct GitHub search REST API. Per source config:
- languages: list of langs — one search call per language
- min_stars: stars: filter
- topics: list — post-filtered against each repo's topics field (combining
  topic: filters in the query string is fragile; doing it in-process is more
  predictable and only costs noise we discard locally)
- window_days: created:> filter (default 14, longer than RSS because a new repo
  needs time to accumulate stars)
- limit: cap on emitted items after merge + sort

Search API has tighter rate limits than the regular REST API (10 req/min
unauthenticated, 30 req/min authenticated). Authenticate via GITHUB_PAT env
var when available.

Stdlib only.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from . import register, Item


HTTP_TIMEOUT_SEC = 15
USER_AGENT = "claude-signal-brief/0.1 (+github-trending-handler)"
DEFAULT_WINDOW_DAYS = 14
DEFAULT_LIMIT = 10


def _fetch_json(url: str, token: str | None) -> dict:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch(source_cfg: dict, state_cfg: dict) -> list[Item]:
    languages = source_cfg.get("languages") or []
    if not isinstance(languages, list):
        languages = [languages]
    if not languages:
        languages = [""]

    min_stars = int(source_cfg.get("min_stars", 50))
    topics = source_cfg.get("topics") or []
    if isinstance(topics, str):
        topics = [topics]
    topic_set = {t.lower() for t in topics}
    window_days = int(source_cfg.get("window_days", DEFAULT_WINDOW_DAYS))
    limit = int(source_cfg.get("limit", DEFAULT_LIMIT))
    name = source_cfg.get("name", "GitHub trending")

    pat_env = ((state_cfg.get("github") or {}).get("pat_env_var")) or "GITHUB_PAT"
    token = os.environ.get(pat_env) or os.environ.get("GITHUB_TOKEN")

    cutoff_date = (datetime.now(tz=timezone.utc).date() - timedelta(days=window_days)).isoformat()

    collected: dict[str, dict] = {}

    for lang in languages:
        q_parts = [f"stars:>{min_stars}", f"created:>{cutoff_date}"]
        if lang:
            q_parts.append(f"language:{lang}")
        q = " ".join(q_parts)
        url = (
            "https://api.github.com/search/repositories?"
            + urllib.parse.urlencode({"q": q, "sort": "stars", "order": "desc", "per_page": 30})
        )
        try:
            payload = _fetch_json(url, token)
        except urllib.error.HTTPError as e:
            if e.code in (403, 422, 429):
                continue
            raise

        for repo in payload.get("items", []) or []:
            if repo.get("archived") or repo.get("fork") or repo.get("disabled"):
                continue
            html_url = repo.get("html_url") or ""
            if not html_url or html_url in collected:
                continue
            if topic_set:
                repo_topics = {t.lower() for t in (repo.get("topics") or [])}
                if not (repo_topics & topic_set):
                    continue
            collected[html_url] = repo

    ranked = sorted(collected.values(), key=lambda r: int(r.get("stargazers_count", 0)), reverse=True)
    ranked = ranked[:limit]

    out: list[Item] = []
    for repo in ranked:
        full_name = repo.get("full_name") or ""
        desc = (repo.get("description") or "").strip()
        title_core = f"{full_name}: {desc}" if desc else full_name
        out.append({
            "title": title_core[:200],
            "url": repo.get("html_url") or "",
            "source": name,
            "summary": "",
            "_extra": {
                "stars": int(repo.get("stargazers_count", 0)),
                "language": repo.get("language") or "",
                "topics": repo.get("topics") or [],
                "created_at": repo.get("created_at"),
                "description_full": desc,
            },
        })

    return out


register("github-mcp-trending", fetch)
