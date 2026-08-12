"""Provider selection and the two credentialed providers.

Live calls are not made — there is no GCP project or OpenAI key here. Instead
each provider is driven through `complete()` against a stubbed client, which
exercises everything except the network round trip: request shape, structured
output configuration, usage accounting, cost, and schema validation.

What is deliberately covered:
  * `is_available()` means *configured*, per provider
  * the four-way `LLM_PROVIDER` selection, aliases, and unknown values
  * fallback to mock when a provider is selected but unconfigured
  * the force-mock override still wins
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from app.agents.outputs import PlannerOutput
from app.config import Settings
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMError, MalformedResponseError
from app.llm.factory import (
    ANTHROPIC,
    MOCK,
    OPENAI,
    PROVIDER_NAMES,
    VERTEX,
    get_provider,
    normalize_provider_name,
)
from app.llm.mock_provider import MockLLMProvider
from app.llm.openai_provider import OpenAIProvider
from app.llm.pricing import estimate_cost
from app.llm.vertex_provider import VertexAIProvider


class Tiny(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_summary: str
    confidence: float


VALID_JSON = '{"change_summary": "ok", "confidence": 0.9}'


def make_settings(**overrides) -> Settings:
    """Settings built from explicit values, ignoring any ambient `.env`."""
    base = {
        "llm_provider": "vertex",
        "mock_llm": False,
        "google_cloud_project": None,
        "anthropic_api_key": None,
        "openai_api_key": None,
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)


# --------------------------------------------------------------------------
# Availability
# --------------------------------------------------------------------------


def test_vertex_available_with_a_project_and_no_api_key():
    """Vertex uses ADC — the project marks it configured, not a key."""
    provider = VertexAIProvider(project="my-gcp-project")
    assert provider.is_available() is True


def test_vertex_unavailable_without_a_project():
    assert VertexAIProvider(project=None).is_available() is False
    assert VertexAIProvider(project="   ").is_available() is False


def test_vertex_defaults_to_gemini_flash():
    assert VertexAIProvider(project="p").model == "gemini-3.6-flash"


def test_openai_availability_follows_the_key():
    assert OpenAIProvider(api_key="sk-test").is_available() is True
    assert OpenAIProvider(api_key=None).is_available() is False


def test_openai_defaults_to_the_configured_model():
    assert OpenAIProvider(api_key="sk-test").model == "gpt-5.6-terra"


def test_anthropic_availability_follows_the_key():
    assert AnthropicProvider(api_key="sk-ant-test").is_available() is True
    assert AnthropicProvider(api_key=None).is_available() is False


def test_settings_availability_helpers():
    assert make_settings(google_cloud_project="p").vertex_configured() is True
    assert make_settings().vertex_configured() is False
    assert make_settings(anthropic_api_key="k").anthropic_configured() is True
    assert make_settings(openai_api_key="k").openai_configured() is True


# --------------------------------------------------------------------------
# Name normalisation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", PROVIDER_NAMES)
def test_canonical_names_pass_through(name):
    assert normalize_provider_name(name) == name


@pytest.mark.parametrize(
    "given,expected",
    [
        ("VERTEX", VERTEX),
        ("Google", VERTEX),
        ("gemini", VERTEX),
        ("vertex_ai", VERTEX),
        ("  Anthropic  ", ANTHROPIC),
        ("claude", ANTHROPIC),
        ("OpenAI", OPENAI),
        ("gpt", OPENAI),
    ],
)
def test_aliases_and_casing_resolve(given, expected):
    assert normalize_provider_name(given) == expected


@pytest.mark.parametrize("given", ["", None, "not-a-provider", "llama"])
def test_unknown_names_resolve_to_mock(given):
    assert normalize_provider_name(given) == MOCK


# --------------------------------------------------------------------------
# Factory selection
# --------------------------------------------------------------------------


def test_vertex_is_the_default_provider():
    settings = make_settings(google_cloud_project="my-project")
    provider = get_provider(settings)

    assert isinstance(provider, VertexAIProvider)
    assert provider.name == "vertex"
    assert provider.model == "gemini-3.6-flash"


def test_selecting_anthropic():
    settings = make_settings(llm_provider="anthropic", anthropic_api_key="sk-ant-test")
    assert get_provider(settings).name == "anthropic"


def test_selecting_openai():
    settings = make_settings(llm_provider="openai", openai_api_key="sk-test")
    provider = get_provider(settings)

    assert provider.name == "openai"
    assert provider.model == "gpt-5.6-terra"


def test_selecting_mock():
    assert get_provider(make_settings(llm_provider="mock")).name == "mock"


@pytest.mark.parametrize("name", [VERTEX, ANTHROPIC, OPENAI])
def test_unconfigured_provider_falls_back_to_mock(name):
    """The offline guarantee: no credentials never means a crash."""
    provider = get_provider(make_settings(llm_provider=name))
    assert provider.name == "mock"


def test_unknown_provider_name_falls_back_to_mock():
    assert get_provider(make_settings(llm_provider="wat")).name == "mock"


def test_force_mock_override_beats_a_configured_provider():
    settings = make_settings(llm_provider="vertex", google_cloud_project="p")
    assert get_provider(settings, mock_override=True).name == "mock"


def test_mock_llm_setting_forces_mock():
    settings = make_settings(llm_provider="vertex", google_cloud_project="p", mock_llm=True)
    assert get_provider(settings).name == "mock"


def test_mock_override_false_does_not_force_a_real_provider_when_unconfigured():
    assert get_provider(make_settings(), mock_override=False).name == "mock"


def test_provider_override_selects_explicitly():
    settings = make_settings(llm_provider="mock", openai_api_key="sk-test")
    assert get_provider(settings, provider_override="openai").name == "openai"


# --------------------------------------------------------------------------
# Vertex AI — driven through a stubbed client
# --------------------------------------------------------------------------


class _Usage:
    def __init__(self, prompt=1200, candidates=300):
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates


class _GeminiResponse:
    def __init__(self, text=VALID_JSON, usage=None):
        self.text = text
        self.usage_metadata = usage or _Usage()


class _StubGeminiModels:
    def __init__(self, response):
        self._response = response
        self.calls: list[dict] = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _StubGeminiClient:
    def __init__(self, response):
        self.aio = type("Aio", (), {"models": _StubGeminiModels(response)})()


def vertex_with_stub(response) -> tuple[VertexAIProvider, _StubGeminiClient]:
    provider = VertexAIProvider(project="p", location="global")
    client = _StubGeminiClient(response)
    provider._client = client
    return provider, client


async def test_vertex_complete_returns_usage_and_cost():
    provider, _ = vertex_with_stub(_GeminiResponse())

    response = await provider.complete(
        system_prompt="sys",
        user_prompt="user",
        response_schema=Tiny,
        agent_name="planner",
    )

    assert response.provider == "vertex"
    assert response.model == "gemini-3.6-flash"
    assert response.prompt_tokens == 1200
    assert response.completion_tokens == 300
    assert response.total_tokens == 1500
    assert response.estimated_cost == estimate_cost("gemini-3.6-flash", 1200, 300)
    assert Tiny.model_validate_json(response.content).confidence == 0.9


async def test_vertex_requests_structured_json_output():
    """The schema must be enforced by the API, not merely asked for in prose."""
    provider, client = vertex_with_stub(_GeminiResponse())

    await provider.complete(
        system_prompt="sys", user_prompt="user", response_schema=Tiny, agent_name="planner"
    )

    call = client.aio.models.calls[0]
    assert call["model"] == "gemini-3.6-flash"
    assert call["contents"] == "user"
    assert call["config"].system_instruction == "sys"
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_schema is Tiny


async def test_vertex_rejects_schema_invalid_response():
    provider, _ = vertex_with_stub(_GeminiResponse(text='{"wrong": "shape"}'))

    with pytest.raises(MalformedResponseError):
        await provider.complete(
            system_prompt="s", user_prompt="u", response_schema=Tiny, agent_name="planner"
        )


async def test_vertex_rejects_empty_response():
    provider, _ = vertex_with_stub(_GeminiResponse(text=""))

    with pytest.raises(MalformedResponseError):
        await provider.complete(
            system_prompt="s", user_prompt="u", response_schema=Tiny, agent_name="planner"
        )


async def test_vertex_wraps_sdk_errors_without_leaking_internals():
    provider, _ = vertex_with_stub(RuntimeError("PERMISSION_DENIED: project/secret-detail"))

    with pytest.raises(LLMError) as exc_info:
        await provider.complete(
            system_prompt="s", user_prompt="u", response_schema=Tiny, agent_name="planner"
        )

    message = str(exc_info.value)
    assert "planner" in message
    assert "secret-detail" not in message


async def test_vertex_without_a_project_raises_rather_than_calling():
    provider = VertexAIProvider(project=None)

    with pytest.raises(LLMError, match="GOOGLE_CLOUD_PROJECT"):
        await provider.complete(
            system_prompt="s", user_prompt="u", response_schema=Tiny, agent_name="planner"
        )


# --------------------------------------------------------------------------
# OpenAI — driven through a stubbed client
# --------------------------------------------------------------------------


class _OpenAIMessage:
    def __init__(self, content=VALID_JSON, refusal=None):
        self.content = content
        self.refusal = refusal


class _OpenAIChoice:
    def __init__(self, content=VALID_JSON, finish_reason="stop", refusal=None):
        self.message = _OpenAIMessage(content, refusal)
        self.finish_reason = finish_reason


class _OpenAIUsage:
    def __init__(self, prompt=900, completion=250):
        self.prompt_tokens = prompt
        self.completion_tokens = completion


class _OpenAIResponse:
    def __init__(self, choice=None, model="gpt-5.6-terra"):
        self.choices = [choice or _OpenAIChoice()]
        self.usage = _OpenAIUsage()
        self.model = model


class _StubCompletions:
    def __init__(self, response):
        self._response = response
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _StubOpenAIClient:
    def __init__(self, response):
        self.chat = type("Chat", (), {"completions": _StubCompletions(response)})()


def openai_with_stub(response) -> tuple[OpenAIProvider, _StubOpenAIClient]:
    provider = OpenAIProvider(api_key="sk-test")
    client = _StubOpenAIClient(response)
    provider._client = client
    return provider, client


async def test_openai_complete_returns_usage_and_cost():
    provider, _ = openai_with_stub(_OpenAIResponse())

    response = await provider.complete(
        system_prompt="sys", user_prompt="user", response_schema=Tiny, agent_name="planner"
    )

    assert response.provider == "openai"
    assert response.prompt_tokens == 900
    assert response.completion_tokens == 250
    assert response.total_tokens == 1150
    assert response.estimated_cost == estimate_cost("gpt-5.6-terra", 900, 250)


async def test_openai_requests_a_strict_json_schema():
    provider, client = openai_with_stub(_OpenAIResponse())

    await provider.complete(
        system_prompt="sys", user_prompt="user", response_schema=Tiny, agent_name="code_analyst"
    )

    call = client.chat.completions.calls[0]
    assert call["model"] == "gpt-5.6-terra"
    assert call["messages"][0] == {"role": "system", "content": "sys"}
    assert call["messages"][1] == {"role": "user", "content": "user"}

    schema_block = call["response_format"]["json_schema"]
    assert call["response_format"]["type"] == "json_schema"
    assert schema_block["strict"] is True
    assert schema_block["name"] == "code_analyst_output"
    # Strict mode requires additionalProperties: false, which `extra="forbid"` gives us.
    assert schema_block["schema"]["additionalProperties"] is False


async def test_openai_truncation_is_a_malformed_response():
    truncated = _OpenAIChoice(content='{"change_summary": "cut o', finish_reason="length")
    provider, _ = openai_with_stub(_OpenAIResponse(choice=truncated))

    with pytest.raises(MalformedResponseError, match="truncated"):
        await provider.complete(
            system_prompt="s", user_prompt="u", response_schema=Tiny, agent_name="planner"
        )


async def test_openai_refusal_is_an_error():
    refused = _OpenAIChoice(content=None, refusal="I can't help with that")
    provider, _ = openai_with_stub(_OpenAIResponse(choice=refused))

    with pytest.raises(LLMError, match="declined"):
        await provider.complete(
            system_prompt="s", user_prompt="u", response_schema=Tiny, agent_name="planner"
        )


async def test_openai_rejects_schema_invalid_response():
    bad = _OpenAIChoice(content='{"unexpected": true}')
    provider, _ = openai_with_stub(_OpenAIResponse(choice=bad))

    with pytest.raises(MalformedResponseError):
        await provider.complete(
            system_prompt="s", user_prompt="u", response_schema=Tiny, agent_name="planner"
        )


async def test_openai_wraps_sdk_errors_without_leaking_the_key():
    provider, _ = openai_with_stub(RuntimeError("401 invalid key sk-secret-value"))

    with pytest.raises(LLMError) as exc_info:
        await provider.complete(
            system_prompt="s", user_prompt="u", response_schema=Tiny, agent_name="planner"
        )

    assert "sk-secret-value" not in str(exc_info.value)


async def test_openai_without_a_key_raises_rather_than_calling():
    provider = OpenAIProvider(api_key=None)

    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        await provider.complete(
            system_prompt="s", user_prompt="u", response_schema=Tiny, agent_name="planner"
        )


# --------------------------------------------------------------------------
# Real agent schemas survive both providers' structured-output paths
# --------------------------------------------------------------------------


def test_agent_schemas_satisfy_openai_strict_mode():
    """Strict mode needs additionalProperties: false and every field required."""
    schema = PlannerOutput.model_json_schema()

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


def test_pricing_covers_every_default_model():
    from app.llm.pricing import PRICE_PER_MTOK

    for model in ("gemini-3.6-flash", "claude-opus-5", "gpt-5.6-terra", "mock-designsync-1"):
        assert model in PRICE_PER_MTOK, f"{model} has no price row"
