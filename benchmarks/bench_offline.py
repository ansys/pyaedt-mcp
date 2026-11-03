# Copyright (C) 2026 Synopsys, Inc. and ANSYS, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Offline benchmark: server performance that does not require an AEDT session.

Measures, over the real stdio MCP protocol:

- Cold start: process spawn until the MCP ``initialize`` handshake completes.
- Footprint: number of processes and resident memory spawned by the server.
- Protocol latency: ``ping``, ``tools/list``, ``prompts/get``, ``resources/read``.
- Tool latency for tools that work without AEDT (``check_aedt_installed``,
  ``check_aedt_status`` [session discovery], ``get_pyaedt_logs``,
  ``get_guidelines_for``).
- Concurrency: N parallel ``check_aedt_status`` calls.
- Prompt size: characters of the instructions delivered at ``initialize``.

Running AEDT sessions on the machine are only *discovered* (read-only); this
benchmark never connects to them.

Usage::

    python benchmarks/bench_offline.py --src src --label current --out results/current.json
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import time

from common import (
    DEFAULT_SRC,
    PingMonitor,
    Recorder,
    current_children,
    mcp_client,
    process_tree_stats,
    tool_text,
    write_results,
)


async def _cold_start(rec: Recorder, src: Path, runs: int, extra_args: list[str]) -> None:
    for _ in range(runs):
        before = current_children()
        start = time.perf_counter()
        async with mcp_client(src, ["--include-context", *extra_args]) as client:
            rec.add("startup.initialize", time.perf_counter() - start)
            # Give lifespan side processes a moment to appear, then sample the footprint.
            await asyncio.sleep(1.0)
            stats = process_tree_stats(before)
            rec.add("startup.process_count", stats["process_count"], unit="count")
            rec.add("startup.rss_mb", stats["rss_mb"], unit="MB")
            instructions = getattr(client, "instructions", None) or ""
            if not instructions and client.initialize_result is not None:
                instructions = client.initialize_result.instructions or ""
            rec.add("prompt.instructions_chars", len(instructions), unit="chars")


async def _latency(rec: Recorder, src: Path, iterations: int, concurrency: int) -> None:
    async with mcp_client(src, ["--include-context"]) as client:
        for _ in range(iterations):
            await rec.timed("protocol.ping", client.ping())
            await rec.timed("protocol.list_tools", client.list_tools())
            await rec.timed("protocol.get_prompt", client.get_prompt("system_prompt"))
            await rec.timed("protocol.read_toolsets", client.read_resource("toolsets://definition"))

        tools = await client.list_tools()
        schema_chars = sum(len(t.model_dump_json()) for t in tools)
        rec.add("prompt.tool_schema_chars", schema_chars, unit="chars")
        rec.add("prompt.tool_count", len(tools), unit="count")

        for _ in range(iterations):
            await rec.timed(
                "tool.check_aedt_installed", client.call_tool("check_aedt_installed", {})
            )
            await rec.timed(
                "tool.get_guidelines_for",
                client.call_tool("get_guidelines_for", {"content": "hfss"}),
            )
            await rec.timed(
                "tool.get_pyaedt_logs",
                client.call_tool("get_pyaedt_logs", {"tail_lines": 200}),
            )
            async with PingMonitor(client) as mon:
                result = await rec.timed(
                    "tool.check_aedt_status.disconnected",
                    client.call_tool("check_aedt_status", {}),
                )
            rec.add("loop.max_ping_during_check_status", mon.max_latency)

        text = tool_text(result)
        rec.notes.append(f"check_aedt_status (disconnected) payload chars: {len(text)}")

        start = time.perf_counter()
        await asyncio.gather(
            *(client.call_tool("check_aedt_status", {}) for _ in range(concurrency))
        )
        rec.add(f"concurrency.check_aedt_status_x{concurrency}", time.perf_counter() - start)


async def main() -> None:
    """Run the offline benchmark."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC, help="src dir to benchmark")
    parser.add_argument("--label", default="current")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--startup-runs", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    rec = Recorder(label=args.label, src=args.src.resolve())
    print(f"[offline] {args.label}: cold start x{args.startup_runs}")
    await _cold_start(rec, args.src.resolve(), args.startup_runs, [])
    print(f"[offline] {args.label}: latency x{args.iterations}")
    await _latency(rec, args.src.resolve(), args.iterations, args.concurrency)
    write_results(args.out, rec)
    print(f"[offline] results written to {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
