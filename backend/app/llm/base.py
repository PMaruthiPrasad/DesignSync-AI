"""The LLM provider interface every agent codes against."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class LLMError(RuntimeError):
    """Provider call failed (network, auth, timeout, rate limit)."""


class MalformedResponseError(LLMError):
    """Provider returned something that does not satisfy the response schema."""


class LLMResponse(BaseModel):
    """A completed provider call, with the observability data we record."""

    content: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float


class LLMProvider(ABC):
    """Minimal contract: produce schema-valid JSON, and report what it cost."""

    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this provider is *configured*.

        Deliberately not "are the credentials valid" — a wrong key should fail
        loudly at call time rather than silently degrade to a fake answer.
        """

    @abstractmethod
    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[BaseModel],
        agent_name: str,
    ) -> LLMResponse:
        """Return a response whose `content` is JSON matching `response_schema`."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Identifier of the model this provider will use."""
