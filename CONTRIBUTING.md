# Contributing

Two ways in. Pick the one that matches what you like doing.

| | **Track A — add a dataset** | **Track B — add a tool** |
|---|---|---|
| You edit | one YAML file | one Python file |
| You need | to know (or be curious about) the data | Python |
| Teaches | what makes an AI answer *right* | how MCP actually works |
| Time | ~15 minutes | ~30 minutes |

Both need the setup below. Neither needs you to be an expert in the other.

---

## Setup (~5 minutes, both tracks)

You need [git](https://git-scm.com) and [uv](https://docs.astral.sh/uv/getting-started/installation/).
uv installs its own Python, so that's the only prerequisite.

```bash
git clone https://github.com/codefordayton/opendayton    # or your fork
cd opendayton
uv sync
uv run pytest                 # should pass
```

Run the server:

```bash
uv run uvicorn server.main:app --reload --port 8000
```

Open <http://localhost:8000>. Point your assistant at `http://localhost:8000/mcp`
(Claude Code: `claude mcp add --transport http opendayton-local http://localhost:8000/mcp`).

**Two things are missing in a local checkout, and that's fine.** The county
database (85 MB) isn't in the repo, so `county_sql` reports itself unavailable —
build it with `uv run python -m county.build` if you want it, or skip it.
Everything in Track A works without it.

The geocoder is a separate public service; point at it to make `geocode` and
`profile_address` work locally:

```bash
export GEOCODER_URL=https://geocoder-production-bb7e.up.railway.app
```

---

## Track A — add a dataset

The catalog, [`datasets/layers.yaml`](datasets/layers.yaml), is the whole
product. The server is boring; this file is where the thinking is.

### 1. Pick a layer

Any ArcGIS layer URL ending in a number works. Start from one of these —
they're all public, queryable, and not in the catalog yet:

| Dataset | Rows | Why it's interesting |
|---|---|---|
| [Litter Containers](https://services2.arcgis.com/3dDB2Kk6kuA2gIGw/arcgis/rest/services/Litter_container/FeatureServer/0) | 424 | Condition of every public litter bin. Nine clean fields — the gentlest start. |
| [City Hall Window Temperature](https://services2.arcgis.com/3dDB2Kk6kuA2gIGw/arcgis/rest/services/City_Hall_Window_Temperature/FeatureServer/0) | 972 | Exactly what it says. Delightfully mundane. |
| [Trees Removed](https://services2.arcgis.com/3dDB2Kk6kuA2gIGw/arcgis/rest/services/Tree_Removed/FeatureServer/0) | 457 | Pairs with tree planting. Has editor-tracking fields to strip. |
| [Road Safety Action Plan](https://services2.arcgis.com/3dDB2Kk6kuA2gIGw/arcgis/rest/services/Point_Line_Shapefile_Upload/FeatureServer/0) | 347 | Resident-reported road safety concerns. |
| [Zoning](https://services2.arcgis.com/3dDB2Kk6kuA2gIGw/arcgis/rest/services/Zoning/FeatureServer/0) | 970 | 29 fields, most of them legacy junk. Good practice at picking the five that matter. |
| [Curb & Sidewalk Repairs](https://services2.arcgis.com/3dDB2Kk6kuA2gIGw/arcgis/rest/services/Curb_and_Sidewalk_Repairs_View/FeatureServer/0) | 1,472 | Walkability. Measurements in feet — units matter here. |
| ⚠️ [Tornado Damage Assessment](https://services2.arcgis.com/3dDB2Kk6kuA2gIGw/arcgis/rest/services/TornadoAssessment_Housing/FeatureServer/0) | 1,015 | 2019 tornado damage — **and the assessor's name and phone number.** |
| ⚠️ [Nuisance Properties](https://services2.arcgis.com/3dDB2Kk6kuA2gIGw/arcgis/rest/services/FinalJoinedSHP/FeatureServer/0) | 1,752 | Nuisance parcels **with addresses.** Read the vacancy discussion in [DECISIONS.md §8b](docs/DECISIONS.md) first. |
| ⚠️ [Mediation Response Unit calls](https://services2.arcgis.com/3dDB2Kk6kuA2gIGw/arcgis/rest/services/MediationResponseUnit_CFS_Units/FeatureServer/0) | 10,049 | Non-police crisis response — **incident addresses and coordinates.** |

The ⚠️ ones are the interesting ones. They carry fields that are published but
shouldn't be one prompt away, and deciding what to leave out *is* the contribution.

### 2. Draft it

```bash
uv run python scripts/probe_layer.py <layer-url> --id my_dataset
```

This reads the layer and prints a YAML block with every field, its type, its
coded values and real sample values. It leaves out editor-tracking and
person-shaped fields by default (`--all` includes them, so you can look).

**It is a draft, not an answer.** Everything marked `TODO` is yours.

### 3. Fill in the judgment

Paste the block into `datasets/layers.yaml` and work through it:

- **`public_via` / `source_page`** — where is the public *meant* to find this?
  A Hub site, an OpenData folder, a public map. If you can't find one, that's a
  signal: reachable isn't the same as published. Ask before adding it.
- **`fields`** — delete every field a resident wouldn't need. Keep the rest and
  say what each one *means*, not what it's called. `CDU: condition` is useless;
  `CDU: condition — AV average, PR poor, UN unsound` is the whole point.
- **`caveats`** — the most valuable part. Anything that would make a confident
  answer wrong: units, a scale that runs backwards, one-row-per-offense rather
  than per-incident, blanks that aren't zeroes, a snapshot that stopped updating.
- **`example_questions`** — two things a resident would actually ask.

> Worth knowing before you write a caveat: we shipped one backwards. The housing
> survey grades houses 1 (sound) to 5 (dilapidated), so a *rising* grade is a
> *declining* house — and the catalog said the opposite. Every answer about
> housing decline was confidently wrong, with a citation attached. A wrong
> caveat is worse than no caveat.

### 4. Check it

```bash
uv run pytest
```

Then run the server and ask your own example questions. If the model answers
something subtly wrong, that's a missing caveat — add it. That loop *is* the work.

---

## Track B — add a tool

Tools live in [`server/main.py`](server/main.py). A tool is a function with a
docstring. The docstring is not a comment — **it is the prompt** the model reads
to decide whether and how to call it, so it carries as much weight as the code.

```python
@server.tool(annotations=READ_ONLY)
async def busiest_hours(dataset_id: str) -> dict[str, Any]:
    """When is this dataset busiest, by hour of day?

    Works on any dataset with an Hour field, such as calls for service.
    Returns counts per hour, 0-23.
    """
    try:
        layer = catalog.get(dataset_id)
        return await arcgis.stats(layer, group_by=["Hour"], order_by="Hour ASC")
    except (CatalogError, WhereError, ArcGISError) as e:
        return _err("failed", str(e))
```

That's the whole shape. Add it, restart the server, ask your assistant a
question that should trigger it.

### The worked example

`profile_address` is the one to read — it composes four datasets behind one
question ("tell me about 275 Linden Ave") and shows the pattern worth copying:
**each lookup is independent, and a failure is reported rather than fatal.**
Partial answers beat no answer.

### Things worth building

- **`compare_neighborhoods(a, b)`** — the same statistics for two neighborhoods, side by side.
- **`per_capita(dataset_id, where)`** — counts normalized by neighborhood population. The model does this in two calls today; one would be better.
- **`nearby(address, meters)`** — everything within a radius: capital projects, storm drains, facilities.
- **`trend(dataset_id, field)`** — a year-over-year series with the direction named, so nobody has to eyeball it.
- **`explain_parcel_id(parcel_id)`** — decode a county parcel ID into its taxing district and what that means.

### Rules for any tool

1. **Read-only.** Nothing writes, ever.
2. **Bounded.** Cap rows and time. Never let one call run away.
3. **Dataset ids, not URLs.** A tool that takes a URL can be pointed anywhere, and the curated boundary stops meaning anything.
4. **Errors are instructions.** When a model gets something wrong, the message should say what *would* work. `"'ADDRESS' is not a field. Allowed: PARCELID, NEIGHBORHOOD, …"` gets it back on track; `"invalid field"` does not.
5. **Attribute.** Return the publisher and as-of date with the data.

---

## Opening a pull request

```bash
git checkout -b add-litter-containers
git commit -am "Add litter containers dataset"
git push origin add-litter-containers
```

Then open a PR on GitHub. In the description, say **where the public is meant to
find this data** and **what you deliberately left out**. That second one is the
part a reviewer most wants to see.

Not sure about something? Open the PR anyway and ask in it. A half-finished
entry with a good question beats a polished one that guessed.
