# Changelog

All notable changes to claude-signal-brief are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the project is pre-1.0, breaking changes bump the MINOR version.

## [Unreleased]

### Added
- `claude-signal-doctor` command + `lib/validate_sources.py` — validates `sources.yml`
  before a fetch run: flags unknown handler types, missing required fields, and reports
  each source's readiness tier (zero-config / optional / auth-required).
- `lib/render_html.py` — optional HTML rendering of the weekly brief (inline CSS, no JS,
  system fonts). Markdown remains the default output; HTML is additive.
- `CHANGELOG.md` (this file).

### Notes
- A Polymarket prediction-market source handler was scoped but deferred — the Polymarket
  API was unreachable from the development network at build time and could not be verified.

## [0.1.0] - 2026-05-26

### Added
- Initial public release as a Claude Code plugin.
- Two slash commands: `claude-signal-daily-fetch`, `claude-signal-weekly-synth`.
- Source handlers: RSS/Atom, Hacker News daily, Reddit JSON, GitHub releases,
  GitHub trending, Anthropic docs sitemap-diff, Gmail newsletter (OAuth, opt-in).
- Append-only JSONL state file with SHA-256 content-hash dedup (`lib/state.py`).
- Per-item Claude-side summarisation + weekly thematic synthesis.
- `sources.yml` configuration; pure Python standard library (no third-party deps).
- Distribution via Claude Code plugin marketplace (`.claude-plugin/marketplace.json`).

[Unreleased]: https://github.com/Wiktor-Potapczyk/claude-signal-brief/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Wiktor-Potapczyk/claude-signal-brief/releases/tag/v0.1.0
