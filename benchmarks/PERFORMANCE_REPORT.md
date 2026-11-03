# PyAEDT-MCP performance and stability report

Branch: `perf/mcp-speed-stability` (base: `916c196`).
Machine: Windows, AEDT 2026.1, Python 3.14 (repo `.venv`).
Method: baseline and optimized code measured with the same harness
(`benchmarks/`) and interpreter, over the real stdio MCP protocol. Offline: 5
cold starts and 5 iterations. Live: 4 workflow iterations against an
**isolated** AEDT on a free port (pre-existing AEDT sessions were never attached
or closed; this was verified after every run). Medians are shown. Raw data is in
`benchmarks/results/`.

## Headline results

| Area | Metric | Before | After | Gain |
|---|---|---:|---:|---:|
| Startup | Process spawn to MCP `initialize` | 2.88 s | 1.70 s | **1.7x faster** |
| Footprint | Processes spawned by the server | 5 | 3 | -2 processes |
| Footprint | Resident memory of the server tree | 349 MB | 145 MB | **-59%** |
| Discovery | `check_aedt_status` (disconnected) | 4.44 s | 5 ms | **~840x** |
| Discovery | `check_aedt_status` (connected, live) | 4.74 s | 26 ms | **~185x** |
| Connect | `connect_to_aedt` (live) | 4.55 s | 110 ms | **41x** |
| Connect | Reconnect to the same session | 4.54 s | 43 ms | **106x** |
| Launch | `launch_aedt` (new AEDT) | 7.87 s | 5.39 s | **-32%** |
| Close | `disconnect_from_aedt(close_desktop=True)` | 9.73 s | 4.27 s | **2.3x faster** |
| Agent loop | Follow-up `run_python_code` edit (reuse app) | 450 ms | 40 ms | **11x** |
| Concurrency | 4 parallel `check_aedt_status` | 10.13 s | 17 ms | **~590x** |
| Responsiveness | Event loop stall during `connect_to_aedt` | 4.55 s | 5 ms | Server stays responsive |
| Responsiveness | Event loop stall during `launch_aedt` | 7.87 s | 235 ms | Server stays responsive |
| Responsiveness | Event loop stall during close | 9.73 s | 2.05 s | -79% |
| Stability | Failed tool calls in the live workflow | 0 | 0 | No regressions |

A typical agent session start (`check_aedt_status`, then `connect_to_aedt`,
then `check_aedt_status`) went from about **13.8 s to 0.24 s** of tool time,
plus 1.2 s less server start-up.

Unchanged within noise: tools dominated by AEDT itself (`create_design`,
geometry, `validate_design`, `export_config`, `save_project`, lists).

## Root causes and changes

### 1. Session discovery spawned `tasklist` twice (~4.5 s per call)
`discover_available_aedt_sessions()` called PyAEDT's `_discover_aedt_sessions`.
On Windows that runs `tasklist` once for `ansysedt.exe` and once for
`ansysedtsv.exe`, about 2.3 s each. It ran on every `check_aedt_status`, on
`connect_to_aedt` without a port, and on `launch_aedt` without confirmation.

**Change (`helpers.py`):** a single `psutil` process scan (~20 ms) that
returns the same records (verified equal against PyAEDT on live sessions).
The port is read from `-grpcsrv`, or else from the loopback LISTEN socket
(same precedence as PyAEDT). Windows only, with automatic fallback to the
PyAEDT implementation. Linux behavior is unchanged.

### 2. PyAEDT's launch, attach, and close loops used the same slow lookup
`Desktop` polls `is_grpc_session_active()` once per second while launching,
calls `active_sessions()` when attaching, and loops `while pid in
active_sessions()` when closing. Each call spawns `tasklist`.

**Change (`helpers.install_fast_process_lookup`):** when PyAEDT runtime
settings are configured, `general_methods._get_pids_by_name_windows` is replaced
with an equivalent `psutil` lookup. Same contract (same accepted names, same
PID list). Windows only and no-op if PyAEDT internals change. This is the main
source of the `connect`, `launch`, and `close` gains.

### 3. Unused persistent Python subprocess at startup
The base class `PyAnsysBaseMCP` started a persistent interpreter that imported
Matplotlib and PyVista. No PyAEDT-MCP tool uses it, because `run_python_code`
executes in-process to share the live `Desktop`.

**Change (`server.py`):** `need_python=False` by default (opt-in via
`PyAEDTMCP(need_python=True)`). Saves 2 processes, ~200 MB, and ~1.2 s per
server start, and removes a possible start-up failure point.

### 4. Async tools blocked the MCP event loop
`launch_aedt`, `connect_to_aedt`, and `disconnect_from_aedt` are `async` but ran
blocking PyAEDT and gRPC calls directly on the event loop. While they ran
(up to ~10 s), the server could not answer pings, other requests,
cancellations, or progress updates. Sync tools were already offloaded by FastMCP.

**Change (`tools.py`):** the blocking parts run in `anyio.to_thread.run_sync`.
This is the same worker-thread model FastMCP already uses for every sync tool,
so it adds no new thread-affinity risk.

### 5. `run_python_code` ergonomics (fewer and cheaper agent round trips)
- **Persistent namespace per connection:** variables and app objects (for
  example `hfss`) survive between calls, so agents no longer re-create an app
  (~0.4 s and extra AEDT calls) for every edit. The namespace is reset on
  `disconnect_from_aedt` and `clear_aedt`. A stale `result` is never returned.
- **Captured `print` output** (stdout and stderr) is returned, so values are no
  longer lost unless assigned to `result`. Output is truncated to its last
  20 000 characters.
- **Actionable errors:** the exception type, failing line number, and source
  line, plus any output printed before the error. This helps the LLM fix code
  in one retry.
- Executions are serialized with a lock (stdout redirection is process-wide,
  and AEDT handles one scripted operation at a time).

### 6. Smaller tool output for the LLM
JSON tool results (`check_aedt_status`, `list_designs`, `list_projects`,
`get_pyaedt_logs`, `export_config`, `get_model_info`) are now compact
(`separators=(",", ":")`) instead of `indent=2`. That is about 20-25% fewer
characters for the same data, and less context consumed per call
(`check_aedt_status` payload: 826 to 663 characters).

### 7. `get_pyaedt_logs` reads only the tail
Previously it read and split the whole rotating log file on every call. Now it
counts lines on raw bytes and decodes only the last 2 MB when no filter is set.
Output is identical. This gives a constant cost as logs grow.

### 8. Internal prompts (`prompts.py`, `toolsets.py`)
- Rule 1 no longer forces `check_aedt_installed` before every workflow. Agents
  start with `check_aedt_status` and call `check_aedt_installed` only before a
  launch or after a failed one. Live cost was ~0.95 s, plus one LLM round trip.
- Rule 7 no longer asks agents to prepend settings boilerplate to every snippet
  (`release_on_exception` is already set by the tool). It now tells agents to
  reuse persistent app objects, batch operations into one call, and use
  `print` or `result`. `pyedb_use_grpc` is only for EDB work.
- The scripting toolset skill no longer wrongly claims that `run_python_script`
  shares the `run_python_code` namespace (it runs in a separate process).

The instructions grow by 400 characters (+11%), in exchange for fewer LLM
round trips and fewer redundant calls per workflow.

## Reusable benchmark suite (`benchmarks/`)

| Script | Purpose |
|---|---|
| `bench_offline.py` | Startup, footprint, protocol and tool latency, concurrency, prompt size. No AEDT needed. |
| `bench_live.py` | Full agent workflow and launch/close against an isolated AEDT, with per-call event-loop monitoring and failure counting. |
| `compare.py` | Markdown diff of two result files (`results/comparison.md`). |
| `show.py` | Dumps every metric in one result file. |

See `benchmarks/README.md` for usage and how to compare any two revisions
with a git worktree.

## Tests

- Existing unit suite: 254 tests pass unchanged.
- New `tests/test_performance.py` (17 tests): psutil discovery parsing and
  fallback, PyAEDT lookup patch, `need_python` default, persistent namespace,
  stale `result`, print capture, error line reporting, syntax errors, output
  truncation, namespace reset on disconnect and clear, log tail correctness,
  compact JSON, and that `connect_to_aedt` does not block the event loop.
- `ruff check` and `ruff format` are clean.

## Behavior changes to note

- `run_python_code` now returns printed output when no `result` is set
  (previously "Code executed successfully..."). Error strings include the
  exception type, for example `Error executing code: ValueError: boom`.
- Variables now persist across `run_python_code` calls for the active
  connection.
- JSON tool output is compact (still valid JSON; parsers are unaffected).
- `PyAEDTMCP` no longer starts the base persistent Python session unless
  `need_python=True` is passed.
