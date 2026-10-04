#!/usr/bin/env python3
"""Pre-flight check before a live demo. Run this ten minutes before you present.

Checks, in order of how likely each is to ruin the demo:

    1. the server is up, with the county database and geocoder attached
    2. every demo question's data path still returns data
    3. the City's on-premise map server is responding (it 503s sometimes)
    4. Ollama is running and the demo model is pulled and warm

Exits non-zero if anything a demo depends on is broken, and prints the
timing of each question so you know your pacing.

    uv run python examples/preflight.py
    uv run python examples/preflight.py --model granite4.1:8b --skip-local
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import httpx
from mcp.client import Client

URL = "https://opendayton.org/mcp"
OLLAMA = "http://localhost:11434"

OK, WARN, BAD = "\033[32m ok \033[0m", "\033[33mwarn\033[0m", "\033[31mFAIL\033[0m"

# The tool calls behind each demo beat. Keep in step with docs/DEMO.md.
BEATS: list[tuple[str, str, dict]] = [
    ("catalog",            "list_datasets", {}),
    ("violent crime 2025", "arcgis_stats",  {"dataset_id": "crimes", "group_by": ["Neighborhood"],
                                             "where": "ORC_Part = 'PART I VIOLENT' AND YEAR = 2025", "limit": 5}),
    ("population (rates)", "arcgis_query",  {"dataset_id": "neighborhood_population",
                                             "out_fields": ["HOOD", "TOTPOP20"], "limit": 5}),
    ("condition change",   "arcgis_stats",  {"dataset_id": "housing_condition_2025",
                                             "where": "HCS_DIFF > 0 AND GRADE > 0 AND GRADE_2023 > 0"}),
    ("geocode address",    "geocode",       {"address": "275 Linden Ave"}),
    ("service requests",   "arcgis_stats",  {"dataset_id": "service_requests", "group_by": ["CatName"]}),
    ("on-prem count stat",  "arcgis_stats",  {"dataset_id": "cip_active", "group_by": ["PROJTYPE"]}),
    ("trash day (on-prem)", "arcgis_query", {"dataset_id": "trash_pickup", "near_latitude": 39.75917,
                                             "near_longitude": -84.16023, "near_meters": 5,
                                             "out_fields": ["NHBHD_NAME", "Day"]}),
    ("lead line lookup",   "arcgis_query",  {"dataset_id": "lead_service_lines",
                                             "where": "address LIKE '275 LINDEN%'",
                                             "out_fields": ["address", "bothsidesstatus"]}),
    ("county demolitions", "county_sql",    {"sql": "SELECT year(permit_date) y, count(*) n FROM cama_permit "
                                                    "WHERE permit_type='DEMO' AND year(permit_date) >= 2015 "
                                                    "GROUP BY 1 ORDER BY 1"}),
    ("county tenure",      "county_sql",    {"sql": "SELECT round(100.0*count(*) FILTER (WHERE owner_occupied='Y')"
                                                    "/count(*),1) AS pct FROM taxroll WHERE city_township='DAYTON' "
                                                    "AND class='R'"}),
]

# Guardrails you may demo. These must be refused.
REFUSALS: list[tuple[str, str, dict]] = [
    ("vacant addresses refused",  "arcgis_query", {"dataset_id": "housing_condition_2025",
                                                   "where": "STATUS = 'VB'", "out_fields": ["PARLOC"]}),
    ("vacant coords refused",     "arcgis_query", {"dataset_id": "housing_condition_2025",
                                                   "where": "STATUS = 'VB'", "include_location": True}),
    ("juvenile detail refused",   "arcgis_query", {"dataset_id": "arrests",
                                                   "where": "Adult_Juvenile = 'JUVENILE'", "out_fields": ["Age"]}),
    ("county write refused",      "county_sql",   {"sql": "DELETE FROM taxroll"}),
]


async def main(model: str, skip_local: bool) -> int:
    problems = 0

    print("\n\033[1mServer\033[0m")
    try:
        health = httpx.get("https://opendayton.org/health", timeout=20).json()
    except Exception as e:  # noqa: BLE001
        print(f"  {BAD}  cannot reach opendayton.org — {e}")
        return 1
    for key, label in [("county_db", "county database"), ("geocoder", "geocoder")]:
        print(f"  {OK if health.get(key) else BAD}  {label}")
        problems += 0 if health.get(key) else 1
    print(f"  {OK}  {health.get('datasets')} datasets, version {health.get('version')}")

    # Pages are served from files that have to be in the deployed image, which
    # local tests cannot prove — /start renders docs/START.md at runtime.
    print("\n\033[1mPages\033[0m")
    for path, must_contain in [("/", "Lead Service Line Inventory"), ("/start", "granite4.1")]:
        try:
            body = httpx.get(f"https://opendayton.org{path}", timeout=20).text
            good = must_contain in body and len(body) > 3000
            print(f"  {OK if good else BAD}  {path:<8} {len(body):>6} bytes"
                  + ("" if good else f"  — missing {must_contain!r}; is it in the image?"))
            problems += 0 if good else 1
        except Exception as e:  # noqa: BLE001
            print(f"  {BAD}  {path:<8} {str(e)[:50]}")
            problems += 1

    print("\n\033[1mDemo questions\033[0m")
    async with Client(URL) as c:
        for label, tool, args in BEATS:
            t0 = time.time()
            try:
                res = await c.call_tool(tool, args)
                data = json.loads(res.content[0].text)
                elapsed = time.time() - t0
                if "error" in data:
                    print(f"  {BAD}  {label:<22} {data['message'][:60]}")
                    problems += 1
                else:
                    n = data.get("count_returned", data.get("count", len(data.get("datasets", []))))
                    slow = " \033[33m(slow)\033[0m" if elapsed > 4 else ""
                    print(f"  {OK}  {label:<22} {n:>5} rows  {elapsed:4.1f}s{slow}")
            except Exception as e:  # noqa: BLE001
                print(f"  {BAD}  {label:<22} {str(e)[:60]}")
                problems += 1

        print("\n\033[1mGuardrails (these must refuse)\033[0m")
        for label, tool, args in REFUSALS:
            try:
                data = json.loads((await c.call_tool(tool, args)).content[0].text)
                refused = "error" in data
                print(f"  {OK if refused else BAD}  {label:<26} {'refused' if refused else 'RETURNED DATA'}")
                problems += 0 if refused else 1
            except Exception as e:  # noqa: BLE001
                print(f"  {WARN}  {label:<26} {str(e)[:50]}")

    if skip_local:
        print(f"\n\033[1mLocal model\033[0m\n  {WARN}  skipped")
    else:
        print("\n\033[1mLocal model\033[0m")
        try:
            tags = httpx.get(f"{OLLAMA}/api/tags", timeout=10).json()
            have = [m["name"] for m in tags.get("models", [])]
            if any(m.split(":")[0] == model.split(":")[0] for m in have):
                print(f"  {OK}  ollama running, {model} present")
                t0 = time.time()
                httpx.post(f"{OLLAMA}/api/chat", timeout=300, json={
                    "model": model, "stream": False,
                    "messages": [{"role": "user", "content": "Reply with the single word: ready"}]})
                print(f"  {OK}  model warm ({time.time() - t0:.0f}s to first response)")
            else:
                print(f"  {BAD}  {model} not pulled — run: ollama pull {model}")
                problems += 1
        except Exception as e:  # noqa: BLE001
            print(f"  {BAD}  ollama not reachable — start it, or pass --skip-local ({str(e)[:40]})")
            problems += 1

    print(f"\n{'\033[32mReady.\033[0m' if not problems else f'\033[31m{problems} problem(s) — fix before demoing.\033[0m'}\n")
    return 1 if problems else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="granite4.1:8b")
    ap.add_argument("--skip-local", action="store_true")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.model, a.skip_local)))
