"""Health endpoint.

Reports which provider will actually serve requests — useful because asking for
the real provider without credentials silently falls back to the mock, and you
want that visible rather than surprising.

Deliberately reports the provider *name*, never the API key.
"""

from fastapi import APIRouter

from app import __version__
from app.config import get_settings
from app.llm.factory import describe_active_provider
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    provider_name, model = describe_active_provider(settings)
    return HealthResponse(
        status="ok",
        version=__version__,
        llm_provider=provider_name,
        llm_model=model,
        mock_llm=settings.mock_llm,
    )
