"""Google Vertex AI provider (Gemini) — the default.

Authentication is **Application Default Credentials**: there is no API key
anywhere in this module. Credentials come from `gcloud auth
application-default login` locally, or from a service account / metadata
server on Google Cloud. `GOOGLE_CLOUD_PROJECT` is what marks the provider
configured.

Structured output is enforced by the API itself — the agent's Pydantic model is
passed as `response_schema` with a JSON response MIME type — and then
re-validated locally, so a response that does not satisfy the contract raises
`MalformedResponseError` instead of being half-parsed into a report.

Uses the `google-genai` SDK. The older `vertexai.generative_models` module was
deprecated in June 2025 and removed on 2026-06-24.
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.llm.base import LLMError, LLMProvider, LLMResponse, MalformedResponseError
from app.llm.pricing import estimate_cost

MAX_OUTPUT_TOKENS = 16000


class VertexAIProvider(LLMProvider):
    """Gemini on Vertex AI, authenticated by Application Default Credentials."""

    name = "vertex"

    def __init__(self, project: str | None = None, location: str | None = None, model: str | None = None):
        settings = get_settings()
        self._project = project or settings.google_cloud_project
        self._location = location or settings.google_cloud_location
        self._model = model or settings.vertex_model
        self._client = None

    @property
    def model(self) -> str:
        return self._model

    def is_available(self) -> bool:
        """Configured when a GCP project is set. ADC supplies the credentials."""
        return bool(self._project and self._project.strip())

    def _get_client(self):
        if self._client is None:
            try:
                from google import genai
            except ImportError as exc:  # pragma: no cover - dependency is pinned
                raise LLMError(
                    "The `google-genai` package is required for the Vertex AI provider."
                ) from exc
            # No api_key: vertexai=True routes through ADC.
            self._client = genai.Client(
                vertexai=True, project=self._project, location=self._location
            )
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
            raise LLMError(
                "Vertex AI provider is not configured (GOOGLE_CLOUD_PROJECT is unset)."
            )

        client = self._get_client()

        try:
            from google.genai import types

            # Native async path — never block the event loop, or the parallel
            # agent execution this project is built to demonstrate collapses.
            response = await client.aio.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                ),
            )
        except Exception as exc:
            # Never leak credentials or raw SDK internals to the caller.
            raise LLMError(f"{type(exc).__name__} calling Vertex AI for {agent_name}") from exc

        text = _response_text(response)
        if not text:
            raise MalformedResponseError(f"No content returned for {agent_name}.")

        try:
            validated = response_schema.model_validate_json(text)
        except ValidationError as exc:
            raise MalformedResponseError(
                f"Response for {agent_name} did not satisfy its schema: {exc}"
            ) from exc

        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        completion_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)

        return LLMResponse(
            content=validated.model_dump_json(),
            model=self._model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost=estimate_cost(self._model, prompt_tokens, completion_tokens),
        )


def _response_text(response) -> str:
    """Extract the JSON payload from a Gemini response.

    `.text` is the convenience accessor; fall back to walking the first
    candidate's parts if the SDK did not populate it.
    """
    text = getattr(response, "text", None)
    if text:
        return text

    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                return part_text
    return ""
