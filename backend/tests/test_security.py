"""Security of untrusted repository input.

The guarantee: an uploaded repository is analysed as **text** and never
executed. These tests cover both halves — archive extraction must not be
tricked into writing outside its sandbox, and analysis must not import or run
anything it reads.
"""

import io
import sys
import zipfile

import pytest

from app.config import get_settings
from app.services.repo_analysis import analyze_repository
from app.services.zip_repository import UnsafeArchiveError, extract_zip


def make_zip(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Archive extraction
# --------------------------------------------------------------------------


def test_valid_archive_extracts():
    data = make_zip({"pkg/mod.py": "def f():\n    return 1\n", "README.md": "# hi"})

    _, root = extract_zip(data)

    assert (root / "pkg" / "mod.py").is_file()


def test_zip_slip_relative_traversal_is_rejected():
    data = make_zip({"../../evil.py": "print('pwned')"})

    with pytest.raises(UnsafeArchiveError, match="traversal"):
        extract_zip(data)


def test_nested_traversal_is_rejected():
    data = make_zip({"pkg/../../../evil.py": "print('pwned')"})

    with pytest.raises(UnsafeArchiveError, match="traversal"):
        extract_zip(data)


def test_absolute_path_is_rejected():
    data = make_zip({"/etc/passwd": "root"})

    with pytest.raises(UnsafeArchiveError, match="absolute path"):
        extract_zip(data)


def test_windows_drive_path_is_rejected():
    data = make_zip({"C:/Windows/System32/evil.py": "x"})

    with pytest.raises(UnsafeArchiveError, match="drive-qualified"):
        extract_zip(data)


def test_backslash_traversal_is_rejected():
    data = make_zip({"..\\..\\evil.py": "x"})

    with pytest.raises(UnsafeArchiveError, match="traversal"):
        extract_zip(data)


def test_symlink_entry_is_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("link.py")
        info.external_attr = (0o120777 << 16)  # S_IFLNK
        archive.writestr(info, "/etc/passwd")

    with pytest.raises(UnsafeArchiveError, match="symlink"):
        extract_zip(buffer.getvalue())


def test_oversized_archive_is_rejected():
    settings = get_settings()
    oversized = b"x" * (settings.max_upload_bytes + 1)

    with pytest.raises(UnsafeArchiveError, match="larger than"):
        extract_zip(oversized)


def test_empty_upload_is_rejected():
    with pytest.raises(UnsafeArchiveError, match="empty"):
        extract_zip(b"")


def test_non_zip_data_is_rejected():
    with pytest.raises(UnsafeArchiveError, match="not a valid ZIP"):
        extract_zip(b"this is definitely not a zip file, but it is long enough")


def test_too_many_entries_is_rejected():
    settings = get_settings()
    data = make_zip({f"f{i}.py": "x = 1" for i in range(settings.max_upload_entries + 1)})

    with pytest.raises(UnsafeArchiveError, match="entries"):
        extract_zip(data)


def test_single_root_folder_is_collapsed():
    """GitHub-style archives wrap everything in one directory."""
    data = make_zip({"my-repo-main/app.py": "x = 1", "my-repo-main/README.md": "# hi"})

    _, root = extract_zip(data)

    assert (root / "app.py").is_file()


# --------------------------------------------------------------------------
# Analysis never executes what it reads
# --------------------------------------------------------------------------


def test_analysis_does_not_execute_repository_code(tmp_path):
    """A file with a destructive side effect at import time must stay inert."""
    marker = tmp_path / "SHOULD_NOT_EXIST.txt"
    (tmp_path / "malicious.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed')\n"
        "raise SystemExit('boom')\n",
        encoding="utf-8",
    )

    summary = analyze_repository(tmp_path, name="hostile")

    assert not marker.exists(), "repository code was executed"
    assert "malicious.py" in summary.files


def test_analysis_does_not_import_repository_modules(tmp_path):
    """Nothing from the analysed repository may end up in sys.modules."""
    (tmp_path / "uniquely_named_module_xyz.py").write_text("VALUE = 1\n", encoding="utf-8")

    before = set(sys.modules)
    analyze_repository(tmp_path, name="import-check")
    added = set(sys.modules) - before

    assert not any("uniquely_named_module_xyz" in name for name in added)


def test_analysis_does_not_run_setup_or_conftest(tmp_path):
    marker = tmp_path / "setup_ran.txt"
    for name in ("setup.py", "conftest.py", "__init__.py"):
        (tmp_path / name).write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('{name}')\n",
            encoding="utf-8",
        )

    analyze_repository(tmp_path, name="setup-check")

    assert not marker.exists()


def test_analysis_of_hostile_archive_is_still_safe():
    """End to end: extract an archive containing a bomb, then analyse it."""
    data = make_zip(
        {
            "app/main.py": "import os\nos.system('echo pwned')\n",
            "app/__init__.py": "raise RuntimeError('import side effect')\n",
        }
    )

    _, root = extract_zip(data)
    summary = analyze_repository(root, name="hostile-archive")

    # `app/` is the archive's single root folder, so it is collapsed away.
    assert "main.py" in summary.files
    assert summary.malformed_files == []


# --------------------------------------------------------------------------
# Upload endpoint
# --------------------------------------------------------------------------


async def test_upload_endpoint_accepts_a_python_repository(client):
    data = make_zip(
        {
            "svc/core.py": "def handler():\n    return 1\n",
            "docs/guide.md": "# Guide\nIt returns 1.\n",
        }
    )

    response = await client.post(
        "/api/repositories/upload",
        files={"file": ("repo.zip", data, "application/zip")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["repository_id"]
    assert "svc/core.py" in body["summary"]["files"]


async def test_upload_endpoint_rejects_traversal(client):
    data = make_zip({"../evil.py": "x"})

    response = await client.post(
        "/api/repositories/upload", files={"file": ("repo.zip", data, "application/zip")}
    )

    assert response.status_code == 400
    assert "traversal" in response.json()["detail"]


async def test_upload_endpoint_rejects_non_zip_filename(client):
    response = await client.post(
        "/api/repositories/upload", files={"file": ("repo.tar.gz", b"data", "application/gzip")}
    )

    assert response.status_code == 400


async def test_upload_endpoint_rejects_repository_without_python(client):
    data = make_zip({"index.js": "console.log(1)", "README.md": "# js only"})

    response = await client.post(
        "/api/repositories/upload", files={"file": ("repo.zip", data, "application/zip")}
    )

    assert response.status_code == 400
    assert "Python" in response.json()["detail"]


async def test_uploaded_repository_can_be_analysed_end_to_end(client):
    data = make_zip(
        {
            "billing/invoice.py": "def build_invoice(order):\n    return order\n",
            "billing/api.py": "from billing.invoice import build_invoice\n",
            "docs/billing.md": "# Billing\nInvoices are numbered sequentially.\n",
        }
    )
    upload = await client.post(
        "/api/repositories/upload", files={"file": ("billing.zip", data, "application/zip")}
    )
    repository_id = upload.json()["repository_id"]

    created = await client.post(
        "/api/analyses",
        json={
            "change_description": "Changed invoice numbering from sequential to date-prefixed.",
            "repository_id": repository_id,
        },
    )

    assert created.status_code == 201
    assert created.json()["repository_name"] == "billing"
