"""Repository endpoints: the bundled demo repo, and ZIP upload."""

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.config import get_settings
from app.schemas import DemoRepositoryResponse, UploadedRepositoryResponse
from app.services.analysis_service import (
    DEFAULT_CHANGE_DESCRIPTION,
    DEMO_REPOSITORY_NAME,
)
from app.services.repo_analysis import analyze_repository
from app.services.zip_repository import UnsafeArchiveError, extract_zip

router = APIRouter(tags=["repositories"])


@router.get("/demo-repository", response_model=DemoRepositoryResponse)
def get_demo_repository() -> DemoRepositoryResponse:
    """The bundled sample repository plus its default demo change."""
    settings = get_settings()
    summary = analyze_repository(settings.demo_repository_path, name=DEMO_REPOSITORY_NAME)
    return DemoRepositoryResponse(
        repository_name=DEMO_REPOSITORY_NAME,
        default_change_description=DEFAULT_CHANGE_DESCRIPTION,
        summary=summary,
    )


@router.post(
    "/repositories/upload",
    response_model=UploadedRepositoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_repository(file: UploadFile = File(...)) -> UploadedRepositoryResponse:
    """Upload a repository as a ZIP archive.

    The archive is validated before a byte is written (traversal, symlinks,
    size and entry-count caps) and then analysed as **text only**. Nothing in
    the uploaded repository is imported or executed.
    """
    filename = file.filename or "uploaded-repository.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Only .zip archives are supported"
        )

    data = await file.read()

    try:
        repository_id, root = extract_zip(data, original_name=filename)
    except UnsafeArchiveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    name = filename.rsplit(".", 1)[0]
    summary = analyze_repository(root, name=name)

    if not summary.files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The archive contained no analysable files.",
        )
    if not summary.python_modules:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No Python modules found. This MVP analyses Python repositories; "
                "other languages are not supported yet."
            ),
        )

    return UploadedRepositoryResponse(
        repository_id=repository_id, repository_name=name, summary=summary
    )
