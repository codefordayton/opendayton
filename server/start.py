"""The attendee-facing setup page at `/start`.

Rendered from docs/START.md so the page and the repo say the same thing — the
handout people open on their phones is the file contributors edit. Deliberately
a tiny subset of Markdown rather than a dependency: headings, lists, fenced
code, links, bold, inline code.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

START_MD = Path(__file__).resolve().parent.parent / "docs" / "START.md"

_INLINE = [
    (re.compile(r"`([^`]+)`"), lambda m: f"<code>{html.escape(m.group(1))}</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), lambda m: f"<strong>{m.group(1)}</strong>"),
    (re.compile(r"\[([^\]]+)\]\(([^)]+)\)"),
     lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>'),
]


def _inline(text: str) -> str:
    out = html.escape(text)
    for pattern, repl in _INLINE:
        out = pattern.sub(repl, out)
    return out


def _to_html(md: str) -> str:
    parts: list[str] = []
    in_code = False
    code: list[str] = []
    list_open = False

    def close_list() -> None:
        nonlocal list_open
        if list_open:
            parts.append("</ul>")
            list_open = False

    for raw in md.splitlines():
        if raw.startswith("```"):
            if in_code:
                parts.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
                code = []
            else:
                close_list()
            in_code = not in_code
            continue
        if in_code:
            code.append(raw)
            continue

        line = raw.rstrip()
        if not line:
            close_list()
            continue
        if m := re.match(r"^(#{1,4})\s+(.*)$", line):
            close_list()
            level = len(m.group(1))
            parts.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
        elif m := re.match(r"^[-*]\s+(.*)$", line):
            if not list_open:
                parts.append("<ul>")
                list_open = True
            parts.append(f"<li>{_inline(m.group(1))}</li>")
        elif re.match(r"^\d+\.\s", line):
            if not list_open:
                parts.append("<ul>")
                list_open = True
            parts.append(f"<li>{_inline(re.sub(r'^\\d+\\.\\s+', '', line))}</li>")
        else:
            close_list()
            parts.append(f"<p>{_inline(line)}</p>")
    close_list()
    if in_code and code:  # unterminated fence; show it rather than swallow it
        parts.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
    return "\n".join(parts)


CSS = """
:root { color-scheme: light dark }
body { margin:0; background:#f6f8f6; color:#1d2721;
  font:17px/1.6 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif }
main { max-width:46rem; margin:0 auto; padding:2.5rem 1.25rem 5rem }
h1 { font-size:2.1rem; line-height:1.15; margin:0 0 1rem }
h2 { font-size:1.4rem; margin:2.5rem 0 .75rem; padding-top:1.25rem; border-top:1px solid #dde5df }
h3 { font-size:1.1rem; margin:1.5rem 0 .5rem }
p, li { color:#2b3a31 }
a { color:#1f6b41 }
code { background:#e6ede8; padding:.12em .35em; border-radius:4px; font-size:.9em;
  font-family:'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace; word-break:break-word }
pre { background:#1d2721; color:#e3f1e6; padding:1rem 1.1rem; border-radius:10px; overflow-x:auto }
pre code { background:none; color:inherit; padding:0; font-size:.86em }
ul { padding-left:1.3rem } li { margin:.3rem 0 }
strong { font-weight:600 }
footer { margin-top:3rem; font-size:.9rem; color:#56645b }
@media (prefers-color-scheme: dark) {
  body { background:#0f1512; color:#e6ede8 }
  p, li { color:#c6d4ca } a { color:#7cc596 }
  h2 { border-top-color:#26332b } code { background:#1d2721; color:#a3d2ac }
  footer { color:#9aaba0 }
}
"""


def render() -> str:
    try:
        body = _to_html(START_MD.read_text())
    except OSError:
        body = "<p>Setup instructions are in docs/START.md in the repository.</p>"
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Start — OpenDayton</title>"
        "<link rel=\"icon\" href=\"/static/favicon.ico\">"
        "<link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?"
        "family=IBM+Plex+Sans:wght@400;600&family=JetBrains+Mono&display=swap\">"
        f"<style>{CSS}</style></head><body><main>{body}"
        "<footer><a href=\"/\">← OpenDayton</a></footer>"
        "</main></body></html>"
    )
