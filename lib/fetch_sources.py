"""Orchestrator for claude-signal-brief.

Usage:
    python fetch_sources.py daily
    python fetch_sources.py weekly

`daily` mode:
- Loads sources.yml + config.json
- For each enabled source, dispatches to its handler
- Dedups items against state file by content_hash
- Appends new items to state.jsonl with empty summary field
- Emits to stdout one JSONL line per NEW item (for slash command to summarise)
- Emits stats to stderr

`weekly` mode:
- Loads state file
- Filters records to current ISO week (or previous week if current is sparse-on-Monday)
- Emits to stdout one JSONL line per record (for slash command to cluster + synthesise)
- Emits stats to stderr

Stdlib only — no PyYAML, no requests. YAML parser is hand-rolled (minimal
shape coverage for sources.yml; matches tech-digest's approach).
"""

from __future__ import annotations

import io
import json
import sys
import traceback
from pathlib import Path

# Force UTF-8 stdout/stderr on Windows (default is cp1250 in PL locale and will
# crash on emoji / non-Latin glyphs in feed titles).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:  # pragma: no cover — fallback for older runtimes
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Add skill directory to sys.path so handlers can be imported
SKILL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_DIR))

import state as state_mod  # noqa: E402  (state.py at lib root)
import handlers           # noqa: E402  (handlers/__init__.py auto-registers)


def load_sources_yaml(path: Path) -> list[dict]:
    """Minimal YAML parser for sources.yml.

    Supports only what sources.yml uses:
      sources:
        - name: ...
          type: ...
          field: value
          list: [a, b, c]
          enabled: true/false
        - ...

    Comments (#) and blank lines are skipped. Indentation rules: 2 spaces.
    No nested mappings beyond list-of-dicts. No multi-line strings.
    Matches camilleroux/tech-digest's load_sources approach (stdlib only).
    """
    text = path.read_text(encoding="utf-8")
    sources: list[dict] = []
    current: dict | None = None
    in_sources_block = False

    for raw_line in text.split("\n"):
        # Strip comments
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        if line.rstrip() == "sources:":
            in_sources_block = True
            continue
        if not in_sources_block:
            continue

        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)

        if stripped.startswith("- "):
            # New source entry
            if current is not None:
                sources.append(current)
            current = {}
            # The "- " line may carry the first key
            kv = stripped[2:]
            if ":" in kv:
                k, v = kv.split(":", 1)
                current[k.strip()] = _parse_value(v.strip())
        elif current is not None and indent >= 4:
            if ":" in stripped:
                k, v = stripped.split(":", 1)
                current[k.strip()] = _parse_value(v.strip())

    if current is not None:
        sources.append(current)

    return sources


def _parse_value(v: str):
    v = v.strip()
    if not v:
        return ""
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    if v.lower() in ("null", "~"):
        return None
    # List shorthand: [a, b, c]
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("'\"") for item in inner.split(",") if item.strip()]
    # Number
    try:
        if "." not in v:
            return int(v)
        return float(v)
    except ValueError:
        pass
    # String (strip surrounding quotes)
    if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
        return v[1:-1]
    return v


# ----------------------------------------------------------------------------
# Daily mode
# ----------------------------------------------------------------------------


def run_daily() -> int:
    state_cfg = state_mod.load_config()
    sources = load_sources_yaml(SKILL_DIR / "sources.yml")
    existing = state_mod.existing_hashes(state_cfg)
    today = state_mod.today_iso()
    this_week = state_mod.week_iso()

    handlers_attempted = 0
    handlers_skipped = 0
    items_new = 0
    items_deduped = 0
    skip_reasons: list[str] = []

    for src in sources:
        if not src.get("enabled", True):
            handlers_skipped += 1
            skip_reasons.append(f"{src.get('name', '?')}: disabled in sources.yml")
            continue
        type_ = src.get("type")
        if not type_:
            handlers_skipped += 1
            skip_reasons.append(f"{src.get('name', '?')}: no type field")
            continue
        handler_fn = handlers.get(type_)
        if handler_fn is None:
            handlers_skipped += 1
            skip_reasons.append(f"{src.get('name', '?')}: unknown type '{type_}'")
            continue

        handlers_attempted += 1
        try:
            items = handler_fn(src, state_cfg)
        except NotImplementedError as e:
            handlers_skipped += 1
            handlers_attempted -= 1
            skip_reasons.append(f"{src.get('name', '?')}: handler not yet implemented ({type_})")
            continue
        except Exception as e:
            handlers_skipped += 1
            handlers_attempted -= 1
            skip_reasons.append(f"{src.get('name', '?')}: handler error: {e}")
            print(traceback.format_exc(), file=sys.stderr)
            continue

        for item in items or []:
            h = state_mod.content_hash(item.get("title", ""), item.get("url", ""))
            if h in existing:
                items_deduped += 1
                continue
            record = {
                "date_fetched": today,
                "week_iso": this_week,
                "source": item.get("source", src.get("name", "?")),
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "summary": "",
                "content_hash": h,
            }
            if "_extra" in item:
                record["_extra"] = item["_extra"]
            state_mod.append_record(record, state_cfg)
            existing.add(h)
            items_new += 1
            # Emit to stdout for slash command to summarise
            record_for_stdout = dict(record)
            record_for_stdout["needs_summary"] = True
            print(json.dumps(record_for_stdout, ensure_ascii=False))

    # Stats to stderr
    print(
        f"[fetch_sources daily] handlers_attempted={handlers_attempted} "
        f"handlers_skipped={handlers_skipped} items_new={items_new} "
        f"items_deduped={items_deduped}",
        file=sys.stderr,
    )
    for reason in skip_reasons:
        print(f"  SKIP: {reason}", file=sys.stderr)

    return 0


# ----------------------------------------------------------------------------
# Weekly mode
# ----------------------------------------------------------------------------


def run_weekly() -> int:
    state_cfg = state_mod.load_config()
    records = state_mod.records_for_week(None, state_cfg)
    if len(records) < 3:
        # Sparse — fall back to previous week
        prev = state_mod.records_for_previous_week(state_cfg)
        if len(prev) > len(records):
            records = prev

    for r in records:
        print(json.dumps(r, ensure_ascii=False))

    print(
        f"[fetch_sources weekly] items_in_window={len(records)}",
        file=sys.stderr,
    )
    return 0


# ----------------------------------------------------------------------------


def main():
    if len(sys.argv) < 2:
        print("usage: python fetch_sources.py {daily|weekly}", file=sys.stderr)
        sys.exit(2)
    mode = sys.argv[1]
    if mode == "daily":
        sys.exit(run_daily())
    elif mode == "weekly":
        sys.exit(run_weekly())
    else:
        print(f"unknown mode: {mode}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
