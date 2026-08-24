"""Install PyAEDT MCP profiles for common coding agents on Windows."""

import json
from pathlib import Path

SERVER_NAME = "pyaedt-mcp"
STDIO_TRANSPORT = "stdio"
HTTP_TRANSPORT = "http"


def profile_command(executable: Path, server_arguments: list[str]) -> tuple[str, list[str]]:
    """Build the executable command used by MCP client configuration files."""
    return str(executable), ["--server", *server_arguments]


def _validate_transport(transport: str) -> None:
    if transport not in {STDIO_TRANSPORT, HTTP_TRANSPORT}:
        raise ValueError(f"Unsupported MCP transport: {transport}")


def _configuration_file(path: Path, default_filename: str) -> Path:
    """Resolve a folder or explicitly named configuration file path."""
    return path if path.suffix else path / default_filename


def _json_profile(
    executable: Path,
    server_arguments: list[str],
    transport: str,
    http_url: str,
    *,
    copilot: bool = False,
) -> dict:
    _validate_transport(transport)
    if transport == HTTP_TRANSPORT:
        profile: dict[str, object] = {"type": "http", "url": http_url}
    else:
        command, arguments = profile_command(executable, server_arguments)
        profile = {"command": command, "args": arguments}
        if copilot:
            profile["type"] = "local"
    if copilot:
        profile["tools"] = ["*"]
    return profile


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{path} is not valid JSON: {error.msg}") from error
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return data


def _write_json_profile(path: Path, container_key: str, profile: dict) -> Path:
    data = _read_json(path)
    profiles = data.setdefault(container_key, {})
    if not isinstance(profiles, dict):
        raise RuntimeError(f"{path} has an invalid {container_key!r} section")
    profiles[SERVER_NAME] = profile
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def install_vscode_profile(workspace: Path, executable: Path, server_arguments: list[str]) -> Path:
    """Install the profile in a workspace's VS Code/Copilot configuration."""
    command, arguments = profile_command(executable, server_arguments)
    return _write_json_profile(
        workspace / ".vscode" / "mcp.json",
        "servers",
        {"type": "stdio", "command": command, "args": arguments},
    )


def install_copilot_cli_profile(
    configuration_directory: Path,
    executable: Path,
    server_arguments: list[str],
    transport: str = STDIO_TRANSPORT,
    http_url: str = "",
) -> Path:
    """Install the profile in GitHub Copilot CLI's configuration file."""
    return _write_json_profile(
        _configuration_file(configuration_directory, "mcp-config.json"),
        "mcpServers",
        _json_profile(executable, server_arguments, transport, http_url, copilot=True),
    )


def install_claude_desktop_profile(
    configuration_directory: Path,
    executable: Path,
    server_arguments: list[str],
    transport: str = STDIO_TRANSPORT,
    http_url: str = "",
) -> Path:
    """Install the profile in Claude Desktop's configuration file."""
    return _write_json_profile(
        _configuration_file(configuration_directory, "claude_desktop_config.json"),
        "mcpServers",
        _json_profile(executable, server_arguments, transport, http_url),
    )


def install_cursor_profile(
    configuration_directory: Path,
    executable: Path,
    server_arguments: list[str],
    transport: str = STDIO_TRANSPORT,
    http_url: str = "",
) -> Path:
    """Install the profile in Cursor's MCP configuration file."""
    return _write_json_profile(
        _configuration_file(configuration_directory, "mcp.json"),
        "mcpServers",
        _json_profile(executable, server_arguments, transport, http_url),
    )


def install_codex_profile(
    configuration_directory: Path,
    executable: Path,
    server_arguments: list[str],
    transport: str = STDIO_TRANSPORT,
    http_url: str = "",
) -> Path:
    """Install the profile in Codex's TOML configuration file."""
    _validate_transport(transport)
    path = _configuration_file(configuration_directory, "config.toml")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = path.read_text(encoding="utf-8") if path.is_file() else ""
    header = f"[mcp_servers.{SERVER_NAME}]"
    if header in content:
        start = content.index(header)
        next_section = content.find("\n[", start + len(header))
        content = content[:start] + (content[next_section + 1 :] if next_section != -1 else "")
    if transport == HTTP_TRANSPORT:
        profile_content = f"url = {json.dumps(http_url)}"
    else:
        command, arguments = profile_command(executable, server_arguments)
        profile_content = f"command = {json.dumps(command)}\nargs = {json.dumps(arguments)}"
    path.write_text(
        f"{content.rstrip()}\n\n{header}\n{profile_content}\n",
        encoding="utf-8",
    )
    return path


def install_claude_code_profile(
    configuration_directory: Path,
    executable: Path,
    server_arguments: list[str],
    transport: str = STDIO_TRANSPORT,
    http_url: str = "",
) -> Path:
    """Install the profile in Claude Code's user configuration file."""
    return _write_json_profile(
        _configuration_file(configuration_directory, ".claude.json"),
        "mcpServers",
        _json_profile(executable, server_arguments, transport, http_url),
    )


def install_opencode_profile(
    configuration_directory: Path,
    executable: Path,
    server_arguments: list[str],
    transport: str = STDIO_TRANSPORT,
    http_url: str = "",
) -> Path:
    """Install the profile in OpenCode's global configuration file."""
    _validate_transport(transport)
    if transport == HTTP_TRANSPORT:
        profile: dict[str, object] = {"type": "remote", "url": http_url}
    else:
        command, arguments = profile_command(executable, server_arguments)
        profile = {"type": "local", "command": [command, *arguments]}
    return _write_json_profile(
        _configuration_file(configuration_directory, "opencode.json"), "mcp", profile
    )
