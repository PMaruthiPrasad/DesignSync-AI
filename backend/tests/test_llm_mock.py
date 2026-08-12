"""Mock provider behaviour.

The mock must be deterministic (so tests and demos are reproducible) and
genuinely grounded in the supplied repository (so it demonstrates the real
pipeline rather than replaying a canned report).
"""

import pytest

from app.agents.outputs import (
    CodeAnalystOutput,
    DependencyAnalystOutput,
    DocsAnalystOutput,
    ImpactReviewerOutput,
    PlannerOutput,
)
from app.agents.prompts import (
    PLANNER_SYSTEM,
    build_base_context,
    code_analyst_prompt,
    docs_analyst_prompt,
    planner_prompt,
)
from app.llm.envelope import extract_context, render_context
from app.llm.factory import get_provider
from app.llm.mock_provider import MockLLMProvider, _split_from_to
from app.llm.pricing import estimate_cost
from app.services.repo_analysis import analyze_repository

from tests.conftest import DEMO_CHANGE

FAST = 0.0


@pytest.fixture
def provider():
    return MockLLMProvider(latency_scale=FAST)


@pytest.fixture
def base_and_prompt(demo_summary):
    base = build_base_context(DEMO_CHANGE, demo_summary)
    return base, planner_prompt(base, demo_summary)


# --------------------------------------------------------------------------
# Envelope
# --------------------------------------------------------------------------


def test_envelope_round_trips():
    context = {"change_description": "x", "files": ["a.py"]}
    assert extract_context(render_context(context)) == context


def test_extract_context_returns_empty_dict_when_absent():
    assert extract_context("no envelope here") == {}


def test_extract_context_survives_malformed_json():
    assert extract_context("<CONTEXT>{not json}</CONTEXT>") == {}


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


async def test_identical_input_produces_identical_output(provider, base_and_prompt):
    _, prompt = base_and_prompt

    first = await provider.complete(
        system_prompt=PLANNER_SYSTEM,
        user_prompt=prompt,
        response_schema=PlannerOutput,
        agent_name="planner",
    )
    second = await provider.complete(
        system_prompt=PLANNER_SYSTEM,
        user_prompt=prompt,
        response_schema=PlannerOutput,
        agent_name="planner",
    )

    assert first.content == second.content
    assert first.total_tokens == second.total_tokens
    assert first.estimated_cost == second.estimated_cost


async def test_different_repositories_produce_different_findings(provider, tmp_path):
    """Proof the mock reads the repository rather than replaying a fixture."""
    (tmp_path / "billing").mkdir()
    (tmp_path / "billing" / "invoice.py").write_text(
        "def build_invoice(order):\n    return order\n", encoding="utf-8"
    )
    other = analyze_repository(tmp_path, name="other-repo")

    base = build_base_context("Changed invoice numbering from sequential to date-prefixed.", other)
    response = await provider.complete(
        system_prompt=PLANNER_SYSTEM,
        user_prompt=planner_prompt(base, other),
        response_schema=PlannerOutput,
        agent_name="planner",
    )

    assert "billing/invoice.py" in response.content
    assert "pricing/discount.py" not in response.content


# --------------------------------------------------------------------------
# Usage accounting
# --------------------------------------------------------------------------


async def test_reports_token_usage_and_cost(provider, base_and_prompt):
    _, prompt = base_and_prompt

    response = await provider.complete(
        system_prompt=PLANNER_SYSTEM,
        user_prompt=prompt,
        response_schema=PlannerOutput,
        agent_name="planner",
    )

    assert response.prompt_tokens > 0
    assert response.completion_tokens > 0
    assert response.total_tokens == response.prompt_tokens + response.completion_tokens
    assert response.estimated_cost > 0
    assert response.provider == "mock"


def test_cost_estimation_matches_the_price_table():
    # 1M input tokens at $5/MTok + 1M output at $25/MTok
    assert estimate_cost("claude-opus-5", 1_000_000, 1_000_000) == 30.0
    assert estimate_cost("claude-haiku-4-5", 1_000_000, 0) == 1.0


def test_unknown_model_falls_back_to_a_default_price():
    assert estimate_cost("some-future-model", 1_000_000, 0) > 0


# --------------------------------------------------------------------------
# Latency simulation
# --------------------------------------------------------------------------


async def test_latency_is_simulated_and_scalable(base_and_prompt):
    import time

    _, prompt = base_and_prompt
    slow = MockLLMProvider(latency_scale=0.2)

    started = time.perf_counter()
    await slow.complete(
        system_prompt=PLANNER_SYSTEM,
        user_prompt=prompt,
        response_schema=PlannerOutput,
        agent_name="planner",
    )
    elapsed = time.perf_counter() - started

    # planner base latency is 1.0s, scaled by 0.2
    assert 0.15 < elapsed < 0.6


# --------------------------------------------------------------------------
# Grounding
# --------------------------------------------------------------------------


def test_change_description_parsing():
    old, new = _split_from_to(DEMO_CHANGE)
    assert "purchase-history" in old
    assert "customer-segment" in new


def test_change_description_parsing_handles_other_phrasing():
    assert _split_from_to("Refactored the parser") == ("", "")


async def test_code_analyst_output_cites_real_files(provider, demo_summary):
    base = build_base_context(DEMO_CHANGE, demo_summary)
    plan = {"investigation_targets": ["pricing/discount.py"]}

    response = await provider.complete(
        system_prompt="",
        user_prompt=code_analyst_prompt(base, demo_summary, plan),
        response_schema=CodeAnalystOutput,
        agent_name="code_analyst",
    )
    output = CodeAnalystOutput.model_validate_json(response.content)

    repository_files = set(demo_summary.files)
    for finding in output.code_findings:
        assert finding.file in repository_files, f"invented file: {finding.file}"
    assert any(f.impact_type == "DIRECT" for f in output.code_findings)
    assert any(f.impact_type == "POTENTIAL_DOWNSTREAM" for f in output.code_findings)


async def test_code_analyst_names_the_relevant_symbol(provider, demo_summary):
    """The headline symbol must relate to the change, not just be file-first.

    `pricing/discount.py` declares the `Customer` dataclass before
    `calculate_discount`; naming `Customer` as the thing whose return value
    changed would be misleading.
    """
    base = build_base_context(DEMO_CHANGE, demo_summary)
    plan = {"investigation_targets": ["pricing/discount.py"]}

    response = await provider.complete(
        system_prompt="",
        user_prompt=code_analyst_prompt(base, demo_summary, plan),
        response_schema=CodeAnalystOutput,
        agent_name="code_analyst",
    )
    output = CodeAnalystOutput.model_validate_json(response.content)
    direct = next(f for f in output.code_findings if f.impact_type == "DIRECT")

    assert direct.symbol == "calculate_discount"


async def test_docs_analyst_quotes_real_documentation(provider, demo_summary):
    base = build_base_context(DEMO_CHANGE, demo_summary)

    response = await provider.complete(
        system_prompt="",
        user_prompt=docs_analyst_prompt(base, demo_summary, {}),
        response_schema=DocsAnalystOutput,
        agent_name="documentation_analyst",
    )
    output = DocsAnalystOutput.model_validate_json(response.content)

    assert output.documentation_findings
    for finding in output.documentation_findings:
        assert finding.document in set(demo_summary.documentation_files)
        assert finding.current_statement, "a stale finding must quote the offending text"


@pytest.mark.parametrize(
    "agent_name,schema",
    [
        ("planner", PlannerOutput),
        ("code_analyst", CodeAnalystOutput),
        ("documentation_analyst", DocsAnalystOutput),
        ("dependency_analyst", DependencyAnalystOutput),
        ("impact_reviewer", ImpactReviewerOutput),
    ],
)
async def test_every_agent_output_validates_against_its_schema(
    provider, demo_summary, agent_name, schema
):
    base = build_base_context(DEMO_CHANGE, demo_summary)
    response = await provider.complete(
        system_prompt="",
        user_prompt=render_context(base),
        response_schema=schema,
        agent_name=agent_name,
    )
    schema.model_validate_json(response.content)


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------


def test_factory_returns_mock_by_default():
    assert get_provider().name == "mock"


def test_factory_falls_back_to_mock_without_credentials():
    """Asking for the real provider with no key must not crash the demo."""
    assert get_provider(mock_override=False).name == "mock"


def test_mock_is_always_available():
    assert MockLLMProvider().is_available() is True
