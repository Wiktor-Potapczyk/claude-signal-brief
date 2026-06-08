"""sources.yml validator / doctor for claude-signal-brief.

Validates sources.yml BEFORE a fetch run so misconfiguration surfaces as a clear
message instead of a mid-run handler error. For each source it reports:
  - readiness TIER: zero-config | optional | auth-required
  - STATUS: ok | error | warn | info
  - a one-line message

Design-inspired by Panniantong/Agent-Reach's Channel.check()/tier pattern (MIT),
reimplemented in pure stdlib against our own handler registry + sources.yml schema.

Run:  python validate_sources.py            # validates lib/sources.yml
      python validate_sources.py <path>     # validates a specific file
Exit code 0 if no ERROR findings, 1 if any ERROR (so it can gate a fetch).

Stdlib only.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

# UTF-8 stdout on Windows (matches fetch_sources.py).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SKILL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_DIR))

import handlers  # noqa: E402  auto-registers all handler types
from fetch_sources import load_sources_yaml  # noqa: E402  reuse the one parser


# Readiness tier per handler type.
#   zero-config   — works with no credentials or external setup
#   optional      — works as-is; a credential/env-var improves it (e.g. rate limits)
#   auth-required — will not work until the user completes an auth/setup step
TIER = {
    "rss": "zero-config",
    "rss-hn-daily": "zero-config",
    "bash-curl-reddit": "zero-config",
    "webfetch-diff": "zero-config",
    "github-mcp-releases": "optional",     # GITHUB_PAT optional; unauth is rate-limited
    "github-mcp-trending": "optional",
    "gmail": "auth-required",              # needs OAuth (setup_gmail_oauth.py)
}

# Required config fields per handler type (besides name/type).
REQUIRED_FIELDS = {
    "rss": ["url"],
    "rss-hn-daily": ["url"],
    "bash-curl-reddit": ["sub"],
    "webfetch-diff": [],                   # validated specially (sitemap_url OR url)
    "github-mcp-releases": ["owner", "repo"],
    "github-mcp-trending": [],             # validated specially (needs a filter)
    "gmail": ["sender"],
}


def _absent(src: dict, field: str) -> bool:
    """A field counts as missing if absent or empty-string (not merely falsy —
    0 / False are legitimate values)."""
    v = src.get(field)
    return v is None or v == ""


class Finding:
    __slots__ = ("name", "tier", "status", "message")

    def __init__(self, name: str, tier: str, status: str, message: str):
        self.name = name
        self.tier = tier
        self.status = status   # ok | error | warn | info
        self.message = message

    def as_dict(self) -> dict:
        return {"name": self.name, "tier": self.tier, "status": self.status, "message": self.message}


def validate(sources: list[dict]) -> list[Finding]:
    findings: list[Finding] = []
    known_types = set(handlers.types())
    seen_names: dict[str, int] = {}

    for src in sources:
        name = src.get("name", "<unnamed>")
        seen_names[name] = seen_names.get(name, 0) + 1
        type_ = src.get("type")
        enabled = src.get("enabled", True)
        tier = TIER.get(type_, "unknown") if type_ else "unknown"

        # Collect config problems independent of enabled state.
        problems: list[str] = []
        if not type_:
            problems.append("no 'type' field")
        elif type_ not in known_types:
            problems.append(
                f"unknown type '{type_}' — registered: {', '.join(sorted(known_types))}")
        else:
            missing = [f for f in REQUIRED_FIELDS.get(type_, []) if _absent(src, f)]
            if type_ == "webfetch-diff" and _absent(src, "sitemap_url") and _absent(src, "url"):
                missing.append("sitemap_url|url (at least one)")
            if type_ == "github-mcp-trending" and not (src.get("languages") or src.get("topics")):
                missing.append("languages|topics (at least one)")
            if missing:
                problems.append(f"type '{type_}' missing required field(s): {', '.join(missing)}")

        # Disabled sources are skipped at fetch — never gate; report problems as info.
        if not enabled:
            if problems:
                msg = "disabled — " + "; ".join(problems) + " (not blocking; fix before enabling)"
            else:
                msg = "disabled in sources.yml (skipped at fetch)"
            findings.append(Finding(name, tier, "info", msg))
            continue

        if problems:
            findings.append(Finding(name, tier, "error", "; ".join(problems)))
            continue

        # Enabled + well-formed. Tier-specific readiness notes.
        if tier == "auth-required":
            findings.append(Finding(
                name, tier, "warn",
                "enabled and requires auth setup — confirm credentials are configured "
                "(gmail: run setup_gmail_oauth.py) or this source will be skipped at fetch"))
        else:
            findings.append(Finding(name, tier, "ok", "enabled, configuration valid"))

    # Duplicate-name warnings.
    for nm, n in seen_names.items():
        if n > 1:
            findings.append(Finding(nm, "-", "warn", f"name appears {n}x — names should be unique"))

    return findings


def render_text(findings: list[Finding]) -> str:
    icon = {"ok": "OK  ", "error": "ERR ", "warn": "WARN", "info": "----"}
    lines = []
    for f in findings:
        lines.append(f"[{icon.get(f.status, '?')}] ({f.tier}) {f.name}: {f.message}")
    n_err = sum(1 for f in findings if f.status == "error")
    n_warn = sum(1 for f in findings if f.status == "warn")
    n_ok = sum(1 for f in findings if f.status == "ok")
    lines.append("")
    lines.append(f"summary: {n_ok} ok, {n_warn} warn, {n_err} error, {len(findings)} total")
    lines.append("RESULT: " + ("FAIL — fix errors before fetch" if n_err else "PASS"))
    return "\n".join(lines)


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    path = Path(arg) if arg else (SKILL_DIR / "sources.yml")
    as_json = "--json" in sys.argv
    if not path.is_file():
        print(f"validate_sources: file not found: {path}", file=sys.stderr)
        return 2
    sources = load_sources_yaml(path)
    findings = validate(sources)
    if as_json:
        print(json.dumps([f.as_dict() for f in findings], ensure_ascii=False, indent=2))
    else:
        print(render_text(findings))
    return 1 if any(f.status == "error" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
