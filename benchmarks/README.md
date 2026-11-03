# PyAEDT-MCP benchmarks

Reusable, repeatable measurements of the speed, footprint, responsiveness, and
stability of the PyAEDT-MCP server. They are **not** pytest tests: they start
the real server over stdio (like an MCP client does), time every request, and
write JSON results that can be compared between code revisions.

| Script | Needs AEDT | What it measures |
|---|---|---|
| `bench_offline.py` | No | Cold start to `initialize`, spawned processes and memory, protocol latency (`ping`, `tools/list`, `prompts/get`, `resources/read`), latency of the tools that work without AEDT, concurrent `check_aedt_status`, and size of the prompt and tool schemas sent to the LLM. |
| `bench_live.py` | Yes (isolated) | A realistic agent workflow: connect, create projects and designs, build geometry with `run_python_code`, list and inspect, validate, save, export config, read logs, recover from a failing snippet, reconnect, and `launch_aedt` / `disconnect_from_aedt(close_desktop=True)`. Each call records duration, the longest event-loop stall (ping latency), and failures. |
| `compare.py` | No | Markdown table of the median of every metric for two result files. |
| `show.py` | No | Prints every metric, sample count, and note in one result file. |

## AEDT isolation

`bench_live.py` never touches AEDT sessions that are already running:

- It starts its own non-graphical AEDT on a free gRPC port, and the server always
  connects with that explicit port.
- At the end it kills only the `ansysedt` PIDs that did not exist before the run
  and warns if a pre-existing session disappeared.
- Projects are written to a temporary folder, which is then deleted.

## Comparing two revisions

The harness runs the server from any `src` folder with the same interpreter, so
a baseline worktree and the current checkout can be measured side by side:

```powershell
git worktree add --detach ..\pyaedt-mcp-baseline main
$py = ".venv\Scripts\python.exe"

& $py benchmarks\bench_offline.py --src ..\pyaedt-mcp-baseline\src --label baseline --out benchmarks\results\baseline.json
& $py benchmarks\bench_live.py    --src ..\pyaedt-mcp-baseline\src --label baseline --out benchmarks\results\baseline.json --version 2026.1

& $py benchmarks\bench_offline.py --src src --label current --out benchmarks\results\current.json
& $py benchmarks\bench_live.py    --src src --label current --out benchmarks\results\current.json --version 2026.1

& $py benchmarks\compare.py benchmarks\results\baseline.json benchmarks\results\current.json --md benchmarks\results\comparison.md
```

Both scripts merge into the given output file, so offline and live results can
share one JSON. Increase `--startup-runs` and `--iterations` to reduce noise.
Results under about 10 ms are dominated by noise.

## Metric naming

- `startup.*`: server process start-up (`initialize`, `process_count`, `rss_mb`).
- `protocol.*`: MCP requests that do not run a tool.
- `tool.*`: tool calls in the offline benchmark.
- `connect.*` and `launch.*`: tool calls in the live scenarios.
- `loop.max_ping.*`: longest ping round trip observed **while** that tool ran.
  A value close to the tool duration means the tool blocked the server's event
  loop, so the server could not answer any other request, cancellation, or
  progress update in the meantime.
- `concurrency.*`: wall time of N concurrent identical calls.
- `prompt.*`: characters delivered to the LLM (instructions and tool schemas).
- `stability.failed_calls`: tool calls that raised, returned an MCP error, or did
  not contain the expected text. `compare.py` reports the sum.
