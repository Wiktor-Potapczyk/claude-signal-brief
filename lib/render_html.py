"""Render a weekly signal brief (Markdown) to a standalone HTML page.

Optional, additive output mode — Markdown remains the canonical brief. This
converts the brief's Markdown subset to a self-contained HTML document with
inline CSS, system fonts, and no JavaScript (safe to email or open offline).

Design-inspired by mvanhorn/last30days-skill's `--emit=html` pattern (MIT):
inline CSS, no JS, system font stack. Reimplemented in pure stdlib.

Supported Markdown subset (what claude-signal-weekly-synth emits):
  - YAML frontmatter (--- ... ---) → stripped (title pulled from first H1)
  - # / ## / ### headings
  - `- ` bullet lists (one level)
  - **bold**, _italic_, [text](url) inline
  - --- horizontal rule
  - blank-line-separated paragraphs

Run:  python render_html.py <brief.md> [out.html]   # out defaults to stdout
Stdlib only.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<![A-Za-z0-9_])_([^_]+)_(?![A-Za-z0-9_])")

CSS = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.55; max-width: 720px; margin: 2.5rem auto; padding: 0 1.2rem; color: #1a1a1a; }
h1 { font-size: 1.7rem; border-bottom: 2px solid #e4e4e7; padding-bottom: .4rem; }
h2 { font-size: 1.25rem; margin-top: 2rem; border-bottom: 1px solid #ececf0; padding-bottom: .25rem; }
h3 { font-size: 1.05rem; margin-top: 1.4rem; color: #3f3f46; }
ul { padding-left: 1.2rem; } li { margin: .35rem 0; }
a { color: #2563eb; text-decoration: none; } a:hover { text-decoration: underline; }
hr { border: none; border-top: 1px solid #e4e4e7; margin: 2rem 0; }
.intro { color: #52525b; font-style: italic; }
@media (prefers-color-scheme: dark) {
  body { color: #e4e4e7; background: #18181b; }
  h1 { border-color: #3f3f46; } h2 { border-color: #2c2c30; } h3 { color: #a1a1aa; }
  a { color: #60a5fa; } .intro { color: #a1a1aa; } hr { border-color: #3f3f46; }
}
""".strip()


_SAFE_SCHEMES = ("http://", "https://", "mailto:")


def _safe_href(url: str) -> str | None:
    """Return an escaped href if the URL uses a safe scheme, else None.

    Blocks `javascript:`, `data:`, `vbscript:`, etc. — a markdown link with a
    dangerous scheme would otherwise become a live XSS vector in the rendered
    page. Relative (`/`, `#`) and the http(s)/mailto schemes are allowed.
    """
    u = url.strip()
    if u.startswith(("/", "#")) or u.lower().startswith(_SAFE_SCHEMES):
        # `&`, `<`, `>` are already entity-escaped by the outer _inline pass;
        # only quotes remain (outer pass used quote=False). Escape just quotes
        # to close attribute-breakout without double-escaping `&` in query strings.
        return u.replace('"', "&quot;").replace("'", "&#x27;")
    return None


def _link_sub(m) -> str:
    href = _safe_href(m.group(2))
    if href is None:
        return m.group(1)  # drop unsafe link, keep the visible text
    return f'<a href="{href}">{m.group(1)}</a>'


def _inline(text: str) -> str:
    """Escape HTML, then re-apply the inline Markdown tokens as HTML."""
    text = html.escape(text, quote=False)
    text = _LINK.sub(_link_sub, text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return text


def _strip_frontmatter(md: str) -> str:
    if md.startswith("---"):
        end = md.find("\n---", 3)
        if end != -1:
            nl = md.find("\n", end + 1)
            return md[nl + 1:] if nl != -1 else ""
    return md


def markdown_to_html(md: str) -> tuple[str, str]:
    """Return (title, body_html). Title = first H1, or 'Signal Brief'."""
    md = _strip_frontmatter(md)
    title = "Signal Brief"
    out: list[str] = []
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in md.split("\n"):
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            close_list()
            continue
        if stripped == "---":
            close_list()
            out.append("<hr>")
            continue
        if stripped.startswith("### "):
            close_list()
            out.append(f"<h3>{_inline(stripped[4:])}</h3>")
            continue
        if stripped.startswith("## "):
            close_list()
            out.append(f"<h2>{_inline(stripped[3:])}</h2>")
            continue
        if stripped.startswith("# "):
            close_list()
            heading = stripped[2:]
            if title == "Signal Brief":
                title = heading
            out.append(f"<h1>{_inline(heading)}</h1>")
            continue
        if stripped.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(stripped[2:])}</li>")
            continue
        # Paragraph. Italic-only lines get the .intro class (the brief's lead line).
        close_list()
        if stripped.startswith("_") and stripped.endswith("_"):
            out.append(f'<p class="intro">{_inline(stripped)}</p>')
        else:
            out.append(f"<p>{_inline(stripped)}</p>")

    close_list()
    return title, "\n".join(out)


def render_document(md: str) -> str:
    title, body = markdown_to_html(md)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>\n{CSS}\n</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python render_html.py <brief.md> [out.html]", file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    if not src.is_file():
        print(f"render_html: file not found: {src}", file=sys.stderr)
        return 2
    htmltext = render_document(src.read_text(encoding="utf-8"))
    if len(sys.argv) >= 3:
        out = Path(sys.argv[2])
        out.write_text(htmltext, encoding="utf-8")
        print(str(out))
    else:
        sys.stdout.write(htmltext)
    return 0


if __name__ == "__main__":
    sys.exit(main())
