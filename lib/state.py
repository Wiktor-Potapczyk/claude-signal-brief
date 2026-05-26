"""State file + config helpers for claude-signal-brief.

State file: JSONL at ~/.claude-signal-brief/state.jsonl, append-only EXCEPT for
the _meta_docs_sitemap_snapshot record (replaced on each sitemap diff).

Bash-callable: `python state.py <cmd> [args]` — see __main__ block for cmds.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_CONFIG = {
    "state_file": "~/.claude-signal-brief/state.jsonl",
    "output_dir": "Inbox",
    "github": {
        "pat_env_var": "GITHUB_PAT",
        "exclude_orgs": [],
        "include_prereleases": False,
    },
    "reddit": {
        "user_agent": "claude-signal-brief/0.1",
    },
    "email_newsletter": {
        "mode": "A",
        "imap": {
            "host": "",
            "port": 993,
            "user": "",
            "password_file": "",
        },
    },
}


def expand(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


def config_path() -> Path:
    return expand("~/.claude-signal-brief/config.json")


def load_config() -> dict:
    p = config_path()
    if not p.is_file():
        return dict(DEFAULT_CONFIG)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"claude-signal-brief: config.json malformed: {e}")


def scaffold_config_if_missing() -> bool:
    p = config_path()
    if p.is_file():
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
    return True


def state_path(config: dict | None = None) -> Path:
    cfg = config or load_config()
    return expand(cfg["state_file"])


def ensure_state_file(config: dict | None = None) -> Path:
    p = state_path(config)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.is_file():
        p.write_text("", encoding="utf-8")
    return p


def content_hash(title: str, url: str) -> str:
    h = hashlib.sha256()
    h.update((title + "\n" + url).encode("utf-8"))
    return "sha256:" + h.hexdigest()


def load_records(config: dict | None = None) -> list[dict]:
    p = ensure_state_file(config)
    out = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def existing_hashes(config: dict | None = None) -> set[str]:
    return {r["content_hash"] for r in load_records(config) if "content_hash" in r}


def append_record(record: dict, config: dict | None = None) -> None:
    p = ensure_state_file(config)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def update_summary(hash_: str, summary: str, config: dict | None = None) -> bool:
    """Find the record with matching content_hash and set its summary field.

    Returns True if found-and-updated, False if not found. Rewrites the file
    in place (state file is small enough; if it grows pathological we'll
    switch to an index approach).
    """
    p = ensure_state_file(config)
    records = load_records(config)
    updated = False
    for r in records:
        if r.get("content_hash") == hash_:
            r["summary"] = summary
            updated = True
            break
    if updated:
        p.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8",
        )
    return updated


def replace_meta_snapshot(snapshot: dict, config: dict | None = None) -> None:
    """Replace the single `_meta_docs_sitemap_snapshot` record."""
    p = ensure_state_file(config)
    records = load_records(config)
    records = [r for r in records if r.get("source") != "_meta_docs_sitemap_snapshot"]
    snap_record = {
        "source": "_meta_docs_sitemap_snapshot",
        "date_fetched": today_iso(),
        "snapshot": snapshot,
        "content_hash": content_hash("_meta_docs_sitemap_snapshot", json.dumps(snapshot, sort_keys=True)),
    }
    records.append(snap_record)
    p.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )


def load_meta_snapshot(config: dict | None = None) -> dict | None:
    for r in load_records(config):
        if r.get("source") == "_meta_docs_sitemap_snapshot":
            return r.get("snapshot")
    return None


def today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def week_iso(d: datetime | None = None) -> str:
    d = d or datetime.now()
    return d.strftime("%Y-W%V")


def records_for_week(week: str | None = None, config: dict | None = None) -> list[dict]:
    target = week or week_iso()
    return [
        r for r in load_records(config)
        if r.get("week_iso") == target and r.get("source") != "_meta_docs_sitemap_snapshot"
    ]


def records_for_previous_week(config: dict | None = None) -> list[dict]:
    prev = datetime.now() - timedelta(days=7)
    return records_for_week(week_iso(prev), config)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "scaffold":
        created = scaffold_config_if_missing()
        print(json.dumps({"scaffolded": created, "path": str(config_path())}))
    elif cmd == "state-path":
        print(state_path())
    elif cmd == "today":
        print(today_iso())
    elif cmd == "week":
        print(week_iso())
    elif cmd == "hash":
        print(content_hash(sys.argv[2], sys.argv[3]))
    elif cmd == "count":
        print(len(load_records()))
    elif cmd == "count-this-week":
        print(len(records_for_week()))
    elif cmd == "update-summary":
        ok = update_summary(sys.argv[2], sys.argv[3])
        print(json.dumps({"updated": ok}))
    elif cmd == "config-path":
        print(config_path())
    else:
        print(
            "usage: python state.py {scaffold|state-path|config-path|today|week|"
            "hash <title> <url>|count|count-this-week|update-summary <hash> <summary>}"
        )
        sys.exit(2)
