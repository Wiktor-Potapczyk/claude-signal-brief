"""Handler registry for claude-signal-brief source types.

Each handler module exports a `fetch(source_cfg, state_cfg) -> list[Item]` function.
`Item` is a dict shape with at least: {title, url, source, summary, _extra}.

Handlers are registered by type. The orchestrator (fetch_sources.py) dispatches
to handlers via this registry.
"""

from __future__ import annotations

from typing import Callable, Any

Item = dict[str, Any]
HandlerFn = Callable[[dict, dict], list[Item]]

_REGISTRY: dict[str, HandlerFn] = {}


def register(type_: str, fn: HandlerFn) -> None:
    _REGISTRY[type_] = fn


def get(type_: str) -> HandlerFn | None:
    return _REGISTRY.get(type_)


def types() -> list[str]:
    return sorted(_REGISTRY.keys())


# Eager import + auto-register on package load.
# Each handler module calls register(type, fetch) at import time.
from . import rss              # noqa: F401  registers "rss" + "rss-hn-daily"
from . import bash_curl_reddit # noqa: F401  registers "bash-curl-reddit"
from . import github_releases  # noqa: F401  registers "github-mcp-releases"
from . import github_trending  # noqa: F401  registers "github-mcp-trending"
from . import webfetch_diff    # noqa: F401  registers "webfetch-diff"
from . import gmail            # noqa: F401  registers "gmail"
