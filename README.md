# OpenDayton

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant answer questions
from curated public datasets about the **City of Dayton** and **Montgomery County, Ohio** —
crime and calls for service, housing condition, lead service lines, trash pickup days,
capital projects, and more — straight from the agencies' own published data.

Ask Claude *"which neighborhoods had the most violent crime last year?"* or *"does 275
Linden Ave have a lead service line?"* and it answers from the City's data, with the source
cited.

A [Code for Dayton](https://codefordayton.org) project, built for Hacktoberfest 2026 and
inspired by the City of Boston's [OpenContext](https://github.com/CityOfBoston/OpenContext).
It's meant to be small enough to read in an afternoon and to spin up for your own city.

## Connect

The public endpoint is `https://<railway-url>/mcp` (see the landing page at the root URL).

- **Claude.ai / Claude Desktop:** Settings → Connectors → *Add custom connector* → paste the endpoint.
- **Claude Code:** `claude mcp add --transport http opendayton https://<railway-url>/mcp`
- **Anything else that speaks MCP over Streamable HTTP:** point it at the endpoint.

Then ask a question. The server's instructions tell the model to call `list_datasets`,
read `describe_dataset` before querying, and prefer aggregates.

## What's in it

The catalog is [`datasets/layers.yaml`](datasets/layers.yaml). Every dataset there is one
the publisher intentionally surfaces to the public — a Hub site, an "OpenData" folder, a
public dashboard, a `_public` service. The server knows about nothing else. See
[`docs/DATASETS.md`](docs/DATASETS.md) for the inclusion criteria and the full survey.

| Theme | Datasets |
|---|---|
| Reference | neighborhoods, public facilities |
| Public safety | crimes (NIBRS), arrests, calls for service, use of force |
| Housing | housing condition survey 2025 (+2023), City-supported housing projects, City-owned parcels |
| Infrastructure | lead service lines, trash pickup days, storm drains |
| Capital | active & completed capital projects, ARPA project applications |

Coming: Montgomery County tax roll, sales, and assessment data (as a DuckDB file), HUD
subsidized housing, MVRPC regional housing study, and the Code for Dayton parcel geocoder.

## Tools

| Tool | What it does |
|---|---|
| `list_datasets(theme?)` | What exists, by theme |
| `describe_dataset(id)` | Fields you may query, coded values, caveats, example questions, live record count |
| `arcgis_query(id, where, out_fields, order_by, limit, offset, near_*)` | Rows |
| `arcgis_stats(id, group_by, stat_type, stat_field, where, ...)` | Server-side counts / sums / averages, grouped |

Every tool takes a dataset **id**, never a URL. Every field in a `where`, `out_fields`,
`group_by`, `stat_field`, or `order_by` must be on that dataset's allowlist in
`layers.yaml`; anything else is rejected with a message naming the allowed fields. Results
are read-only, row-capped, and carry the dataset title, publisher, and source page.

## Run it locally

```bash
uv sync
uv run uvicorn server.main:app --reload --port 8000
# landing page: http://localhost:8000/   MCP endpoint: http://localhost:8000/mcp
uv run pytest
```

Try it from Claude Code: `claude mcp add --transport http opendayton http://localhost:8000/mcp`

## How it's built

```
Claude / any MCP client
        │  Streamable HTTP
        ▼
server/main.py      MCPServer (official mcp SDK) — tools, instructions, landing page
server/catalog.py   loads datasets/layers.yaml; the allowlist lives here
server/where.py     tokenizing validator: only allowlisted fields, literals, fixed operators
server/arcgis.py    read-only ArcGIS REST client: schema (cached), query, statistics, `near`
datasets/layers.yaml  the curated catalog — add a dataset here, no Python required
```

Design notes and the reasoning behind them are in [`docs/DECISIONS.md`](docs/DECISIONS.md).
The short version: *curated, not crawled; ids not URLs; allowlist not blocklist; read-only;
cite everything.*

## Adding a dataset

1. Confirm the publisher surfaces it to the public on purpose. Note where (`public_via`, `source_page`).
2. Add an entry to `datasets/layers.yaml` with the full layer URL and a `fields` allowlist —
   only the fields a resident needs, with plain-language descriptions. Leave out anything
   that identifies a person (names, account numbers, contact details) and editor-tracking junk.
3. Write `caveats` for the traps you found and two or three `example_questions`.
4. `uv run pytest`, then run the server and ask the example questions.

## Deploy

Railway, from the Dockerfile. `railway.toml` sets the health check. Set
`OPENDAYTON_PUBLIC_URL` to the public URL so the landing page shows the right endpoint.

## Credits & license

Design inspired by the City of Boston's [OpenContext](https://github.com/CityOfBoston/OpenContext)
(MIT). Dataset curation draws on Code for Dayton's Dayton / Montgomery County data inventory.
Data belongs to its publishers; check each dataset's `source_page` for terms.

MIT.
