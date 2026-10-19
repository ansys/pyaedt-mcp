"""Query and control PyAEDT MCP lanes through the installed ``--lanes`` command line."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess  # nosec B404
import time

from desktop_launcher import hidden_window_options

LANES_FLAG = "--lanes"
COMMAND_TIMEOUT_SECONDS = 60
DASHBOARD_URL_PATTERN = re.compile(r"http://127\.0\.0\.1:\d+/")
LANES_STATE_DIRECTORY_NAME = "ansys-aedt-mcp"
LANES_REGISTRY_FILENAME = "registry.json"


@dataclass(frozen=True)
class Lane:
    """One registered lane as reported by ``ansys-aedt-mcp --lanes status --json``."""

    lane_id: str
    http_port: int
    aedt_port: int | None
    pid: int | None
    listening: bool
    pid_alive: bool
    started_at: float | None

    @classmethod
    def from_status(cls, data: dict) -> "Lane":
        """Build a lane from one ``servers`` entry of the status JSON."""
        return cls(
            lane_id=str(data["server_id"]),
            http_port=int(data["http_port"]),
            aedt_port=data.get("aedt_gpc_port"),
            pid=data.get("pid"),
            listening=bool(data.get("listening")),
            pid_alive=bool(data.get("pid_alive")),
            started_at=data.get("started_at"),
        )

    @property
    def healthy(self) -> bool:
        """Whether the backend process is alive and serving its HTTP port."""
        return self.listening and self.pid_alive

    def uptime(self, now: float | None = None) -> str:
        """Return a compact uptime such as ``3h 12m``, or ``?`` when unknown."""
        if self.started_at is None:
            return "?"
        minutes = int(max(0.0, (now or time.time()) - self.started_at) // 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def lanes_registry_path() -> Path:
    """Return the per-user lanes registry, mirroring ``ansys.aedt.mcp.lanes.registry``."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / LANES_STATE_DIRECTORY_NAME / LANES_REGISTRY_FILENAME


def registered_lane_count() -> int:
    """Return how many lanes are registered, without starting any process."""
    try:
        data = json.loads(lanes_registry_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    servers = data.get("servers") if isinstance(data, dict) else None
    return len(servers) if isinstance(servers, dict) else 0


def lanes_profile_arguments(server_arguments: list[str]) -> list[str]:
    """Return Stdio profile arguments that start the lanes proxy.

    Server options are forwarded after ``--`` to every lane backend.
    """
    return [LANES_FLAG, "--", *server_arguments] if server_arguments else [LANES_FLAG]


class LanesClient:
    """Run lanes subcommands with the MCP command of the selected environment."""

    def __init__(self, command: Path) -> None:
        self.command = command

    def _arguments(self, *arguments: str) -> list[str]:
        return [str(self.command), LANES_FLAG, *arguments]

    def _run(self, *arguments: str) -> str:
        if not self.command.is_file():
            raise RuntimeError("Install PyAEDT MCP before managing lanes")
        result = subprocess.run(  # nosec B603
            self._arguments(*arguments),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
            **hidden_window_options(),
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            details = (result.stderr.strip() or output).splitlines()
            raise RuntimeError(details[-1] if details else f"exit code {result.returncode}")
        return output

    def list_lanes(self) -> list[Lane]:
        """Return the registered lanes with their liveness."""
        try:
            status = json.loads(self._run("status", "--json"))
        except ValueError as error:
            raise RuntimeError(f"Unexpected lanes status output: {error}") from error
        return sorted(
            (Lane.from_status(entry) for entry in status.get("servers", [])),
            key=lambda lane: lane.lane_id,
        )

    def stop(self, lane_id: str) -> str:
        """Stop a lane backend and remove it from the registry."""
        return self._run("stop", lane_id)

    def reap(self) -> str:
        """Drop registry entries whose backend is no longer running."""
        return self._run("reap")

    def reset(self) -> str:
        """Stop every lane process and clear the registry."""
        return self._run("reset", "--kill", "--yes")

    def start_dashboard(self) -> tuple[subprocess.Popen, str]:
        """Start the read-only lanes dashboard and return its process and URL."""
        if not self.command.is_file():
            raise RuntimeError("Install PyAEDT MCP before opening the lanes dashboard")
        process = subprocess.Popen(  # nosec B603
            self._arguments("dashboard", "--port", "0", "--no-browser"),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_window_options(),
        )
        first_line = process.stdout.readline() if process.stdout else ""
        match = DASHBOARD_URL_PATTERN.search(first_line)
        if match is None:
            process.kill()
            raise RuntimeError(first_line.strip() or "The lanes dashboard did not start")
        return process, match.group()
