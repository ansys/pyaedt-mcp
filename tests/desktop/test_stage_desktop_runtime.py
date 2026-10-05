"""Tests for staging the desktop runtime payload."""

import hashlib
import importlib.util
from pathlib import Path
import zipfile

import pytest


@pytest.fixture(scope="module")
def runtime_stager():
    desktop_app_directory = Path(__file__).parents[2] / "desktop_app"
    script_path = desktop_app_directory / "stage_desktop_runtime.py"
    spec = importlib.util.spec_from_file_location("stage_desktop_runtime", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the desktop runtime staging script")
    module = importlib.util.module_from_spec(spec)
    # Only exposed on sys.path for the duration of the import, not the whole test session.
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.syspath_prepend(str(desktop_app_directory))
        spec.loader.exec_module(module)
    return module


def _write_zip(path: Path, files: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def _fake_urlretrieve(source_archive: Path):
    def _urlretrieve(url, filename):  # noqa: ARG001 - signature matches urllib.request.urlretrieve
        Path(filename).write_bytes(source_archive.read_bytes())

    return _urlretrieve


def test_stage_embedded_python_downloads_verifies_and_extracts(tmp_path, monkeypatch, runtime_stager):
    source_archive = tmp_path / "download-source" / "python-embed-amd64.zip"
    _write_zip(source_archive, {"python.exe": b"python executable", "python313.dll": b"dll"})
    checksum = hashlib.sha256(source_archive.read_bytes()).hexdigest()
    monkeypatch.setattr(runtime_stager, "PYTHON_ARCHIVE_SHA256", checksum)
    monkeypatch.setattr(runtime_stager.urllib.request, "urlretrieve", _fake_urlretrieve(source_archive))

    runtime_dir = tmp_path / "runtime"
    runtime_stager.stage_embedded_python(runtime_dir)

    assert (runtime_dir / "python" / "python.exe").read_bytes() == b"python executable"
    assert not (runtime_dir.parent / source_archive.name).exists()


def test_stage_embedded_python_rejects_checksum_mismatch(tmp_path, monkeypatch, runtime_stager):
    source_archive = tmp_path / "download-source" / "python-embed-amd64.zip"
    _write_zip(source_archive, {"python.exe": b"python executable"})
    monkeypatch.setattr(runtime_stager, "PYTHON_ARCHIVE_SHA256", "0" * 64)
    monkeypatch.setattr(runtime_stager.urllib.request, "urlretrieve", _fake_urlretrieve(source_archive))

    runtime_dir = tmp_path / "runtime"
    with pytest.raises(RuntimeError, match="Unexpected SHA-256"):
        runtime_stager.stage_embedded_python(runtime_dir)

    assert not (runtime_dir.parent / source_archive.name).exists()
    assert not (runtime_dir / "python").exists()


def test_stage_embedded_python_rejects_archive_missing_executable(tmp_path, monkeypatch, runtime_stager):
    source_archive = tmp_path / "download-source" / "python-embed-amd64.zip"
    _write_zip(source_archive, {"README.txt": b"no python here"})
    checksum = hashlib.sha256(source_archive.read_bytes()).hexdigest()
    monkeypatch.setattr(runtime_stager, "PYTHON_ARCHIVE_SHA256", checksum)
    monkeypatch.setattr(runtime_stager.urllib.request, "urlretrieve", _fake_urlretrieve(source_archive))

    runtime_dir = tmp_path / "runtime"
    with pytest.raises(RuntimeError, match="does not contain python.exe"):
        runtime_stager.stage_embedded_python(runtime_dir)


def test_stage_uv_downloads_verifies_and_extracts(tmp_path, monkeypatch, runtime_stager):
    source_archive = tmp_path / "download-source" / "uv-x86_64-pc-windows-msvc.zip"
    _write_zip(source_archive, {"uv.exe": b"uv executable", "uvx.exe": b"uvx executable"})
    checksum = hashlib.sha256(source_archive.read_bytes()).hexdigest()
    monkeypatch.setattr(runtime_stager, "UV_ARCHIVE_SHA256", checksum)
    monkeypatch.setattr(runtime_stager.urllib.request, "urlretrieve", _fake_urlretrieve(source_archive))

    runtime_dir = tmp_path / "runtime"
    runtime_stager.stage_uv(runtime_dir)

    assert (runtime_dir / "uv" / "uv.exe").read_bytes() == b"uv executable"
    assert not (runtime_dir.parent / source_archive.name).exists()


def test_stage_uv_rejects_checksum_mismatch(tmp_path, monkeypatch, runtime_stager):
    source_archive = tmp_path / "download-source" / "uv-x86_64-pc-windows-msvc.zip"
    _write_zip(source_archive, {"uv.exe": b"uv executable"})
    monkeypatch.setattr(runtime_stager, "UV_ARCHIVE_SHA256", "0" * 64)
    monkeypatch.setattr(runtime_stager.urllib.request, "urlretrieve", _fake_urlretrieve(source_archive))

    runtime_dir = tmp_path / "runtime"
    with pytest.raises(RuntimeError, match="Unexpected SHA-256"):
        runtime_stager.stage_uv(runtime_dir)

    assert not (runtime_dir.parent / source_archive.name).exists()
    assert not (runtime_dir / "uv").exists()


def test_stage_uv_rejects_archive_missing_executable(tmp_path, monkeypatch, runtime_stager):
    source_archive = tmp_path / "download-source" / "uv-x86_64-pc-windows-msvc.zip"
    _write_zip(source_archive, {"README.txt": b"no uv here"})
    checksum = hashlib.sha256(source_archive.read_bytes()).hexdigest()
    monkeypatch.setattr(runtime_stager, "UV_ARCHIVE_SHA256", checksum)
    monkeypatch.setattr(runtime_stager.urllib.request, "urlretrieve", _fake_urlretrieve(source_archive))

    runtime_dir = tmp_path / "runtime"
    with pytest.raises(RuntimeError, match="does not contain uv.exe"):
        runtime_stager.stage_uv(runtime_dir)
