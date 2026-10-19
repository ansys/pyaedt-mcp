"""Windows Authenticode signature verification for locally installed executables."""

import os
from pathlib import Path
import subprocess  # nosec B404


def _quote_powershell_string(value: str) -> str:
    """Escape `value` as a single-quoted PowerShell string literal."""
    return "'" + value.replace("'", "''") + "'"


def verified_publisher(executable: Path) -> str | None:
    """Return the Authenticode signer subject for a validly signed, trusted executable.

    Returns ``None`` if the platform is not Windows, the file is missing, unsigned,
    or its signature does not chain to a trusted root (e.g. tampered or self-signed).
    """
    if os.name != "nt" or not executable.is_file():
        return None
    # Embed the path as a quoted literal rather than a separate argv entry: `-Command`
    # does not bind trailing arguments to `$args`, and paths may contain spaces.
    quoted_path = _quote_powershell_string(str(executable))
    script = (
        f"$signature = Get-AuthenticodeSignature -LiteralPath {quoted_path}; "
        "if ($signature.Status -eq 'Valid') { $signature.SignerCertificate.Subject }"
    )
    try:
        result = subprocess.run(  # nosec B603 B607
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    subject = result.stdout.strip()
    return subject or None


def is_trusted_publisher(executable: Path, trusted_publishers: list[str]) -> bool:
    """Return whether `executable` is validly signed by one of the given publishers.

    An empty `trusted_publishers` list means no allow-list is configured for this agent,
    so detection falls back to the caller's existing (non-signature) check.
    """
    if not trusted_publishers:
        return executable.is_file()
    subject = verified_publisher(executable)
    if subject is None:
        return False
    return any(publisher in subject for publisher in trusted_publishers)
