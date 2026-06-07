# claude-signal-brief

A Claude Code plugin that fetches AI/dev signal from configured sources daily, dedups + summarises per item, then synthesises a weekly Markdown brief.

Designed for Claude Code Desktop **Local Routines** — runs unattended on your machine, lands two Markdown files into a folder of your choice (e.g. an Obsidian vault `Inbox/`).

Design-inspired by [camilleroux/tech-digest](https://github.com/camilleroux/tech-digest) (MIT).

---

## What it does

Two slash commands:

- **`/claude-signal-daily-fetch`** — runs once a day. Hits all enabled sources, dedups against a persistent state file, generates a 1-2 line summary per new item, writes `team-signal-digest-YYYY-MM-DD.md` to your output folder.
- **`/claude-signal-weekly-synth`** — runs once a week. Reads the past 7 days of state, clusters by theme, generates `team-signal-brief-YYYY-Www.md` (TL;DR + themed clusters).

Both are invoked by Claude Code Routines (subscription-covered on Claude Max). Manual invocation works the same.

## Source types

`lib/sources.yml` lists sources by `type:` discriminator. Out of the box:

| Type | What it does | Auth |
|---|---|---|
| `rss` | Generic RSS/Atom feeds | none |
| `rss-hn-daily` | Hacker News daily digest (hnrss.org format with `Points: N` scoring) | none |
| `bash-curl-reddit` | Reddit subreddit JSON | none |
| `github-mcp-releases` | GitHub releases for a specific repo | optional GitHub PAT |
| `github-mcp-trending` | GitHub search-by-stars + created-date | optional GitHub PAT |
| `webfetch-diff` | URL sitemap diff against a snapshot | none |
| `gmail` | Gmail newsletter ingest via OAuth | Gmail OAuth (one-time setup) |

Defaults enabled: Hacker News Daily, n8n releases, anthropics/claude-code releases, GitHub trending (AI/agent), Anthropic docs (sitemap diff), r/LocalLLaMA, r/ClaudeAI, r/MachineLearning. Disabled by default: AlphaSignal newsletter (needs Gmail OAuth setup).

---

## Install

### From Claude Code Desktop (recommended)

```
claude plugin marketplace add Wiktor-Potapczyk/claude-signal-brief
claude plugin install claude-signal-brief@claude-signal-brief
```

### From a clone (development)

```bash
git clone https://github.com/Wiktor-Potapczyk/claude-signal-brief.git
cp -r claude-signal-brief ~/.claude/plugins/
```

---

## First-run setup

### 1. Scaffold the config

```bash
python3 ~/.claude/plugins/claude-signal-brief/lib/state.py scaffold
```

Creates `~/.claude-signal-brief/config.json` (state file path, output dir, model preferences) and a blank `state.jsonl`. Idempotent.

Default output dir is `Inbox` (relative to your shell working directory when the commands run). Edit `~/.claude-signal-brief/config.json` to change.

### 2. Review the source list

Open `~/.claude/plugins/claude-signal-brief/lib/sources.yml`. Set `enabled: false` on any source you don't want. Changes take effect on the next run — no restart.

### 3. (Optional) Set up GitHub PAT

The GitHub release + trending handlers work without auth at 60 req/h. For 5000 req/h, set `GITHUB_PAT` (or `GITHUB_TOKEN`) in your environment.

### 4. (Optional) Gmail OAuth for newsletters

If you want the AlphaSignal source (or any Gmail-based newsletter ingest):

**a.** Create a GCP project + OAuth Desktop client at https://console.cloud.google.com/apis/credentials. Enable the Gmail API. Download the OAuth client JSON.

**b.** Place it at `~/.gmail-mcp/gcp-oauth.keys.json`.

**c.** Run the one-time OAuth bootstrap:

```bash
python3 ~/.claude/plugins/claude-signal-brief/lib/setup_gmail_oauth.py
```

A browser opens; sign in once. Refresh token writes to `~/.claude-signal-brief/gmail-token.json` and persists across sessions.

**d.** Flip the AlphaSignal entry in `sources.yml` to `enabled: true`. Change the `sender:` field if you want a different newsletter.

### 5. Test the daily fetch

From Claude Code Desktop:

```
/claude-signal-daily-fetch
```

Check that `team-signal-digest-<today>.md` appears in your output dir. The first run of the Anthropic docs source stores a baseline snapshot and emits zero items (correct — avoids flooding with the full sitemap on day 1).

### 6. Schedule the routines

In Claude Code Desktop → Settings → Routines, create two entries:

| Routine name | Schedule | Command |
|---|---|---|
| Signal daily | Daily, e.g. 10:05 | `/claude-signal-daily-fetch` |
| Signal weekly | Monday, e.g. 11:00 | `/claude-signal-weekly-synth` |

Weekly fires after the Monday daily fetch so the brief includes that morning's items.

---

## How it stores state

`~/.claude-signal-brief/state.jsonl` — append-only except for the `_meta_docs_sitemap_snapshot` record. Trim manually if it grows beyond your comfort; no automatic retention.

Dedup is via `sha256(title + "\n" + url)` per item. Re-running the daily fetch the same day adds nothing.

---

## Known constraints

- **Claude Code Desktop must be running + machine awake** for Local Routines to fire. Mitigation: Desktop Settings → Keep computer awake. Catches up max 1 missed run within 7 days.
- **Reddit may 403 on rare days** (UA block or rate limit). Handler fails soft (returns empty list); other sources still run.
- **LLM cost: $0 beyond your Claude Code subscription.** The per-item summary + weekly clustering run inside your Claude Code session, not via a separate API call.
- **Plugin runtime path:** the commands invoke Python via `${CLAUDE_PLUGIN_ROOT}/lib/...`. If your Claude Code version doesn't populate `CLAUDE_PLUGIN_ROOT`, the commands fall back to `~/.claude/plugins/claude-signal-brief/lib/...`.

---

## Customising sources

`sources.yml` is plain YAML. Each entry has `type:`, `enabled:`, and source-specific fields.

**To add a subreddit:**

```yaml
- name: r/ExampleSub
  type: bash-curl-reddit
  sub: ExampleSub
  window: day
  min_score: 50
  enabled: true
```

**To add a GitHub repo's releases:**

```yaml
- name: openai/openai-python releases
  type: github-mcp-releases
  owner: openai
  repo: openai-python
  window_days: 7
  enabled: true
```

**To add a generic RSS/Atom feed:**

```yaml
- name: My Blog
  type: rss
  url: https://example.com/feed.xml
  enabled: true
```

---

## Credits

Design-inspired by [camilleroux/tech-digest](https://github.com/camilleroux/tech-digest) (MIT). Borrowed patterns: stdlib YAML parsing, parallel feed fetching, HN score extraction. Added: multi-handler source dispatch, persistent JSONL state, weekly synthesis pass, Local Routine scheduling.

## License

MIT. See [LICENSE](LICENSE).
