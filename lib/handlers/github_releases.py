"""github-mcp-releases handler.

Direct GitHub REST API. Public releases endpoint works unauthenticated at low
call volume (60 req/h per IP). If GITHUB_PAT env var is set (or whatever
state_cfg["github"]["pat_env_var"] names), auth bumps the limit to 5000 req/h.

Returns release entries published within window_days. Skips drafts. Skips
pre-releases unless include_prereleases=true on the source.

Stdlib only.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from . import register, Item


HTTP_TIMEOUT_SEC = 15
USER_AGENT = "claude-signal-brief/0.1 (+github-releases-handler)"
DEFAULT_WINDOW_DAYS = 7
DEFAULT_PER_PAGE = 10


def _fetch_json(url: str, token: str | None) -> list | dict:
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


def _parse_iso(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None


def fetch(source_cfg: dict, state_cfg: dict) -> list[Item]:
    owner = source_cfg.get("owner")
    repo = source_cfg.get("repo")
    if not owner or not repo:
        return []
    window_days = int(source_cfg.get("window_days", DEFAULT_WINDOW_DAYS))
    include_prereleases = bool(source_cfg.get("include_prereleases", False))
    per_page = int(source_cfg.get("per_page", DEFAULT_PER_PAGE))
    name = source_cfg.get("name", f"{owner}/{repo} releases")

    pat_env = ((state_cfg.get("github") or {}).get("pat_env_var")) or "GITHUB_PAT"
    token = os.environ.get(pat_env) or os.environ.get("GITHUB_TOKEN")

    url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page={per_page}"
    try:
        releases = _fetch_json(url, token)
    except urllib.error.HTTPError as e:
        if e.code in (403, 404, 429):
            return []
        raise

    if not isinstance(releases, list):
        return []

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=window_days)
    out: list[Item] = []

    for rel in releases:
        if rel.get("draft"):
            continue
        if rel.get("prerelease") and not include_prereleases:
            continue
        pub = _parse_iso(rel.get("published_at", ""))
        if not pub or pub < cutoff:
            continue

        tag = rel.get("tag_name") or ""
        rel_name = (rel.get("name") or "").strip()
        title_core = rel_name if rel_name and rel_name != tag else tag
        title = f"{repo} {tag}: {title_core}" if tag and title_core != tag else f"{repo} {tag}"
        html_url = rel.get("html_url") or ""
        if not html_url or not tag:
            continue

        body = (rel.get("body") or "").strip()
        out.append({
            "title": title,
            "url": html_url,
            "source": name,
            "summary": "",
            "_extra": {
                "tag": tag,
                "published_at": rel.get("published_at"),
                "prerelease": bool(rel.get("prerelease")),
                "body_preview": body[:500] if body else "",
            },
        })

    return out


register("github-mcp-releases", fetch)
