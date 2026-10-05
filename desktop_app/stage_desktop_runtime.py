"""Stage the embedded runtime payload for the Windows MCP executable."""

import hashlib
from pathlib import Path
import shutil
import sys
import urllib.request
import zipfile

from desktop_config import (
    ARCHIVE_URL,
    CPYTHON_VERSION,
    PYTHON_ARCHIVE_SHA256,
    UV_ARCHIVE_SHA256,
    UV_ARCHIVE_URL,
    UV_VERSION,
)

RUNTIME_DIR = Path(__file__).resolve().parent / ".desktop-runtime"


def stage_embedded_python(runtime_dir: Path) -> None:
    """Download and unpack the verified Windows CPython embedded distribution.

    Parameters
    ----------
    runtime_dir : Path
        The directory where the embedded Python runtime should be staged.
    """
    archive_path = runtime_dir.parent / Path(ARCHIVE_URL).name
    runtime_dir.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading CPython {CPYTHON_VERSION} embedded distribution")
    urllib.request.urlretrieve(ARCHIVE_URL, archive_path)  # nosec B310

    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if checksum != PYTHON_ARCHIVE_SHA256:
        archive_path.unlink(missing_ok=True)
        raise RuntimeError(f"Unexpected SHA-256 for {archive_path.name}: {checksum}")

    python_dir = runtime_dir / "python"
    shutil.rmtree(python_dir, ignore_errors=True)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(python_dir)
    archive_path.unlink()

    if not (python_dir / "python.exe").is_file():
        raise RuntimeError("Embedded CPython archive does not contain python.exe")


def stage_uv(runtime_dir: Path) -> None:
    """Download and unpack the verified uv release, rather than trusting whatever uv is on PATH.

    Parameters
    ----------
    runtime_dir : Path
        The directory where the uv release should be staged.
    """
    archive_path = runtime_dir.parent / Path(UV_ARCHIVE_URL).name
    runtime_dir.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading uv {UV_VERSION} release")
    urllib.request.urlretrieve(UV_ARCHIVE_URL, archive_path)  # nosec B310

    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if checksum != UV_ARCHIVE_SHA256:
        archive_path.unlink(missing_ok=True)
        raise RuntimeError(f"Unexpected SHA-256 for {archive_path.name}: {checksum}")

    uv_dir = runtime_dir / "uv"
    shutil.rmtree(uv_dir, ignore_errors=True)
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(uv_dir)
    archive_path.unlink()

    if not (uv_dir / "uv.exe").is_file():
        raise RuntimeError("uv release archive does not contain uv.exe")


def main() -> int:
    stage_embedded_python(RUNTIME_DIR)
    stage_uv(RUNTIME_DIR)
    print(f"Staged embedded runtime at {RUNTIME_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
