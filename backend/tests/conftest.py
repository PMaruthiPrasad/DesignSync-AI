"""Shared test fixtures.

Environment is configured *before* app modules are imported, because settings
are cached and the database engine is created at import time.

`MOCK_LATENCY_SCALE` is turned down so the suite runs in seconds while leaving
the simulated agent latencies large enough that concurrency overlap is still
measurable — the parallelism tests depend on that.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("MOCK_LLM", "true")
os.environ.setdefault("MOCK_LATENCY_SCALE", "0.1")
os.environ.setdefault("ANTHROPIC_API_KEY", "")

# Hard override, not setdefault: a real GOOGLE_CLOUD_PROJECT in .env makes
# VertexAIProvider(project=None) fall back to it (vertex_provider.py:36), so
# the "unconfigured provider" tests would see a configured one — and one of
# them would issue a real, billed Vertex call. Tests that want a project pass
# it explicitly.
os.environ["GOOGLE_CLOUD_PROJECT"] = ""

_TMP_DB = Path(tempfile.gettempdir()) / "designsync_test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"
os.environ["UPLOAD_DIR"] = str(Path(tempfile.gettempdir()) / "designsync_test_uploads")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.repo_analysis import analyze_repository  # noqa: E402

DEMO_CHANGE = (
    "Changed discount calculation from customer purchase-history based to "
    "customer-segment based."
)


@pytest.fixture(autouse=True)
def clean_database():
    """Every test starts from an empty schema."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def demo_summary(settings):
    """Deterministic analysis of the bundled demo repository."""
    return analyze_repository(settings.demo_repository_path, name="sample-repository")


@pytest.fixture
async def client():
    """HTTP client bound to the ASGI app, with lifespan run."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        async with app.router.lifespan_context(app):
            yield http_client


async def run_to_completion(client: AsyncClient, execution_id: str, max_polls: int = 300) -> dict:
    """Poll an execution until it reaches a terminal state."""
    import asyncio

    for _ in range(max_polls):
        response = await client.get(f"/api/executions/{execution_id}")
        body = response.json()
        if body["status"] in ("SUCCESS", "PARTIAL", "FAILED"):
            return body
        await asyncio.sleep(0.05)
    raise AssertionError(f"Execution {execution_id} did not finish in time")
