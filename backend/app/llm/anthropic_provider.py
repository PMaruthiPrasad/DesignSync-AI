"""Real LLM provider: Anthropic Claude.

This is the only module in the project that imports a vendor SDK. Agents never
touch it — they depend on `LLMProvider`, so the real provider and the mock are
interchangeable.

Structured output is enforced by the API itself via `output_config.format`
with the agent's JSON schema, then re-validated locally with the same Pydantic
model. A response that does not satisfy the contract raises
`MalformedResponseError` and is recorded as an agent failure, rather than being
half-parsed into a misleading report.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.llm.base import LLMError, LLMProvider, LLMResponse, MalformedResponseError
from app.llm.pricing import estimate_cost

MAX_TOKENS = 16000

# Structured extraction over supplied evidence does not need maximum reasoning
# depth; `medium` keeps latency and spend sane without hurting quality here.
EFFORT = "medium"


class AnthropicProvider(LLMProvider):
    """Claude-backed provider using the Messages API with structured outputs."""

    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self._api_key = api_key or settings.anthropic_api_key
        self._model = model or settings.llm_model
        self._client = None

    @property
    def model(self) -> str:
        return self._model

    def is_available(self) -> bool:
        """Configured, not validated — see `LLMProvider.is_available`."""
        return bool(self._api_key and self._api_key.strip())

    def _get_client(self):
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as exc:  # pragma: no cover - dependency is pinned
                raise LLMError(
                    "The `anthropic` package is required for the real provider."
                ) from exc
            self._client = AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[BaseModel],
        agent_name: str,
    ) -> LLMResponse:
        if not self.is_available():
            raise LLMError("Anthropic provider is not configured (ANTHROPIC_API_KEY is unset).")

        client = self._get_client()

        try:
            message = await client.messages.create(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                output_config={
                    "effort": EFFORT,
                    "format": {
                        "type": "json_schema",
                        "schema": response_schema.model_json_schema(),
                    },
                },
            )
        except Exception as exc:  # SDK raises a family of typed errors
            # Never leak the key or raw SDK internals to the caller.
            raise LLMError(f"{type(exc).__name__} calling Anthropic for {agent_name}") from exc

        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason == "refusal":
            raise LLMError(f"Model declined the request for {agent_name}.")
        if stop_reason == "max_tokens":
            raise MalformedResponseError(
                f"Response for {agent_name} was truncated at max_tokens; JSON is incomplete."
            )

        text = _first_text_block(message)
        if not text:
            raise MalformedResponseError(f"No text content returned for {agent_name}.")

        try:
            validated = response_schema.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise MalformedResponseError(
                f"Response for {agent_name} did not satisfy its schema: {exc}"
            ) from exc

        usage = getattr(message, "usage", None)
        prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)

        return LLMResponse(
            content=validated.model_dump_json(),
            model=getattr(message, "model", self._model),
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost=estimate_cost(self._model, prompt_tokens, completion_tokens),
        )


def _first_text_block(message) -> str:
    """Return the first text block. Thinking blocks may precede it."""
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            return getattr(block, "text", "") or ""
    return ""
