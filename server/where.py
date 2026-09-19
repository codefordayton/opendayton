"""Allowlist validator for ArcGIS `where` clauses.

The model writes SQL-ish where clauses; ArcGIS evaluates them. Rather than
block bad keywords, this tokenizes the clause and only lets through:

  * field names on the layer's allowlist (rewritten to canonical spelling),
  * string / numeric literals and DATE / TIMESTAMP literals,
  * a fixed set of comparison and boolean operators and functions.

Anything else is rejected with a message that names the allowed fields, which
is the feedback the model needs to fix its query.
"""

from __future__ import annotations

import re

from .catalog import Layer

MAX_WHERE_LENGTH = 1500

# Keywords and functions that may appear as bare identifiers.
KEYWORDS = {
    "AND", "OR", "NOT", "IN", "IS", "NULL", "LIKE", "BETWEEN",
    "DATE", "TIMESTAMP", "CURRENT_DATE", "CURRENT_TIMESTAMP",
    "INTERVAL", "FROM", "TRUE", "FALSE",
}
# Only valid directly after `INTERVAL '<n>'` or `EXTRACT(`; otherwise they look
# like (and would be mistaken for) field names.
UNIT_KEYWORDS = {"DAY", "MONTH", "YEAR", "HOUR", "MINUTE", "SECOND"}
FUNCTIONS = {"UPPER", "LOWER", "EXTRACT"}

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<string>'(?:[^']|'')*')
  | (?P<number>-?\d+(?:\.\d+)?)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op><>|!=|<=|>=|=|<|>|\(|\)|,|\+|-)
  | (?P<bad>.)
    """,
    re.VERBOSE,
)


class WhereError(ValueError):
    pass


def validate_where(where: str | None, layer: Layer) -> str:
    """Return a validated where clause, or raise WhereError.

    Empty input becomes "1=1". Field names are rewritten to their canonical
    (allowlisted) spelling so downstream code can rely on exact matches.
    """
    if where is None or not where.strip():
        return "1=1"
    where = where.strip()
    if len(where) > MAX_WHERE_LENGTH:
        raise WhereError(f"where clause is too long ({len(where)} chars; max {MAX_WHERE_LENGTH})")
    if "--" in where or "/*" in where or ";" in where:
        raise WhereError("where clause may not contain comments or statement separators")
    if where == "1=1":
        return where

    out: list[str] = []
    sig: list[tuple[str, str]] = []  # significant (kind, text) tokens, for context checks
    depth = 0
    for m in _TOKEN_RE.finditer(where):
        kind = m.lastgroup
        text = m.group()
        if kind == "ws":
            out.append(" ")
            continue
        if kind == "string" or kind == "number":
            out.append(text)
        elif kind == "op":
            if text == "(":
                depth += 1
            elif text == ")":
                depth -= 1
                if depth < 0:
                    raise WhereError("unbalanced parentheses in where clause")
            out.append(text)
        elif kind == "ident":
            # Field names win over keywords: layers commonly have YEAR / MONTH /
            # DAY columns that collide with INTERVAL units, and a field must be
            # checked against the allowlist, never waved through as a keyword.
            canonical = layer.canonical_field(text)
            if canonical is not None:
                out.append(canonical)
                sig.append(("field", canonical))
                continue
            upper = text.upper()
            if upper in UNIT_KEYWORDS and _unit_context_ok(sig):
                out.append(upper)
            elif upper in KEYWORDS or upper in FUNCTIONS:
                out.append(upper)
            else:
                raise WhereError(
                    f"'{text}' is not a queryable field on dataset '{layer.id}'. "
                    f"Allowed fields: {', '.join(layer.field_names)}"
                )
            text = upper
        else:  # bad
            raise WhereError(
                f"unsupported character {text!r} in where clause. "
                "Use field comparisons, AND/OR/NOT, IN, LIKE, BETWEEN, IS NULL, "
                "and DATE 'YYYY-MM-DD' literals."
            )
        sig.append((kind, text))
    if depth != 0:
        raise WhereError("unbalanced parentheses in where clause")

    result = "".join(out).strip()
    if not result:
        return "1=1"
    return result


def _unit_context_ok(sig: list[tuple[str, str]]) -> bool:
    """True if a DAY/MONTH/YEAR unit word is in a legitimate position."""
    if len(sig) >= 2 and sig[-1][0] == "string" and sig[-2] == ("ident", "INTERVAL"):
        return True  # INTERVAL '30' DAY
    if len(sig) >= 2 and sig[-1] == ("op", "(") and sig[-2] == ("ident", "EXTRACT"):
        return True  # EXTRACT(YEAR FROM field)
    return False


def validate_field_list(names: list[str] | str | None, layer: Layer, *, what: str) -> list[str]:
    """Validate a list of field names (or a comma-separated string) against the allowlist."""
    if names is None:
        return []
    if isinstance(names, str):
        names = [n for n in (p.strip() for p in names.split(",")) if n]
    result: list[str] = []
    for n in names:
        canonical = layer.canonical_field(n)
        if canonical is None:
            raise WhereError(
                f"{what}: '{n}' is not a queryable field on dataset '{layer.id}'. "
                f"Allowed fields: {', '.join(layer.field_names)}"
            )
        if canonical not in result:
            result.append(canonical)
    return result


_ORDER_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(ASC|DESC)?\s*$", re.IGNORECASE)


def validate_order_by(
    order_by: str | None, layer: Layer, *, extra_allowed: set[str] | None = None
) -> str | None:
    """Validate `FIELD [ASC|DESC], FIELD [ASC|DESC]` against the allowlist.

    `extra_allowed` lets statistics queries order by their output aliases
    (e.g. `count DESC`).
    """
    if not order_by or not order_by.strip():
        return None
    extra = {e.lower(): e for e in (extra_allowed or set())}
    parts = []
    for piece in order_by.split(","):
        m = _ORDER_RE.match(piece)
        if not m:
            raise WhereError(f"order_by must look like 'FIELD ASC, OTHER DESC'; got {piece.strip()!r}")
        name = m.group(1)
        canonical = layer.canonical_field(name) or extra.get(name.lower())
        if canonical is None:
            allowed = layer.field_names + sorted(extra.values())
            raise WhereError(
                f"order_by: '{name}' is not a queryable field on dataset '{layer.id}'. "
                f"Allowed: {', '.join(allowed)}"
            )
        parts.append(f"{canonical} {(m.group(2) or 'ASC').upper()}")
    return ", ".join(parts)
