"""The evidence envelope embedded in every agent's user prompt.

Agents serialise their deterministic evidence into a `<CONTEXT>...</CONTEXT>`
JSON block inside the user prompt. A real model reads it as context; the mock
provider parses the *same* block and derives its answers from it.

That is what keeps mock mode honest: the mock is grounded in the actual
repository the user supplied, not in a canned report. Both providers see
exactly the same evidence.
"""

from __future__ import annotations

import json
import re

CONTEXT_OPEN = "<CONTEXT>"
CONTEXT_CLOSE = "</CONTEXT>"

_CONTEXT_RE = re.compile(
    re.escape(CONTEXT_OPEN) + r"\s*(.*?)\s*" + re.escape(CONTEXT_CLOSE),
    re.DOTALL,
)


def render_context(context: dict) -> str:
    """Serialise evidence into the prompt envelope (sorted keys => stable bytes)."""
    body = json.dumps(context, indent=2, sort_keys=True, default=str)
    return f"{CONTEXT_OPEN}\n{body}\n{CONTEXT_CLOSE}"


def extract_context(user_prompt: str) -> dict:
    """Pull the evidence dict back out of a user prompt. `{}` if absent."""
    match = _CONTEXT_RE.search(user_prompt)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
