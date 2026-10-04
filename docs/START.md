# Start here

OpenDayton lets an AI assistant answer questions from the City of Dayton and
Montgomery County's own published data — crime, housing condition, lead water
lines, trash pickup, capital projects, and fifteen years of county property
records.

It's free, read-only, and takes about two minutes to connect.

## 1. Connect it (2 minutes)

**Claude (web or desktop)**

1. Settings → Connectors → **Add custom connector**
2. Name: `OpenDayton` — URL: `https://opendayton.org/mcp`
3. Save. In a new chat, click **+** → Connectors → switch OpenDayton on.

**Claude Code**

```
claude mcp add -s user --transport http opendayton https://opendayton.org/mcp
```

**Anything else that speaks MCP** — point it at `https://opendayton.org/mcp`
(Streamable HTTP, no key needed).

## 2. Ask it something

- Which neighborhoods had the most violent crime last year?
- Now show that as a rate per 1,000 residents.
- What day is trash pickup at 275 Linden Ave, and does it have a lead water line?
- How many demolition permits has the county recorded each year since 2015?
- Tell me everything you know about my address.
- What share of homes in Dayton are owner-occupied?

Try one about your own street. If the answer looks wrong, that's interesting —
tell us.

## 3. Run it with your own model instead (optional)

No API key, no cloud, nothing leaves your laptop. You need
[Ollama](https://ollama.com/download).

**Do this before the workshop if you can — the model is a 5 GB download and
venue wifi will not enjoy twenty people doing it at once.**

```bash
ollama pull granite4.1:8b
```

Then either use a ready-made client:

```bash
uv tool install ollmcp
ollmcp -u https://opendayton.org/mcp -m granite4.1:8b
```

…or run our example, which prints every tool call so you can watch it think:

```bash
git clone https://github.com/codefordayton/opendayton && cd opendayton
uv sync
uv run python examples/local_model.py --model granite4.1:8b \
  "How many crimes were reported in Five Oaks in 2025?"
```

Tool calling, not writing quality, is what matters for this. Measured on an
M2 Max: `granite4.1:8b` (5.3 GB) answers in about 30 seconds and three tool
calls; a similarly sized model that isn't tuned for tools took four times
longer and made five.

## 4. Add something to it

The catalog is the product — sixteen datasets, each with its fields chosen by
a person and its traps written down. Adding one is editing a text file.

See **[CONTRIBUTING.md](https://github.com/codefordayton/opendayton/blob/main/CONTRIBUTING.md)**
for both paths: adding a dataset (YAML, no programming) or adding a tool (Python).

## What it will not do

Owner names, the addresses of vacant buildings, exact arrest dates and ages,
and crime-victim details are deliberately not exposed — all of it is public
record, but public record and one-sentence-away are different things. The
reasoning is in [DECISIONS.md](https://github.com/codefordayton/opendayton/blob/main/docs/DECISIONS.md).

## Other pieces

- **Parcel geocoder** — `https://geocoder-production-bb7e.up.railway.app/geocode?address=275+LINDEN`
  turns any Montgomery County address into a parcel ID and coordinates. Public,
  read-only, free to use in your own project.
- **Source** — [github.com/codefordayton/opendayton](https://github.com/codefordayton/opendayton), MIT.

A [Code for Dayton](https://codefordayton.org) project.
