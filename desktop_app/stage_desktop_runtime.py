"""Stage the embedded runtime payload for the Windows MCP executable."""

import hashlib
from pathlib import Path
import shutil
import sys
import urllib.request
import zipfile

CPYTHON_VERSION = "3.13.8"
ARCHIVE_URL = (
    f"https://www.python.org/ftp/python/{CPYTHON_VERSION}/python-{CPYTHON_VERSION}-embed-amd64.zip"
)
ARCHIVE_SHA256 = "3de305b550bdc582f7c31a0f286f5b08c453ae5628ef2800a1bb1f86a42b746c"
RUNTIME_DIR = Path(__file__).resolve().parent / ".desktop-runtime"


def stage_embedded_python(runtime_dir: Path) -> None:
    """Download and unpack the verified Windows CPython embedded distribution."""
    archive_path = runtime_dir.parent / Path(ARCHIVE_URL).name
    runtime_dir.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading CPython {CPYTHON_VERSION} embedded distribution")
    urllib.request.urlretrieve(ARCHIVE_URL, archive_path)  # nosec B310

    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if checksum != ARCHIVE_SHA256:
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
    """Copy uv from the release environment into the distributable payload."""
    uv_executable = shutil.which("uv")
    if uv_executable is None:
        raise RuntimeError("uv must be available on PATH to build the Windows executable")

    uv_dir = runtime_dir / "uv"
    shutil.rmtree(uv_dir, ignore_errors=True)
    uv_dir.mkdir(parents=True)
    shutil.copy2(uv_executable, uv_dir / "uv.exe")


def main() -> int:
    stage_embedded_python(RUNTIME_DIR)
    stage_uv(RUNTIME_DIR)
    print(f"Staged embedded runtime at {RUNTIME_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
