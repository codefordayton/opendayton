#!/usr/bin/env python3
"""Drive the MCP tools directly for each gold question's data path.

This checks that the tool calls behind each question succeed against the live
sources (it doesn't judge model answers — that's a manual read of the checks
in questions.yaml). Usage:

    uv run python evals/run.py [--url http://localhost:8000/mcp]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from mcp.client import Client

LAST_YEAR = date.today().year - 1

# One representative tool call per question id (kept in sync with questions.yaml by hand).
CALLS: dict[str, tuple[str, dict]] = {
    "crimes_by_neighborhood": ("arcgis_stats", {"dataset_id": "crimes", "group_by": ["Neighborhood"], "where": f"ORC_Part = 'PART I VIOLENT' AND YEAR = {LAST_YEAR}", "limit": 10}),
    "calls_busiest_hours": ("arcgis_stats", {"dataset_id": "calls_for_service", "group_by": ["Hour"]}),
    "use_of_force_incidents": ("arcgis_stats", {"dataset_id": "use_of_force", "group_by": ["Year", "Disposition"]}),
    "hcs_worst_neighborhoods": ("arcgis_stats", {"dataset_id": "housing_condition_2025", "group_by": ["NEIGHBORHOOD"], "where": "GRADE >= 3", "limit": 10}),
    "hcs_change": ("arcgis_stats", {"dataset_id": "housing_condition_2025", "where": "HCS_DIFF > 0 AND GRADE > 0 AND GRADE_2023 > 0"}),
    "trash_day_at_address": ("arcgis_query", {"dataset_id": "trash_pickup", "near_latitude": 39.75917, "near_longitude": -84.16023, "near_meters": 5, "out_fields": ["NHBHD_NAME", "Day"]}),
    "geocode_address": ("geocode", {"address": "275 Linden Avenue, Dayton OH"}),
    "lead_at_address": ("arcgis_query", {"dataset_id": "lead_service_lines", "where": "address LIKE '275 LINDEN%'", "out_fields": ["address", "utilstatus", "custstatus", "bothsidesstatus", "replacestatus"]}),
    "lead_by_zip": ("arcgis_stats", {"dataset_id": "lead_service_lines", "group_by": ["zip"], "where": "utilstatus = 'Lead'"}),
    "cip_cost_by_type": ("arcgis_stats", {"dataset_id": "cip_completed", "group_by": ["PROJTYPE"], "stat_type": "sum", "stat_field": "AwdConstructionCost"}),
    "arpa_requests": ("arcgis_stats", {"dataset_id": "arpa_projects", "group_by": ["Applicant_Organization"], "stat_type": "sum", "stat_field": "Funding_Requested", "limit": 10}),
    "county_owner_occupancy": ("county_sql", {"sql": "SELECT round(100.0*count(*) FILTER (WHERE owner_occupied='Y')/count(*),1) AS pct FROM taxroll WHERE city_township='DAYTON' AND class='R'"}),
    "county_delinquency": ("county_sql", {"sql": "SELECT count(*) n, sum(net_delinquent) owed FROM taxroll WHERE net_delinquent > 0 AND city_township='DAYTON'"}),
    "county_demolitions": ("county_sql", {"sql": "SELECT year(permit_date) y, count(*) n FROM cama_permit WHERE permit_type='DEMO' AND year(permit_date) >= 2015 GROUP BY 1 ORDER BY 1"}),
    "county_median_price": ("county_sql", {"sql": "SELECT file_year, median(sale_price) FROM sales WHERE sale_validity='VALID SALE' AND class='R' AND parcel_id LIKE 'R72%' AND file_year >= 2015 GROUP BY 1 ORDER BY 1"}),
    "county_rental_delinquent": ("county_sql", {"sql": "SELECT count(*) FROM taxroll WHERE rental_registered='Y' AND net_delinquent > 0"}),
    "county_poor_condition_units": ("county_sql", {"sql": "SELECT sum(p.living_units) units FROM cama_dwelling d JOIN cama_parcel p USING (parcel_id) JOIN taxroll t USING (parcel_id) WHERE d.condition_code IN ('PR','UN','VP') AND t.city_township='DAYTON'"}),
    "survey": ("list_datasets", {}),
}


# Claims the catalog makes in prose, checked against the live data. A caveat
# that is confidently backwards is worse than no caveat — it steers the model
# wrong with authority — so the ones that encode a direction are asserted here.
async def check_invariants(client) -> list[str]:
    failures: list[str] = []

    async def rows(tool, args):
        res = await client.call_tool(tool, args)
        return json.loads(res.content[0].text).get("rows", [])

    # The grade scale runs good -> bad, so a rising grade is a declining building.
    scale = {r["GRADE"]: r["GRADE_DESC"] for r in await rows(
        "arcgis_stats", {"dataset_id": "housing_condition_2025", "group_by": ["GRADE", "GRADE_DESC"], "limit": 10})}
    if scale.get(1) != "SOUND" or scale.get(5) != "DILAPIDATED":
        failures.append(f"grade scale changed: {scale}")

    # HCS_DIFF > 0 must mean the grade rose, i.e. the building got worse.
    for r in await rows("arcgis_query", {"dataset_id": "housing_condition_2025",
                                         "where": "HCS_DIFF > 0", "out_fields": ["GRADE", "GRADE_2023"], "limit": 20}):
        if not r["GRADE"] > r["GRADE_2023"]:
            failures.append(f"HCS_DIFF > 0 but grade did not rise: {r}")
            break

    # Owner-occupancy credit is far broader than the homestead exemption.
    r = (await rows("county_sql", {"sql": "SELECT count(*) FILTER (WHERE owner_occupied='Y') AS oo, "
                                          "count(*) FILTER (WHERE homestead='Y') AS hs FROM taxroll"}))[0]
    if not r["oo"] > r["hs"] * 2:
        failures.append(f"owner_occupied should far exceed homestead: {r}")

    return failures


async def main(url: str) -> int:
    failures = 0
    async with Client(url) as client:
        for qid, (tool, args) in CALLS.items():
            try:
                res = await client.call_tool(tool, args)
                text = res.content[0].text if res.content else "{}"
                data = json.loads(text)
                if "error" in data:
                    raise RuntimeError(f"{data['error']}: {data['message']}")
                n = data.get("count_returned", len(data.get("datasets", [])))
                print(f"  ok   {qid:<30} {tool:<16} rows={n}")
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"  FAIL {qid:<30} {tool:<16} {str(e)[:120]}")
        print("\n  checking documented invariants against live data …")
        for problem in await check_invariants(client):
            failures += 1
            print(f"  FAIL invariant: {problem}")

    print(f"\n{len(CALLS) - failures}/{len(CALLS)} tool paths + invariants passed")
    return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000/mcp")
    sys.exit(asyncio.run(main(ap.parse_args().url)))
