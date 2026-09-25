"""The human-facing landing page at `/`.

One self-contained HTML page (no build step, no external JS): what OpenDayton
is, how to connect it, sample questions to try, and the dataset catalog.
Logos come from github.com/codefordayton/logos (CC BY 4.0) and are served
from server/static/.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from .catalog import Catalog
from .county import CountyDB

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {p.name: p for p in STATIC_DIR.iterdir() if p.is_file()} if STATIC_DIR.is_dir() else {}

THEME_LABELS = {
    "reference": "Neighborhoods & reference",
    "public_safety": "Public safety",
    "housing": "Housing",
    "infrastructure": "Infrastructure & services",
    "capital": "Capital projects & spending",
    "community": "Community",
    "environment": "Environment",
    "regional": "Regional",
}

# Plain-language questions a resident might ask, grouped. Each one is
# answerable from the catalog or the County database.
SAMPLE_QUESTIONS: list[tuple[str, list[str]]] = [
    (
        "About an address",
        [
            "What day is trash pickup at 275 Linden Ave?",
            "Does 275 Linden Ave have a lead water service line?",
            "Are any water, sewer, or street projects planned near 200 W Norman Ave?",
            "Are there storm drains near 100 Salem Ave that nobody has adopted yet?",
        ],
    ),
    (
        "Neighborhoods & public safety",
        [
            "Which neighborhoods had the most violent crime last year, per 1,000 residents?",
            "What hours of the day are busiest for police calls?",
            "Which neighborhoods lost the most population between 2010 and 2020?",
            "How many police use-of-force incidents were there each year?",
        ],
    ),
    (
        "Housing & property",
        [
            "Which neighborhoods have the most houses needing major repair?",
            "How many homes got worse between the 2023 and 2025 housing surveys?",
            "What was the median home sale price in Dayton each year since 2015?",
            "How many Dayton parcels are tax-delinquent, and how much do they owe?",
            "What share of homes in each census tract are owner-occupied?",
            "How many vacant City-owned lots are for sale in each neighborhood?",
        ],
    ),
    (
        "City spending & services",
        [
            "What capital projects are under construction right now, and what do they cost?",
            "How much did the City spend on street projects each fiscal year?",
            "How much ARPA funding was requested, broken down by ZIP code?",
            "How many lead service lines have been replaced each year?",
        ],
    ),
]

TOOLS = [
    ("list_datasets", "What exists, by theme"),
    ("describe_dataset", "Fields, coded values, caveats, live record count"),
    ("arcgis_query", "Rows from a City dataset"),
    ("arcgis_stats", "Server-side counts, sums, and averages"),
    ("county_schema", "Tables and columns of the County database"),
    ("county_sql", "One read-only SELECT against County records"),
    ("geocode", "Address or parcel ID → parcel and coordinates"),
]

CSS = """
:root{--bg:#f6f8f6;--surface:#fff;--ink:#16211b;--muted:#56645b;--line:#dde5df;
--brand:#126840;--brand-2:#35985f;--brand-soft:#e3f1e6;--code:#eef3ef;--shadow:0 1px 2px rgb(0 0 0/.04),0 4px 16px rgb(0 0 0/.04)}
@media (prefers-color-scheme:dark){:root{--bg:#0f1512;--surface:#161e19;--ink:#e6ede8;--muted:#9aaba0;--line:#26332b;
--brand:#7cc596;--brand-2:#a3d2ac;--brand-soft:#1c2a21;--code:#1d2721;--shadow:none}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 "Lexend Deca",system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--brand)}a:hover{color:var(--brand-2)}
code{font:.88em/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--code);padding:.12rem .35rem;border-radius:4px}
.wrap{max-width:68rem;margin:0 auto;padding:0 1rem}
header.top{border-bottom:1px solid var(--line);background:var(--surface)}
header.top .wrap{display:flex;align-items:center;justify-content:space-between;gap:1rem;padding-top:.75rem;padding-bottom:.75rem}
header.top img{height:44px;width:auto;display:block}
header.top nav{display:flex;gap:1.25rem;font-size:.95rem}
header.top nav a{color:var(--muted);text-decoration:none}header.top nav a:hover{color:var(--brand)}
.wrap.hero{padding-top:3.5rem;padding-bottom:2.5rem}
.eyebrow{display:inline-block;font-size:.8rem;letter-spacing:.08em;text-transform:uppercase;color:var(--brand);background:var(--brand-soft);padding:.2rem .6rem;border-radius:999px;margin-bottom:1rem}
h1{font-size:clamp(2rem,5vw,3rem);line-height:1.15;margin:0 0 1rem;letter-spacing:-.01em}
h1 span{color:var(--brand)}
.lede{font-size:1.15rem;color:var(--muted);max-width:44rem;margin:0}
.stats{display:flex;flex-wrap:wrap;gap:.75rem 2rem;margin-top:1.75rem;color:var(--muted);font-size:.95rem}
.stats b{display:block;font-size:1.5rem;color:var(--ink)}
section{padding:2.25rem 0;border-top:1px solid var(--line)}
h2{font-size:1.5rem;margin:0 0 .35rem}
.sub{color:var(--muted);margin:0 0 1.5rem}
.endpoint{display:flex;align-items:center;gap:.5rem;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:.5rem .5rem .5rem 1rem;max-width:36rem;box-shadow:var(--shadow)}
.endpoint code{background:none;padding:0;font-size:1rem;flex:1;overflow-wrap:anywhere}
button.copy{font:inherit;font-size:.85rem;border:1px solid var(--brand);background:var(--brand);color:#fff;border-radius:7px;padding:.35rem .8rem;cursor:pointer;white-space:nowrap}
@media (prefers-color-scheme:dark){button.copy{color:#0f1512}}
button.copy:hover{filter:brightness(1.08)}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:1rem;margin-top:1.5rem}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:1.1rem 1.2rem;box-shadow:var(--shadow);min-width:0}
.card h3{font-size:1rem;margin:0 0 .4rem}
.card p{margin:0;color:var(--muted);font-size:.93rem}
.card pre{margin:.6rem 0 0;background:var(--code);border-radius:8px;padding:.6rem .75rem;white-space:pre-wrap;overflow-wrap:anywhere;font-size:.8rem}
.card pre code{background:none;padding:0}
.qgroups{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1.5rem 1.25rem}
@media (max-width:760px){.qgroups{grid-template-columns:1fr}}
.qgroups h3{font-size:.85rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 .6rem}
.qgroups ul{list-style:none;margin:0;padding:0;display:grid;gap:.5rem}
.q{display:block;width:100%;text-align:left;font:inherit;font-size:.95rem;line-height:1.45;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--brand-2);border-radius:8px;padding:.6rem .8rem;cursor:pointer;transition:border-color .15s,background .15s}
.q:hover{border-color:var(--brand);background:var(--brand-soft)}
.q.copied{border-color:var(--brand);background:var(--brand-soft)}
.q.copied::after{content:" ✓ copied";color:var(--brand);font-size:.8rem}
.hint{font-size:.85rem;color:var(--muted);margin-top:1rem}
.theme{margin-top:1.75rem}
.theme h3{font-size:1.05rem;margin:0 0 .75rem;display:flex;align-items:baseline;gap:.5rem}
.theme h3 small{color:var(--muted);font-weight:400;font-size:.85rem}
.dsgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(18rem,1fr));gap:.9rem}
.ds h4{margin:0 0 .3rem;font-size:.98rem}
.ds .meta{display:flex;flex-wrap:wrap;gap:.25rem .75rem;margin-top:.6rem;font-size:.8rem;color:var(--muted)}
.ds .meta code{font-size:.78rem}
.tools{display:grid;grid-template-columns:repeat(auto-fill,minmax(18rem,1fr));gap:.4rem 1.5rem;margin:0;padding:0;list-style:none}
.tools li{font-size:.93rem;color:var(--muted)}.tools code{color:var(--ink)}
footer{border-top:1px solid var(--line);background:var(--surface);padding:2rem 0;margin-top:1rem;font-size:.9rem;color:var(--muted)}
footer .wrap{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:1rem}
footer img{height:36px;width:auto;display:block}
@media (max-width:640px){header.top nav{display:none}.wrap.hero{padding-top:2.25rem;padding-bottom:1.5rem}}
"""

JS = """
function copyText(t,el,cls){navigator.clipboard&&navigator.clipboard.writeText(t).then(function(){
el.classList.add(cls);var o=el.textContent;if(el.dataset.label){el.textContent='Copied!'}
setTimeout(function(){el.classList.remove(cls);if(el.dataset.label){el.textContent=el.dataset.label}},1600)})}
document.querySelectorAll('.q').forEach(function(b){b.addEventListener('click',function(){copyText(b.textContent,b,'copied')})});
document.querySelectorAll('button.copy').forEach(function(b){b.dataset.label=b.textContent;
b.addEventListener('click',function(){copyText(b.dataset.copy,b,'done')})});
"""


def _logo() -> str:
    return (
        "<picture>"
        '<source srcset="/static/cfd-logo-stacked-light.png" media="(prefers-color-scheme: dark)">'
        f'<img src="/static/cfd-logo-stacked-dark.png" alt="Code for Dayton" width="720" height="240">'
        "</picture>"
    )


def _first_sentence(text: str) -> str:
    text = " ".join(text.split())
    cut = text.find(". ")
    return text if cut == -1 else text[: cut + 1]


def render(catalog: Catalog, county: CountyDB, public_url: str) -> str:
    endpoint = f"{public_url}/mcp"
    cc_cmd = f"claude mcp add --transport http opendayton {endpoint}"

    questions = "".join(
        f"<div><h3>{escape(group)}</h3><ul>"
        + "".join(f'<li><button class="q" type="button">{escape(q)}</button></li>' for q in qs)
        + "</ul></div>"
        for group, qs in SAMPLE_QUESTIONS
    )

    themes_html = []
    present = catalog.themes()
    for theme in sorted(present, key=lambda t: list(THEME_LABELS).index(t) if t in THEME_LABELS else len(THEME_LABELS)):
        cards = "".join(
            f'<article class="card ds"><h4>{escape(l.title)}</h4>'
            f"<p>{escape(_first_sentence(l.description))}</p>"
            f'<div class="meta"><span>{escape(l.publisher)}</span>'
            + (f"<span>~{l.approx_records:,} records</span>" if l.approx_records else "")
            + f'<code>{escape(l.id)}</code><a href="{escape(l.source_page)}" rel="noopener">source ↗</a></div></article>'
            for l in catalog.by_theme(theme)
        )
        themes_html.append(
            f'<div class="theme"><h3>{escape(THEME_LABELS.get(theme, theme))}</h3><div class="dsgrid">{cards}</div></div>'
        )

    county_meta = county.meta() if county.available else []
    if county_meta:
        county_card = (
            '<article class="card ds"><h4>Montgomery County property records</h4>'
            f"<p>{escape(_first_sentence(county.schema.description))} Queried with SQL; "
            "countywide, so answers can be filtered to the City of Dayton.</p>"
            '<div class="meta">'
            f"<span>{escape(county.schema.publisher)}</span>"
            + "".join(f"<code>{escape(m['table'])}</code>" for m in county_meta)
            + f'<a href="{escape(county.schema.source_page)}" rel="noopener">source ↗</a></div>'
            '<div class="meta">Files as of '
            + escape(", ".join(sorted({str(m["file_date"]) for m in county_meta})))
            + "</div></article>"
        )
    else:
        county_card = (
            '<article class="card ds"><h4>Montgomery County property records</h4>'
            "<p>Tax roll, sales, delinquency, and assessment records. Not loaded on this server.</p></article>"
        )
    themes_html.append(
        f'<div class="theme"><h3>County property records <small>SQL database</small></h3><div class="dsgrid">{county_card}</div></div>'
    )

    tools = "".join(f"<li><code>{escape(n)}</code> — {escape(d)}</li>" for n, d in TOOLS)
    n = len(catalog)

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenDayton · Ask questions of Dayton's public data</title>
<meta name="description" content="OpenDayton is a Code for Dayton MCP server that lets AI assistants like Claude answer questions from {n} public datasets about Dayton and Montgomery County, Ohio.">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="/static/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/static/favicon-180.png">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lexend+Deca:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head><body>

<header class="top"><div class="wrap">
<a href="https://codefordayton.org" aria-label="Code for Dayton">{_logo()}</a>
<nav><a href="#connect">Connect</a><a href="#ask">Try asking</a><a href="#data">Datasets</a><a href="https://github.com/codefordayton/opendayton">GitHub</a></nav>
</div></header>

<main>
<div class="wrap hero">
<span class="eyebrow">OpenDayton · a Code for Dayton project</span>
<h1>Ask questions about Dayton,<br><span>answered from public data.</span></h1>
<p class="lede">OpenDayton connects AI assistants like Claude to curated open data from the City of Dayton
and Montgomery County: crime and 911 calls, housing conditions, lead water lines, trash pickup, capital
projects, property records, and more. Answers cite the agency that published the data.</p>
<div class="stats">
<div><b>{n}</b>City &amp; regional datasets</div>
{f"<div><b>{len(county_meta)}</b>County property record tables</div>" if county_meta else ""}
<div><b>Free</b>No account or API key</div>
</div>
</div>

<section id="connect"><div class="wrap">
<h2>Connect in a minute</h2>
<p class="sub">OpenDayton is an <a href="https://modelcontextprotocol.io">MCP</a> server. Add this address to your AI assistant:</p>
<div class="endpoint"><code>{escape(endpoint)}</code><button class="copy" type="button" data-copy="{escape(endpoint)}">Copy</button></div>
<div class="steps">
<div class="card"><h3>Claude.ai &amp; Claude Desktop</h3><p>Settings → Connectors → <em>Add custom connector</em>, name it OpenDayton, and paste the address above.</p></div>
<div class="card"><h3>Claude Code</h3><p>Run this in your terminal:</p><pre><code>{escape(cc_cmd)}</code></pre></div>
<div class="card"><h3>Other MCP clients</h3><p>Anything that speaks MCP over Streamable HTTP can point at the address. No API key needed.</p></div>
</div>
</div></section>

<section id="ask"><div class="wrap">
<h2>Things to ask</h2>
<p class="sub">Once connected, ask in plain English. Click a question to copy it.</p>
<div class="qgroups">{questions}</div>
<p class="hint">Tip: for address questions, include a street address in Dayton. The assistant looks up the parcel and checks what's nearby.</p>
</div></section>

<section id="data"><div class="wrap">
<h2>What's inside</h2>
<p class="sub">Every dataset is one its publisher already shares with the public. OpenDayton only reads what's listed here.</p>
{"".join(themes_html)}
</div></section>

<section id="tools"><div class="wrap">
<h2>For developers</h2>
<p class="sub">The tools the server exposes. Queries are validated against each dataset's field allowlist and are row-capped.
Also: <a href="/datasets.json">/datasets.json</a> · <a href="/health">/health</a></p>
<ul class="tools">{tools}</ul>
</div></section>
</main>

<footer><div class="wrap">
<a href="https://codefordayton.org" aria-label="Code for Dayton">{_logo()}</a>
<div>Built by volunteers at <a href="https://codefordayton.org">Code for Dayton</a>.
Inspired by the City of Boston's <a href="https://github.com/CityOfBoston/OpenContext">OpenContext</a>.
Source on <a href="https://github.com/codefordayton/opendayton">GitHub</a>.</div>
</div></footer>

<script>{JS}</script>
</body></html>"""
