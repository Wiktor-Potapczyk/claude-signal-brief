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

While processing, keep a running count of items you had to degrade (`degraded`) — you will report it in Step 4. For each item from stdout in Step 2:

1. **Get the item's content (in priority order):**
   - If the item's `_extra` field already holds body content (the handler pre-fetched it), **use that and skip WebFetch entirely** — no fetch, no retry needed.
   - Otherwise call WebFetch on the item's `url`.
2. **Transient-failure retry — do NOT silently degrade.** Treat as TRANSIENT (and retry) any WebFetch that: fails outright, times out, returns an empty body, or returns an "overloaded / unavailable / rate-limited / API error / 5xx / 429 / 529" message. Retry up to **2 more times (3 attempts total)**. Two required details, or the retry is useless:
   - **Cache-bust each retry:** WebFetch caches a response ~15 min per URL, so re-calling the same URL just replays the failure. On attempt 2 and 3, append a cache-busting query param — `?_r=2` / `?_r=3` (use `&_r=N` if the URL already contains `?`).
   - **Backoff for 429:** for a rate-limit/429, wait ~5–10 s before retrying; for 5xx/529/timeout, retry immediately.
   - **Do NOT retry permanent failures:** a 404 / not-found / DNS-resolution error goes straight to fallback (step 3) — retrying wastes attempts.
3. **Visible fallback (last resort).** If all attempts fail — or the page is a paywall/login-wall (often HTTP 200 with only a modal or truncated body) — fall back to a title-derived summary, increment `degraded` by 1, and append ` _[title-only: <reason>]_` to that item's summary, where `<reason>` is exactly one of: `retry-exhausted`, `paywall`, `timeout`, `empty`, `not-found`. Never degrade silently.
4. Generate a 1-2 line summary. Concrete, signal-rich. NOT "An interesting article about X" — say "X claims Y because Z" or "New release: <feature list, max 5 items>".
5. Update the state record: call `python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/claude-signal-brief}/lib/state.py" update-summary <content_hash> "<summary>"`.

Carry the final `degraded` total into Step 4's Stats block.

### Step 4: Write daily digest file

After Step 3 has summarised all new items, write a daily digest at `<output_dir>/claude-signal-digest-YYYY-MM-DD.md` (output_dir from config, default `Inbox`).

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
- Degraded (title-only fallback after retries): D
- State file lines: <new total>
```

The `Degraded` line makes WebFetch signal-loss visible per run. If `D` is high (≥3) or the same source degrades repeatedly across days, that is a real signal-quality regression to investigate — not noise to ignore.

Rules:
- Use the `summary` field of each item from state (populated in Step 3). If `summary` is empty, use the first 1-2 sentences of `_extra.body_preview` or `_extra.selftext_preview` instead.
- Group by `source`, sort sources by item count desc, sort items within source by source-specific signal (Reddit: score; GitHub trending: stars; releases: published_at desc; HN: appearance order).
- Skip sources with zero new items.
- If `items_new == 0`: write the file anyway with body "Nothing new in today's window. Last fetched at HH:MM." — this confirms the routine ran.

### Step 5: Report status to caller

After writing the digest file, output a single terse status line:

```
Daily digest written: <output_dir>/claude-signal-digest-YYYY-MM-DD.md  (K new, L deduped, M sources)
```

## Notes

- If a handler errors, log it and continue with other handlers. Don't fail the whole daily fetch on one source.
- WebFetch is a Claude-side tool, not Python — the orchestrator marks items needing WebFetch with `_needs_webfetch_url`; Step 3 handles them.
- LLM summary calls happen at Step 3 by you (Claude), not from inside Python — the Python orchestrator only does mechanical work.

## Credits

Design-inspired by `camilleroux/tech-digest` (MIT). See `README.md` for full attribution.
