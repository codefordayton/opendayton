#!/usr/bin/env python3
"""Ask OpenDayton a question using a local open-weight model.

Ollama has no MCP client of its own, so this is the bridge, in about a page:
fetch the tool list over MCP, hand it to the model in Ollama's tool format,
run whatever tool calls come back, feed the results in, repeat until the model
answers. That loop is all an "MCP client" is.

    ollama serve                       # in another terminal, if not running
    ollama pull qwen3.8:27b            # or use one you already have
    uv run python examples/local_model.py "How many crimes in Five Oaks in 2025?"

    --model    Ollama model (default: $OLLAMA_MODEL or qwen3.8:27b)
    --url      MCP endpoint (default: https://opendayton.org/mcp)
    --quiet    hide the tool-call trace
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

import httpx
from mcp.client import Client

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.8:27b")
DEFAULT_URL = os.environ.get("OPENDAYTON_URL", "https://opendayton.org/mcp")
MAX_STEPS = 8

SYSTEM = """You answer questions about Dayton, Ohio using only the tools provided.

Work in this order:
1. list_datasets to see what exists.
2. describe_dataset before querying one for the first time — it tells you the
   exact field names you may use and the traps to avoid. Do not guess field names.
3. arcgis_stats for counts and rankings; arcgis_query for individual rows;
   county_sql for parcel, tax, sales and permit questions; geocode for addresses.

Cite the dataset and publisher in your answer. If the tools cannot answer the
question, say so plainly rather than guessing."""


def to_ollama_tools(mcp_tools) -> list[dict]:
    """MCP tool definitions -> Ollama's OpenAI-shaped `tools` array."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": (t.description or "").strip(),
                "parameters": t.input_schema or {"type": "object", "properties": {}},
            },
        }
        for t in mcp_tools
    ]


async def chat(client: httpx.AsyncClient, model: str, messages: list[dict], tools: list[dict]) -> dict:
    r = await client.post(
        f"{OLLAMA}/api/chat",
        json={"model": model, "messages": messages, "tools": tools, "stream": False,
              "options": {"temperature": 0}},
        timeout=600,
    )
    r.raise_for_status()
    return r.json()["message"]


async def run(question: str, model: str, url: str, verbose: bool) -> int:
    async with Client(url) as mcp, httpx.AsyncClient() as http:
        listed = await mcp.list_tools()
        tools = to_ollama_tools(listed.tools)
        if verbose:
            print(f"connected: {len(tools)} tools — {', '.join(t['function']['name'] for t in tools)}\n")

        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
        started = time.time()

        for step in range(MAX_STEPS):
            msg = await chat(http, model, messages, tools)
            calls = msg.get("tool_calls") or []
            messages.append(msg)

            if not calls:
                print(f"\n{(msg.get('content') or '').strip()}")
                print(f"\n[{model} · {step} tool calls · {time.time() - started:.0f}s]")
                return 0

            for call in calls:
                fn = call["function"]
                name = fn["name"]
                # Ollama returns arguments as a dict; some builds return a JSON string.
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                if verbose:
                    print(f"  → {name}({json.dumps(args)[:150]})")
                try:
                    result = await mcp.call_tool(name, args)
                    text = result.content[0].text if result.content else "{}"
                except Exception as e:  # noqa: BLE001 — feed tool errors back to the model
                    text = json.dumps({"error": "tool_failed", "message": str(e)[:300]})
                if verbose:
                    print(f"  ← {text[:200].replace(chr(10), ' ')}")
                messages.append({"role": "tool", "tool_name": name, "content": text[:8000]})

        print(f"\nGave up after {MAX_STEPS} steps without a final answer.", file=sys.stderr)
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question", nargs="+")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    try:
        return asyncio.run(run(" ".join(a.question), a.model, a.url, not a.quiet))
    except httpx.ConnectError:
        print(f"Can't reach Ollama at {OLLAMA}. Is `ollama serve` running?", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
