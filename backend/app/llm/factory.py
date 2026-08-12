"""Provider selection.

Four providers sit behind one interface — three real, one deterministic mock:

    vertex     Google Vertex AI (Gemini)   Application Default Credentials
    anthropic  Anthropic (Claude)          ANTHROPIC_API_KEY
    openai     OpenAI (GPT)                OPENAI_API_KEY
    mock       deterministic, offline      no credentials

`LLM_PROVIDER` picks one; the default is `vertex`.

The rule that matters, and the reason a fresh clone runs with an empty `.env`:

    a provider is used only if `is_available()` returns true; otherwise the
    request falls back to the mock.

`is_available()` reports *configured*, not *credentials valid*. A wrong key or
an expired ADC session therefore fails loudly at call time — recorded as an
agent failure with the real error — instead of silently fabricating an answer.
"""

from __future__ import annotations

from collections.abc import Callable

from app.config import Settings, get_settings
from app.llm.base import LLMProvider
from app.llm.mock_provider import MockLLMProvider

VERTEX = "vertex"
ANTHROPIC = "anthropic"
OPENAI = "openai"
MOCK = "mock"

PROVIDER_NAMES = (VERTEX, ANTHROPIC, OPENAI, MOCK)

# Aliases so a reasonable spelling in `.env` does not silently fall back to the
# mock and leave the user wondering why their credentials are being ignored.
_ALIASES = {
    "google": VERTEX,
    "gemini": VERTEX,
    "vertexai": VERTEX,
    "vertex_ai": VERTEX,
    "google-vertex-ai": VERTEX,
    "claude": ANTHROPIC,
    "gpt": OPENAI,
    "open_ai": OPENAI,
    "mock_llm": MOCK,
    "none": MOCK,
}


def normalize_provider_name(name: str | None) -> str:
    """Canonical provider name. Unknown values resolve to the mock."""
    if not name:
        return MOCK
    key = name.strip().lower().replace(" ", "")
    key = _ALIASES.get(key, key)
    return key if key in PROVIDER_NAMES else MOCK


# Builders take the resolved Settings explicitly rather than reading the cached
# global, so a caller passing its own Settings actually gets them honoured.
def _build_vertex(settings: Settings) -> LLMProvider:
    from app.llm.vertex_provider import VertexAIProvider

    return VertexAIProvider(
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        model=settings.vertex_model,
    )


def _build_anthropic(settings: Settings) -> LLMProvider:
    from app.llm.anthropic_provider import AnthropicProvider

    return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.llm_model)


def _build_openai(settings: Settings) -> LLMProvider:
    from app.llm.openai_provider import OpenAIProvider

    return OpenAIProvider(api_key=settings.openai_api_key, model=settings.openai_model)


# Imports are deferred into these builders so that a missing optional SDK only
# affects the provider that needs it, rather than breaking startup for everyone.
_BUILDERS: dict[str, Callable[[Settings], LLMProvider]] = {
    VERTEX: _build_vertex,
    ANTHROPIC: _build_anthropic,
    OPENAI: _build_openai,
}


def get_provider(
    settings: Settings | None = None,
    *,
    mock_override: bool | None = None,
    provider_override: str | None = None,
) -> LLMProvider:
    """Return the provider to use for a run.

    `mock_override` lets one analysis force the mock from the UI toggle without
    changing global configuration. `provider_override` does the same for the
    provider choice, and is used by the tests.
    """
    settings = settings or get_settings()

    # An explicit request for the mock always wins.
    force_mock = settings.mock_llm if mock_override is None else mock_override
    if force_mock:
        return MockLLMProvider()

    name = normalize_provider_name(provider_override or settings.llm_provider)
    builder = _BUILDERS.get(name)
    if builder is None:
        return MockLLMProvider()

    try:
        provider = builder(settings)
    except Exception:
        # A provider whose SDK is missing or misconfigured must not take the
        # application down — fall back so the demo always runs.
        return MockLLMProvider()

    if provider.is_available():
        return provider

    # Selected but not configured: fall back rather than fail. The health
    # endpoint and the agent panels report which provider actually ran.
    return MockLLMProvider()


def describe_active_provider(settings: Settings | None = None) -> tuple[str, str]:
    """`(provider_name, model)` for the health endpoint."""
    provider = get_provider(settings)
    return provider.name, provider.model
