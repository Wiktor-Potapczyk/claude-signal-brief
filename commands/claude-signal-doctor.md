---
description: Validate sources.yml before a fetch run — flags unknown handler types, missing required fields, and reports each source's readiness tier (zero-config / optional / auth-required).
argument-hint: (no arguments) — validates the plugin's lib/sources.yml
allowed-tools: ["Bash"]
---

# /claude-signal-doctor

Pre-flight check for the signal-brief configuration. Run this after editing `sources.yml`
or when a fetch produced fewer items than expected.

Plugin lib path: `${CLAUDE_PLUGIN_ROOT}/lib/` (fallback: `~/.claude/plugins/claude-signal-brief/lib/`).

## Steps

### Step 1: Run the validator

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/claude-signal-brief}/lib/validate_sources.py"
```

The script prints one line per source — `[STATUS] (tier) name: message` — then a summary
and a `RESULT: PASS|FAIL` line. It exits non-zero if any source has an ERROR.

### Step 2: Report

Relay the validator output to the user verbatim. If `RESULT: FAIL`, summarise which
sources need fixing and what each needs (missing field, unknown type). If `RESULT: PASS`,
confirm the configuration is fetch-ready and note any `WARN` sources (e.g. auth-required
sources that still need credential setup).

## Notes

- This command only reads `sources.yml` + the handler registry — it makes no network calls
  and does not fetch any signal.
- Readiness tiers: **zero-config** (works as-is), **optional** (works; a credential improves
  it, e.g. a GitHub token to lift rate limits), **auth-required** (needs setup, e.g. Gmail OAuth).
