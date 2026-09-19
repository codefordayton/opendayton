#!/usr/bin/env python3
"""Build county.duckdb from the Montgomery County Auditor/Treasurer bulk files.

The County publishes its tax roll, sales, delinquency, and CAMA (assessment)
extracts as plain ZIP downloads with record layouts in PDFs — public, but not
queryable. This script turns the newest of each into one DuckDB file with
typed columns and readable names, so the `county_sql` tool can answer questions
over them.

    uv run python -m county.build                # discover, download, build
    uv run python -m county.build --offline      # use what's already in county/downloads
    uv run python -m county.build --include-pii  # keep owner names & mailing addresses

Privacy policy (default build): owner names, mailing names, mailing street
addresses, and mortgage codes are DROPPED from every table. Parcel IDs, the
property's own address, values, flags, tract, and the owner's mailing *city*
(the absentee-ownership signal) are kept. `--include-pii` exists for the
housing subcommittee's private build and is never what gets deployed.

Sources: https://go.mcohio.org/applications/treasurer/search/filedownloads.cfm
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import sys
import time
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import httpx
import yaml

from .cama import read_rows as cama_read_rows

HERE = Path(__file__).resolve().parent
DOWNLOADS = HERE / "downloads"
EXTRACT = DOWNLOADS / "extract"
DEFAULT_OUT = HERE / "county.duckdb"
CAMA_SPEC = HERE / "cama_spec.json"
COUNTY_YAML = HERE.parent / "datasets" / "county.yaml"

BASE = "https://go.mcohio.org/applications/treasurer/search/"
LISTING = BASE + "fdpopup.cfm?dtype={code}"
USER_AGENT = "OpenDayton county build (https://github.com/codefordayton/opendayton)"

# Listing pages are legacy ColdFusion: unquoted, backslash-separated hrefs.
_ANCHOR = re.compile(
    r"<a\s[^>]*?href\s*=\s*(?P<href>\"[^\"]*\"|'[^']*'|[^\s>]+)[^>]*>(?P<label>.*?)</a>",
    re.S | re.I,
)
_FILE_EXT = re.compile(r"\.(zip|htm|html)$", re.I)

# CAMA tables we load, and the .DAT file each comes from.
CAMA_TABLES = {
    "PARDAT": "PARDAT.DAT",
    "DWELDAT": "DWELL.DAT",
    "PERMIT": "PERMIT.DAT",
    "COMAPT": "COMAPT.DAT",
}
CAMA_CODE_FILES = ["GRADE", "EXTWALL", "HEAT", "BSMT", "ATTIC", "SHFACT", "NBHD"]

# Columns dropped unless --include-pii. Matched case-insensitively after
# header cleanup, against every CSV-derived table.
PII_COLUMNS = {
    "OWNERNAME1", "OWNERNAME2", "OWNERNAME 1", "OWNERNAME 2",
    "MAILINGNAME1", "MAILINGNAME2", "PADDR1", "PADDR2", "MORTCO", "OLDOWN",
    "NAME", "ADDR1", "ADDR2", "ADDR3",
}


# ── Discovery & download ────────────────────────────────────────────────────


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def parse_listing(page: str) -> list[dict]:
    files = []
    for m in _ANCHOR.finditer(page):
        href = html.unescape(m.group("href")).strip("\"'")
        if not _FILE_EXT.search(href):
            continue
        files.append({"label": _clean_text(m.group("label")), "url": BASE + href.replace("\\", "/")})
    return files


def _date_key(url: str) -> str:
    """Sort key: the YYYYMMDD or YYYY embedded in the filename."""
    m = re.search(r"(\d{8})", url) or re.search(r"(\d{4})", url)
    return m.group(1) if m else ""


def discover(client: httpx.Client) -> dict[str, list[str]]:
    """Return the download URLs to use: newest TR/DQ/CC/NC, every YS year."""
    chosen: dict[str, list[str]] = {}
    for code in ["TR", "DQ", "CC", "NC", "YS"]:
        page = client.get(LISTING.format(code=code)).text
        files = parse_listing(page)
        if code == "NC":
            files = [f for f in files if f["url"].lower().endswith((".htm", ".html"))]
        else:
            files = [f for f in files if f["url"].lower().endswith(".zip")]
        if not files:
            raise SystemExit(f"no files found in listing for {code}")
        files.sort(key=lambda f: _date_key(f["url"]))
        chosen[code] = [f["url"] for f in files] if code == "YS" else [files[-1]["url"]]
        print(f"  {code}: {len(files)} listed; using {len(chosen[code])} (newest {files[-1]['label']})")
    return chosen


def download(client: httpx.Client, url: str) -> Path:
    dest = DOWNLOADS / url.rsplit("/", 1)[-1]
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    print(f"  downloading {dest.name} …", end="", flush=True)
    with client.stream("GET", url) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    print(f" {dest.stat().st_size / 1e6:.1f} MB")
    return dest


def offline_files() -> dict[str, list[str]]:
    """Pick the newest local file per type when running --offline."""
    pick: dict[str, list[str]] = {}
    for code, pattern in [("TR", "TAXROLL_*.zip"), ("DQ", "Delq_*.zip"), ("CC", "Cama_Files_*.zip"), ("NC", "neighborhood_codes_*.htm")]:
        found = sorted(DOWNLOADS.glob(pattern), key=lambda p: _date_key(p.name))
        if not found:
            raise SystemExit(f"--offline: no {pattern} in {DOWNLOADS}")
        pick[code] = [str(found[-1])]
    pick["YS"] = [str(p) for p in sorted(DOWNLOADS.glob("SALES_*.zip"))]
    return pick


# ── Extraction ──────────────────────────────────────────────────────────────


def _zip_members(zpath: Path) -> dict[str, str]:
    """basename -> member name (zips were made on Windows; paths use backslashes)."""
    with zipfile.ZipFile(zpath) as z:
        return {n.replace("\\", "/").rsplit("/", 1)[-1]: n for n in z.namelist() if not n.endswith(("/", "\\"))}


def extract_members(zpath: Path, wanted: list[str] | None, dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    members = _zip_members(zpath)
    with zipfile.ZipFile(zpath) as z:
        for base, member in members.items():
            if wanted is not None and base not in wanted:
                continue
            target = dest / base
            if not target.exists() or target.stat().st_size == 0:
                if base.lower().endswith(".csv"):
                    with z.open(member) as src:
                        _normalize_csv(src, target)
                else:
                    with z.open(member) as src, open(target, "wb") as dst:
                        while chunk := src.read(1 << 20):
                            dst.write(chunk)
            out.append(target)
    return out


def _normalize_csv(src, target: Path) -> None:
    """Rewrite a County CSV as clean UTF-8 with one row per record.

    The County files are Windows-1252 and some (the delinquent file) carry
    report-style continuation lines — an owner-name fragment alone on a line.
    Rows whose field count doesn't match the header are dropped and counted.
    Header names are stripped of the padding the County adds.
    """
    text = io.TextIOWrapper(src, encoding="cp1252", errors="replace", newline="")
    reader = csv.reader(text)
    header = [h.strip() for h in next(reader)]
    kept = dropped = 0
    with open(target, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(header)
        for row in reader:
            if len(row) != len(header):
                dropped += 1
                continue
            writer.writerow([v.strip() for v in row])
            kept += 1
    if dropped:
        print(f"    {target.name}: kept {kept:,} rows, dropped {dropped:,} malformed continuation lines")


# ── Helpers for the SQL side ────────────────────────────────────────────────


def clean_header(name: str) -> str:
    """'PARCELLOCATION   ' -> parcellocation ; 'SQ. FT.' -> sq_ft ; 'CITY/TOWNSHIP' -> city_township."""
    n = name.strip().lower()
    n = re.sub(r"[^a-z0-9]+", "_", n).strip("_")
    return n


_HALF = {
    "chg": "charge", "red": "reduction", "adj": "adjusted_charge", "rlbk": "rollback",
    "hmsd": "homestead_reduction", "hmrb": "homestead_rollback", "pen": "penalty",
    "spasmts": "special_assessments", "amtdue": "amount_due", "daycrdt": "dayton_credit",
    "delq": "delinquent",
}
TAXROLL_RENAMES = {
    "txyr": "tax_year", "parcelid": "parcel_id", "parcellocation": "parcel_location",
    "txdst": "tax_district", "cls": "class", "cityname": "mailing_city",
    "fullyramtdue": "full_year_amount_due", "netdelq": "net_delinquent",
    "agland": "cauv_land_value", "asmtland": "appraised_land", "asmtbldg": "appraised_bldg",
    "asmttotal": "appraised_total", "taxableland": "taxable_land", "taxablebldg": "taxable_bldg",
    "taxabletotal": "taxable_total", "publicutility": "public_utility_value", "rolltype": "roll_type",
    "hmsdland": "homestead_land", "hmsdbldg": "homestead_bldg",
    "frclsr": "foreclosure_date", "foreclosure": "foreclosure_date",
    "salesdte": "sale_date", "price": "sale_price", "yrbl": "year_built",
    "grossrate": "gross_tax_rate", "effrate": "effective_tax_rate", "redrate": "reduction_factor",
    "duedate": "due_date", "b": "bill_half", "rentalreg": "rental_registered",
    "aetasmtland": "abated_appraised_land", "aetasmtbldg": "abated_appraised_bldg",
    "aetasmttotal": "abated_appraised_total", "aettaxableland": "abated_taxable_land",
    "aettaxablebldg": "abated_taxable_bldg", "aettaxabletotal": "abated_taxable_total",
    "casmtland": "cauv_appraised_land", "ctaxableland": "cauv_taxable_land",
    "hmsdflag": "homestead", "sq_ft": "sq_ft", "dytncrdt": "dayton_credit",
    "ownocc": "owner_occupied", "parcel_location_zip": "parcel_zip",
    "ac": "appeal_code", "appealcode": "appeal_code", "asmtwen": "asmt_updated",
    "certdlqyr": "certified_delinquent_year",
}
for _h in ("hlf1", "hlf2"):
    for _k, _v in _HALF.items():
        TAXROLL_RENAMES[f"{_h}{_k}"] = f"{_h}_{_v}"

SALES_RENAMES = {
    "parid": "parcel_id", "convnum": "conveyance_number", "saledte": "sale_date",
    "saledt": "sale_date", "price": "sale_price", "parcellocation": "parcel_location",
    "paddr3": "mailing_city_state", "cls": "class", "taxland": "taxable_land",
    "taxbldg": "taxable_bldg", "taxtotal": "taxable_total", "taxableland": "taxable_land",
    "taxablebldg": "taxable_bldg", "taxabletotal": "taxable_total",
    "asmtland": "appraised_land", "asmtbldg": "appraised_bldg", "asmttotl": "appraised_total",
    "asmttotal": "appraised_total", "salevalidity": "sale_validity", "saletype": "sale_type",
    "dytncrdt": "dayton_credit", "deedreference": "deed_reference",
}

DATE_COLS = {"foreclosure_date", "sale_date", "due_date", "asmt_updated"}
INT_COLS = {"tax_year", "year_built", "certified_delinquent_year", "conveyance_number", "sq_ft"}
_MONEY_WORDS = ("charge", "reduction", "rollback", "penalty", "assessments", "amount_due",
                "delinquent", "credit", "value", "appraised", "taxable", "homestead_land",
                "homestead_bldg", "sale_price", "refund")
# Columns that exist only to carry a file-level attribute into extra_select.
HELPER_COLS = {"filename"}
# PADDR3 is the mailing city/state/zip line; keep it on sales (as mailing_city_state)
# but the tax roll already has CITYNAME, so drop it there.
DROP_PER_TABLE = {"taxroll": {"paddr3", "school_district"}, "delinquent": {"paddr3", "school_district"}}


# Y/N flags whose names would otherwise trip the money-word heuristic.
FLAG_COLS = {"dayton_credit", "owner_occupied", "homestead", "rental_registered"}


def is_money(name: str) -> bool:
    return any(w in name for w in _MONEY_WORDS) and name not in INT_COLS and name not in FLAG_COLS


MC_DATE_MACRO = """
CREATE OR REPLACE MACRO mc_date(s) AS (
  -- County dates are 'DD-MON-YY' (sometimes 'MM/DD/YYYY'). DuckDB pivots
  -- two-digit years 00-68 to 20xx; anything more than a year in the future is
  -- really 19xx (permits go back to 1960).
  CASE WHEN s IS NULL OR trim(s) = '' THEN NULL
       WHEN coalesce(try_strptime(trim(s), '%d-%b-%y'), try_strptime(trim(s), '%m/%d/%Y')) IS NULL THEN NULL
       WHEN coalesce(try_strptime(trim(s), '%d-%b-%y'), try_strptime(trim(s), '%m/%d/%Y'))::DATE > current_date + INTERVAL 1 YEAR
            THEN (coalesce(try_strptime(trim(s), '%d-%b-%y'), try_strptime(trim(s), '%m/%d/%Y')) - INTERVAL 100 YEAR)::DATE
       ELSE coalesce(try_strptime(trim(s), '%d-%b-%y'), try_strptime(trim(s), '%m/%d/%Y'))::DATE END
)
"""


def mc_date_sql(col: str) -> str:
    return f"mc_date({col})"


def build_select(con: duckdb.DuckDBPyConnection, raw_table: str, renames: dict[str, str], *, include_pii: bool, table_name: str = "") -> tuple[str, list[str]]:
    """Build a SELECT that cleans, renames, types, and (optionally) drops PII from a raw all-varchar table."""
    cols = [r[0] for r in con.execute(f"DESCRIBE {raw_table}").fetchall()]
    exprs, out_names = [], []
    for raw in cols:
        key = clean_header(raw)
        if key in HELPER_COLS or key in DROP_PER_TABLE.get(table_name, set()):
            continue
        if not include_pii and raw.strip().upper() in PII_COLUMNS:
            continue
        name = renames.get(key, key)
        q = f'"{raw}"'
        if name in DATE_COLS:
            expr = mc_date_sql(q)
        elif name in INT_COLS:
            expr = f"try_cast(trim({q}) AS INTEGER)"
        elif name == "acres":
            expr = f"try_cast(trim({q}) AS DECIMAL(12,5))"
        elif name in ("gross_tax_rate", "effective_tax_rate", "reduction_factor"):
            expr = f"try_cast(trim({q}) AS DOUBLE)"
        elif is_money(name):
            expr = f"try_cast(trim({q}) AS DECIMAL(18,2))"
        else:
            expr = f"nullif(trim({q}), '')"
        exprs.append(f"{expr} AS {name}")
        out_names.append(name)
    return ", ".join(exprs), out_names


def load_csv_table(con, name: str, files: list[Path], renames: dict[str, str], *, include_pii: bool, extra_select: str = "") -> int:
    paths = "[" + ", ".join(f"'{p}'" for p in files) + "]"
    con.execute(f"CREATE OR REPLACE TEMP TABLE raw_{name} AS SELECT * FROM read_csv({paths}, all_varchar=true, header=true, union_by_name=true, filename=true)")
    # union_by_name on padded headers: coalesce the padded and unpadded spellings of the same column.
    cols = [r[0] for r in con.execute(f"DESCRIBE raw_{name}").fetchall()]
    groups: dict[str, list[str]] = {}
    for c in cols:
        groups.setdefault(c.strip().upper(), []).append(c)
    merged = []
    for key, variants in groups.items():
        if key == "FILENAME":
            merged.append('"filename"')
        elif len(variants) == 1:
            merged.append(f'"{variants[0]}" AS "{key}"')
        else:
            merged.append("coalesce(" + ", ".join(f'nullif(trim("{v}"), \'\')' for v in variants) + f') AS "{key}"')
    con.execute(f"CREATE OR REPLACE TEMP TABLE raw2_{name} AS SELECT {', '.join(merged)} FROM raw_{name}")
    select, _ = build_select(con, f"raw2_{name}", renames, include_pii=include_pii, table_name=name)
    con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT {select}{extra_select} FROM raw2_{name}")
    con.execute(f"DROP TABLE raw_{name}")
    con.execute(f"DROP TABLE raw2_{name}")
    return con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]


# ── CAMA ────────────────────────────────────────────────────────────────────


def cama_to_csv(spec: dict, table: str, dat: Path, out_csv: Path) -> int:
    cols = [c["column"] for c in spec[table]]
    n = 0
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for row in cama_read_rows(spec, table, str(dat)):
            w.writerow([row[c] for c in cols])
            n += 1
    return n


def load_cama_codes(con, cama_dir: Path) -> int:
    """DWELDAT lookup tables shipped as tiny .DAT files: 'DWELDAT GRADE   1A+ VERY GOOD +'."""
    rows = []
    line_re = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+(.*?)\s*$")
    for name in CAMA_CODE_FILES:
        p = cama_dir / f"{name}.DAT"
        if not p.exists():
            continue
        for line in open(p, encoding="utf-8", errors="replace"):
            m = line_re.match(line.rstrip("\r\n"))
            if not m:
                continue
            table, column, token, desc = m.groups()
            if name == "NBHD":
                code = token  # 'PARDAT NBHD 98010000 S E WASHINGTON TWP'
            else:
                code = token[1:]  # leading digit is a table number, not part of the code
            rows.append((table, column.replace("-", ""), code, desc))
    # The extract ships no lookup for the dwelling CDU (condition) column; these
    # are the standard CAMA condition codes, verified against the inventory's
    # distribution (AV 149k, FR 17k, GD 16k, VG 3.5k, PR 3k, UN 800, VP 1).
    rows += [
        ("DWELDAT", "CDU", code, desc)
        for code, desc in [("EX", "EXCELLENT"), ("VG", "VERY GOOD"), ("GD", "GOOD"), ("AV", "AVERAGE"),
                           ("FR", "FAIR"), ("PR", "POOR"), ("VP", "VERY POOR"), ("UN", "UNSOUND")]
    ]
    rows = sorted(set(rows))  # NBHD.DAT repeats codes across tax years
    con.execute("CREATE OR REPLACE TABLE cama_codes (cama_table VARCHAR, column_name VARCHAR, code VARCHAR, description VARCHAR)")
    con.executemany("INSERT INTO cama_codes VALUES (?, ?, ?, ?)", rows)
    return len(rows)


def load_cama(con, spec: dict, cama_dir: Path, *, include_pii: bool) -> dict[str, int]:
    counts = {}
    for table, fname in CAMA_TABLES.items():
        dat = cama_dir / fname
        tmp = EXTRACT / f"cama_{table}.csv"
        n = cama_to_csv(spec, table, dat, tmp)
        con.execute(f"CREATE OR REPLACE TEMP TABLE raw_{table} AS SELECT * FROM read_csv('{tmp}', all_varchar=true, header=true)")
        counts[table] = n
    # PARDAT -> cama_parcel
    con.execute("""
        CREATE OR REPLACE TABLE cama_parcel AS
        SELECT parid AS parcel_id,
               try_cast(taxyr AS INTEGER) AS tax_year,
               nullif(trim(concat_ws(' ', nullif(adrno,'0'), adrpre, adrdir, adrstr, adrsuf, adrsuf2)), '') AS address,
               nullif(cityname,'') AS city, nullif(zip1,'') AS zip,
               nullif(nbhd,'') AS nbhd, nullif(class,'') AS class, nullif(luc,'') AS luc,
               try_cast(livunit AS INTEGER) AS living_units,
               try_cast(calcacres AS DECIMAL(12,5)) AS calc_acres,
               try_cast(acres AS DECIMAL(12,5)) AS acres,
               nullif(street1,'') AS street_type, nullif(traffic,'') AS traffic,
               nullif(topo1,'') AS topography, nullif(location,'') AS location_code,
               nullif(fronting,'') AS fronting, nullif(util1,'') AS utility,
               nullif(note1,'') AS note1, nullif(note2,'') AS note2
        FROM raw_PARDAT WHERE deactivat = '' OR deactivat IS NULL
    """)
    # DWELDAT -> cama_dwelling
    con.execute(f"""
        CREATE OR REPLACE TABLE cama_dwelling AS
        SELECT parid AS parcel_id, try_cast(card AS INTEGER) AS card,
               try_cast(taxyr AS INTEGER) AS tax_year,
               try_cast(stories AS DOUBLE) AS stories,
               nullif(extwall,'') AS ext_wall_code, nullif(style,'') AS style_code,
               try_cast(yrblt AS INTEGER) AS year_built, try_cast(yrremod AS INTEGER) AS year_remodeled,
               try_cast(rmtot AS INTEGER) AS rooms, try_cast(rmbed AS INTEGER) AS bedrooms,
               try_cast(rmfam AS INTEGER) AS family_rooms,
               try_cast(fixbath AS INTEGER) AS full_baths, try_cast(fixhalf AS INTEGER) AS half_baths,
               nullif(bsmt,'') AS basement_code, nullif(heat,'') AS heat_code,
               nullif(heatsys,'') AS heat_system_code, nullif(fuel,'') AS fuel_code,
               nullif(grade,'') AS grade, nullif(cdu,'') AS condition_code,
               nullif(attic,'') AS attic_code,
               try_cast(sfla AS INTEGER) AS living_area_sqft,
               try_cast(wbfp_o AS INTEGER) AS fireplaces,
               try_cast(effyr AS INTEGER) AS effective_year,
               nullif(rectype,'') AS record_type
        FROM raw_DWELDAT
    """)
    # PERMIT -> cama_permit
    con.execute(f"""
        CREATE OR REPLACE TABLE cama_permit AS
        SELECT parid AS parcel_id, nullif(num,'') AS permit_number,
               {mc_date_sql('permdt')} AS permit_date,
               nullif(why,'') AS permit_type,
               nullif(trim(concat_ws(' ', nullif(adrno,'0'), adradd, adrdir, adrstr, adsuf, adsuf2)), '') AS address,
               try_cast(amount AS DECIMAL(14,2)) AS amount,
               nullif(flag,'') AS status_code,
               nullif(trim(concat_ws(' ', note1, note2, note3)), '') AS notes,
               {mc_date_sql('deactivat')} AS deactivated_date
        FROM raw_PERMIT
    """)
    con.execute("DELETE FROM cama_permit WHERE permit_date > current_date + INTERVAL 1 YEAR")
    # COMAPT -> cama_apartment
    con.execute("""
        CREATE OR REPLACE TABLE cama_apartment AS
        SELECT parid AS parcel_id, try_cast(card AS INTEGER) AS card,
               try_cast(taxyr AS INTEGER) AS tax_year,
               nullif(usetype,'') AS use_type_code,
               try_cast(cnt AS INTEGER) AS unit_count,
               try_cast(bed AS INTEGER) AS bedrooms, try_cast(bath AS INTEGER) AS full_baths,
               try_cast(half AS INTEGER) AS half_baths,
               try_cast(rent AS DECIMAL(12,2)) AS annual_rent_per_unit,
               try_cast(income AS DECIMAL(14,2)) AS annual_income
        FROM raw_COMAPT WHERE deactivat = '' OR deactivat IS NULL
    """)
    for table in CAMA_TABLES:
        con.execute(f"DROP TABLE raw_{table}")
    counts["codes"] = load_cama_codes(con, cama_dir)
    return counts


# ── Neighborhood codes ──────────────────────────────────────────────────────


def load_nbhd_codes(con, htm: Path) -> int:
    page = open(htm, encoding="utf-8", errors="replace").read()
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [_clean_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(cells) >= 2 and cells[0] and cells[1]:
            rows.append((cells[0], cells[1]))
    con.execute("CREATE OR REPLACE TABLE nbhd_codes (nbhd VARCHAR, description VARCHAR)")
    con.executemany("INSERT INTO nbhd_codes VALUES (?, ?)", rows)
    return len(rows)


# ── Schema conformance ──────────────────────────────────────────────────────


def conform_to_schema(con) -> None:
    """Make the database match datasets/county.yaml exactly.

    Every documented column must exist (else the build fails — fix the YAML or
    the loader). Every undocumented column is dropped, so what the model can
    see is exactly what has a written description.
    """
    doc = yaml.safe_load(open(COUNTY_YAML))
    documented = {t: list(spec["columns"]) for t, spec in doc["tables"].items()}
    live_tables = {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables() WHERE NOT internal").fetchall()}
    problems = []
    for table, cols in documented.items():
        if table not in live_tables:
            problems.append(f"documented table '{table}' was not built")
            continue
        live_cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
        for c in cols:
            if c not in live_cols:
                problems.append(f"{table}.{c} is documented but does not exist (have: {', '.join(live_cols)})")
        extra = [c for c in live_cols if c not in cols]
        for c in extra:
            con.execute(f'ALTER TABLE {table} DROP COLUMN "{c}"')
        if extra:
            print(f"  {table}: dropped {len(extra)} undocumented columns ({', '.join(extra[:8])}{'…' if len(extra) > 8 else ''})")
    for table in live_tables - set(documented):
        problems.append(f"table '{table}' exists but is not documented in county.yaml")
    if problems:
        raise SystemExit("county.yaml does not match the built database:\n  " + "\n  ".join(problems))


# ── Main ────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--offline", action="store_true", help="use files already in county/downloads")
    ap.add_argument("--include-pii", action="store_true", help="keep owner names and mailing addresses (private build)")
    args = ap.parse_args(argv)

    t0 = time.time()
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    EXTRACT.mkdir(parents=True, exist_ok=True)

    if args.offline:
        chosen = offline_files()
        local = {code: [Path(p) for p in paths] for code, paths in chosen.items()}
    else:
        print("Discovering newest files …")
        with httpx.Client(timeout=900, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            chosen = discover(client)
            print("Downloading …")
            local = {code: [download(client, u) for u in urls] for code, urls in chosen.items()}

    print("Extracting …")
    taxroll_csv = extract_members(local["TR"][0], None, EXTRACT / "taxroll")
    delq_csv = extract_members(local["DQ"][0], None, EXTRACT / "delq")
    sales_csvs = []
    for z in local["YS"]:
        sales_csvs += [p for p in extract_members(z, None, EXTRACT / "sales" / z.stem) if p.suffix.lower() == ".csv"]
    cama_dir = EXTRACT / "cama"
    extract_members(local["CC"][0], list(CAMA_TABLES.values()) + [f"{c}.DAT" for c in CAMA_CODE_FILES], cama_dir)

    if args.out.exists():
        args.out.unlink()
    con = duckdb.connect(str(args.out))
    con.execute(MC_DATE_MACRO)
    counts: dict[str, int] = {}

    print("Loading tax roll …")
    counts["taxroll"] = load_csv_table(con, "taxroll", taxroll_csv, TAXROLL_RENAMES, include_pii=args.include_pii)
    print(f"  {counts['taxroll']:,} parcels")

    print("Loading delinquent …")
    counts["delinquent"] = load_csv_table(con, "delinquent", delq_csv, TAXROLL_RENAMES, include_pii=args.include_pii)
    print(f"  {counts['delinquent']:,} rows")

    print(f"Loading sales ({len(sales_csvs)} files) …")
    counts["sales"] = load_csv_table(
        con, "sales", sales_csvs, SALES_RENAMES, include_pii=args.include_pii,
        extra_select=", regexp_extract(\"filename\", 'SALES_(\\d{4})', 1)::INTEGER AS file_year",
    )
    print(f"  {counts['sales']:,} transfers")

    print("Loading CAMA …")
    spec = json.load(open(CAMA_SPEC))
    for k, v in load_cama(con, spec, cama_dir, include_pii=args.include_pii).items():
        counts[f"cama_{k}"] = v
        print(f"  {k}: {v:,}")

    print("Loading neighborhood codes …")
    counts["nbhd_codes"] = load_nbhd_codes(con, local["NC"][0])
    print(f"  {counts['nbhd_codes']:,} codes")

    # Provenance, so every answer can say "as of the 2026-09-18 tax roll".
    con.execute("CREATE OR REPLACE TABLE _meta (table_name VARCHAR, source_file VARCHAR, file_date DATE, row_count BIGINT, built_at TIMESTAMP, pii_included BOOLEAN)")
    built_at = datetime.now(timezone.utc).replace(tzinfo=None)

    def fdate(p: Path) -> date | None:
        m = re.search(r"(\d{8})", p.name)
        return datetime.strptime(m.group(1), "%Y%m%d").date() if m else None

    meta_rows = [
        ("taxroll", local["TR"][0].name, fdate(local["TR"][0]), counts["taxroll"]),
        ("delinquent", local["DQ"][0].name, fdate(local["DQ"][0]), counts["delinquent"]),
        ("sales", f"SALES_{min(_date_key(p.name) for p in local['YS'])}..{max(_date_key(p.name) for p in local['YS'])}.zip", fdate(local["YS"][-1]) or date.today(), counts["sales"]),
        ("cama_parcel", local["CC"][0].name, fdate(local["CC"][0]), counts["cama_PARDAT"]),
        ("cama_dwelling", local["CC"][0].name, fdate(local["CC"][0]), counts["cama_DWELDAT"]),
        ("cama_permit", local["CC"][0].name, fdate(local["CC"][0]), counts["cama_PERMIT"]),
        ("cama_apartment", local["CC"][0].name, fdate(local["CC"][0]), counts["cama_COMAPT"]),
        ("cama_codes", local["CC"][0].name, fdate(local["CC"][0]), counts["cama_codes"]),
        ("nbhd_codes", local["NC"][0].name, fdate(local["NC"][0]), counts["nbhd_codes"]),
    ]
    con.executemany("INSERT INTO _meta VALUES (?, ?, ?, ?, ?, ?)", [(*r, built_at, args.include_pii) for r in meta_rows])

    print("Conforming to datasets/county.yaml …")
    conform_to_schema(con)

    con.execute("CHECKPOINT")
    con.close()
    size = args.out.stat().st_size / 1e6
    print(f"\nWrote {args.out} ({size:.0f} MB) in {time.time() - t0:.0f}s"
          + ("  ⚠ INCLUDES PII — do not deploy" if args.include_pii else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
