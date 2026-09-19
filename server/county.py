"""Read-only SQL over county.duckdb.

The database is opened read-only with external access disabled, so the
engine itself refuses file reads, ATTACH, INSTALL, and COPY. On top of that
the query must parse as exactly one SELECT, gets wrapped in a row cap, and is
interrupted if it runs past the time budget. Schema documentation comes from
datasets/county.yaml — the build guarantees the database matches it.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from decimal import Decimal
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COUNTY_YAML = REPO_ROOT / "datasets" / "county.yaml"
DEFAULT_DB = Path(os.environ.get("OPENDAYTON_COUNTY_DB", REPO_ROOT / "county" / "county.duckdb"))

DEFAULT_LIMIT = 200
MAX_LIMIT = 2000
QUERY_TIMEOUT_SECONDS = 30
MAX_SQL_LENGTH = 6000

_LEADING_RE = re.compile(r"^\s*(WITH|SELECT|FROM)\b", re.IGNORECASE)


class CountySQLError(ValueError):
    pass


@dataclass
class CountySchema:
    publisher: str
    source_page: str
    public_via: str
    description: str
    join_keys: list[str]
    tables: dict[str, dict[str, Any]]  # name -> {description, columns: {col: desc}}
    caveats: list[str]
    example_questions: list[str]

    @classmethod
    def load(cls, path: Path = COUNTY_YAML) -> "CountySchema":
        doc = yaml.safe_load(open(path))
        return cls(
            publisher=doc["publisher"],
            source_page=doc["source_page"],
            public_via=doc["public_via"],
            description=" ".join(doc["description"].split()),
            join_keys=list(doc.get("join_keys", [])),
            tables={
                name: {
                    "description": " ".join(spec["description"].split()),
                    "columns": {c: str(d).strip() for c, d in spec["columns"].items()},
                }
                for name, spec in doc["tables"].items()
            },
            caveats=list(doc.get("caveats", [])),
            example_questions=list(doc.get("example_questions", [])),
        )


class CountyDB:
    def __init__(self, path: Path = DEFAULT_DB):
        self.path = path
        self.schema = CountySchema.load()
        self._con: duckdb.DuckDBPyConnection | None = None
        if path.exists():
            self._con = duckdb.connect(str(path), read_only=True)
            self._con.execute("SET enable_external_access = false")
            self._con.execute("SET memory_limit = '512MB'")
            self._con.execute("SET threads = 2")
            self._con.execute("SET lock_configuration = true")

    @property
    def available(self) -> bool:
        return self._con is not None

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None

    # ── Schema ──────────────────────────────────────────────────────────────

    def meta(self) -> list[dict[str, Any]]:
        if not self._con:
            return []
        cur = self._con.cursor()
        try:
            rows = cur.execute("SELECT table_name, source_file, file_date, row_count, built_at FROM _meta ORDER BY 1").fetchall()
        finally:
            cur.close()
        return [
            {"table": r[0], "source_file": r[1], "file_date": _json(r[2]), "row_count": r[3], "built_at": _json(r[4])}
            for r in rows
        ]

    def describe(self, table: str | None = None) -> dict[str, Any]:
        s = self.schema
        if table is not None and table not in s.tables:
            raise CountySQLError(f"unknown table '{table}'. Tables: {', '.join(s.tables)}")
        types: dict[str, dict[str, str]] = {}
        if self._con:
            cur = self._con.cursor()
            try:
                for t in ([table] if table else s.tables):
                    types[t] = {r[0]: r[1] for r in cur.execute(f"DESCRIBE {t}").fetchall()}
            finally:
                cur.close()
        meta = {m["table"]: m for m in self.meta()}

        def table_doc(name: str) -> dict[str, Any]:
            spec = s.tables[name]
            return {
                "table": name,
                "description": spec["description"],
                "rows": meta.get(name, {}).get("row_count"),
                "as_of": meta.get(name, {}).get("file_date"),
                "columns": [
                    {"name": c, "type": types.get(name, {}).get(c), "description": d}
                    for c, d in spec["columns"].items()
                ],
            }

        if table:
            return {"database": "county.duckdb", "available": self.available, **table_doc(table)}
        return {
            "database": "county.duckdb",
            "available": self.available,
            "publisher": s.publisher,
            "public_via": s.public_via,
            "source_page": s.source_page,
            "description": s.description,
            "join_keys": s.join_keys,
            "tables": [
                {"table": n, "description": spec["description"], "rows": meta.get(n, {}).get("row_count"),
                 "as_of": meta.get(n, {}).get("file_date"), "columns": list(spec["columns"])}
                for n, spec in s.tables.items()
            ],
            "caveats": s.caveats,
            "example_questions": s.example_questions,
            "dialect": "DuckDB SQL (PostgreSQL-like). Call county_schema(table) for column descriptions.",
        }

    # ── Query ───────────────────────────────────────────────────────────────

    def validate(self, sql: str) -> str:
        if not self._con:
            raise CountySQLError("county database is not available on this server")
        sql = (sql or "").strip().rstrip(";").strip()
        if not sql:
            raise CountySQLError("sql is empty")
        if len(sql) > MAX_SQL_LENGTH:
            raise CountySQLError(f"sql is too long ({len(sql)} chars; max {MAX_SQL_LENGTH})")
        if not _LEADING_RE.match(sql):
            raise CountySQLError("only SELECT queries are allowed (start with SELECT, WITH, or FROM)")
        try:
            statements = self._con.extract_statements(sql)
        except duckdb.Error as e:
            raise CountySQLError(f"SQL parse error: {e}") from e
        if len(statements) != 1:
            raise CountySQLError("exactly one statement is allowed")
        if statements[0].type != duckdb.StatementType.SELECT:
            raise CountySQLError(f"only SELECT statements are allowed (got {statements[0].type.name})")
        return sql

    def query(self, sql: str, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
        sql = self.validate(sql)
        limit = max(1, min(int(limit), MAX_LIMIT))
        wrapped = f"SELECT * FROM ({sql}) AS q LIMIT {limit + 1}"
        assert self._con is not None
        cur = self._con.cursor()
        timer = threading.Timer(QUERY_TIMEOUT_SECONDS, cur.interrupt)
        timer.start()
        try:
            result = cur.execute(wrapped)
            columns = [d[0] for d in result.description]
            rows = result.fetchall()
        except duckdb.InterruptException as e:
            raise CountySQLError(f"query exceeded {QUERY_TIMEOUT_SECONDS}s and was cancelled; add filters or aggregate") from e
        except duckdb.Error as e:
            raise CountySQLError(f"SQL error: {_clean_error(str(e))}") from e
        finally:
            timer.cancel()
            cur.close()
        truncated = len(rows) > limit
        rows = rows[:limit]
        return {
            "sql": sql,
            "columns": columns,
            "count_returned": len(rows),
            "truncated": truncated,
            "rows": [dict(zip(columns, (_json(v) for v in r))) for r in rows],
        }


def _json(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v) if v != v.to_integral_value() else int(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _clean_error(msg: str) -> str:
    # DuckDB errors include a caret-marked copy of the query; keep the first line and any candidate hints.
    lines = [l for l in msg.splitlines() if l.strip() and not l.strip().startswith("^") and "LINE " not in l]
    return " ".join(lines[:3])
