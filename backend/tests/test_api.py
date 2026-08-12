"""HTTP API behaviour."""

from tests.conftest import DEMO_CHANGE, run_to_completion


async def create_analysis(client, **overrides):
    payload = {"change_description": DEMO_CHANGE, "concurrency_limit": 3}
    payload.update(overrides)
    return await client.post("/api/analyses", json=payload)


# --------------------------------------------------------------------------
# Health & repository
# --------------------------------------------------------------------------


async def test_health_reports_the_active_provider(client):
    response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["llm_provider"] == "mock"
    assert body["version"]


async def test_health_never_exposes_credentials(client):
    """No setting that could contain a secret may appear in the payload."""
    body = await client.get("/api/health")
    text = body.text.lower()

    assert "api_key" not in text
    assert "sk-" not in text


async def test_demo_repository_endpoint(client):
    response = await client.get("/api/demo-repository")

    assert response.status_code == 200
    body = response.json()
    assert body["repository_name"] == "sample-repository"
    assert "purchase-history" in body["default_change_description"]
    assert "pricing/discount.py" in body["summary"]["files"]


# --------------------------------------------------------------------------
# Creating analyses
# --------------------------------------------------------------------------


async def test_create_analysis(client):
    response = await create_analysis(client)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["repository_name"] == "sample-repository"
    assert body["repository_summary"]["import_graph"], "repository analysis runs at creation"


async def test_create_analysis_derives_a_name(client):
    body = (await create_analysis(client)).json()
    assert body["name"]
    assert len(body["name"]) <= 71


async def test_create_analysis_accepts_an_explicit_name(client):
    body = (await create_analysis(client, name="Discount rework")).json()
    assert body["name"] == "Discount rework"


async def test_empty_change_description_is_rejected(client):
    response = await client.post("/api/analyses", json={"change_description": "   "})
    assert response.status_code == 422


async def test_too_short_change_description_is_rejected(client):
    response = await client.post("/api/analyses", json={"change_description": "fix"})
    assert response.status_code == 422


async def test_missing_change_description_is_rejected(client):
    response = await client.post("/api/analyses", json={})
    assert response.status_code == 422


async def test_out_of_range_concurrency_limit_is_rejected(client):
    response = await create_analysis(client, concurrency_limit=99)
    assert response.status_code == 422


async def test_unknown_repository_id_returns_404(client):
    response = await create_analysis(client, repository_id="does-not-exist")
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Reading analyses
# --------------------------------------------------------------------------


async def test_get_analysis(client):
    analysis_id = (await create_analysis(client)).json()["id"]

    response = await client.get(f"/api/analyses/{analysis_id}")

    assert response.status_code == 200
    assert response.json()["id"] == analysis_id


async def test_get_unknown_analysis_returns_404(client):
    response = await client.get("/api/analyses/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["detail"] == "Analysis not found"


async def test_list_analyses_starts_empty(client):
    response = await client.get("/api/analyses")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_analyses_returns_created_analyses(client):
    await create_analysis(client)
    await create_analysis(client)

    body = (await client.get("/api/analyses")).json()
    assert len(body) == 2


# --------------------------------------------------------------------------
# Executing
# --------------------------------------------------------------------------


async def test_execute_returns_202_immediately(client):
    analysis_id = (await create_analysis(client)).json()["id"]

    response = await client.post(f"/api/analyses/{analysis_id}/execute")

    assert response.status_code == 202
    assert response.json()["execution_id"]


async def test_execute_unknown_analysis_returns_404(client):
    response = await client.post("/api/analyses/nope/execute")
    assert response.status_code == 404


async def test_execution_completes_and_records_metrics(client):
    analysis_id = (await create_analysis(client)).json()["id"]
    execution_id = (await client.post(f"/api/analyses/{analysis_id}/execute")).json()[
        "execution_id"
    ]

    execution = await run_to_completion(client, execution_id)

    assert execution["status"] == "SUCCESS"
    metrics = execution["metrics"]
    assert metrics["duration_ms"] > 0
    assert metrics["estimated_sequential_duration_ms"] > metrics["duration_ms"]
    assert metrics["estimated_speedup"] > 1.0
    assert metrics["total_tokens"] > 0
    assert metrics["parallel_agent_count"] == 3


async def test_execution_produces_the_expected_report(client):
    analysis_id = (await create_analysis(client)).json()["id"]
    execution_id = (await client.post(f"/api/analyses/{analysis_id}/execute")).json()[
        "execution_id"
    ]
    await run_to_completion(client, execution_id)

    analysis = (await client.get(f"/api/analyses/{analysis_id}")).json()

    assert analysis["status"] == "SUCCESS"
    assert analysis["overall_severity"] == "HIGH"

    components = [f["component"] for f in analysis["impact_findings"]]
    assert "pricing/discount.py" in components
    assert "checkout/service.py" in components

    documents = [f["document"] for f in analysis["documentation_findings"]]
    assert "docs/pricing.md" in documents
    assert "docs/API_REFERENCE.md" in documents

    report = analysis["report"]
    assert report["recommended_tests"]
    assert report["recommended_actions"]
    assert report["confirmed_findings"]


async def test_execution_events_are_ordered_and_pollable(client):
    analysis_id = (await create_analysis(client)).json()["id"]
    execution_id = (await client.post(f"/api/analyses/{analysis_id}/execute")).json()[
        "execution_id"
    ]
    await run_to_completion(client, execution_id)

    events = (await client.get(f"/api/executions/{execution_id}/events")).json()

    sequences = [event["seq"] for event in events]
    assert sequences == sorted(sequences)
    types = [event["event_type"] for event in events]
    assert types[0] == "execution_started"
    assert types[-1] == "execution_completed"
    assert types.count("agent_completed") == 5


async def test_events_can_be_fetched_incrementally(client):
    analysis_id = (await create_analysis(client)).json()["id"]
    execution_id = (await client.post(f"/api/analyses/{analysis_id}/execute")).json()[
        "execution_id"
    ]
    await run_to_completion(client, execution_id)

    everything = (await client.get(f"/api/executions/{execution_id}/events")).json()
    tail = (
        await client.get(
            f"/api/executions/{execution_id}/events", params={"after_seq": everything[2]["seq"]}
        )
    ).json()

    assert len(tail) == len(everything) - 3
    assert all(event["seq"] > everything[2]["seq"] for event in tail)


async def test_agents_endpoint_exposes_full_observability(client):
    analysis_id = (await create_analysis(client)).json()["id"]
    execution_id = (await client.post(f"/api/analyses/{analysis_id}/execute")).json()[
        "execution_id"
    ]
    await run_to_completion(client, execution_id)

    agents = (await client.get(f"/api/executions/{execution_id}/agents")).json()

    assert len(agents) == 5
    for agent in agents:
        assert agent["status"] == "SUCCESS"
        assert agent["model"] and agent["provider"]
        assert agent["total_tokens"] > 0
        assert agent["estimated_cost"] >= 0
        assert agent["system_prompt"] and agent["user_prompt"]
        assert agent["output_data"] is not None
        assert agent["duration_ms"] is not None


async def test_unknown_execution_returns_404(client):
    assert (await client.get("/api/executions/nope")).status_code == 404
    assert (await client.get("/api/executions/nope/events")).status_code == 404
    assert (await client.get("/api/executions/nope/agents")).status_code == 404


async def test_rerunning_an_analysis_does_not_duplicate_findings(client):
    analysis_id = (await create_analysis(client)).json()["id"]

    for _ in range(2):
        execution_id = (await client.post(f"/api/analyses/{analysis_id}/execute")).json()[
            "execution_id"
        ]
        await run_to_completion(client, execution_id)

    analysis = (await client.get(f"/api/analyses/{analysis_id}")).json()
    components = [f["component"] for f in analysis["impact_findings"]]

    assert len(components) == len(set(components)), "findings accumulated across runs"


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------


async def test_dashboard_stats_on_an_empty_database(client):
    body = (await client.get("/api/dashboard/stats")).json()

    assert body["total_analyses"] == 0
    assert body["recent_analyses"] == []
    assert body["average_speedup"] is None


async def test_dashboard_stats_after_a_run(client):
    analysis_id = (await create_analysis(client)).json()["id"]
    execution_id = (await client.post(f"/api/analyses/{analysis_id}/execute")).json()[
        "execution_id"
    ]
    await run_to_completion(client, execution_id)

    body = (await client.get("/api/dashboard/stats")).json()

    assert body["total_analyses"] == 1
    assert body["successful_analyses"] == 1
    assert body["high_impact_changes"] == 1
    assert body["documentation_updates"] > 0
    assert body["average_speedup"] > 1.0
    assert len(body["recent_analyses"]) == 1
