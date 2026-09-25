#!/usr/bin/env bash
# entrypoint.sh – smart launcher for PyAEDT-MCP inside Docker
set -euo pipefail

CMD_ARGS=(
    ansys-aedt-mcp
    --transport http
    # HTTP_HOST/HTTP_PORT bind the process inside the container. Network
    # exposure to the host/network is controlled separately by the "ports"
    # mapping in docker-compose.yml (or -p flag), which should stay bound to
    # 127.0.0.1 unless the port is protected by a reverse proxy with
    # authentication, since this HTTP transport has no built-in auth.
    --http-host "${HTTP_HOST:-0.0.0.0}"
    --http-port "${HTTP_PORT:-8080}"
    --machine "${AEDT_MACHINE:-host.docker.internal}"
    --port   "${AEDT_PORT:-50051}"
)

# Optionally pass --version
if [ -n "${AEDT_VERSION:-}" ]; then
    CMD_ARGS+=(--version "$AEDT_VERSION")
fi

# Honour CONNECT_ON_STARTUP (default: false)
if [ "${CONNECT_ON_STARTUP:-false}" = "true" ]; then
    CMD_ARGS+=(--connect)
fi

# Non-graphical flag
if [ "${AEDT_NON_GRAPHICAL:-true}" = "true" ]; then
    CMD_ARGS+=(--non-graphical)
else
    CMD_ARGS+=(--graphical)
fi

exec "${CMD_ARGS[@]}"
