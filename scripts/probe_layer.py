#!/usr/bin/env python3
"""Turn an ArcGIS layer URL into a draft entry for datasets/layers.yaml.

Reads the layer's schema and a few real rows, then prints a YAML block you can
paste into the catalog and edit. It does the tedious half — field names, types,
coded values, record counts — and leaves you the half that matters: deciding
which fields belong and writing down what they mean.

    uv run python scripts/probe_layer.py <layer-url> --id my_dataset

    --id        the dataset id to use in the draft (default: guessed)
    --all       include fields this script would normally leave out
    --rows N    how many sample rows to show (default 3)

The URL must end in a layer number, e.g.
    https://services2.arcgis.com/.../Dayton_Alleys/FeatureServer/0
Find them on a City Hub site, or in the Code for Dayton data inventory.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

USER_AGENT = "OpenDayton probe_layer (https://github.com/codefordayton/opendayton)"

# Fields we leave out of the draft by default. Not a security boundary — the
# allowlist in layers.yaml is that — just a nudge, so the common mistakes
# (shipping an editor's login, an owner's name, a GUID nobody needs) take a
# deliberate --all rather than inattention.
SKIP_EXACT = {
    "objectid", "objectid_1", "fid", "globalid", "globalid_1", "shape",
    "shape__area", "shape__length", "shape_leng", "shape_area", "se_anno_cad_data",
}
SKIP_PATTERNS = [
    (re.compile(r"owner.*name|^name\d*$|first.?name|last.?name", re.I), "may be a person's name"),
    (re.compile(r"email|phone|mobile|contact", re.I), "contact details"),
    (re.compile(r"created_?(user|date)|last_?edit|editor|edit_?date|creator", re.I), "editor tracking"),
    (re.compile(r"account|ssn|license|permit_?no|booking|warrant", re.I), "may identify a person or account"),
    (re.compile(r"^globalid|guid|^se_", re.I), "internal identifier"),
]


def human_date(ms) -> str:
    """ArcGIS reports dates as epoch milliseconds; nobody can read those."""
    if not isinstance(ms, (int, float)):
        return "?"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def get(url: str, params: dict | None = None) -> dict:
    full = url + "?" + urllib.parse.urlencode({**(params or {}), "f": "json"})
    req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    if isinstance(data, dict) and "error" in data:
        raise SystemExit(f"ArcGIS error: {data['error'].get('message')}\n  {url}")
    return data


def should_skip(name: str) -> str | None:
    if name.lower() in SKIP_EXACT:
        return "system field"
    for pattern, why in SKIP_PATTERNS:
        if pattern.search(name):
            return why
    return None


def yaml_quote(text: str) -> str:
    """Quote a description if YAML would otherwise mangle it."""
    text = " ".join(str(text).split())
    if re.search(r'^[>|&*!%@`\[{]|: |#| $|^$', text) or text.endswith(":"):
        return '"' + text.replace('"', '\\"') + '"'
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--id", dest="dataset_id")
    ap.add_argument("--all", action="store_true", help="include fields normally left out")
    ap.add_argument("--rows", type=int, default=3)
    ap.add_argument("--out", help="also write just the YAML draft to this file")
    args = ap.parse_args()

    url = args.url.strip().rstrip("/")
    if not re.search(r"/(FeatureServer|MapServer)/\d+$", url):
        raise SystemExit(
            "URL must end in a layer number, e.g. .../FeatureServer/0\n"
            f"  got: {url}\n"
            "  (open the service in a browser and pick a numbered layer)"
        )

    meta = get(url)
    count = get(url + "/query", {"where": "1=1", "returnCountOnly": "true"}).get("count")
    fields = meta.get("fields") or []
    sample = get(url + "/query", {
        "where": "1=1", "outFields": "*", "resultRecordCount": max(1, args.rows),
        "returnGeometry": "false",
    })
    rows = [f.get("attributes", {}) for f in sample.get("features", [])]

    caps = meta.get("capabilities", "")
    adv = meta.get("advancedQueryCapabilities") or {}
    geom = {"esriGeometryPoint": "point", "esriGeometryPolygon": "polygon",
            "esriGeometryPolyline": "line", None: "table"}.get(meta.get("geometryType"), "table")
    dataset_id = args.dataset_id or re.sub(r"[^a-z0-9]+", "_", (meta.get("name") or "dataset").lower()).strip("_")[:40]

    # ── Report ──────────────────────────────────────────────────────────────
    print(f"\n\033[1m{meta.get('name')}\033[0m")
    print(f"  {count:,} records · {geom} · last edited "
          f"{human_date((meta.get('editingInfo') or {}).get('lastEditDate'))}")
    print(f"  query: {'yes' if 'Query' in caps else 'NO — unusable'} · "
          f"statistics: {'yes' if adv.get('supportsStatistics') else 'no — arcgis_stats will not work'} · "
          f"max per request: {meta.get('maxRecordCount')}")
    if "Create" in caps or "Update" in caps or "Delete" in caps:
        print("  \033[33mnote:\033[0m the service advertises editing. We only ever read.")

    kept, skipped = [], []
    for f in fields:
        why = should_skip(f["name"])
        (skipped if why and not args.all else kept).append((f, why))

    if skipped:
        print(f"\n  \033[33mleft out of the draft ({len(skipped)}):\033[0m")
        for f, why in skipped:
            print(f"    {f['name']:<28} {why}")
        print("    (--all includes them; add back only what a resident needs)")

    # ── Draft ───────────────────────────────────────────────────────────────
    print(f"\n\033[1mDraft — paste into datasets/layers.yaml and edit every TODO:\033[0m\n")

    out = []
    out.append(f"  - id: {dataset_id}")
    out.append(f"    title: {yaml_quote(meta.get('name') or 'TODO')}")
    out.append("    theme: TODO            # reference public_safety housing infrastructure capital community environment regional")
    out.append("    publisher: TODO        # the agency, e.g. City of Dayton Department of Water")
    out.append("    public_via: TODO       # where the public is meant to find this — a Hub site, an OpenData folder, a public map")
    out.append("    source_page: TODO      # the URL of that public page")
    out.append(f"    url: {url}")
    out.append(f"    geometry: {geom}")
    out.append(f"    approx_records: {count}")
    desc = " ".join((meta.get("description") or "").split())
    desc = re.sub(r"<[^>]+>", "", desc)[:300]
    out.append("    description: >")
    out.append(f"      TODO — what this is, in plain language a resident would use."
               + (f" The service says: {desc}" if desc else ""))
    out.append("    fields:")
    for f, _ in kept:
        name, ftype = f["name"], f["type"].replace("esriFieldType", "")
        hint = f"TODO ({ftype}"
        dom = f.get("domain")
        if dom and dom.get("type") == "codedValue":
            codes = [str(cv["code"]) for cv in dom.get("codedValues", [])][:6]
            hint += f"; values: {', '.join(codes)}" + ("…" if len(dom.get("codedValues", [])) > 6 else "")
        elif rows:
            raw = [r.get(name) for r in rows if r.get(name) not in (None, "", " ")][:2]
            if ftype in ("Date", "DateOnly"):
                raw = [human_date(v) for v in raw]
            if raw:
                hint += "; e.g. " + ", ".join(str(v)[:28] for v in raw)
        if f.get("alias") and f["alias"] != name:
            hint += f"; alias: {f['alias'][:40]}"
        out.append(f"      {name}: {hint})")
    out.append("    caveats:")
    out.append("      - TODO — anything that would make an answer wrong. Units, a scale that runs backwards,")
    out.append("        one-row-per-something, blank values that are not zero, a stale snapshot.")
    out.append("    example_questions:")
    out.append("      - TODO — a question a resident would actually ask")
    out.append("      - TODO — one more")
    draft = "\n".join(out)
    print(draft)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(draft + "\n")
        print(f"\n  written to {args.out}")

    print(f"\n\033[1mNext:\033[0m uv run pytest  ·  then run the server and ask your example questions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
