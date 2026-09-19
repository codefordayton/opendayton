# Design decisions

Short records of the choices that shape OpenDayton and why. Each one is a talking point
in the "how it's built" walkthrough; together they're the answer to "why not just
point Claude at the City's GIS server?"

## 1. Curated, not crawled

**Decision.** The server knows exactly the datasets listed in `datasets/layers.yaml` and
`datasets/county.yaml`. It never searches, enumerates, or discovers services at runtime.

**Why.** Dayton has no open-data portal with a search API — its public data is spread across
two ArcGIS orgs, an on-premise map server, a County file server, and federal sources. A
crawl of those would surface hundreds of internal forms, editing views, duplicate layers,
and things that are reachable but not meant to be found. A hand-picked list with a
written description per dataset is smaller, more accurate, and it forces someone to have
looked at each dataset before the model can. Boston's OpenContext gets discovery for free
from CKAN; we replace that step with curation.

**Consequence.** Adding a dataset is a YAML edit and a review, not a code change. The
inclusion bar is written down in `DATASETS.md`.

## 2. Dataset ids, never URLs

**Decision.** Tools take a dataset `id`; the server owns the URL map.

**Why.** If the model could pass a URL, the curated boundary would be advisory — it could
be talked into querying anything reachable. With ids, the boundary is enforced in code.

## 3. Allowlist, not blocklist

**Decision.** Each ArcGIS layer lists the fields the model may see, filter, group, and sort
on. The where-clause validator tokenizes the clause and only admits allowlisted field names,
literals, and a fixed operator set. Everything else is rejected with a message naming the
allowed fields. The County database is conformed at build time so it contains only the
columns `county.yaml` documents.

**Why.** Boston's validator blocks keywords (`DROP`, `DELETE`, …). That stops vandalism but
not exposure: a layer's `OWNER_NAME`, a water `accountid`, an adopter's phone number, or an
editor's login would all flow through. Public layers routinely carry fields that are public
in the legal sense but shouldn't be one prompt away. An allowlist makes "what can the model
see" a reviewable list, and the rejection message is the feedback the model needs to
self-correct.

**Consequence.** Writing the field list is the main work of adding a dataset. That's the
point — it's the review.

## 4. Read-only, bounded, attributed

**Decision.** No tool can write. ArcGIS queries have row caps and retries; County SQL is a
single SELECT against a database opened read-only with external access disabled, wrapped in
a row cap and a 30-second interrupt. Every result carries the dataset title, publisher,
source page, and as-of information.

**Why.** The model should never be able to change anything, exhaust anyone's server, or
present a number without saying where it came from and how old it is.

## 5. `describe_dataset` carries the dictionary and the traps

**Decision.** Before querying, the model reads a description that includes field meanings,
coded values (live from the service), caveats, and example questions.

**Why.** Most wrong answers from data tools aren't SQL errors; they're confident misreadings
— treating `HCS_DIFF < 0` as "improved", counting rows in a one-row-per-charge arrests
table as people, reporting a blank neighborhood bucket as a place, or citing assessor
valuation rents as market rents. The caveats are where the inventory work pays off.

## 6. Official MCP SDK, not a fork of OpenContext

**Decision.** ~600 lines on the official `mcp` Python SDK over Streamable HTTP, borrowing
Boston's *design* (list → describe → schema → query, read-only validators) and crediting it.

**Why.** OpenContext's core is a plugin manager plus AWS Lambda / API Gateway / Terraform /
OAuth plumbing. On Railway with one server and a fixed dataset list, that's weight without
benefit, and a walkthrough is better at 600 lines than 3,000.

## 7. County data as DuckDB, built monthly, baked into the image

**Decision.** `county/build.py` turns the Auditor/Treasurer bulk ZIPs into one DuckDB file.
A GitHub Action rebuilds it monthly and publishes it as a release asset; the Dockerfile
downloads it at build time. The running service has no writable state.

**Why.** The County publishes the richest local data (tenure, values, delinquency, sales
history, permits, dwelling characteristics) but only as fixed-width and CSV downloads with
PDF layouts. DuckDB gives a real SQL engine over them with no server to run, the file ships
with the container, columnar storage makes county-wide aggregates instant, and the model
already writes DuckDB's PostgreSQL-flavored SQL well. Baking it in keeps the service
stateless; monthly matches the County's cadence.

## 8. PII is removed at build time, not filtered at query time

**Decision.** Owner names, mailing names, mailing street addresses, and mortgage codes are
dropped when `county.duckdb` is built. Owner-name fields on City layers are simply not on
the allowlist. The mailing *city* stays (absentee-ownership signal).

**Why.** Public record is not the same as "should be one prompt away." A tax roll you
download and open in a spreadsheet is a different thing from a chatbot that answers "who
owns every house on this street." Removing at build time means there's nothing to get
wrong at query time. A private build with the columns exists for the housing subcommittee's
own work and is never deployed.

## 9. The geocoder is a separate service

**Decision.** Code for Dayton's parcel geocoder keeps its own repo and Railway service; the
MCP server calls it and exposes a `geocode` tool.

**Why.** Other CfD projects use it and have nothing to do with AI. The MCP server is one
client among several — "MCP wraps services you already have" is the general lesson.

## 10. Railway

**Decision.** Deploy from the Dockerfile on every push to `main`, one service, custom domain
`opendayton.org`.

**Why.** It's where Code for Dayton's other projects live, it gives zero-config HTTPS (which
claude.ai custom connectors require), and the whole deploy story fits in one paragraph of
the README.
