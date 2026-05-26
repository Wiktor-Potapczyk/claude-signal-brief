"""rss and rss-hn-daily handlers.

Design-inspired by camilleroux/tech-digest (MIT). Ported functions:
- strip_html, parse_rss_date, parse_score, parse_hn_daily
- RSS 2.0 + Atom parsing branches
- Per-day top-N filter when source has `limit:`

Adapted to our handler signature `fetch(source_cfg, state_cfg) -> list[Item]`
and our item shape `{title, url, source, summary, _extra}`. Dedup happens at
the orchestrator level (content_hash against state), so this handler doesn't
do cross-call dedup itself.

Stdlib only.
"""

from __future__ import annotations

import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from . import register, Item


HTTP_TIMEOUT_SEC = 15
USER_AGENT = "claude-signal-brief/0.1 (+rss-handler)"
DEFAULT_WINDOW_DAYS = 7


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = " ".join(text.split())
    return text[:150]


def parse_rss_date(date_str: str):
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str.strip())
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_score(raw_description: str):
    """Extract HN Points: N from hnrss.org-style descriptions."""
    if not raw_description:
        return None
    m = re.search(r"Points:\s*(\d+)", raw_description)
    return int(m.group(1)) if m else None


def _fetch_xml(url: str) -> ET.Element | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        data = resp.read()
    return ET.fromstring(data)


def _parse_hn_daily(root: ET.Element, cutoff_date, source_name: str, limit: int) -> list[dict]:
    """daemonology.net HN daily — one item per day, top articles in description HTML."""
    items: list[dict] = []
    for item in root.findall(".//item"):
        date_str = item.findtext("pubDate", "")
        pub_date = parse_rss_date(date_str)
        if not pub_date or pub_date.date() < cutoff_date:
            continue
        desc_html = item.findtext("description", "")
        links = re.findall(r'class="storylink"><a href="([^"]+)">([^<]+)</a>', desc_html)
        for url, title in links[:limit]:
            items.append({
                "date": pub_date,
                "title": html.unescape(title),
                "link": url,
                "score": None,
            })
    return items


def _parse_rss_or_atom(root: ET.Element, cutoff_date, source_name: str) -> list[dict]:
    """Standard RSS 2.0 + Atom branches. Returns intermediate dicts; mapping
    to our Item shape happens in the caller."""
    items: list[dict] = []
    rss_items = root.findall(".//item")

    if rss_items:
        # RSS 2.0
        for el in rss_items:
            title = (el.findtext("title", "") or "").strip()
            link = (el.findtext("link", "") or "").strip()
            date_str = el.findtext("pubDate", "")
            raw_desc_text = el.findtext("description", "") or ""
            score = parse_score(raw_desc_text)
            raw_desc = strip_html(raw_desc_text)
            desc = "" if (
                raw_desc.startswith("Comments")
                or raw_desc.startswith("http")
                or raw_desc.startswith("Article URL:")
            ) else raw_desc
            pub_date = parse_rss_date(date_str)
            if pub_date and pub_date.date() >= cutoff_date and title and link:
                items.append({
                    "date": pub_date,
                    "title": title,
                    "link": link,
                    "description": desc,
                    "score": score,
                })
    else:
        # Atom
        atom_ns = "http://www.w3.org/2005/Atom"
        for entry in root.findall(f".//{{{atom_ns}}}entry"):
            title = (entry.findtext(f"{{{atom_ns}}}title") or "").strip()
            link_el = entry.find(f"{{{atom_ns}}}link[@href]")
            link = link_el.get("href", "") if link_el is not None else ""
            date_str = (
                entry.findtext(f"{{{atom_ns}}}updated")
                or entry.findtext(f"{{{atom_ns}}}published")
                or ""
            )
            raw_content = (
                entry.findtext(f"{{{atom_ns}}}summary")
                or entry.findtext(f"{{{atom_ns}}}content")
                or ""
            )
            desc = strip_html(raw_content[:2000])
            pub_date = parse_rss_date(date_str)
            if pub_date and pub_date.date() >= cutoff_date and title and link:
                items.append({
                    "date": pub_date,
                    "title": title,
                    "link": link,
                    "description": desc,
                    "score": None,
                })

    return items


def _apply_per_day_limit(items: list[dict], limit: int) -> list[dict]:
    """Keep top-N per day by score (scored items first, then by recency)."""
    by_day = defaultdict(list)
    for it in items:
        by_day[it["date"].date()].append(it)
    out: list[dict] = []
    for day_items in by_day.values():
        day_items.sort(
            key=lambda a: (a["score"] is not None, a["score"] or 0, a["date"]),
            reverse=True,
        )
        out.extend(day_items[:limit])
    return out


def fetch(source_cfg: dict, state_cfg: dict) -> list[Item]:
    url = source_cfg["url"]
    name = source_cfg.get("name", url)
    type_ = source_cfg.get("type", "rss")
    window_days = int(source_cfg.get("window_days", DEFAULT_WINDOW_DAYS))
    cutoff_date = (datetime.now(tz=timezone.utc).date() - timedelta(days=window_days))

    root = _fetch_xml(url)
    if root is None:
        return []

    if type_ == "rss-hn-daily":
        limit = int(source_cfg.get("limit", 5))
        raw_items = _parse_hn_daily(root, cutoff_date, name, limit)
    else:
        raw_items = _parse_rss_or_atom(root, cutoff_date, name)
        limit = source_cfg.get("limit")
        if limit:
            raw_items = _apply_per_day_limit(raw_items, int(limit))

    # Map to our Item shape
    out: list[Item] = []
    for it in raw_items:
        item: Item = {
            "title": it["title"],
            "url": it["link"],
            "source": name,
            "summary": "",
        }
        # Stash the cleaned description as _extra so the LLM-summary step
        # has context without needing a separate WebFetch.
        if it.get("description"):
            item["_extra"] = {"description": it["description"]}
        if it.get("score") is not None:
            item.setdefault("_extra", {})["score"] = it["score"]
        out.append(item)
    return out


register("rss", fetch)
register("rss-hn-daily", fetch)
