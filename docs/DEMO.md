# Demo run-of-show

A 10–15 minute demo-heavy walkthrough. Live against `https://opendayton.org/mcp`.

**Ten minutes before you start:**

```bash
uv run python examples/preflight.py
```

It checks the server, every question below, the City's flaky on-premise server,
the guardrails, and whether Ollama has the model warm. Green means go. It also
prints per-question timing so you know your pacing.

---

## Setup on screen

Have these open and **nothing else** (the local model wants the RAM):

1. Claude (desktop or web) with the OpenDayton connector enabled, fresh chat
2. A terminal, large font, in the repo
3. `datasets/layers.yaml` open in an editor, scrolled to the `crimes` layer

---

## Beat 1 — The problem (90s, no demo)

Dayton publishes ~1,800 datasets across two ArcGIS orgs, an on-premise map
server, and a County file server whose record layouts are PDFs. There is no
search. Nobody outside GIS can find anything.

> "Everything I'm about to show you was already public this morning. None of
> this is new data. What's new is that you can ask for it in a sentence."

## Beat 2 — The hero question (2 min, live in Claude)

Ask:

> **Which neighborhoods had the most violent crime last year?**

Point at the tool-call disclosure as it runs — `list_datasets`,
`describe_dataset`, `arcgis_stats`. Then the answer, with the source cited.

Then the follow-up, which is the better moment:

> **Now show that as a rate per 1,000 residents.**

It has to find the population layer on its own and do the division. Watch for
it flagging that these are apportioned Census estimates.

> "Nobody wrote a 'crime rate' feature. It composed two datasets because both
> were described well enough for it to know they could join."

## Beat 3 — Why it's right (2 min, editor + one question)

Switch to `layers.yaml`, `crimes` layer. Show `fields:` and `caveats:`.

> "This is the whole product. Not the server — this file. Every field has a
> plain-language description, and every trap somebody hit is written down."

Then ask the trap question:

> **How many parcels got worse between the 2023 and 2025 condition surveys?**

The grade scale runs 1 SOUND → 5 DILAPIDATED, so a *rising* grade is a
*declining* building. Correct answer ≈ **15,577** worse, 4,365 improved.

> "I got this backwards in the caveat and shipped it. Everything downstream
> confidently reported the improved count as the worsened count. The fix
> wasn't in the code — it was one sentence of documentation. That's where the
> bugs live in these systems."

*(This is the most honest thing in the talk. Don't skip it.)*

## Beat 4 — Address questions (90s, live)

> **What day is trash pickup at 275 Linden Ave, and does it have a lead water line?**

Two tools chained: `geocode` turns the address into a parcel and coordinates,
then a spatial query against the trash routes and a lookup against the lead
inventory. Answer: **Monday**; the line is non-lead, already replaced.

> "The geocoder isn't part of this project. It's a separate Code for Dayton
> service that four other projects use. MCP just wrapped something we already had."

## Beat 5 — The guardrails (2 min, live — this is the civic-tech heart)

Ask:

> **Who owns 275 Linden Ave?**

It explains owner names aren't in the data. Then:

> **List the addresses of the vacant boarded-up houses in Westwood.**

Refused — the field isn't exposed.

> "All of that is public record. You can download the tax roll right now. But
> 'public record' and 'one sentence away from anyone with a chatbot' are
> different things. There are about 4,300 vacant structures in that survey.
> A filtered address list of empty buildings is a target list for copper theft
> and arson. So the addresses aren't in the catalog — and neither are the
> coordinates, because that's the same list one step removed. An 8B model
> found that gap for me by trying it."

Then show the aggregate still works:

> **How many vacant and boarded structures are in Westwood?**

> "The easy path is the aggregate one. That's the whole design."

## Beat 6 — Local model, failing then succeeding (3–4 min, terminal)

First, with no guidance — the model is on its own:

```bash
uv run python examples/local_model.py --model granite4.1:8b --naive \
  "List the addresses of the vacant boarded-up houses in Westwood."
```

Narrate the trace as it scrolls. It guesses `ADDRESS`, gets rejected **with the
list of valid fields**, tries SQL against a table that doesn't exist, gets told
which tables *do* exist, and works its way around.

> "That's a 5-gigabyte model running on this laptop, no API key, no cloud.
> Watch what the server tells it when it gets something wrong — it doesn't just
> say no, it says what's allowed. That error message is the reason it recovers.
> Half the work in an MCP server is writing good failures."

**Expect it to find the workaround, and say so before the room does.** It ends
by proposing: pull the vacant parcel IDs, then geocode each one back to an
address. That works — one call per parcel.

> "And there it is. It found the seam. The addresses aren't in the catalog, but
> parcel IDs are, and our geocoder turns a parcel ID into an address — that's
> its job, four other projects depend on it. So this is friction, not a wall:
> bulk is blocked, patient and one-at-a-time is not.
>
> I'd rather show you that than pretend otherwise. Field-level curation raises
> the cost of the bad use without breaking the good one. If we wanted a wall
> we'd have to stop publishing the data, and that's the City's call, not ours.
> An 8B model found this in one shot — which is the argument for having a model
> attack your own server before you hand out the URL."

Then with guidance, same model:

```bash
uv run python examples/local_model.py --model granite4.1:8b \
  "How many crimes were reported in Five Oaks in 2025?"
```

Three calls, ~30 seconds, correct (**351**).

> "Same model, same server. The difference is a system prompt that says 'read
> the schema before you query.' That's it."

## Beat 7 — How it's built (2 min, slides or editor)

```
server/main.py      tools + instructions        ~250 lines
server/catalog.py   loads layers.yaml           the allowlist
server/where.py     tokenizing validator        only allowlisted fields
server/arcgis.py    read-only REST client       schema cache, retries
server/county.py    read-only DuckDB            single SELECT, capped
```

Four points:

- **Curated, not crawled.** The server knows 16 datasets. It cannot enumerate
  the City's GIS servers. Adding one is a YAML edit plus a review.
- **Ids, not URLs.** The model can't point a tool at an arbitrary service.
- **Allowlist, not blocklist.** Every queryable field was chosen by a person.
- **Read-only and attributed.** Every answer carries publisher and as-of date.

> "Boston built OpenContext, which is where this idea came from. Theirs plugs
> into a CKAN portal and gets search for free. We have no portal — so the
> curation *is* the product."

## Beat 8 — Contribute (1 min)

`github.com/codefordayton/opendayton` · `opendayton.org`

Good first issues: add a dataset (YAML + field descriptions, no Python), write
a caveat you know from working with the data, add a gold question, add ACS or
RTA data.

> "If you know one of these datasets well enough to know where it lies to you,
> that knowledge is the contribution. It's a text file."

---

## If something breaks

| Symptom | Do this |
|---|---|
| Trash pickup or capital projects errors | The City's on-prem server 503s. Say so — it's a real point about municipal infrastructure — and move on. |
| A question hangs in Claude | Don't wait. "While that thinks —" and go to the terminal beat. |
| Local model is slow | It's a laptop doing 5 GB of matrix math. Talk over it; the trace is the point, not the latency. |
| Ollama is cold | First call takes ~30s to load. `preflight.py` warms it — run it. |
| Everything is down | `git log --oneline` and `layers.yaml` tell the whole story without a network. |

## Numbers to know cold

| | |
|---|---|
| Crimes in Five Oaks, 2025 | 351 |
| Parcels worse 2023→2025 | 15,577 (improved: 4,365) |
| Vacant structures citywide | ~4,300 |
| Dayton residential owner-occupancy | 45.7% |
| Demolition permits, 2019 | 442 (the Memorial Day tornadoes) |
| Trash day at 275 Linden Ave | Monday |
| County parcels / geocoder | ~255k / 273,203 |
