"""LLM provider abstraction.

Four providers behind one `LLMProvider` interface — three real, one mock:

| Provider  | Selector    | Auth                                 |
|-----------|-------------|--------------------------------------|
| Vertex AI | `vertex`    | Application Default Credentials      |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY`                  |
| OpenAI    | `openai`    | `OPENAI_API_KEY`                     |
| Mock      | `mock`      | none — always available              |

Agents depend on the interface only — no agent imports a vendor SDK. Choosing a
provider, or dropping to the deterministic mock, is a factory decision rather
than a code change in the agent layer.
"""

from app.llm.base import LLMProvider, LLMResponse, LLMError, MalformedResponseError
from app.llm.factory import (
    PROVIDER_NAMES,
    describe_active_provider,
    get_provider,
    normalize_provider_name,
)
from app.llm.mock_provider import MockLLMProvider

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "LLMError",
    "MalformedResponseError",
    "MockLLMProvider",
    "get_provider",
    "describe_active_provider",
    "normalize_provider_name",
    "PROVIDER_NAMES",
]
