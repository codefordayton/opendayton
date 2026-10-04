# Workshop run-of-show — 50 minutes, hands-on

For the session where people bring laptops. The 15-minute talk-only version is
[DEMO.md](DEMO.md); this reuses its slides and adds the parts where the room works.

**Send [opendayton.org/start](https://opendayton.org/start) out in advance.** It
has the pre-work. Put it on a slide as a QR code at minute zero and leave it up.

## The one thing that will go wrong

Twenty people pulling a 5 GB model over venue wifi at the same moment. It will
not work and it will eat ten minutes.

So: **the Ollama segment is pre-work, not live.** The page says to pull the
model before arriving. In the room, you demo it from your laptop, and anyone
who did the pre-work follows along. Nobody downloads anything during the session.

Everything else needs only a browser.

---

## Before the room arrives

```bash
uv run python examples/preflight.py        # must say Ready
```

Open and leave open: Claude with the connector on, a terminal in the repo, an
editor on `datasets/layers.yaml`. Close everything else — the local model wants
the memory.

---

## 0:00 — The problem (4 min) · slides 1–2

1,782 datasets, no search, record layouts as PDFs. Everything is already public;
none of it is usable. Don't demo yet.

## 0:04 — What MCP is, and the seven tools (5 min) · slides 3–4

The three-box diagram, then read the tool list aloud. Twenty seconds on each of
`list_datasets` and `describe_dataset` — the second one is why the answers are right.

## 0:09 — Live demo (6 min) · slides 5, 7

> Which neighborhoods had the most violent crime last year?
> → Now show that as a rate per 1,000 residents.
> → What day is trash pickup at 275 Linden Ave, and does it have a lead water line?

Point at the tool calls as they run. The rate question is the one that lands:
nobody wrote a crime-rate feature, it composed two datasets on its own.

## 0:15 — **Checkpoint 1: everyone connects** (7 min)

Put the QR code up. Settings → Connectors → Add custom connector →
`https://opendayton.org/mcp`.

Then: **"ask it about your own street."**

Walk the room. Expect these:

| Problem | Fix |
|---|---|
| No Claude account | Pair them with a neighbor. Don't let anyone sit out. |
| Connector added but no tools | They forgot to switch it on in the chat: **+** → Connectors. |
| "It said it can't" | Usually a guardrail working. Ask what they typed — it's good material. |
| Corporate laptop blocks it | Phone browser works fine. |

Don't move on until most of the room has had one answer come back. This is the
moment the whole thing becomes real to them.

## 0:22 — Why the answers are right, and one that wasn't (6 min) · slides 6–7

The catalog slide, then the backwards-caveat story: houses graded 1 sound to 5
dilapidated, a rising grade is a declining house, and I wrote it down the other
way. 8,567 vs 15,577. The code was fine; the fix was one sentence of English.

This sets up the next 20 minutes: **what you're about to write is the part that
makes it right or wrong.**

## 0:28 — The guardrails (4 min) · slides 8–9

> Who owns 275 Linden Ave? → refused
> List the addresses of the vacant boarded-up houses in Westwood. → refused
> How many vacant and boarded structures are in Westwood? → answers

Public record vs. one-sentence-away. ~4,300 empty buildings; a filtered address
list is a target list. Mention that an 8B model found a way around it anyway
(parcel IDs plus the geocoder, one at a time) — friction, not a wall.

## 0:32 — **Checkpoint 2: pick a track and build** (16 min)

Put both on a slide and let people choose:

**Track A — add a dataset.** YAML only, no programming. For people who know the
data or want to.

**Track B — add a tool.** Python. For people who want to see how MCP actually works.

Both are in [CONTRIBUTING.md](../CONTRIBUTING.md). Setup is four commands and
takes about five minutes:

```bash
git clone https://github.com/codefordayton/opendayton && cd opendayton
uv sync && uv run pytest
uv run uvicorn server.main:app --reload --port 8000
```

For Track A, send them straight to the candidate table — nine pre-checked
layers, three of them deliberately carrying fields that shouldn't be exposed.
The draft comes from one command:

```bash
uv run python scripts/probe_layer.py <layer-url> --id my_dataset
```

Circulate. The question to keep asking is **"what did you leave out, and why?"**
That's the whole lesson; the YAML is just where it gets written down.

For Track B the equivalent question is **"who is this result for, the model or
the person?"** If someone proposes a tool that draws a map, renders a chart or
produces a report, that's the conversation to have — CONTRIBUTING.md has it
worked through as a short "why we said no to a map tool" section. It is the
question that settles most tool ideas, in either direction.

### What goes wrong here

| Problem | Fix |
|---|---|
| No `uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh`, or pair them up |
| `county_sql` / `geocode` unavailable locally | Expected — the county DB and geocoder aren't in a checkout. Track A doesn't need them. For geocode, `export GEOCODER_URL=https://geocoder-production-bb7e.up.railway.app` |
| Probe says "URL must end in a layer number" | They grabbed the service URL. Add `/0`. |
| Tests fail after editing YAML | Almost always indentation, or a value with a `:` in it that needs quoting. |
| Someone wants a dataset not on the list | Great — check `public_via` together. If there's no public page, that's the lesson. |

## 0:48 — Land it (2 min) · slide 15

Good first issues, the repo, and the ask:

> If you know one of these datasets well enough to know where it lies to you,
> that knowledge is the contribution. It's a text file.

Anything half-finished becomes a PR during Hacktoberfest hacking time.

---

## If you're short on time

Cut in this order: the guardrails segment to two minutes (keep the vacant-houses
refusal, drop the rest), then the local-model demo entirely, then Checkpoint 2
down to 10 minutes with everyone on Track A.

**Never cut Checkpoint 1.** A room that connected and got one answer back will
go home and use it. A room that only watched won't.
