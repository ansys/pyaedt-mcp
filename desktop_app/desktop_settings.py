"""Persisted user settings for the PyAEDT MCP desktop manager."""

from pathlib import Path

import yaml

SETTINGS_FILENAME = "settings.yaml"


def settings_path(application_directory: Path) -> Path:
    """Return the location of the user-owned desktop settings file."""
    return application_directory / SETTINGS_FILENAME


def load_settings(application_directory: Path) -> dict[str, bool | None]:
    """Load persisted desktop settings, returning defaults for a new installation."""
    path = settings_path(application_directory)
    if not path.is_file():
        return {"offline_install": None}
    try:
        settings = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise RuntimeError(f"{path} is not valid YAML: {error}") from error
    if not isinstance(settings, dict):
        raise RuntimeError(f"{path} must contain a YAML mapping")
    offline_install = settings.get("offline_install")
    if offline_install is not None and not isinstance(offline_install, bool):
        raise RuntimeError(f"{path} has an invalid offline_install value")
    return {"offline_install": offline_install}


def save_settings(application_directory: Path, *, offline_install: bool) -> Path:
    """Save desktop installation settings in the managed application directory."""
    path = settings_path(application_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {"offline_install": offline_install},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path
