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
| County (SQL) | Montgomery County tax roll, delinquent list, sales 2001→, CAMA parcels / dwellings / permits / apartments |

Coming: HUD subsidized housing, MVRPC regional housing study, and the Code for Dayton parcel geocoder.

## Tools

| Tool | What it does |
|---|---|
| `list_datasets(theme?)` | What exists, by theme |
| `describe_dataset(id)` | Fields you may query, coded values, caveats, example questions, live record count |
| `arcgis_query(id, where, out_fields, order_by, limit, offset, near_*)` | Rows |
| `arcgis_stats(id, group_by, stat_type, stat_field, where, ...)` | Server-side counts / sums / averages, grouped |
| `county_schema(table?)` | Tables and columns of the County database, with meanings, join keys, caveats, as-of dates |
| `county_sql(sql, limit)` | One read-only SELECT (DuckDB SQL) against the County database |

Every ArcGIS tool takes a dataset **id**, never a URL. Every field in a `where`, `out_fields`,
`group_by`, `stat_field`, or `order_by` must be on that dataset's allowlist in
`layers.yaml`; anything else is rejected with a message naming the allowed fields.
`county_sql` must be a single SELECT; the database is opened read-only with external
access disabled, queries are row-capped and time-limited, and the schema is exactly what
`datasets/county.yaml` documents. Results carry the dataset title, publisher, source page,
and as-of dates.

## Run it locally

```bash
uv sync
uv run python -m county.build     # ~200 MB of County downloads → county/county.duckdb (~90 MB), a few minutes
uv run uvicorn server.main:app --reload --port 8000
# landing page: http://localhost:8000/   MCP endpoint: http://localhost:8000/mcp
uv run pytest
```

The server runs without `county.duckdb` (the county tools report unavailable), so you can
skip the build if you only care about the ArcGIS layers.

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
server/county.py    read-only DuckDB: single-SELECT guard, row cap, timeout, schema from county.yaml
county/build.py     County ZIPs → county.duckdb (typed, renamed, PII dropped, conformed to county.yaml)
datasets/layers.yaml  the curated ArcGIS catalog — add a dataset here, no Python required
datasets/county.yaml  the County database documentation — the build makes the DB match it exactly
```

The County database is rebuilt monthly by a GitHub Action and published as the
`county-data` release asset, which the Dockerfile bakes into the image.

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

Railway, from the Dockerfile, on every push to `main`. `railway.toml` sets the health
check. Set `OPENDAYTON_PUBLIC_URL` to the public URL so the landing page shows the right
endpoint. The Dockerfile downloads `county.duckdb` from the `county-data` GitHub release;
run the *Rebuild County database* workflow (or `gh release upload county-data
county/county.duckdb --clobber` after a local build) to refresh it.

## Credits & license

Design inspired by the City of Boston's [OpenContext](https://github.com/CityOfBoston/OpenContext)
(MIT). Dataset curation draws on Code for Dayton's Dayton / Montgomery County data inventory.
Data belongs to its publishers; check each dataset's `source_page` for terms.

MIT.
