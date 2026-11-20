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

"""In-process PyAEDT version fixes applied by lane backends.

PyAEDT treats the newest installed AEDT that is not newer than its
``CURRENT_STABLE_AEDT_VERSION`` as the default. With a newer AEDT installed,
``launch_aedt`` without a version starts the older release, and
``connect_to_aedt(port=...)`` can decide the port belongs to another AEDT
version and launch a new session instead of attaching. Also, once a process
loads the gRPC client of one AEDT version it can never attach to another
version (``[WinError 127] The specified procedure could not be found``).

:func:`install` addresses this without modifying PyAEDT:

* The default version becomes the newest installed AEDT, or the one chosen
  with ``--aedt-version``.
* Attaching to a local port uses the version of the AEDT process on that port.
* Attaching to a version the process can no longer load fails fast with an
  actionable message.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
import functools
import inspect
import logging
import os
from pathlib import Path
import re
from typing import Any

VERSION_ENV = "ANSYS_AEDT_MCP_LANE_AEDT_VERSION"
"""Environment variable forwarding ``--aedt-version`` to lane backends."""

DEFAULT_PREFERENCE = "latest"

_MARKER = "_ansys_aedt_mcp_lanes_patched"
_RELEASE_RE = re.compile(r"^\d{4}\.\d$")
_LOCAL_MACHINES = {"", "localhost", "127.0.0.1", "::1"}
_VERSION_PATTERNS = (
    (r"(\d{2})(\d)", "20{}.{}"),
    (r"(\d{2})\.(\d)", "20{}.{}"),
    (r"(\d{4})\.(\d)", "{}.{}"),
    (r"(\d{4}) ?[rR](\d)", "{}.{}"),
)

logger = logging.getLogger(__name__)

_loaded_plugin_dir: str | None = None
"""Installation directory of the AEDT gRPC client loaded by this process."""


class AedtVersionClashError(RuntimeError):
    """Raised when the process already loaded another AEDT version's gRPC client."""


def normalize_version(value: Any) -> str:
    """Normalize an AEDT version to the ``YYYY.R`` form.

    Parameters
    ----------
    value : Any
        Version such as ``"271"``, ``"27.1"``, ``"2027.1"``, or ``"2027 R1"``.

    Returns
    -------
    str
        Normalized version, for example ``"2027.1"``.

    Raises
    ------
    ValueError
        If ``value`` is not a recognized AEDT version.
    """
    text = str(value).strip()
    for pattern, fmt in _VERSION_PATTERNS:
        match = re.fullmatch(pattern, text)
        if match:
            return fmt.format(*match.groups())
    raise ValueError(f"Not an AEDT version: {value!r} (expected e.g. 2027.1 or 271).")


def validate_preference(value: str) -> str:
    """Validate an ``--aedt-version`` value.

    Parameters
    ----------
    value : str
        ``"latest"``, ``"pyaedt"``, or an AEDT version.

    Returns
    -------
    str
        Normalized preference.

    Raises
    ------
    ValueError
        If ``value`` is not a valid preference.
    """
    text = value.strip().lower()
    if text in {"latest", "pyaedt"}:
        return text
    return normalize_version(text)


def resolve_default_version(preference: str, installed: Iterable[str]) -> str | None:
    """Map an ``--aedt-version`` preference to the version to pin.

    Parameters
    ----------
    preference : str
        ``"latest"`` picks the newest regular release in ``installed``,
        ignoring student and client variants. ``"pyaedt"`` keeps the PyAEDT
        default. Any other value is an explicit version.
    installed : Iterable[str]
        Installed version keys, as in ``aedt_versions.installed_versions``.

    Returns
    -------
    str or None
        Version to pin, or ``None`` to leave PyAEDT unchanged.
    """
    pref = validate_preference(preference or DEFAULT_PREFERENCE)
    if pref == "pyaedt":
        return None
    if pref == "latest":
        releases = [key for key in installed if _RELEASE_RE.fullmatch(key)]
        return max(releases, key=float) if releases else None
    return pref


def pin_default_version(version: str) -> None:
    """Make ``version`` the PyAEDT default for this process.

    Parameters
    ----------
    version : str
        Normalized AEDT version.
    """
    from ansys.aedt.core.internal import aedt_versions as versions_mod

    versions_mod.CURRENT_STABLE_AEDT_VERSION = float(version)
    cache = versions_mod.aedt_versions
    cache._stable_versions = None
    cache._current_version = None
    cache._current_student_version = None


def _session_on_port(port: int) -> tuple[str, bool] | None:
    """Return the version and student flag of the local AEDT serving ``port``."""
    try:
        from ansys.aedt.core.cli.aedt import _discover_aedt_sessions

        sessions = _discover_aedt_sessions()
    except Exception:
        logger.debug("AEDT session discovery failed", exc_info=True)
        return None
    for session in sessions:
        if session.port == port and _RELEASE_RE.fullmatch(str(session.version)):
            return str(session.version), bool(session.student_version)
    return None


def _same_dir(first: str, second: str) -> bool:
    """Check whether two paths point to the same directory."""
    return os.path.normcase(Path(first).resolve()) == os.path.normcase(Path(second).resolve())


def _try_normalize(value: Any) -> str | None:
    try:
        return normalize_version(value)
    except ValueError:
        return None


def rewrite_desktop_arguments(
    arguments: dict[str, Any],
    *,
    find_session: Callable[[int], tuple[str, bool] | None],
    installed: dict[str, str],
    loaded_plugin_dir: str | None,
    reusing_session: bool,
) -> list[str]:
    """Fix ``Desktop.__init__`` arguments in place.

    Parameters
    ----------
    arguments : dict[str, Any]
        Bound ``Desktop.__init__`` arguments with defaults applied.
    find_session : Callable[[int], tuple[str, bool] | None]
        Returns the version and student flag of the AEDT serving a port.
    installed : dict[str, str]
        Installed versions mapped to their installation directories.
    loaded_plugin_dir : str, optional
        Directory of the gRPC client already loaded by the process.
    reusing_session : bool
        Whether PyAEDT is about to return an existing session. In that case
        nothing is changed.

    Returns
    -------
    list[str]
        Log messages describing the changes.

    Raises
    ------
    AedtVersionClashError
        If the target version cannot be loaded by this process.
    """
    if reusing_session:
        return []
    notes: list[str] = []
    port = int(arguments.get("port") or 0)
    machine = str(arguments.get("machine") or "").strip().lower()
    if not arguments.get("new_desktop", True) and port > 0 and machine in _LOCAL_MACHINES:
        found = find_session(port)
        if found is not None:
            actual, student = found
            requested = arguments.get("version")
            if (_try_normalize(requested) if requested else None) != actual:
                notes.append(
                    f"AEDT on port {port} is {actual}{' (student)' if student else ''}; "
                    f"attaching as {actual} instead of {requested or 'the PyAEDT default'}."
                )
                arguments["version"] = actual
            arguments["student_version"] = student

    target = arguments.get("version")
    if target and loaded_plugin_dir:
        normalized = _try_normalize(target)
        key = f"{normalized}{'SV' if arguments.get('student_version') else ''}"
        target_dir = installed.get(key) if normalized else None
        if target_dir and not _same_dir(target_dir, loaded_plugin_dir):
            raise AedtVersionClashError(
                f"This lane backend already loaded the AEDT gRPC client from {loaded_plugin_dir}, "
                f"so it cannot attach to AEDT {target} ({target_dir}) in the same process "
                "(PyAEDT would fail with '[WinError 127] The specified procedure could not be "
                "found'). Run recycle_lane to restart this lane's backend, then connect again, "
                "or spawn_lane a new lane for this AEDT version."
            )
    return notes


def _patch_grpc_plugin() -> None:
    """Record the directory of the first gRPC client the process loads."""
    from ansys.aedt.core.internal import grpc_plugin_dll_class as plugin_mod

    original = plugin_mod.AEDT.__init__
    if getattr(original, _MARKER, False):
        return

    @functools.wraps(original)
    def patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        global _loaded_plugin_dir
        original(self, *args, **kwargs)
        if _loaded_plugin_dir is None:
            _loaded_plugin_dir = str(self.pathDir)

    setattr(patched_init, _MARKER, True)
    plugin_mod.AEDT.__init__ = patched_init  # type: ignore[method-assign]


def _patch_desktop() -> None:
    """Route ``Desktop.__init__`` through :func:`rewrite_desktop_arguments`."""
    from ansys.aedt.core import desktop as desktop_mod
    from ansys.aedt.core.generic.settings import settings
    from ansys.aedt.core.internal.aedt_versions import aedt_versions

    desktop_cls = desktop_mod.Desktop
    original = desktop_cls.__init__
    if getattr(original, _MARKER, False):
        return
    signature = inspect.signature(original)

    @functools.wraps(original)
    def patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        try:
            bound = signature.bind(self, *args, **kwargs)
        except TypeError:
            return original(self, *args, **kwargs)
        bound.apply_defaults()
        reusing = bool(desktop_mod._desktop_sessions) and not settings.use_multi_desktop
        try:
            notes = rewrite_desktop_arguments(
                bound.arguments,
                find_session=_session_on_port,
                installed=aedt_versions.installed_versions,
                loaded_plugin_dir=_loaded_plugin_dir,
                reusing_session=reusing,
            )
        except AedtVersionClashError:
            raise
        except Exception:
            logger.warning("AEDT version check skipped", exc_info=True)
            return original(self, *args, **kwargs)
        for note in notes:
            logger.warning(note)
        return original(*bound.args, **bound.kwargs)

    setattr(patched_init, _MARKER, True)
    desktop_cls.__init__ = patched_init  # type: ignore[method-assign]


def install(preference: str | None = None) -> str | None:
    """Apply the version fixes to this process.

    Calling it more than once is safe.

    Parameters
    ----------
    preference : str, optional
        AEDT version preference. Defaults to :data:`VERSION_ENV`, then ``"latest"``.

    Returns
    -------
    str or None
        Pinned default version, or ``None`` if the PyAEDT default is kept.
    """
    from ansys.aedt.core.internal.aedt_versions import aedt_versions

    preference = preference or os.environ.get(VERSION_ENV) or DEFAULT_PREFERENCE
    pinned = resolve_default_version(preference, aedt_versions.installed_versions)
    if pinned is not None:
        pin_default_version(pinned)
        logger.warning("Default AEDT version pinned to %s (--aedt-version %s).", pinned, preference)
    _patch_grpc_plugin()
    _patch_desktop()
    return pinned
