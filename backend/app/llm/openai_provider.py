"""OpenAI provider.

Structured output is enforced by the API through a strict JSON schema, then
re-validated locally so a response that does not satisfy the contract raises
`MalformedResponseError` rather than being half-parsed into a report.

The agent output models already satisfy OpenAI's strict-mode requirements:
`extra="forbid"` emits `additionalProperties: false`, and every field is
required by construction (see `app/agents/outputs.py`).
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.llm.base import LLMError, LLMProvider, LLMResponse, MalformedResponseError
from app.llm.pricing import estimate_cost

MAX_OUTPUT_TOKENS = 16000


class OpenAIProvider(LLMProvider):
    """GPT models via the Chat Completions API with strict structured outputs."""

    name = "openai"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self._api_key = api_key or settings.openai_api_key
        self._model = model or settings.openai_model
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
                from openai import AsyncOpenAI
            except ImportError as exc:  # pragma: no cover - dependency is pinned
                raise LLMError(
                    "The `openai` package is required for the OpenAI provider."
                ) from exc
            self._client = AsyncOpenAI(api_key=self._api_key)
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
            raise LLMError("OpenAI provider is not configured (OPENAI_API_KEY is unset).")

        client = self._get_client()

        try:
            response = await client.chat.completions.create(
                model=self._model,
                max_completion_tokens=MAX_OUTPUT_TOKENS,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": f"{agent_name}_output",
                        "strict": True,
                        "schema": response_schema.model_json_schema(),
                    },
                },
            )
        except Exception as exc:
            # Never leak the key or raw SDK internals to the caller.
            raise LLMError(f"{type(exc).__name__} calling OpenAI for {agent_name}") from exc

        choice = (getattr(response, "choices", None) or [None])[0]
        if choice is None:
            raise MalformedResponseError(f"No choices returned for {agent_name}.")

        if getattr(choice, "finish_reason", None) == "length":
            raise MalformedResponseError(
                f"Response for {agent_name} was truncated at the token limit; JSON is incomplete."
            )

        message = getattr(choice, "message", None)
        if getattr(message, "refusal", None):
            raise LLMError(f"Model declined the request for {agent_name}.")

        text = getattr(message, "content", None)
        if not text:
            raise MalformedResponseError(f"No text content returned for {agent_name}.")

        try:
            validated = response_schema.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise MalformedResponseError(
                f"Response for {agent_name} did not satisfy its schema: {exc}"
            ) from exc

        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

        return LLMResponse(
            content=validated.model_dump_json(),
            model=getattr(response, "model", self._model),
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost=estimate_cost(self._model, prompt_tokens, completion_tokens),
        )
