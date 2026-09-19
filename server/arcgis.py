"""Read-only ArcGIS REST client for curated layers.

Three operations: schema (cached), row query, and statistics (group-by
aggregates). Every operation takes a Layer from the catalog and applies its
field allowlist and base_where. Results are cleaned: only allowlisted fields
are returned, epoch-millisecond dates become ISO strings, coded values are
decoded where the service publishes a domain.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from .catalog import Layer
from .where import WhereError, validate_field_list, validate_order_by, validate_where

USER_AGENT = "OpenDayton MCP (https://github.com/codefordayton/opendayton)"
DEFAULT_LIMIT = 100
MAX_LIMIT = 2000
STATS_MAX_LIMIT = 500
SCHEMA_TTL_SECONDS = 3600
RETRIES = 3

STAT_TYPES = {"count", "sum", "min", "max", "avg", "stddev", "var"}


class ArcGISError(RuntimeError):
    pass


@dataclass
class FieldInfo:
    name: str
    type: str  # e.g. "String", "Integer", "Date"
    alias: str | None = None
    domain: dict[Any, str] | None = None  # code -> label


@dataclass
class Schema:
    layer_id: str
    name: str
    geometry_type: str | None
    fields: dict[str, FieldInfo]  # only allowlisted fields
    missing_fields: list[str]  # allowlisted names not on the live service
    max_record_count: int | None
    supports_statistics: bool
    last_edit: str | None
    fetched_at: float = field(default_factory=time.time)

    @property
    def date_fields(self) -> set[str]:
        return {n for n, f in self.fields.items() if f.type in ("Date", "DateOnly")}


class ArcGISClient:
    def __init__(self, timeout: float = 60.0):
        self._http = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        self._schemas: dict[str, Schema] = {}
        self._schema_locks: dict[str, asyncio.Lock] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── HTTP ────────────────────────────────────────────────────────────────

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        params = {**params, "f": "json"}
        last_exc: Exception | None = None
        for attempt in range(RETRIES):
            try:
                resp = await self._http.get(url, params=params)
                if resp.status_code >= 500:
                    raise ArcGISError(f"HTTP {resp.status_code} from {url}")
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict) and "error" in data:
                    err = data["error"]
                    details = "; ".join(err.get("details") or [])
                    msg = f"ArcGIS error {err.get('code')}: {err.get('message')}"
                    if details:
                        msg += f" ({details})"
                    # Bad where clauses etc. are not retryable.
                    raise ArcGISError(msg)
                return data
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = ArcGISError(f"network error talking to {url}: {exc}")
            except ArcGISError as exc:
                if "HTTP 5" not in str(exc):
                    raise
                last_exc = exc
            await asyncio.sleep(0.5 * (2**attempt))
        raise last_exc or ArcGISError(f"failed to fetch {url}")

    # ── Schema ──────────────────────────────────────────────────────────────

    async def schema(self, layer: Layer) -> Schema:
        cached = self._schemas.get(layer.id)
        if cached and time.time() - cached.fetched_at < SCHEMA_TTL_SECONDS:
            return cached
        lock = self._schema_locks.setdefault(layer.id, asyncio.Lock())
        async with lock:
            cached = self._schemas.get(layer.id)
            if cached and time.time() - cached.fetched_at < SCHEMA_TTL_SECONDS:
                return cached
            meta = await self._get_json(layer.url, {})
            live = {}
            for f in meta.get("fields", []) or []:
                dom = f.get("domain")
                domain = None
                if dom and dom.get("type") == "codedValue":
                    domain = {cv["code"]: cv["name"] for cv in dom.get("codedValues", [])}
                live[f["name"]] = FieldInfo(
                    name=f["name"],
                    type=str(f.get("type", "")).replace("esriFieldType", ""),
                    alias=f.get("alias"),
                    domain=domain,
                )
            fields = {n: live[n] for n in layer.fields if n in live}
            missing = [n for n in layer.fields if n not in live]
            edit_info = meta.get("editingInfo") or {}
            last_edit_ms = edit_info.get("lastEditDate")
            schema = Schema(
                layer_id=layer.id,
                name=meta.get("name", ""),
                geometry_type=meta.get("geometryType"),
                fields=fields,
                missing_fields=missing,
                max_record_count=meta.get("maxRecordCount"),
                supports_statistics=bool(
                    (meta.get("advancedQueryCapabilities") or {}).get("supportsStatistics", False)
                ),
                last_edit=_ms_to_iso(last_edit_ms) if last_edit_ms else None,
            )
            self._schemas[layer.id] = schema
            return schema

    async def count(self, layer: Layer, where: str = "1=1") -> int:
        data = await self._get_json(
            f"{layer.url}/query",
            {"where": self._full_where(layer, where), "returnCountOnly": "true"},
        )
        return int(data.get("count", 0))

    # ── Query ───────────────────────────────────────────────────────────────

    async def query(
        self,
        layer: Layer,
        *,
        where: str | None = None,
        out_fields: list[str] | str | None = None,
        order_by: str | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        near: tuple[float, float, float] | None = None,  # (lat, lon, meters)
        include_location: bool = False,
    ) -> dict[str, Any]:
        schema = await self.schema(layer)
        where_sql = validate_where(where, layer)
        fields = validate_field_list(out_fields, layer, what="out_fields") or list(schema.fields)
        order_sql = validate_order_by(order_by, layer)
        limit = max(1, min(int(limit), MAX_LIMIT))

        params: dict[str, Any] = {
            "where": self._full_where(layer, where_sql),
            "outFields": ",".join(fields),
            "resultRecordCount": limit,
            "resultOffset": max(0, int(offset)),
            "returnGeometry": "false",
        }
        if order_sql:
            params["orderByFields"] = order_sql
        if near is not None:
            self._apply_near(params, layer, near)
        want_geometry = include_location and layer.geometry in ("point", "polygon")
        if want_geometry:
            params["returnGeometry"] = "true"
            params["outSR"] = 4326
            if layer.geometry == "polygon":
                params["returnCentroid"] = "true"
                params["returnGeometry"] = "false"

        data = await self._get_json(f"{layer.url}/query", params)
        rows = []
        for feat in data.get("features", []) or []:
            row = self._clean_row(feat.get("attributes", {}) or {}, schema, fields)
            if want_geometry:
                loc = _extract_location(feat, layer.geometry)
                if loc:
                    row["latitude"], row["longitude"] = loc
            rows.append(row)
        return {
            "dataset": layer.id,
            "where": where_sql,
            "count_returned": len(rows),
            "limit": limit,
            "offset": offset,
            "exceeded_limit": bool(data.get("exceededTransferLimit")) or len(rows) >= limit,
            "rows": rows,
        }

    # ── Statistics ──────────────────────────────────────────────────────────

    async def stats(
        self,
        layer: Layer,
        *,
        group_by: list[str] | str | None = None,
        stat_type: str = "count",
        stat_field: str | None = None,
        where: str | None = None,
        order_by: str | None = None,
        limit: int = STATS_MAX_LIMIT,
        near: tuple[float, float, float] | None = None,
    ) -> dict[str, Any]:
        schema = await self.schema(layer)
        if not schema.supports_statistics:
            raise ArcGISError(f"dataset '{layer.id}' does not support server-side statistics")
        stat_type = (stat_type or "count").lower()
        if stat_type not in STAT_TYPES:
            raise WhereError(f"stat_type must be one of {sorted(STAT_TYPES)}")
        groups = validate_field_list(group_by, layer, what="group_by")
        if stat_type == "count":
            on_field = groups[0] if groups else next(iter(schema.fields))
            alias = "count"
            if stat_field:
                on_field = validate_field_list([stat_field], layer, what="stat_field")[0]
        else:
            if not stat_field:
                raise WhereError(f"stat_field is required for stat_type '{stat_type}'")
            on_field = validate_field_list([stat_field], layer, what="stat_field")[0]
            alias = f"{stat_type}_{on_field}"
        where_sql = validate_where(where, layer)
        order_sql = validate_order_by(order_by, layer, extra_allowed={alias})
        limit = max(1, min(int(limit), STATS_MAX_LIMIT))

        params: dict[str, Any] = {
            "where": self._full_where(layer, where_sql),
            "outStatistics": json.dumps(
                [{"statisticType": stat_type, "onStatisticField": on_field, "outStatisticFieldName": alias}]
            ),
            "returnGeometry": "false",
            "resultRecordCount": limit,
        }
        if groups:
            params["groupByFieldsForStatistics"] = ",".join(groups)
        params["orderByFields"] = order_sql or (f"{alias} DESC" if groups else alias)
        if near is not None:
            self._apply_near(params, layer, near)

        data = await self._get_json(f"{layer.url}/query", params)
        rows = []
        for feat in data.get("features", []) or []:
            attrs = feat.get("attributes", {}) or {}
            row = self._clean_row(attrs, schema, groups)
            row[alias] = attrs.get(alias)
            rows.append(row)
        return {
            "dataset": layer.id,
            "where": where_sql,
            "group_by": groups,
            "statistic": {"type": stat_type, "field": on_field, "as": alias},
            "count_returned": len(rows),
            "truncated": len(rows) >= limit,
            "rows": rows,
        }

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _full_where(layer: Layer, where_sql: str) -> str:
        if layer.base_where:
            return f"({layer.base_where}) AND ({where_sql})"
        return where_sql

    @staticmethod
    def _apply_near(params: dict[str, Any], layer: Layer, near: tuple[float, float, float]) -> None:
        if layer.geometry == "table":
            raise WhereError(f"dataset '{layer.id}' has no geometry; `near` cannot be used")
        lat, lon, meters = near
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise WhereError("near: latitude/longitude out of range")
        meters = max(1.0, min(float(meters), 10_000.0))
        params.update(
            {
                "geometry": f"{lon},{lat}",
                "geometryType": "esriGeometryPoint",
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "distance": meters,
                "units": "esriSRUnit_Meter",
            }
        )

    @staticmethod
    def _clean_row(attrs: dict[str, Any], schema: Schema, fields: list[str]) -> dict[str, Any]:
        row: dict[str, Any] = {}
        for name in fields:
            if name not in attrs:
                continue
            value = attrs[name]
            info = schema.fields.get(name)
            # Dates become ISO strings. Coded values stay raw so the model can
            # reuse them in the next where clause; describe_dataset shows labels.
            if (
                info is not None
                and value is not None
                and info.type in ("Date", "DateOnly")
                and isinstance(value, (int, float))
            ):
                value = _ms_to_iso(value, date_only=info.type == "DateOnly")
            if isinstance(value, str):
                value = value.strip()
            row[name] = value
        return row


def _ms_to_iso(ms: float, *, date_only: bool = False) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.date().isoformat() if date_only else dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_location(feat: dict[str, Any], geometry: str) -> tuple[float, float] | None:
    if geometry == "point":
        g = feat.get("geometry") or {}
        if "x" in g and "y" in g:
            return round(g["y"], 6), round(g["x"], 6)
    if geometry == "polygon":
        c = feat.get("centroid") or {}
        if "x" in c and "y" in c:
            return round(c["y"], 6), round(c["x"], 6)
    return None
