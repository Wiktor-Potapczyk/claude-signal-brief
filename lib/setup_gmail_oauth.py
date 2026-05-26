"""One-time Gmail OAuth bootstrap for the claude-signal-brief plugin.

Runs an OAuth 2.0 authorization-code flow against Google to obtain a refresh
token for the `gmail.readonly` scope. Subsequent daily fetches use the
refresh token via handlers/gmail.py — no further browser interaction.

Reads: ~/.gmail-mcp/gcp-oauth.keys.json (Desktop OAuth client credentials,
                                          downloaded from GCP Console)
Writes: ~/.claude-signal-brief/gmail-token.json (refresh + access tokens)
Updates: ~/.claude-signal-brief/config.json (email_newsletter section)

Stdlib only. Run once:
    python setup_gmail_oauth.py

Re-run is safe — it overwrites the token file (useful if the refresh token
gets revoked from Google Account > Security).
"""

from __future__ import annotations

import http.server
import json
import secrets
import socketserver
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path


CLIENT_JSON = Path.home() / ".gmail-mcp" / "gcp-oauth.keys.json"
TOKEN_PATH = Path.home() / ".claude-signal-brief" / "gmail-token.json"
CONFIG_PATH = Path.home() / ".claude-signal-brief" / "config.json"

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
CALLBACK_PORT = 53682
CALLBACK_PATH = "/oauth2callback"


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    received: dict = {}

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.received = {
            k: v[0] for k, v in params.items() if v
        }
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = (
            "<html><body style='font-family:sans-serif;padding:40px;'>"
            "<h2>Authorization received.</h2>"
            "<p>You can close this tab and return to the terminal.</p>"
            "</body></html>"
        )
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format, *args):
        pass


def _serve_until_callback(timeout_sec: int = 180) -> dict:
    _CallbackHandler.received = {}
    server = socketserver.TCPServer(("127.0.0.1", CALLBACK_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    deadline = time.monotonic() + timeout_sec
    try:
        while time.monotonic() < deadline:
            if _CallbackHandler.received:
                break
            time.sleep(0.2)
        return dict(_CallbackHandler.received)
    finally:
        server.shutdown()
        server.server_close()


def _load_client_json() -> dict:
    if not CLIENT_JSON.exists():
        print(f"ERROR: client credentials not found at {CLIENT_JSON}", file=sys.stderr)
        print("Place the GCP OAuth client JSON there first (see README §First-run setup §4).",
              file=sys.stderr)
        sys.exit(2)
    with open(CLIENT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "installed" in data:
        return data["installed"]
    if "web" in data:
        return data["web"]
    return data


def _build_auth_url(client_id: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}",
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return AUTH_ENDPOINT + "?" + urllib.parse.urlencode(params)


def _exchange_code_for_token(code: str, client_id: str, client_secret: str) -> dict:
    body = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}",
        "grant_type": "authorization_code",
    }).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _save_token(token: dict, client_id: str, client_secret: str) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "access_token": token["access_token"],
        "refresh_token": token["refresh_token"],
        "expires_at": int(time.time()) + int(token.get("expires_in", 3600)),
        "token_type": token.get("token_type", "Bearer"),
        "scope": token.get("scope", " ".join(SCOPES)),
        "client_id": client_id,
        "client_secret": client_secret,
    }
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _update_config() -> None:
    """Flip email_newsletter.mode = "A" in ~/.claude-signal-brief/config.json."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import state as _state_mod  # noqa: E402
    defaults = json.loads(json.dumps(_state_mod.DEFAULT_CONFIG))

    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        for k, v in defaults.items():
            cfg.setdefault(k, v)
    else:
        cfg = defaults

    cfg.setdefault("email_newsletter", {})
    cfg["email_newsletter"]["mode"] = "A"
    cfg["email_newsletter"]["token_path"] = str(TOKEN_PATH)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def main() -> int:
    client = _load_client_json()
    client_id = client["client_id"]
    client_secret = client["client_secret"]
    state = secrets.token_urlsafe(24)
    auth_url = _build_auth_url(client_id, state)

    print("Opening browser for Google OAuth consent...")
    print(f"If the browser doesn't open, paste this URL manually:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    received = _serve_until_callback()
    if not received:
        print("ERROR: no callback received within 3 minutes.", file=sys.stderr)
        return 1
    if received.get("state") != state:
        print(f"ERROR: state mismatch (CSRF protection). Got {received.get('state')!r}.",
              file=sys.stderr)
        return 1
    if "error" in received:
        print(f"ERROR from Google: {received['error']}: "
              f"{received.get('error_description', '')}", file=sys.stderr)
        return 1
    code = received.get("code")
    if not code:
        print(f"ERROR: no authorization code in callback. Got: {received}",
              file=sys.stderr)
        return 1

    print("Exchanging authorization code for tokens...")
    token = _exchange_code_for_token(code, client_id, client_secret)
    if "refresh_token" not in token:
        print("ERROR: Google did not return a refresh_token. This usually means "
              "you've already granted consent without `prompt=consent` — try "
              "revoking access at https://myaccount.google.com/permissions and "
              "re-run.", file=sys.stderr)
        print(f"Token response: {token}", file=sys.stderr)
        return 1

    _save_token(token, client_id, client_secret)
    _update_config()

    print()
    print(f"SUCCESS. Token written to: {TOKEN_PATH}")
    print(f"Config updated:            {CONFIG_PATH}")
    print()
    print("Next: enable the AlphaSignal source in sources.yml")
    print("  (change `enabled: false` to `enabled: true` on the gmail entry)")
    print("Then re-run /claude-signal-daily-fetch or trigger the scheduled routine.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
