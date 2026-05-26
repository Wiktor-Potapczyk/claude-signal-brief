"""webfetch-diff handler.

Diffs a URL set against the previously-stored snapshot. Designed for sitemaps
(docs.anthropic.com/sitemap.xml) but works for any XML with <loc> elements
or any plain newline-separated URL list at the source URL.

Mechanism:
  1. Fetch source URL via urllib.
  2. Parse all <loc> elements (XML sitemap) — fall back to any line that
     looks like a URL if XML parse fails.
  3. Compare current URL set against snapshot stored via
     state.load_meta_snapshot().
  4. Emit new URLs as items (capped at source.cap).
  5. Save new snapshot via state.replace_meta_snapshot().

On first run (no snapshot yet) — store the snapshot and emit zero items so
the first day's brief isn't flooded with the entire sitemap.

Stdlib only.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import state as state_mod  # noqa: E402 — state is on sys.path via fetch_sources

from . import register, Item


HTTP_TIMEOUT_SEC = 20
USER_AGENT = "claude-signal-brief/0.1 (+sitemap-diff-handler)"
DEFAULT_CAP = 20

URL_LINE_RE = re.compile(r"https?://\S+")


def _fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_urls(text: str) -> set[str]:
    urls: set[str] = set()
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        root = None

    if root is not None:
        ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
        for loc in root.iter(f"{{{ns}}}loc"):
            if loc.text:
                urls.add(loc.text.strip())
        if not urls:
            for loc in root.iter("loc"):
                if loc.text:
                    urls.add(loc.text.strip())

    if not urls:
        for line in text.split("\n"):
            for m in URL_LINE_RE.finditer(line):
                urls.add(m.group(0).rstrip(",.<>\"';)"))

    return urls


def fetch(source_cfg: dict, state_cfg: dict) -> list[Item]:
    sitemap_url = source_cfg.get("sitemap_url") or source_cfg.get("url")
    if not sitemap_url:
        return []
    cap = int(source_cfg.get("cap", DEFAULT_CAP))
    name = source_cfg.get("name", sitemap_url)

    try:
        text = _fetch_text(sitemap_url)
    except urllib.error.HTTPError as e:
        if e.code in (403, 404, 429):
            return []
        raise

    current = _parse_urls(text)
    if not current:
        return []

    prior_snapshot = state_mod.load_meta_snapshot(state_cfg) or {}
    prior_urls: set[str] = set(prior_snapshot.get(sitemap_url, []))

    new_snapshot = dict(prior_snapshot)
    new_snapshot[sitemap_url] = sorted(current)

    if not prior_urls:
        state_mod.replace_meta_snapshot(new_snapshot, state_cfg)
        return []

    added = sorted(current - prior_urls)
    state_mod.replace_meta_snapshot(new_snapshot, state_cfg)

    if not added:
        return []

    truncated = added[:cap]
    out: list[Item] = []
    for url in truncated:
        path_tail = url.rstrip("/").rsplit("/", 1)[-1] or url
        title = f"New docs page: {path_tail.replace('-', ' ').replace('_', ' ')}"
        out.append({
            "title": title[:200],
            "url": url,
            "source": name,
            "summary": "",
            "_extra": {
                "added_count_total": len(added),
                "shown_in_brief": len(truncated),
            },
        })

    return out


register("webfetch-diff", fetch)
