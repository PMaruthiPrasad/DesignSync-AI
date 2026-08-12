"""Deterministic mock LLM provider.

Mandatory for the demo: with `MOCK_LLM=true` the entire system runs offline —
no API key, no network — while still exercising the real path:

    API -> orchestration -> agents -> reviewer -> persistence -> UI

It is *not* a canned report. The mock parses the same `<CONTEXT>` evidence
envelope the real model receives and derives every finding from the actual
repository: real file paths, the real import graph, real symbol names, real
documentation excerpts. Point it at a different repository and the findings
change accordingly.

It also simulates what a real call costs you: per-agent latency, token counts
derived from prompt size, and dollar cost from the same price table the real
provider uses.
"""

from __future__ import annotations

import asyncio
import re

from pydantic import BaseModel

from app.config import get_settings
from app.llm.base import LLMProvider, LLMResponse
from app.llm.envelope import extract_context
from app.llm.pricing import estimate_cost

MOCK_MODEL = "mock-designsync-1"

# Simulated per-agent latency in seconds. These are the numbers behind the
# demo's parallel-vs-sequential story:
#   sequential = 1.0 + 2.5 + 2.0 + 2.2 + 1.2 = 8.9s
#   parallel   = 1.0 + max(2.5, 2.0, 2.2) + 1.2 = 4.7s
AGENT_LATENCY_SECONDS = {
    "planner": 1.0,
    "code_analyst": 2.5,
    "documentation_analyst": 2.0,
    "dependency_analyst": 2.2,
    "impact_reviewer": 1.2,
}
DEFAULT_LATENCY_SECONDS = 1.0


class MockLLMProvider(LLMProvider):
    """Offline, deterministic, repository-grounded stand-in for a real model."""

    name = "mock"

    def __init__(self, latency_scale: float | None = None):
        settings = get_settings()
        self.latency_scale = (
            settings.mock_latency_scale if latency_scale is None else latency_scale
        )

    @property
    def model(self) -> str:
        return MOCK_MODEL

    def is_available(self) -> bool:
        """Always available — that is the point of it."""
        return True

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[BaseModel],
        agent_name: str,
    ) -> LLMResponse:
        await asyncio.sleep(
            AGENT_LATENCY_SECONDS.get(agent_name, DEFAULT_LATENCY_SECONDS)
            * self.latency_scale
        )

        context = extract_context(user_prompt)
        builder = _BUILDERS.get(agent_name)
        payload = builder(context) if builder else {}

        # Validate against the same schema the real provider is held to, so a
        # bug in the mock surfaces as a caught error, not a corrupt report.
        validated = response_schema.model_validate(payload)
        content = validated.model_dump_json()

        prompt_tokens = _estimate_tokens(system_prompt) + _estimate_tokens(user_prompt)
        completion_tokens = _estimate_tokens(content)

        return LLMResponse(
            content=content,
            model=MOCK_MODEL,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost=estimate_cost(MOCK_MODEL, prompt_tokens, completion_tokens),
        )


def _estimate_tokens(text: str) -> int:
    """~4 characters per token — the usual rough English approximation."""
    return max(1, len(text) // 4)


# --------------------------------------------------------------------------
# Reading the change description
# --------------------------------------------------------------------------

_FROM_TO_RE = re.compile(
    r"\bfrom\s+(?P<old>.{3,90}?)\s+to\s+(?P<new>.{3,90}?)\s*(?:[.;]|$)",
    re.IGNORECASE | re.DOTALL,
)


def _split_from_to(change_description: str) -> tuple[str, str]:
    """Pull the "from OLD to NEW" pair out of a change description.

    "Changed discount calculation from purchase-history based to
    customer-segment based." -> ("purchase-history based", "customer-segment based")

    Returns ("", "") when the description is not phrased that way; callers fall
    back to generic wording.
    """
    match = _FROM_TO_RE.search(change_description)
    if not match:
        return "", ""
    return match.group("old").strip(), match.group("new").strip()


def _significant_terms(phrase: str) -> list[str]:
    """Content words from a phrase, used to spot stale documentation."""
    stop = {"based", "the", "a", "an", "of", "on", "to", "from", "and", "or", "using"}
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", phrase.lower())
    seen: list[str] = []
    for word in words:
        if word not in stop and word not in seen:
            seen.append(word)
    return seen


def _headline_symbol(symbols: list[dict], change_description: str) -> str:
    """Pick the symbol the change is most plausibly about.

    Naively taking the first symbol in a file surfaces whatever happens to be
    declared at the top — often a dataclass rather than the function whose
    behaviour changed. Rank by overlap with the change description, and prefer
    callable symbols over type declarations.
    """
    if not symbols:
        return ""

    terms = set(_significant_terms(change_description))

    def score(symbol: dict) -> tuple[int, int, int]:
        # Split on both dots and underscores so `calculate_discount` matches a
        # change description that says "discount".
        readable = symbol.get("name", "").replace(".", " ").replace("_", " ")
        name_terms = set(_significant_terms(readable))
        overlap = len(terms & name_terms)
        callable_bonus = 1 if symbol.get("kind") in ("function", "method") else 0
        public_bonus = 0 if symbol.get("name", "").startswith("_") else 1
        return (overlap, callable_bonus, public_bonus)

    best = max(symbols, key=score)
    return best.get("name", "") if score(best) > (0, 0, 0) else symbols[0].get("name", "")


def _confidence(base: float, evidence_items: int) -> float:
    """Confidence that rises with the amount of hard evidence, capped at 0.97."""
    return round(min(0.97, base + 0.03 * min(evidence_items, 5)), 2)


def _short(text: str, limit: int = 220) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# --------------------------------------------------------------------------
# Agent 1: Planner
# --------------------------------------------------------------------------


def _build_planner(ctx: dict) -> dict:
    change = ctx.get("change_description", "")
    candidates = ctx.get("candidate_files", [])
    primary_area = ctx.get("primary_area") or "unknown"
    old, new = _split_from_to(change)

    targets = [c["file"] for c in candidates][:6]
    if not targets:
        targets = ctx.get("python_files", [])[:5]

    if old and new:
        summary = (
            f"The change replaces {old} logic with {new} logic in the "
            f"'{primary_area}' area."
        )
    else:
        summary = f"Change described as: {_short(change, 180)}"

    reason_lines = [
        f"{c['file']}: {'; '.join(c.get('reasons', [])[:2])}" for c in candidates[:4]
    ]
    reasoning = (
        "Ranked repository files by name, defined symbols and documentation "
        "mentions against the change description, then pulled in downstream "
        "importers from the deterministic import graph. "
        + (" ".join(reason_lines) if reason_lines else "No strong textual matches found.")
    )

    return {
        "change_summary": summary,
        "primary_area": primary_area,
        "investigation_targets": targets,
        "reasoning": reasoning,
        "confidence": _confidence(0.82, len(candidates)),
    }


# --------------------------------------------------------------------------
# Agent 2: Code Analyst
# --------------------------------------------------------------------------


def _build_code_analyst(ctx: dict) -> dict:
    change = ctx.get("change_description", "")
    primary = ctx.get("primary_target") or ""
    downstream = ctx.get("downstream_files", [])
    symbols = ctx.get("target_symbols", [])
    test_files = ctx.get("test_files", [])
    imported_by = ctx.get("imported_by", {})
    old, new = _split_from_to(change)

    findings: list[dict] = []
    breakages: list[dict] = []

    # --- Direct impact: the file the change lands in ----------------------
    if primary:
        symbol_names = [s["name"] for s in symbols if s.get("file") == primary]
        headline = _headline_symbol(
            [s for s in symbols if s.get("file") == primary], change
        )
        evidence_parts = []
        if symbol_names:
            evidence_parts.append(f"defines {', '.join(symbol_names[:4])}")
        direct_importers = imported_by.get(primary, [])
        if direct_importers:
            evidence_parts.append(f"imported by {len(direct_importers)} module(s)")

        findings.append(
            {
                "file": primary,
                "symbol": headline,
                "severity": "HIGH",
                "impact_type": "DIRECT",
                "explanation": (
                    f"This file contains the changed logic. Moving from {old or 'the previous rule'} "
                    f"to {new or 'the new rule'} alters the value returned by "
                    f"{headline or 'its public functions'}, so every caller sees different results "
                    "for the same inputs."
                ),
                "evidence": f"{primary}: {'; '.join(evidence_parts)}" if evidence_parts else primary,
                "confidence": _confidence(0.88, len(symbol_names)),
            }
        )

        # Inputs the old rule depended on may no longer be supplied.
        old_terms = _significant_terms(old)
        if old_terms:
            breakages.append(
                {
                    "file": primary,
                    "description": (
                        f"Callers still passing {'/'.join(old_terms[:3])} data may now be "
                        "supplying fields the new rule ignores, or omitting fields it requires."
                    ),
                    "severity": "HIGH",
                    "confidence": 0.8,
                }
            )

    # --- Downstream impact: real importers, from the import graph ----------
    for module in downstream:
        if module.endswith("__init__.py"):
            continue
        is_test = module in test_files
        findings.append(
            {
                "file": module,
                "symbol": "",
                "severity": "MEDIUM" if not is_test else "LOW",
                "impact_type": "POTENTIAL_DOWNSTREAM",
                "explanation": (
                    f"{module} consumes {primary} through the import graph, so it inherits the "
                    "new behaviour without any change of its own. "
                    + (
                        "As a test module it encodes the old expectations and will need updating."
                        if is_test
                        else "Its own assumptions about the returned values should be re-checked."
                    )
                ),
                "evidence": f"{module} imports {primary} (deterministic import graph)",
                "confidence": _confidence(0.7, 2),
            }
        )
        if not is_test:
            breakages.append(
                {
                    "file": module,
                    "description": (
                        f"Logic in {module} that branches on the value produced by {primary} "
                        "may take different paths after the change."
                    ),
                    "severity": "MEDIUM",
                    "confidence": 0.66,
                }
            )

    # --- Recommended tests -------------------------------------------------
    tests: list[dict] = []
    new_terms = _significant_terms(new)
    slug = ("_".join(new_terms[:3]) if new_terms else "new_behaviour").replace("-", "_")
    if primary:
        tests.append(
            {
                "test_name": f"test_{slug}",
                "reason": (
                    f"There is no test covering the {new or 'new'} rule. Add a case pinning the "
                    "new expected values so the change cannot silently regress."
                ),
                "affected_component": primary,
                "priority": "HIGH",
            }
        )
    for test_file in test_files:
        if primary and primary in ctx.get("import_graph", {}).get(test_file, []):
            tests.append(
                {
                    "test_name": f"update {test_file}",
                    "reason": (
                        f"{test_file} asserts the previous behaviour of {primary} and will fail "
                        "or, worse, keep passing against stale expectations."
                    ),
                    "affected_component": test_file,
                    "priority": "HIGH",
                }
            )

    components = [primary] if primary else []
    components += [m for m in downstream if not m.endswith("__init__.py")]

    return {
        "affected_components": components,
        "code_findings": findings,
        "potential_breakages": breakages,
        "recommended_tests": tests,
        "confidence": _confidence(0.8, len(findings)),
    }


# --------------------------------------------------------------------------
# Agent 3: Documentation Analyst
# --------------------------------------------------------------------------


def _build_docs_analyst(ctx: dict) -> dict:
    change = ctx.get("change_description", "")
    documents = ctx.get("documents", [])
    old, new = _split_from_to(change)
    old_terms = _significant_terms(old) or _significant_terms(change)[:3]

    findings: list[dict] = []
    stale: list[str] = []
    proposals: list[str] = []

    for document in documents:
        path = document.get("path", "")
        excerpt = document.get("excerpt", "")
        lowered = excerpt.lower()

        hits = [term for term in old_terms if term in lowered]
        if not hits:
            continue

        statement = _find_statement(excerpt, hits[0])
        section = _find_section(excerpt, statement) or (
            document.get("headings", [""])[0] if document.get("headings") else ""
        )

        findings.append(
            {
                "document": path,
                "section": section,
                "current_statement": _short(statement, 260),
                "why_stale": (
                    f"This text describes {old or 'the previous behaviour'} "
                    f"({', '.join(hits[:3])}), which the change replaces with "
                    f"{new or 'the new behaviour'}. A reader following this document would "
                    "implement or expect the wrong thing."
                ),
                "recommended_update": (
                    f"Rewrite the '{section or path}' section to describe {new or 'the new behaviour'}, "
                    f"and remove references to {', '.join(hits[:3])}."
                ),
                "status": "STALE",
                "confidence": _confidence(0.84, len(hits)),
            }
        )
        stale.append(path)
        proposals.append(f"Update {path}: describe {new or 'the new behaviour'} instead of {old or 'the old behaviour'}.")

    return {
        "documentation_findings": findings,
        "stale_documents": stale,
        "proposed_updates": proposals,
        "confidence": _confidence(0.78, len(findings)) if findings else 0.55,
    }


def _find_statement(excerpt: str, term: str) -> str:
    """The most specific line of documentation that mentions `term`."""
    best = ""
    for line in excerpt.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if term in stripped.lower() and len(stripped) > len(best):
            best = stripped
            if len(best) > 80:
                break
    return best or _short(excerpt, 160)


def _find_section(excerpt: str, statement: str) -> str:
    """The nearest markdown heading above `statement`."""
    heading = ""
    for line in excerpt.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
        elif statement and stripped == statement.strip():
            return heading
    return heading


# --------------------------------------------------------------------------
# Agent 4: Dependency Analyst
# --------------------------------------------------------------------------


def _build_dependency_analyst(ctx: dict) -> dict:
    primary = ctx.get("primary_target") or ""
    import_graph = ctx.get("import_graph", {})
    imported_by = ctx.get("imported_by", {})
    downstream = ctx.get("downstream_files", [])
    test_files = set(ctx.get("test_files", []))

    edges: list[dict] = []
    for source, targets in sorted(import_graph.items()):
        for target in targets:
            if target == primary or source == primary or target in downstream:
                edges.append(
                    {
                        "source": source,
                        "target": target,
                        "relationship": "imports",
                    }
                )

    risks: list[dict] = []
    direct = [m for m in imported_by.get(primary, []) if not m.endswith("__init__.py")]
    for module in direct:
        is_test = module in test_files
        risks.append(
            {
                "module": module,
                "risk": (
                    f"{module} imports {primary} directly, so it is exposed to the change with no "
                    "intermediate layer to absorb it."
                    + (" It encodes the old expectations as assertions." if is_test else "")
                ),
                "severity": "LOW" if is_test else "HIGH",
                "confidence": 0.92,
            }
        )

    indirect = [m for m in downstream if m not in direct and not m.endswith("__init__.py")]
    for module in indirect:
        risks.append(
            {
                "module": module,
                "risk": (
                    f"{module} reaches {primary} transitively, so the impact is real but "
                    "second-order — verify rather than assume."
                ),
                "severity": "MEDIUM",
                "confidence": 0.72,
            }
        )

    modules = sorted({m for m in [primary, *downstream] if m and not m.endswith("__init__.py")})

    return {
        "dependencies": edges,
        "affected_modules": modules,
        "dependency_risks": risks,
        "confidence": _confidence(0.9, len(edges)),
    }


# --------------------------------------------------------------------------
# Agent 5: Impact Reviewer
# --------------------------------------------------------------------------

_SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
_SEVERITY_BY_RANK = {rank: name for name, rank in _SEVERITY_ORDER.items()}


def _build_impact_reviewer(ctx: dict) -> dict:
    change = ctx.get("change_description", "")
    old, new = _split_from_to(change)
    unavailable = ctx.get("unavailable_evidence", [])

    code = ctx.get("code_analyst_output") or {}
    docs = ctx.get("documentation_analyst_output") or {}
    deps = ctx.get("dependency_analyst_output") or {}
    imported_by = ctx.get("imported_by", {})
    primary = ctx.get("primary_target") or ""

    # --- Consolidate components ------------------------------------------
    components: list[dict] = []
    seen: set[str] = set()

    for finding in code.get("code_findings", []):
        file = finding.get("file", "")
        if not file or file in seen:
            continue
        seen.add(file)
        # A component named by BOTH the code analyst and the dependency graph
        # is corroborated, so it earns a confidence bump.
        corroborated = any(
            risk.get("module") == file for risk in deps.get("dependency_risks", [])
        )
        components.append(
            {
                "component": file,
                "impact": _short(finding.get("explanation", ""), 320),
                "severity": finding.get("severity", "MEDIUM"),
                "evidence": finding.get("evidence", ""),
                "confidence": min(
                    0.97, finding.get("confidence", 0.5) + (0.05 if corroborated else 0.0)
                ),
            }
        )

    # Modules only the dependency analyst saw still deserve a mention.
    for risk in deps.get("dependency_risks", []):
        module = risk.get("module", "")
        if not module or module in seen:
            continue
        seen.add(module)
        components.append(
            {
                "component": module,
                "impact": _short(risk.get("risk", ""), 320),
                "severity": risk.get("severity", "MEDIUM"),
                "evidence": f"import graph: {module} depends on {primary}",
                "confidence": risk.get("confidence", 0.6),
            }
        )

    components.sort(
        key=lambda c: (-_SEVERITY_ORDER.get(c["severity"], 0), -c["confidence"], c["component"])
    )

    # --- Documentation ----------------------------------------------------
    documentation = [
        {
            "document": finding.get("document", ""),
            "status": finding.get("status", "REVIEW"),
            "reason": _short(finding.get("why_stale", ""), 300),
            "recommended_action": _short(finding.get("recommended_update", ""), 300),
            "confidence": finding.get("confidence", 0.6),
        }
        for finding in docs.get("documentation_findings", [])
    ]

    # --- Tests -------------------------------------------------------------
    tests = list(code.get("recommended_tests", []))

    # --- Severity ----------------------------------------------------------
    overall = _overall_severity(components, documentation, unavailable)

    # --- Evidence tiers ----------------------------------------------------
    confirmed: list[str] = []
    likely: list[str] = []
    uncertain: list[str] = []

    for component in components:
        line = f"{component['component']} — {component['severity']}"
        # Confirmed means backed by the deterministic import graph, not by
        # model inference. That distinction is the whole point of this section.
        if component["component"] == primary:
            confirmed.append(f"{line}: contains the changed logic.")
        elif component["component"] in imported_by.get(primary, []):
            confirmed.append(
                f"{line}: imports {primary} directly (verified in the import graph)."
            )
        elif component["confidence"] >= 0.7:
            likely.append(f"{line}: reaches {primary} transitively.")
        else:
            uncertain.append(f"{line}: relationship inferred, not verified.")

    for document in documentation:
        text = f"{document['document']} — {document['status']}"
        if document["confidence"] >= 0.8:
            confirmed.append(f"{text}: contains text describing the replaced behaviour.")
        else:
            likely.append(f"{text}: may reference the replaced behaviour.")

    for agent in unavailable:
        uncertain.append(
            f"{agent} produced no evidence (agent failed); findings in its area are incomplete."
        )

    # --- Contradictions / unsupported claims -------------------------------
    contradictions: list[str] = []
    unsupported: list[str] = []

    code_components = set(code.get("affected_components", []))
    dep_modules = set(deps.get("affected_modules", []))
    only_code = sorted(code_components - dep_modules - {""})
    for component in only_code:
        unsupported.append(
            f"{component} was named by the Code Analyst but has no supporting edge in the "
            "import graph — treat as unverified."
        )

    if unavailable:
        contradictions.append(
            "Consolidation is partial: "
            + ", ".join(unavailable)
            + " did not return evidence, so gaps in those areas are unknown rather than absent."
        )

    # --- Actions -----------------------------------------------------------
    actions: list[str] = []
    if documentation:
        for document in documentation[:3]:
            actions.append(f"Update {document['document']} to describe {new or 'the new behaviour'}.")
    high_risk = [c for c in components if c["severity"] in ("HIGH", "CRITICAL")]
    if high_risk:
        actions.append(
            "Review "
            + ", ".join(c["component"] for c in high_risk[:3])
            + " for assumptions that no longer hold."
        )
    if tests:
        actions.append(
            "Add or update regression tests: " + ", ".join(t["test_name"] for t in tests[:3]) + "."
        )
    medium = [c for c in components if c["severity"] == "MEDIUM"]
    if medium:
        actions.append(
            "Verify downstream behaviour in " + ", ".join(c["component"] for c in medium[:3]) + "."
        )
    if not actions:
        actions.append("No actionable impact identified; re-run with a more specific change description.")

    # --- Risks -------------------------------------------------------------
    risks = [
        _short(breakage.get("description", ""), 240)
        for breakage in code.get("potential_breakages", [])
    ]
    for risk in deps.get("dependency_risks", []):
        if risk.get("severity") in ("HIGH", "CRITICAL"):
            risks.append(_short(risk.get("risk", ""), 240))
    if documentation:
        risks.append(
            f"{len(documentation)} document(s) still describe {old or 'the previous behaviour'}; "
            "readers and API consumers will be misled until they are updated."
        )

    summary = _build_summary(change, old, new, primary, components, documentation, unavailable)

    confidences = [c["confidence"] for c in components] or [0.5]
    overall_confidence = round(sum(confidences) / len(confidences), 2)
    if unavailable:
        overall_confidence = round(max(0.3, overall_confidence - 0.15), 2)

    return {
        "overall_severity": overall,
        "summary": summary,
        "affected_components": components,
        "documentation_updates": documentation,
        "recommended_tests": tests,
        "recommended_actions": actions,
        "risks": _dedupe(risks),
        "confirmed_findings": confirmed,
        "likely_findings": likely,
        "uncertain_findings": uncertain,
        "contradictions": contradictions,
        "unsupported_claims": unsupported,
        "confidence": overall_confidence,
    }


def _overall_severity(components: list[dict], documentation: list[dict], unavailable: list) -> str:
    if not components:
        return "LOW"
    top = max(_SEVERITY_ORDER.get(c["severity"], 0) for c in components)
    high_count = sum(1 for c in components if c["severity"] in ("HIGH", "CRITICAL"))
    # Breadth escalates severity: several high-severity components plus stale
    # public documentation is a bigger deal than one isolated hot spot.
    if top >= 2 and high_count >= 2 and documentation:
        return "HIGH"
    if top >= 2 and len(components) >= 3:
        return "HIGH"
    return _SEVERITY_BY_RANK.get(top, "MEDIUM")


def _build_summary(
    change: str,
    old: str,
    new: str,
    primary: str,
    components: list[dict],
    documentation: list[dict],
    unavailable: list,
) -> str:
    parts: list[str] = []
    if old and new:
        parts.append(
            f"The change replaces {old} logic with {new} logic"
            + (f", implemented in {primary}." if primary else ".")
        )
    else:
        parts.append(_short(change, 200))

    if components:
        parts.append(
            f"It directly affects {components[0]['component']} and reaches "
            f"{len(components) - 1} further component(s) through the import graph."
            if len(components) > 1
            else f"It affects {components[0]['component']}."
        )

    if documentation:
        parts.append(
            f"{len(documentation)} document(s) still describe the previous behaviour and are now stale: "
            + ", ".join(d["document"] for d in documentation[:3])
            + "."
        )

    if unavailable:
        parts.append(
            "Note: " + ", ".join(unavailable) + " failed, so this report is based on partial evidence."
        )

    return " ".join(parts)


def _dedupe(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.append(item)
    return seen


_BUILDERS = {
    "planner": _build_planner,
    "code_analyst": _build_code_analyst,
    "documentation_analyst": _build_docs_analyst,
    "dependency_analyst": _build_dependency_analyst,
    "impact_reviewer": _build_impact_reviewer,
}
