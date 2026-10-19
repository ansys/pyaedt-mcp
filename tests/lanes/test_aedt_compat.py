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

"""Unit tests for the in-process PyAEDT version fixes of lane backends."""

import warnings

import pytest

from ansys.aedt.mcp.lanes import aedt_compat

# PyAEDT's import chain emits third-party DeprecationWarnings.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import ansys.aedt.core.cli.aedt  # noqa: F401
    import ansys.aedt.core.desktop  # noqa: F401
    import ansys.aedt.core.internal.grpc_plugin_dll_class  # noqa: F401

pytestmark = pytest.mark.unit

V271 = r"C:\Program Files\ANSYS Inc\v271\AnsysEM"
V261 = r"C:\Program Files\ANSYS Inc\v261\AnsysEM"
INSTALLED = {
    "2027.1": V271,
    "2026.1": V261,
    "2027.1AWP": r"C:\Program Files\ANSYS Inc\v271",
    "2026.1SV": r"C:\Program Files\ANSYS Inc\ANSYS Student\v261\AnsysEM",
}


@pytest.fixture
def versions(monkeypatch):
    """PyAEDT version cache with a fake 2027.1 + 2026.1 install, restored afterwards."""
    from ansys.aedt.core.internal import aedt_versions as versions_mod

    cache = versions_mod.aedt_versions
    monkeypatch.setattr(versions_mod, "CURRENT_STABLE_AEDT_VERSION", 2026.1)
    monkeypatch.setattr(cache, "_installed_versions", dict(INSTALLED))
    for attr in (
        "_stable_versions",
        "_current_version",
        "_current_student_version",
        "_latest_version",
    ):
        monkeypatch.setattr(cache, attr, None)
    return cache


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("271", "2027.1"),
        ("27.1", "2027.1"),
        ("2027.1", "2027.1"),
        ("2027 R1", "2027.1"),
        (2026.1, "2026.1"),
    ],
)
def test_normalize_version(raw, expected):
    assert aedt_compat.normalize_version(raw) == expected


@pytest.mark.parametrize("raw", ["", "latest", "2027", "v271", "2027.12"])
def test_normalize_version_rejects_garbage(raw):
    with pytest.raises(ValueError):
        aedt_compat.normalize_version(raw)


def test_validate_preference():
    assert aedt_compat.validate_preference(" Latest ") == "latest"
    assert aedt_compat.validate_preference("PyAEDT") == "pyaedt"
    assert aedt_compat.validate_preference("271") == "2027.1"
    with pytest.raises(ValueError):
        aedt_compat.validate_preference("newest")


def test_resolve_default_version():
    assert aedt_compat.resolve_default_version("latest", INSTALLED) == "2027.1"
    assert aedt_compat.resolve_default_version("LATEST", ["2026.1SV", "2025.2"]) == "2025.2"
    assert aedt_compat.resolve_default_version("latest", ["2026.1SV"]) is None
    assert aedt_compat.resolve_default_version("pyaedt", INSTALLED) is None
    assert aedt_compat.resolve_default_version("261", INSTALLED) == "2026.1"
    with pytest.raises(ValueError):
        aedt_compat.resolve_default_version("newest", INSTALLED)


def test_cli_rejects_bad_aedt_version(capsys):
    from ansys.aedt.mcp.lanes import cli

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--aedt-version", "newest"])
    assert exc_info.value.code == 2
    assert "--aedt-version" in capsys.readouterr().err


def test_pyaedt_caps_default_at_its_stable_version(versions):
    """The upstream behavior this module works around."""
    assert versions.current_version == "2026.1"


def test_pin_default_version(versions):
    aedt_compat.pin_default_version("2027.1")
    assert versions.current_version == "2027.1"
    assert "2027.1" in versions.stable_versions


def test_install_pins_latest_and_patches_once(versions, monkeypatch):
    from ansys.aedt.core import desktop as desktop_mod
    from ansys.aedt.core.internal import grpc_plugin_dll_class as plugin_mod

    monkeypatch.setattr(desktop_mod.Desktop, "__init__", desktop_mod.Desktop.__init__)
    monkeypatch.setattr(plugin_mod.AEDT, "__init__", plugin_mod.AEDT.__init__)
    monkeypatch.delenv(aedt_compat.VERSION_ENV, raising=False)

    assert aedt_compat.install() == "2027.1"
    patched = desktop_mod.Desktop.__init__
    assert getattr(patched, aedt_compat._MARKER)
    assert getattr(plugin_mod.AEDT.__init__, aedt_compat._MARKER)
    assert versions.current_version == "2027.1"

    monkeypatch.setenv(aedt_compat.VERSION_ENV, "pyaedt")
    assert aedt_compat.install() is None
    assert desktop_mod.Desktop.__init__ is patched


def _args(**overrides):
    base = {
        "version": None,
        "non_graphical": False,
        "new_desktop": False,
        "close_on_exit": None,
        "student_version": False,
        "machine": "localhost",
        "port": 50051,
        "aedt_process_id": None,
    }
    return {**base, **overrides}


def _rewrite(arguments, session=("2027.1", False), loaded=None, reusing=False):
    return aedt_compat.rewrite_desktop_arguments(
        arguments,
        find_session=lambda port: session if port == 50051 else None,
        installed=INSTALLED,
        loaded_plugin_dir=loaded,
        reusing_session=reusing,
    )


def test_attach_uses_version_of_the_aedt_on_the_port():
    arguments = _args()
    notes = _rewrite(arguments)
    assert arguments["version"] == "2027.1"
    assert "port 50051 is 2027.1" in notes[0]


def test_attach_overrides_a_wrong_explicit_version():
    arguments = _args(version="2026.1")
    _rewrite(arguments)
    assert arguments["version"] == "2027.1"


def test_attach_with_matching_version_is_untouched():
    arguments = _args(version="271")
    assert _rewrite(arguments) == []
    assert arguments["version"] == "271"


def test_attach_to_student_session_sets_student_flag():
    arguments = _args()
    _rewrite(arguments, session=("2026.1", True))
    assert arguments["version"] == "2026.1"
    assert arguments["student_version"] is True


@pytest.mark.parametrize(
    "overrides",
    [{"new_desktop": True}, {"machine": "remote-box"}, {"port": 0}, {"port": 50052}],
)
def test_non_local_attach_calls_are_untouched(overrides):
    arguments = _args(**overrides)
    assert _rewrite(arguments) == []
    assert arguments["version"] is None


def test_reused_session_is_untouched():
    arguments = _args(version="2026.1")
    assert _rewrite(arguments, loaded=V271, reusing=True) == []
    assert arguments["version"] == "2026.1"


def test_attach_to_other_version_than_loaded_plugin_fails_fast():
    with pytest.raises(aedt_compat.AedtVersionClashError, match="recycle_lane"):
        _rewrite(_args(), loaded=V261)


def test_same_version_as_loaded_plugin_is_allowed():
    arguments = _args()
    _rewrite(arguments, loaded=V271)
    assert arguments["version"] == "2027.1"


def test_default_version_call_is_not_guarded():
    """``version=None`` without a resolvable port keeps the PyAEDT default and no guard."""
    arguments = _args(new_desktop=True)
    assert _rewrite(arguments, loaded=V261) == []
