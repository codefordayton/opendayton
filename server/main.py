"""OpenDayton MCP server.

Exposes a curated set of City of Dayton / Montgomery County open datasets to
any MCP client over Streamable HTTP. Tools take dataset ids from
datasets/layers.yaml — never URLs — and every query is read-only, validated
against the layer's field allowlist, and bounded.

Run locally:   uv run uvicorn server.main:app --reload --port 8000
MCP endpoint:  http://localhost:8000/mcp
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response

from .arcgis import DEFAULT_LIMIT, MAX_LIMIT, STATS_MAX_LIMIT, ArcGISClient, ArcGISError
from . import landing as landing_page
from .catalog import Catalog, CatalogError
from .county import DEFAULT_LIMIT as COUNTY_DEFAULT_LIMIT, CountyDB, CountySQLError
from .geocode import GeocodeError, GeocoderClient
from .where import WhereError

VERSION = "0.1.0"
PUBLIC_URL = os.environ.get("OPENDAYTON_PUBLIC_URL", "http://localhost:8000")

catalog = Catalog.load()
arcgis = ArcGISClient()
county = CountyDB()
geocoder = GeocoderClient()

INSTRUCTIONS = f"""\
OpenDayton gives you read-only access to {len(catalog)} curated public datasets
about the City of Dayton and Montgomery County, Ohio, published by the City,
County, and regional agencies, plus a SQL database of the Montgomery County
tax roll, sales, delinquency, and assessment (CAMA) records.

How to work:
1. Call list_datasets to see what exists (optionally filtered by theme).
2. Call describe_dataset before querying a dataset for the first time. It
   returns the field allowlist, coded values, caveats, and example questions.
   Queries can only use fields that appear there.
3. Prefer arcgis_stats (group-by counts/sums) for "how many / which most"
   questions; use arcgis_query for row-level detail.
4. For parcel-level County questions (values, tenure, delinquency, sales
   history, permits, dwelling characteristics) call county_schema, then
   county_sql with a single SELECT. The County data is countywide: filter
   city_township = 'DAYTON' for City of Dayton figures.
5. For "at this address" questions: call geocode(address) to get the parcel
   and its latitude/longitude, then pass near_latitude / near_longitude to
   arcgis_query or arcgis_stats (trash pickup, storm drains, capital
   projects, lead lines), or use the parcel_id with county_sql.

Rules: cite the dataset title and publisher in answers; report the as-of
information returned with results; never claim a dataset covers something
its description doesn't; if a question needs data that isn't here, say so.
"""

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)


@asynccontextmanager
async def lifespan(_server: MCPServer):
    try:
        yield {}
    finally:
        await arcgis.aclose()
        await geocoder.aclose()
        county.close()


server = MCPServer(
    name="OpenDayton",
    title="OpenDayton — Dayton & Montgomery County open data",
    version=VERSION,
    instructions=INSTRUCTIONS,
    website_url=PUBLIC_URL,
    lifespan=lifespan,
)


def _err(kind: str, message: str) -> dict[str, Any]:
    return {"error": kind, "message": message}


# ── Tools ────────────────────────────────────────────────────────────────────


@server.tool(annotations=READ_ONLY)
async def list_datasets(theme: str | None = None) -> dict[str, Any]:
    """List the curated datasets available, optionally filtered by theme.

    Themes: reference, public_safety, housing, infrastructure, capital,
    community, environment, regional. Returns id, title, theme, publisher,
    approximate record count, and a one-line description for each dataset.
    Call describe_dataset(id) before querying one.
    """
    layers = catalog.by_theme(theme)
    if theme and not layers:
        return _err("unknown_theme", f"no datasets in theme '{theme}'. Themes: {list(catalog.themes())}")
    return {
        "themes": catalog.themes(),
        "datasets": [
            {
                "id": l.id,
                "title": l.title,
                "theme": l.theme,
                "publisher": l.publisher,
                "geometry": l.geometry,
                "approx_records": l.approx_records,
                "description": l.description,
            }
            for l in layers
        ],
    }


@server.tool(annotations=READ_ONLY)
async def describe_dataset(dataset_id: str) -> dict[str, Any]:
    """Describe one dataset: fields you may query, coded values, caveats, and
    example questions. Also returns the live record count and last-edit date.

    Read this before writing a where clause. Field names are case-sensitive
    as listed. Date fields accept `FIELD >= DATE '2025-01-01'`.
    """
    try:
        layer = catalog.get(dataset_id)
    except CatalogError as e:
        return _err("unknown_dataset", str(e))
    try:
        schema = await arcgis.schema(layer)
        count = await arcgis.count(layer)
    except ArcGISError as e:
        return _err("upstream_error", str(e))

    fields = []
    for name, desc in layer.fields.items():
        info = schema.fields.get(name)
        entry: dict[str, Any] = {"name": name, "description": desc}
        if info is None:
            entry["warning"] = "not present on the live service right now"
        else:
            entry["type"] = info.type
            if info.domain:
                entry["values"] = {str(k): v for k, v in list(info.domain.items())[:60]}
        fields.append(entry)

    out: dict[str, Any] = {
        "id": layer.id,
        "title": layer.title,
        "theme": layer.theme,
        "publisher": layer.publisher,
        "public_via": layer.public_via,
        "source_page": layer.source_page,
        "description": layer.description,
        "geometry": layer.geometry,
        "record_count": count,
        "last_edit": schema.last_edit,
        "time_field": layer.time_field,
        "fields": fields,
        "caveats": layer.caveats,
        "example_questions": layer.example_questions,
        "query_tips": [
            "Only the fields listed above can be used in where, out_fields, group_by, stat_field, order_by.",
            "String comparisons are case-sensitive on most services; use UPPER(field) = 'VALUE' when unsure.",
            "Dates: FIELD >= DATE '2025-01-01' or FIELD BETWEEN DATE '2025-01-01' AND DATE '2025-12-31'.",
            "Use arcgis_stats with group_by for counts and rollups instead of pulling rows.",
        ],
    }
    if layer.base_where:
        out["always_applied_filter"] = layer.base_where
    dictionary = layer.dictionary()
    if dictionary:
        out["dictionary_markdown"] = dictionary
    return out


@server.tool(annotations=READ_ONLY)
async def arcgis_query(
    dataset_id: str,
    where: str | None = None,
    out_fields: list[str] | None = None,
    order_by: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    near_latitude: float | None = None,
    near_longitude: float | None = None,
    near_meters: float = 250,
    include_location: bool = False,
) -> dict[str, Any]:
    """Return rows from a dataset.

    `where` is a SQL-style filter using only allowlisted fields, e.g.
    "Neighborhood = 'Five Oaks' AND Year = 2025". `out_fields` narrows the
    columns; `order_by` is "FIELD DESC". `limit` caps rows (max 2000); use
    `offset` to page. For "near this address" questions, pass near_latitude /
    near_longitude (from geocode) and a radius in meters. include_location
    adds latitude/longitude to each row for point and polygon datasets.
    """
    try:
        layer = catalog.get(dataset_id)
        near = None
        if near_latitude is not None or near_longitude is not None:
            if near_latitude is None or near_longitude is None:
                return _err("bad_request", "provide both near_latitude and near_longitude")
            near = (near_latitude, near_longitude, near_meters)
        result = await arcgis.query(
            layer,
            where=where,
            out_fields=out_fields,
            order_by=order_by,
            limit=min(limit, MAX_LIMIT),
            offset=offset,
            near=near,
            include_location=include_location,
        )
    except CatalogError as e:
        return _err("unknown_dataset", str(e))
    except WhereError as e:
        return _err("invalid_query", str(e))
    except ArcGISError as e:
        return _err("upstream_error", str(e))
    result["source"] = _source(layer)
    return result


@server.tool(annotations=READ_ONLY)
async def arcgis_stats(
    dataset_id: str,
    group_by: list[str] | None = None,
    stat_type: str = "count",
    stat_field: str | None = None,
    where: str | None = None,
    order_by: str | None = None,
    limit: int = STATS_MAX_LIMIT,
    near_latitude: float | None = None,
    near_longitude: float | None = None,
    near_meters: float = 250,
) -> dict[str, Any]:
    """Aggregate a dataset server-side: counts or sum/avg/min/max/stddev of a
    field, optionally grouped by one or more fields.

    Examples: group_by=["Neighborhood"] with stat_type="count" gives a count
    per neighborhood; group_by=["YEAR","NIBRS_Category"] gives a two-level
    rollup; stat_type="sum", stat_field="AwdConstructionCost",
    group_by=["PROJTYPE"] sums cost by project type. The statistic column is
    named `count` or `<type>_<field>`; order_by may reference it
    (default: statistic DESC).
    """
    try:
        layer = catalog.get(dataset_id)
        near = None
        if near_latitude is not None and near_longitude is not None:
            near = (near_latitude, near_longitude, near_meters)
        result = await arcgis.stats(
            layer,
            group_by=group_by,
            stat_type=stat_type,
            stat_field=stat_field,
            where=where,
            order_by=order_by,
            limit=limit,
            near=near,
        )
    except CatalogError as e:
        return _err("unknown_dataset", str(e))
    except WhereError as e:
        return _err("invalid_query", str(e))
    except ArcGISError as e:
        return _err("upstream_error", str(e))
    result["source"] = _source(layer)
    return result


@server.tool(annotations=READ_ONLY)
async def county_schema(table: str | None = None) -> dict[str, Any]:
    """Describe the Montgomery County SQL database: tables, columns with
    meanings, join keys, caveats, and the as-of date of each source file.

    Call with no arguments for the overview and table list; call with a
    table name for its columns. Read this before writing county_sql.
    """
    try:
        return county.describe(table)
    except CountySQLError as e:
        return _err("unknown_table", str(e))


@server.tool(annotations=READ_ONLY)
async def county_sql(sql: str, limit: int = COUNTY_DEFAULT_LIMIT) -> dict[str, Any]:
    """Run one read-only SELECT against the Montgomery County database
    (DuckDB SQL; PostgreSQL-like). Tables: taxroll, delinquent, sales,
    cama_parcel, cama_dwelling, cama_permit, cama_apartment, cama_codes,
    nbhd_codes, _meta. Join on parcel_id.

    Aggregate rather than dumping rows; results are capped at `limit`
    (default 200, max 2000) and 30 seconds. Filter city_township = 'DAYTON'
    for City of Dayton. Owner names are not in the database.
    """
    try:
        result = county.query(sql, limit=limit)
    except CountySQLError as e:
        return _err("invalid_sql", str(e))
    result["source"] = {
        "dataset": "Montgomery County tax roll, sales, delinquency, and CAMA bulk files",
        "publisher": county.schema.publisher,
        "source_page": county.schema.source_page,
        "as_of": {m["table"]: m["file_date"] for m in county.meta()},
        "note": "Cite the publisher and the as-of file date when using these results.",
    }
    return result


@server.tool(annotations=READ_ONLY)
async def geocode(address: str | None = None, parcel_id: str | None = None, limit: int = 10) -> dict[str, Any]:
    """Find Montgomery County parcels by street address or parcel ID and
    return each parcel's ID, address, ZIP, latitude, and longitude.

    Give a street address like "275 Linden Ave" (city and ZIP are ignored;
    partial addresses like "LINDEN AVE" match many parcels) or a parcel ID
    like "R72 12307 0032". Use the coordinates with the near_* parameters of
    arcgis_query / arcgis_stats, and the parcel_id with county_sql.
    """
    try:
        return await geocoder.geocode(address=address, parcel_id=parcel_id, limit=limit)
    except GeocodeError as e:
        return _err("geocode_error", str(e))


def _source(layer) -> dict[str, Any]:
    return {
        "dataset": layer.title,
        "publisher": layer.publisher,
        "source_page": layer.source_page,
        "note": "Cite the dataset title and publisher when using these results.",
    }


# ── Landing page & health ───────────────────────────────────────────────────


@server.custom_route("/", methods=["GET"])
async def landing(_request: Request) -> HTMLResponse:
    return HTMLResponse(landing_page.render(catalog, county, PUBLIC_URL))


@server.custom_route("/static/{name}", methods=["GET"])
async def static(request: Request) -> Response:
    path = landing_page.STATIC_FILES.get(request.path_params["name"])
    if path is None:
        return Response(status_code=404)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


@server.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "version": VERSION, "datasets": len(catalog), "county_db": county.available, "geocoder": geocoder.available})


@server.custom_route("/datasets.json", methods=["GET"])
async def datasets_json(_request: Request) -> JSONResponse:
    return JSONResponse(json.loads(json.dumps(await list_datasets())))


# ── ASGI app ─────────────────────────────────────────────────────────────────

# DNS-rebinding protection is for servers bound to localhost; this one is
# public and read-only. Set OPENDAYTON_ALLOWED_HOSTS to re-enable it.
_allowed_hosts = [h for h in os.environ.get("OPENDAYTON_ALLOWED_HOSTS", "").split(",") if h]
_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=bool(_allowed_hosts),
    allowed_hosts=_allowed_hosts,
    allowed_origins=[],
)

app = server.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    transport_security=_security,
)
