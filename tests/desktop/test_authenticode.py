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

"""Tests for Authenticode signature verification."""

import importlib.util
import os
from pathlib import Path
import sys

import pytest

_VSCODE_EXECUTABLE = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe"
)


@pytest.fixture(scope="module")
def authenticode():
    desktop_app_directory = Path(__file__).parents[2] / "desktop_app"
    script_path = desktop_app_directory / "authenticode.py"
    spec = importlib.util.spec_from_file_location("authenticode", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the authenticode script")
    module = importlib.util.module_from_spec(spec)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.syspath_prepend(str(desktop_app_directory))
        spec.loader.exec_module(module)
    return module


def test_verified_publisher_returns_none_for_missing_file(tmp_path, authenticode):
    assert authenticode.verified_publisher(tmp_path / "does-not-exist.exe") is None


def test_is_trusted_publisher_without_allowlist_falls_back_to_file_existence(
    tmp_path, authenticode
):
    executable = tmp_path / "agent.exe"
    executable.touch()

    assert authenticode.is_trusted_publisher(executable, []) is True
    assert authenticode.is_trusted_publisher(tmp_path / "missing.exe", []) is False


def test_is_trusted_publisher_rejects_unsigned_file_with_allowlist(tmp_path, authenticode):
    executable = tmp_path / "agent.exe"
    executable.write_bytes(b"not a signed executable")

    assert authenticode.is_trusted_publisher(executable, ["O=Microsoft Corporation"]) is False


@pytest.mark.skipif(sys.platform != "win32", reason="Authenticode verification is Windows-only")
@pytest.mark.skipif(not _VSCODE_EXECUTABLE.is_file(), reason="VS Code is not installed locally")
def test_verified_publisher_matches_real_signed_executable(authenticode):
    subject = authenticode.verified_publisher(_VSCODE_EXECUTABLE)

    assert subject is not None
    assert "Microsoft Corporation" in subject
    assert authenticode.is_trusted_publisher(_VSCODE_EXECUTABLE, ["O=Microsoft Corporation"])
    assert not authenticode.is_trusted_publisher(_VSCODE_EXECUTABLE, ["O=Some Other Vendor"])
