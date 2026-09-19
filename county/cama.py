#!/usr/bin/env python3
"""Parse the Montgomery County CAMA bulk extract.

The CAMA download is a 35-table fixed-width relational dump (~2.3 GB uncompressed).
Field positions come from the official layout PDF, so this module first turns that
PDF into a machine-readable spec, then reads the .DAT files against it.

Usage:
    ./cama.py spec  <layout.txt> <out.json>      # build the field spec
    ./cama.py head  <spec.json> <TABLE> <file>   # show first rows as key/value
    ./cama.py freq  <spec.json> <TABLE> <file> <COL> [COL...]   # value counts
    ./cama.py cols  <spec.json> <TABLE>          # list columns

Generate layout.txt with:
    pdftotext -layout docs/mc_file_layouts/Cama_Data_Layout.pdf layout.txt
"""
import collections
import json
import re
import sys

# "Pardat.Dat Pardat    Parid    1  30 Alpha   Parcel Id Number" — the filename
# column is only present on a table's first row, so it is optional here.
ROW = re.compile(
    r"^\s*(?:(?P<file>[A-Za-z0-9_]+\.[Dd]at)\s+)?"
    r"(?P<table>[A-Za-z][A-Za-z0-9_]*)\s+"
    r"(?P<col>[A-Za-z][A-Za-z0-9_]*)\s+"
    r"(?P<start>\d+)\s+(?P<len>\d+)\s+"
    r"(?P<type>Alpha|Numeric|Date|Alphanumeric)\s*"
    r"(?P<desc>.*?)\s*$"
)


def build_spec(layout_path):
    spec = collections.OrderedDict()
    for line in open(layout_path, encoding="utf-8", errors="replace"):
        m = ROW.match(line)
        if not m:
            continue
        table = m.group("table").upper()
        spec.setdefault(table, [])
        spec[table].append({
            "column": m.group("col").upper(),
            "start": int(m.group("start")),
            "length": int(m.group("len")),
            "type": m.group("type"),
            "description": re.sub(r"\s+", " ", m.group("desc")).strip(),
        })
    # A column can be listed twice across page breaks; keep first occurrence.
    for table, cols in spec.items():
        seen, uniq = set(), []
        for c in cols:
            key = (c["column"], c["start"])
            if key not in seen:
                seen.add(key)
                uniq.append(c)
        spec[table] = sorted(uniq, key=lambda c: c["start"])
    return spec


# The layout PDF disagrees with the delivered data in one place: in DWELDAT a
# single extra character appears between HEAT (start 92) and GRADE (start 95),
# so every column from position 95 on sits one byte later than documented.
# Verified empirically — with the shift, CDU matches the documented code set
# (AV/FR/GD/VG/PR/UN/EX/VP) for 99.9% of 189,389 records and GRADE resolves to
# the letter grades in GRADE.DAT; without it, neither matches at all.
OFFSET_FIXES = {"DWELDAT": [(95, 1)]}


def _shift(table, start):
    return start + sum(off for frm, off in OFFSET_FIXES.get(table, []) if start >= frm)


# Some tables (DWELL.DAT) wrap one logical record across several physical
# lines: a full-width data line, then a short trailing line, then a blank.
# Reading line-by-line would triple the record count and invent blank rows, so
# the reader stitches lines back together up to the table's declared width.
def _slice(buf, table, cols):
    out = {}
    for c in cols:
        s0 = _shift(table, c["start"]) - 1
        out[c["column"]] = buf[s0: s0 + c["length"]].strip()
    return out


def read_rows(spec, table, path, limit=None):
    cols = spec[table]
    width = max(c["start"] + c["length"] - 1 for c in cols)
    buf, emitted = "", 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line and not buf:
                continue
            buf += line
            # A record is complete once the next line would start a new one:
            # detect by the buffer reaching at least the last populated column.
            if len(buf) >= width or (buf and len(line) == 0):
                yield _slice(buf, table, cols)
                buf = ""
                emitted += 1
                if limit and emitted >= limit:
                    return
    if buf:
        yield _slice(buf, table, cols)


def main():
    cmd = sys.argv[1]
    if cmd == "spec":
        spec = build_spec(sys.argv[2])
        json.dump(spec, open(sys.argv[3], "w"), indent=2)
        print(f"{len(spec)} tables, {sum(len(v) for v in spec.values())} columns -> {sys.argv[3]}")
        for t, c in spec.items():
            print(f"  {t:<12} {len(c):>3} cols, width {max(x['start'] + x['length'] - 1 for x in c)}")
        return

    spec = json.load(open(sys.argv[2]))
    table = sys.argv[3].upper()

    if cmd == "cols":
        for c in spec[table]:
            print(f"  {c['column']:<14} {c['start']:>4} +{c['length']:<4} {c['type']:<9} {c['description']}")
    elif cmd == "head":
        for row in read_rows(spec, table, sys.argv[4], limit=2):
            for k, v in row.items():
                if v:
                    print(f"  {k:<14} {v}")
            print("  " + "-" * 40)
    elif cmd == "freq":
        targets = [c.upper() for c in sys.argv[5:]]
        counters = {c: collections.Counter() for c in targets}
        n = 0
        for row in read_rows(spec, table, sys.argv[4]):
            n += 1
            for c in targets:
                counters[c][row.get(c, "")] += 1
        print(f"rows: {n:,}")
        for c in targets:
            print(f"--- {c} ---")
            for v, k in counters[c].most_common(14):
                print(f"  {(v or '(blank)'):<34}{k:>10,}")


if __name__ == "__main__":
    main()
