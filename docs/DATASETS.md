# The datasets

A survey of what's in OpenDayton, why each dataset is in, and what it can answer. The
machine-readable versions are `datasets/layers.yaml` (ArcGIS layers) and
`datasets/county.yaml` (the County SQL database); this page is the human tour.

## The inclusion bar

A dataset goes in when all of these are true:

1. **The publisher surfaces it to the public on purpose.** A Hub site, an "OpenData"
   folder, a public dashboard or StoryMap, a `_public`-suffixed service, or a public
   download page. Reachable-but-unadvertised doesn't count. Each entry records where
   (`public_via`) and links to it (`source_page`).
2. **It's queryable** — an ArcGIS layer that answers `/query`, or a bulk file we can load.
3. **A resident would ask about it.** Crime, trash day, lead pipes, what the City is
   building, what a house is worth. Internal operational layers, editing views, and
   Survey123 forms don't clear this bar.
4. **It isn't a duplicate.** The City publishes several copies of many layers; the
   inventory's duplicate analysis picks one.
5. **Its fields have been reviewed.** Someone wrote the allowlist and the caveats. Fields
   that identify a person (names, account numbers, contact details) and editor-tracking
   fields stay off. So does anything whose harm comes from the *combination* — an exact
   date next to demographics and a small geography, or an address next to a vacancy flag.
   `tests/test_privacy.py` pins those decisions with reasons; see
   [`DECISIONS.md`](DECISIONS.md) §8b.

## City of Dayton — ArcGIS layers

### Reference

| id | What | Answers |
|---|---|---|
| `neighborhoods` | The 65 official neighborhoods and their Priority Boards | The join key for everything else; "which neighborhoods are in the Northeast Priority Board?" |
| `public_facilities` | Schools, libraries, rec centers, fire stations | "What public high schools are in Dayton?" |

### Public safety (Dayton Police open data)

| id | What | Answers |
|---|---|---|
| `crimes` | NIBRS-coded incidents, ~52k rows, 2023→ | Crime by type, neighborhood, month; violent vs property (`ORC_Part`) |
| `arrests` | Arrests by charge, ~50k rows | Arrests by charge, year, neighborhood; demographic breakdowns (no identifiers) |
| `calls_for_service` | 911 and officer-initiated calls, ~26k rows | Busiest neighborhoods/hours, response time by priority |
| `use_of_force` | Internal-affairs use-of-force records, ~1.3k rows | Force by type/year, dispositions, injuries |

Traps: `Neighborhood` is UPPER CASE in crimes and Title Case elsewhere; crimes and arrests
are one row per offense/charge, not per incident/person; some incidents have no
neighborhood recorded; every police layer is a rolling window — check the year range first.

Withheld here: exact arrest dates and arrestee age (a fifth of arrests are juveniles),
and exact offense dates and the victim-offender relationship. These layers answer
aggregate questions by year and month, not questions about a person or a day.

### Housing

| id | What | Answers |
|---|---|---|
| `housing_condition_2025` | Every parcel's exterior condition grade (0–5) from the 2025 windshield survey, with the 2023 grade in the same row | Condition by neighborhood; what got worse; which defects are common; vacant & boarded counts |
| `housing_projects` | City-funded housing projects with program, affordability, tenure, units | Where the City has invested, by program and affordability |
| `city_owned_parcels` | Parcels the City owns (2021 snapshot) | Vacant City lots by neighborhood; parcels marked for sale |

Traps: `HCS_DIFF` is 2025 minus 2023, so negative means *worse*; grade 0 is a vacant lot,
not a condition; ~13.5k parcels are unsurveyed (null); owner names and street addresses
are on the source layer and deliberately not exposed — geocode an address to a parcel ID
to look up one property.

### Infrastructure

| id | What | Answers |
|---|---|---|
| `lead_service_lines` | The water service line at every address: material both sides, verification, replacement status and tier | "Does my address have lead?"; lead lines by ZIP; replacements by year |
| `trash_pickup` | Trash route areas with pickup day | "What day is trash pickup at…?" (with geocode + `near`) |
| `storm_drains` | Storm drain inlets and Adopt-A-Drain status | Adopted vs available drains; drains near an address |

Traps: "Unknown" is a real and common lead status; addresses are UPPER CASE with
abbreviated street types; adopter contact details are on the source and not exposed.

### Capital investment

| id | What | Answers |
|---|---|---|
| `cip_active` | Capital projects in design or construction | What's being built, where, what it costs, who's funding it |
| `cip_completed` | Completed capital projects | Spend by type and fiscal year |
| `arpa_projects` | ARPA (Dayton Recovery Plan) community project applications | Requests by organization and ZIP |

Traps: ARPA rows are *applications*, not awards; staff and contractor contact details are
not exposed; the CIP layers come from the City's on-premise server and occasionally error —
retry once.

## Montgomery County — SQL database

Built from the Auditor/Treasurer bulk downloads by `county/build.py`; queried with
`county_sql`. Countywide — filter `city_township = 'DAYTON'` for the City.

| table | What | Answers |
|---|---|---|
| `taxroll` | One row per parcel (~255k): class, values, owner-occupancy and homestead flags, rental registration, delinquency, foreclosure date, last sale, year built, census tract | Tenure by tract; delinquency totals; foreclosure counts; value distributions; absentee ownership via mailing city |
| `delinquent` | The certified delinquent list (~25k) with the certified year | How long parcels have been delinquent |
| `sales` | Every recorded transfer 2001–02 and 2011→ (~418k) with price, validity, type | Median valid sale price by year and area; investor (out-of-state buyer) share |
| `cama_parcel` | CAMA parcel master with living-unit counts | Housing units by area; unit-count denominators |
| `cama_dwelling` | One row per dwelling: year built, rooms, baths, grade, condition, living area | Age of stock; condition (poor/unsound) counts; typical house size |
| `cama_permit` | Building permits (~254k, 1990s→) by type incl. DEMO | Permits and demolitions by year; the 2019 tornado spike |
| `cama_apartment` | Apartment unit inventory by bedroom count with assessor rents | Multifamily inventory (rents are valuation rents, not market) |
| `cama_codes`, `nbhd_codes` | Code lookups | Decoding grade/condition/heat codes and Auditor neighborhood numbers |
| `_meta` | Provenance: source file, file date, row count per table | The as-of date to cite |

Traps: `owner_occupied` is the tenure flag, `homestead` is a narrow exemption; the County
publishes no sales for 2003–2010; sale validity is null before 2011; apartment rents are
assessor valuation rents; owner names and mailing street addresses are removed at build.

## Considered and not (yet) included

| Dataset | Status |
|---|---|
| Housing code enforcement incidents (Accela) | Live open layer, but not advertised on any public page. Held until the City confirms it's intended to be public. |
| City employee list | Public record, but a name list is a different thing in a chatbot. Out. |
| Group homes with 1,000-ft buffers | Sensitive by nature. Out. |
| Vacant-lot mowing layers | One-off snapshots, five near-duplicates. Out. |
| MVRPC Regional Housing Study block groups | In the plan (regional cost burden, tenure, rent bands). Next. |
| HUD LIHTC / project-based Section 8 / public housing | In the plan (subsidized inventory and expirations). Next. |
| Zoning districts, street trees, sidewalks, Mediation Response Unit, Police reform tracker, Preschool Promise, emissions | In the plan; each needs a field review. Good first issues. |
| Census ACS (tract / block group) | The obvious join target for `census_tract`. Candidate. |
| RTA GTFS | Public transit schedules; fun demo material. Candidate. |
| Monthly tax roll snapshots since 2019 as a time series | ~23M rows; would need a volume. Later. |
