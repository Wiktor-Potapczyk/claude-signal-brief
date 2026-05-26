"""gmail handler — Gmail REST API via OAuth refresh token.

Mode A — REST API (default after `python setup_gmail_oauth.py`):
  Reads ~/.claude-signal-brief/gmail-token.json (refresh_token + client_id/secret).
  Refreshes access_token if expired, then calls
  https://gmail.googleapis.com/gmail/v1/users/me/messages?q=... + per-id GET.
  Returns list[Item] with title=subject, url=permalink to Gmail thread,
  _extra={"sender": ..., "snippet": ..., "body_text": ...}.

Mode B — IMAP forwarder: still a stub. Kept for the App-Password fallback path
  if OAuth ever becomes unworkable.

Fail-soft contract:
- email_newsletter not configured (no mode in state_cfg) -> return []
- mode == "A" but token file missing -> raise NotImplementedError so the
  orchestrator surfaces a SKIP line (don't silently swallow setup gaps)
- Gmail API 401/403 (token revoked) -> raise so user sees the failure

Stdlib only.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import register, Item


HTTP_TIMEOUT_SEC = 15
USER_AGENT = "claude-signal-brief/0.1 (+gmail-handler)"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
MESSAGES_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
THREAD_BASE_URL = "https://mail.google.com/mail/u/0/#inbox"

DEFAULT_TOKEN_PATH = Path.home() / ".claude-signal-brief" / "gmail-token.json"
DEFAULT_WINDOW_DAYS = 1
DEFAULT_MAX_RESULTS = 10
REFRESH_LEEWAY_SEC = 300


def _load_token(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_token(path: Path, token: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(token, f, indent=2)


def _refresh_access_token(token: dict) -> dict:
    body = urllib.parse.urlencode({
        "client_id": token["client_id"],
        "client_secret": token["client_secret"],
        "refresh_token": token["refresh_token"],
        "grant_type": "refresh_token",
    }).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    token["access_token"] = payload["access_token"]
    token["expires_at"] = int(time.time()) + int(payload.get("expires_in", 3600))
    return token


def _ensure_fresh(token: dict, token_path: Path) -> dict:
    expires_at = int(token.get("expires_at", 0))
    if expires_at - REFRESH_LEEWAY_SEC > time.time():
        return token
    token = _refresh_access_token(token)
    _save_token(token_path, token)
    return token


def _gmail_get(url: str, access_token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _list_messages(query: str, max_results: int, access_token: str) -> list[dict]:
    qs = urllib.parse.urlencode({"q": query, "maxResults": max_results})
    payload = _gmail_get(f"{MESSAGES_ENDPOINT}?{qs}", access_token)
    return payload.get("messages", []) or []


def _get_message(msg_id: str, access_token: str) -> dict:
    return _gmail_get(f"{MESSAGES_ENDPOINT}/{msg_id}?format=full", access_token)


def _decode_b64url(data: str) -> str:
    if not data:
        return ""
    pad = (-len(data)) % 4
    try:
        raw = base64.urlsafe_b64decode(data + ("=" * pad))
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_text_part(payload: dict) -> str:
    if not payload:
        return ""
    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {}) or {}
    data = body.get("data")
    parts = payload.get("parts") or []

    if data and mime_type == "text/plain":
        return _decode_b64url(data)

    plain = ""
    html_fallback = ""
    for part in parts:
        sub = _extract_text_part(part)
        if part.get("mimeType") == "text/plain" and sub and not plain:
            plain = sub
        elif part.get("mimeType") == "text/html" and sub and not html_fallback:
            html_fallback = sub
    if plain:
        return plain
    if html_fallback:
        return _strip_html(html_fallback)
    if data:
        return _decode_b64url(data)
    return ""


def _strip_html(html: str) -> str:
    import re
    out = re.sub(r"<style.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"<script.*?</script>", "", out, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"<[^>]+>", " ", out)
    out = re.sub(r"\s+", " ", out)
    return out.strip()


def _header(headers: list[dict], name: str) -> str:
    name_lower = name.lower()
    for h in headers or []:
        if h.get("name", "").lower() == name_lower:
            return h.get("value", "") or ""
    return ""


def fetch(source_cfg: dict, state_cfg: dict) -> list[Item]:
    email_cfg = (state_cfg or {}).get("email_newsletter") or {}
    mode = email_cfg.get("mode")

    if not mode:
        return []

    if mode == "B":
        raise NotImplementedError("Gmail handler mode 'B' (IMAP) not yet wired")

    if mode != "A":
        return []

    token_path = Path(email_cfg.get("token_path", DEFAULT_TOKEN_PATH)).expanduser()
    if not token_path.exists():
        raise NotImplementedError(
            f"Gmail token file not found at {token_path}. Run "
            "`python setup_gmail_oauth.py` from the claude-signal-brief plugin "
            "lib directory first."
        )

    token = _load_token(token_path)
    try:
        token = _ensure_fresh(token, token_path)
    except urllib.error.HTTPError as e:
        if e.code in (400, 401):
            raise NotImplementedError(
                f"Gmail refresh token rejected (HTTP {e.code}). Token may have "
                "been revoked at https://myaccount.google.com/permissions — "
                "re-run setup_gmail_oauth.py to reauthorize."
            ) from e
        raise

    sender = source_cfg.get("sender")
    if not sender:
        return []
    window_days = int(source_cfg.get("window_days", DEFAULT_WINDOW_DAYS))
    max_results = int(source_cfg.get("max_results", DEFAULT_MAX_RESULTS))
    name = source_cfg.get("name", f"gmail:{sender}")
    query = source_cfg.get("query") or f"from:{sender} newer_than:{window_days}d"

    try:
        message_ids = _list_messages(query, max_results, token["access_token"])
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise NotImplementedError(
                f"Gmail API rejected the access token (HTTP {e.code}). "
                "Scope may be insufficient or token revoked — re-run "
                "setup_gmail_oauth.py."
            ) from e
        if e.code == 429:
            return []
        raise

    out: list[Item] = []
    for msg_ref in message_ids:
        msg_id = msg_ref.get("id")
        if not msg_id:
            continue
        try:
            msg = _get_message(msg_id, token["access_token"])
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise

        headers = msg.get("payload", {}).get("headers", []) or []
        subject = _header(headers, "Subject").strip() or "(no subject)"
        from_hdr = _header(headers, "From").strip()
        snippet = (msg.get("snippet") or "").strip()
        body_text = _extract_text_part(msg.get("payload") or {})

        thread_id = msg.get("threadId") or msg_id
        url = f"https://mail.google.com/mail/u/0/#inbox/{thread_id}"

        item: Item = {
            "title": subject[:200],
            "url": url,
            "source": name,
            "summary": "",
            "_extra": {
                "sender": from_hdr,
                "snippet": snippet[:300],
                "body_preview": body_text[:1500] if body_text else "",
                "thread_id": thread_id,
                "message_id": msg_id,
            },
        }
        out.append(item)

    return out


register("gmail", fetch)
