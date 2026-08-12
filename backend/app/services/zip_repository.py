"""Safe extraction of uploaded repository archives.

Security posture: an uploaded archive is **untrusted input**. This module
treats it as data, never as code.

  * No uploaded file is ever imported, executed, or evaluated.
  * No setup script, `__init__.py`, `setup.py` or `conftest.py` is run.
  * Analysis is text parsing only (`ast.parse`), performed elsewhere.

Extraction itself is the risky part, so it is done member-by-member with
explicit checks rather than `ZipFile.extractall`:

  * path traversal / zip-slip (`../`, absolute paths, drive letters) rejected
  * symlinks and non-regular members rejected
  * archive size, entry count and per-file size capped (zip-bomb guard)
"""

from __future__ import annotations

import shutil
import uuid
import zipfile
from pathlib import Path

from app.config import get_settings


# Holds the uploaded repository's display name. Dot-prefixed so the analysis
# walker skips it.
NAME_MARKER = ".designsync_name"


class UnsafeArchiveError(ValueError):
    """The archive was rejected before anything was written to disk."""


def _is_unsafe_member(name: str) -> str | None:
    """Return a rejection reason for an unsafe entry name, else None."""
    normalized = name.replace("\\", "/")

    if normalized.startswith("/"):
        return f"absolute path in archive: {name}"
    if ":" in normalized.split("/")[0]:
        return f"drive-qualified path in archive: {name}"
    parts = [p for p in normalized.split("/") if p]
    if any(part == ".." for part in parts):
        return f"path traversal in archive: {name}"
    return None


def validate_archive(data: bytes) -> None:
    """Validate an archive's bytes. Raises `UnsafeArchiveError` if unacceptable."""
    settings = get_settings()

    if not data:
        raise UnsafeArchiveError("Uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise UnsafeArchiveError(
            f"Archive is larger than the {settings.max_upload_bytes // (1024 * 1024)}MB limit."
        )


def extract_zip(data: bytes, original_name: str = "uploaded-repository") -> tuple[str, Path]:
    """Extract an uploaded ZIP to an isolated directory.

    Returns `(repository_id, extracted_root)`.
    """
    settings = get_settings()
    validate_archive(data)

    repository_id = str(uuid.uuid4())
    destination = settings.upload_path / repository_id
    destination.mkdir(parents=True, exist_ok=True)

    import io

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()

            if len(infos) > settings.max_upload_entries:
                raise UnsafeArchiveError(
                    f"Archive contains {len(infos)} entries, above the "
                    f"{settings.max_upload_entries} limit."
                )

            total_uncompressed = sum(info.file_size for info in infos)
            if total_uncompressed > settings.max_upload_bytes * 20:
                raise UnsafeArchiveError(
                    "Archive expands to an implausible size (possible zip bomb)."
                )

            # Validate every member before writing a single byte.
            for info in infos:
                reason = _is_unsafe_member(info.filename)
                if reason:
                    raise UnsafeArchiveError(reason)
                if _is_symlink(info):
                    raise UnsafeArchiveError(f"symlink in archive: {info.filename}")

            for info in infos:
                if info.is_dir():
                    continue
                target = (destination / info.filename).resolve()
                # Belt and braces: confirm the resolved path stays inside.
                if not _is_within(destination.resolve(), target):
                    raise UnsafeArchiveError(f"path escapes extraction root: {info.filename}")
                if info.file_size > settings.max_source_file_bytes * 8:
                    continue  # skip oversized blobs rather than fail the upload

                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, open(target, "wb") as handle:
                    shutil.copyfileobj(source, handle, length=64 * 1024)

    except zipfile.BadZipFile as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise UnsafeArchiveError("File is not a valid ZIP archive.") from exc
    except UnsafeArchiveError:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise UnsafeArchiveError(f"Could not read archive: {type(exc).__name__}") from exc

    # Remember the display name. The extraction directory is named by UUID, and
    # an archive with several top-level folders has no single folder to borrow a
    # name from, so without this the repository would surface as a raw UUID.
    # Dot-prefixed, so repository analysis skips it.
    display_name = Path(original_name).stem or "uploaded-repository"
    (destination / NAME_MARKER).write_text(display_name, encoding="utf-8")

    root = _collapse_single_root(destination)
    return repository_id, root


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    """ZIP stores UNIX mode in the high 16 bits of external_attr."""
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _collapse_single_root(destination: Path) -> Path:
    """GitHub-style ZIPs wrap everything in one folder — descend into it."""
    entries = [p for p in destination.iterdir() if not p.name.startswith(".")]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return destination


def resolve_repository_path(repository_id: str) -> Path | None:
    """Locate a previously uploaded repository by id."""
    settings = get_settings()
    base = settings.upload_path / repository_id
    if not base.is_dir():
        return None
    return _collapse_single_root(base)


def resolve_repository_name(repository_id: str, fallback: str) -> str:
    """Display name recorded at upload time, or `fallback`."""
    settings = get_settings()
    marker = settings.upload_path / repository_id / NAME_MARKER
    try:
        name = marker.read_text(encoding="utf-8").strip()
        return name or fallback
    except OSError:
        return fallback
