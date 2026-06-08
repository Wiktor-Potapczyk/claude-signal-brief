---
description: Synthesise the past 7 days of fetched signal into a weekly Markdown brief at <output_dir>/team-signal-brief-YYYY-Www.md
argument-hint: (no arguments) — current ISO week is auto-detected
allowed-tools: ["Read", "Write", "Edit", "Bash", "Grep"]
---

# /claude-signal-weekly-synth

Weekly synthesis. Reads the past 7 days of state, clusters by theme, generates a Markdown brief.

Plugin lib path: `${CLAUDE_PLUGIN_ROOT}/lib/` (fallback: `~/.claude/plugins/claude-signal-brief/lib/`).

## Steps

### Step 1: Load the week's items

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/claude-signal-brief}/lib/fetch_sources.py" weekly
```

The script emits to stdout one JSONL line per state record from the current ISO week (or previous week if today is Monday and current week is sparse). Each record includes `title`, `url`, `source`, `summary`, `date_fetched`, `week_iso`.

### Step 2: Cluster

If `<8` items total: skip clustering. Present them flat under a single `## This week's signal` section.

Otherwise: group items into 3-6 themes. Themes are emergent from content — don't pre-define. Typical themes you'll see: "Model releases", "New developer tools", "Research papers worth reading", "Industry moves", "Security disclosures", "Anthropic / Claude Code updates", "Agent ecosystem".

### Step 3: Synthesise

For each cluster (or flat list):

- **Header:** `### <theme name>` — short, content-derived, NOT generic
- **Body:** 2-4 items per cluster, each formatted as:
  ```
  - **<short title or claim>** — 1-line distillation of why this matters. End with source link.
  ```
- **Filter:** ~60-70% inclusion rate from the input list. The cuts are the value. Skip weak items even if they're in state.

### Step 4: Frame the brief

Start with:

```markdown
---
date: YYYY-MM-DD
tags: [claude-signal-brief, weekly-brief]
status: active
---

# Signal Brief — Week YYYY-Www

_Synthesised from N items collected DATE-RANGE. K items shown, M filtered as weak signal._

## TL;DR

3-5 bullets. One sentence each. The reader needs only this section to get the gist.

## <Theme 1>

<bullets per Step 3>

## <Theme 2>

...
```

End with:

```markdown
---

_Signal/noise score (manual, yes-no per weekday): __ / 5 weekdays this week_
```

The blank `__` is for manual trial-scoring if you want to track signal quality over time.

### Step 5: Write

Path: `<output_dir>/team-signal-brief-YYYY-Www.md`.

If file exists for this week: append a `## Update <HH:MM>` section instead of overwriting. First synth of the week is canonical; later re-runs are append-only updates.

### Step 5b (optional): HTML render

If the user wants a shareable/offline HTML copy of the brief (inline CSS, no JS):

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/claude-signal-brief}/lib/render_html.py" \
  "<output_dir>/team-signal-brief-YYYY-Www.md" "<output_dir>/team-signal-brief-YYYY-Www.html"
```

Markdown stays canonical; the HTML is an additive copy. Skip this step unless asked.

### Step 6: Report

```
[claude-signal-weekly-synth — YYYY-Www]
items_in_window: N
items_included: K
items_filtered: M
output_path: <relative>
clusters: <N or "flat">
```

## Notes

- DO NOT invent items not in state. Every bullet traces back to a state record.
- DO NOT inflate weak weeks with prose. Honest "this week was quiet, 4 items came in" beats fake density.

## Credits

Design-inspired by `camilleroux/tech-digest` (MIT). See `README.md` for full attribution.
