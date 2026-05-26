---
description: Fetch today's AI/dev signal from configured sources; dedup + summarise; append to state file. Designed for daily Routine invocation.
argument-hint: (no arguments) — date/window is auto from current day
allowed-tools: ["Read", "Write", "Edit", "Bash", "WebFetch", "Grep", "Glob"]
---

# /claude-signal-daily-fetch

Daily collection pass. Idempotent — re-running on the same day produces no duplicate state records.

Plugin lib path: `${CLAUDE_PLUGIN_ROOT}/lib/` (fallback: `~/.claude/plugins/claude-signal-brief/lib/`).

## Steps

### Step 1: Bootstrap (first run only)

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/claude-signal-brief}/lib/state.py" scaffold
```

If output reports `"scaffolded": true`, this is the first run. STOP and message the user: "Default config scaffolded at `~/.claude-signal-brief/config.json`. Review + tune source list (`lib/sources.yml`), then re-invoke."

If `"scaffolded": false`, continue.

### Step 2: Run the daily fetch

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/claude-signal-brief}/lib/fetch_sources.py" daily
```

The script:
- Loads `lib/sources.yml` from the plugin directory
- For each enabled source, dispatches to the matching handler in `lib/handlers/<type>.py`
- Each handler returns a list of items: `[{title, url, source, summary, _extra}]`
- Computes `content_hash = sha256(title + "\n" + url)` per item
- Dedups against the state file (`~/.claude-signal-brief/state.jsonl`)
- For each new item, appends a JSONL record with `date_fetched`, `week_iso`, and an empty `summary` field
- Reports stats per source on stderr: `[handler-name] N items emitted, M deduped`
- Items that need LLM summary land in stdout as one JSONL line each, marked `needs_summary: true` — Step 3 below handles them

### Step 3: Summarise new items

For each item from stdout in Step 2:

1. Read the item's `url` content (use WebFetch for the URL OR the item's `_extra` field if the handler pre-fetched content for you).
2. Generate a 1-2 line summary. Concrete, signal-rich. NOT "An interesting article about X" — say "X claims Y because Z" or "New release: <feature list, max 5 items>".
3. Update the state record: call `python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/claude-signal-brief}/lib/state.py" update-summary <content_hash> "<summary>"`.

### Step 4: Write daily digest file

After Step 3 has summarised all new items, write a daily digest at `<output_dir>/team-signal-digest-YYYY-MM-DD.md` (output_dir from config, default `Inbox`).

Frontmatter:

```yaml
---
date: YYYY-MM-DD
tags: [claude-signal-brief, daily-digest]
status: active
type: daily-digest
---
```

Body structure:

```markdown
# Signal — YYYY-MM-DD

_N items collected today across M sources._

## Top items (grouped by source)

### <Source A>
- **<title>** — <1-2 line summary from Step 3>. [link](<url>)
- ...

### <Source B>
...

## Stats
- Handlers attempted: N
- Handlers skipped: M
- New items: K
- Deduped: L
- State file lines: <new total>
```

Rules:
- Use the `summary` field of each item from state (populated in Step 3). If `summary` is empty, use the first 1-2 sentences of `_extra.body_preview` or `_extra.selftext_preview` instead.
- Group by `source`, sort sources by item count desc, sort items within source by source-specific signal (Reddit: score; GitHub trending: stars; releases: published_at desc; HN: appearance order).
- Skip sources with zero new items.
- If `items_new == 0`: write the file anyway with body "Nothing new in today's window. Last fetched at HH:MM." — this confirms the routine ran.

### Step 5: Report status to caller

After writing the digest file, output a single terse status line:

```
Daily digest written: <output_dir>/team-signal-digest-YYYY-MM-DD.md  (K new, L deduped, M sources)
```

## Notes

- If a handler errors, log it and continue with other handlers. Don't fail the whole daily fetch on one source.
- WebFetch is a Claude-side tool, not Python — the orchestrator marks items needing WebFetch with `_needs_webfetch_url`; Step 3 handles them.
- LLM summary calls happen at Step 3 by you (Claude), not from inside Python — the Python orchestrator only does mechanical work.

## Credits

Design-inspired by `camilleroux/tech-digest` (MIT). See `README.md` for full attribution.
