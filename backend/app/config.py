"""Application configuration.

Every setting has a working default so a fresh clone runs with an empty `.env`
and no API credentials. Secrets are read here and never logged or serialised
into any API response.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
DEMO_REPOSITORY_PATH = Path(__file__).resolve().parent / "demo_repository"


class Settings(BaseSettings):
    """Runtime configuration, sourced from environment variables / `.env`."""

    model_config = SettingsConfigDict(
        # Look for .env in the project root first, then the backend dir, so the
        # app behaves the same whether it is started from either location.
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM ---------------------------------------------------------------

    # Which provider to use: "vertex" | "anthropic" | "openai" | "mock".
    # Vertex AI is the default. With no GCP project configured it reports
    # itself unavailable and the request falls back to the mock, so a fresh
    # clone still runs offline with an empty `.env`.
    llm_provider: str = "vertex"

    # Force the mock regardless of `llm_provider`. Kept as an override because
    # the UI's "Mock LLM" toggle and `Analysis.mock_llm` both depend on it.
    mock_llm: bool = False

    # Google Vertex AI — Application Default Credentials, no API key.
    # Run `gcloud auth application-default login` locally.
    google_cloud_project: str | None = None
    google_cloud_location: str = "global"
    vertex_model: str = "gemini-3.6-flash"

    # Anthropic
    anthropic_api_key: str | None = None
    llm_model: str = "claude-opus-5"

    # OpenAI
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-terra"

    # --- Execution ---------------------------------------------------------
    default_concurrency_limit: int = 3
    max_concurrency_limit: int = 8
    mock_latency_scale: float = 1.0

    # --- Persistence -------------------------------------------------------
    database_url: str = "sqlite:///./designsync.db"

    # --- HTTP --------------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Uploads -----------------------------------------------------------
    upload_dir: str = "./data/uploads"
    max_upload_bytes: int = 5 * 1024 * 1024      # 5 MB archive cap
    max_upload_entries: int = 2000               # entry-count cap (zip bomb guard)
    max_source_file_bytes: int = 512 * 1024      # per-file cap when analysing

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list, ignoring blanks."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def demo_repository_path(self) -> Path:
        """Absolute path to the bundled demo repository."""
        return DEMO_REPOSITORY_PATH

    @property
    def upload_path(self) -> Path:
        """Absolute path to the uploaded-repository directory."""
        path = Path(self.upload_dir)
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()

    # --- Provider availability ---------------------------------------------
    #
    # These report *configured*, not *credentials valid*. A wrong key or an
    # expired ADC session fails loudly at call time — recorded as an agent
    # failure with the real error — rather than silently falling back to a
    # fabricated answer.

    def vertex_configured(self) -> bool:
        """Vertex AI uses Application Default Credentials, so there is no key.

        The GCP project is what marks it configured; credentials come from ADC
        (`gcloud auth application-default login`, a service account, or the
        metadata server when running on Google Cloud).
        """
        return bool(self.google_cloud_project and self.google_cloud_project.strip())

    def anthropic_configured(self) -> bool:
        return bool(self.anthropic_api_key and self.anthropic_api_key.strip())

    def openai_configured(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
