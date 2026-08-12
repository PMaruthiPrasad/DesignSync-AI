"""System prompts and evidence-envelope builders for each agent.

Design decision: rather than one giant prompt, each agent gets a narrow role, a
narrow output schema, and only the evidence it needs. The deterministic
repository facts travel in a `<CONTEXT>` JSON block, so the model reasons over
structured evidence instead of rediscovering the repository from scratch.
"""

from __future__ import annotations

from app.llm.envelope import render_context
from app.schemas import RepositorySummary
from app.services.change_targeting import (
    TargetCandidate,
    downstream_files,
    find_candidates,
    primary_area,
)

MAX_DOC_EXCERPT = 2500
MAX_DOCS = 8

EVIDENCE_RULES = """
Rules you must follow:
- Ground every finding in the supplied evidence. Cite the file, symbol or
  document that supports it in the `evidence` field.
- Never invent a file, module, symbol or document that is not in the context.
- Distinguish what the evidence proves from what it merely suggests, and set
  `confidence` accordingly (0.0-1.0).
- Return JSON matching the schema exactly. No prose outside the JSON.
""".strip()

PLANNER_SYSTEM = f"""
You are the Planner in a software change-impact analysis system.

Your job is to turn a developer's change description into an investigation
plan. You scope the work; you do NOT perform the analysis yourself and you do
NOT list findings.

Identify the main software area involved, the files most likely to be relevant,
and explain briefly why you chose them.

{EVIDENCE_RULES}
""".strip()

CODE_ANALYST_SYSTEM = f"""
You are the Code Analyst in a software change-impact analysis system.

Analyse how the described change affects the code: functions, classes, imports,
callers, references, downstream modules and behaviour.

You must clearly separate:
- DIRECT impact: the code that actually changed.
- POTENTIAL_DOWNSTREAM impact: code that consumes the changed code and may be
  affected as a consequence.

Do not claim a breakage you cannot point to evidence for. An unproven
possibility belongs in `potential_breakages` with a lower confidence, not in
`code_findings` as fact.

{EVIDENCE_RULES}
""".strip()

DOCS_ANALYST_SYSTEM = f"""
You are the Documentation Analyst in a software change-impact analysis system.

Find documentation that has become stale because of the change: READMEs, docs/
markdown, API references, usage examples, configuration docs.

For each finding, quote the specific existing statement that is now wrong,
explain why the change invalidates it, and propose the corrected wording.

A document that merely mentions the area is not automatically stale. Only flag
text whose meaning the change actually contradicts.

{EVIDENCE_RULES}
""".strip()

DEPENDENCY_ANALYST_SYSTEM = f"""
You are the Dependency Analyst in a software change-impact analysis system.

The import graph in your context was produced by deterministic AST parsing, not
by a model. Treat it as fact.

Your job is interpretation, not discovery: explain what those relationships mean
for this change — which modules are exposed directly, which are exposed
transitively, and where the risk concentrates.

{EVIDENCE_RULES}
""".strip()

IMPACT_REVIEWER_SYSTEM = f"""
You are the Impact Reviewer, the final synthesis and quality-control agent in a
software change-impact analysis system.

You receive the outputs of the Code, Documentation and Dependency analysts.
Your responsibilities:
1. Consolidate their findings into one coherent report.
2. Identify contradictions between them.
3. Identify unsupported claims — assertions no evidence backs.
4. Determine the overall impact severity.
5. Identify the high-risk areas.
6. Determine which documentation must change.
7. Recommend tests.
8. Produce a concise, ordered engineering action plan.

You must sort every finding into exactly one of three tiers:
- `confirmed_findings`: backed by hard evidence (e.g. a verified import edge).
- `likely_findings`: well supported inference, not proof.
- `uncertain_findings`: plausible but unverified, or blocked by missing evidence.

If an analyst's evidence is unavailable, say so explicitly rather than
presenting the remaining picture as complete. Never present inference as fact.

{EVIDENCE_RULES}
""".strip()


# --------------------------------------------------------------------------
# Shared evidence
# --------------------------------------------------------------------------


def build_base_context(
    change_description: str,
    summary: RepositorySummary,
    candidates: list[TargetCandidate] | None = None,
) -> dict:
    """Deterministic evidence shared by every agent."""
    candidates = candidates if candidates is not None else find_candidates(change_description, summary)

    python_candidates = [c.file for c in candidates if c.file.endswith(".py")]
    primary_target = python_candidates[0] if python_candidates else ""
    downstream = downstream_files([primary_target], summary) if primary_target else []

    return {
        "change_description": change_description,
        "repository_name": summary.name,
        "primary_area": primary_area(candidates),
        "primary_target": primary_target,
        "candidate_files": [
            {"file": c.file, "score": c.score, "reasons": c.reasons} for c in candidates
        ],
        "downstream_files": downstream,
        "python_files": [f for f in summary.files if f.endswith(".py")],
        "test_files": summary.test_files,
        "documentation_files": summary.documentation_files,
    }


def _relevant_graph(summary: RepositorySummary, files: list[str]) -> tuple[dict, dict]:
    """Trim the import graph to the neighbourhood of `files`, to keep prompts small."""
    keep = set(files)
    for file in files:
        keep.update(summary.import_graph.get(file, []))
        keep.update(summary.imported_by.get(file, []))

    graph = {k: v for k, v in summary.import_graph.items() if k in keep or set(v) & keep}
    reverse = {k: v for k, v in summary.imported_by.items() if k in keep}
    return graph, reverse


# --------------------------------------------------------------------------
# Per-agent prompts
# --------------------------------------------------------------------------


def planner_prompt(base: dict, summary: RepositorySummary) -> str:
    context = {
        **base,
        "repository_structure": {
            "files": summary.files,
            "python_modules": summary.python_modules,
            "documentation_files": summary.documentation_files,
            "test_files": summary.test_files,
        },
        "symbols_sample": [
            {"name": s.name, "kind": s.kind, "file": s.file, "line": s.line}
            for s in summary.symbols[:40]
        ],
    }
    return (
        "Produce an investigation plan for the following software change.\n\n"
        f"CHANGE DESCRIPTION:\n{base['change_description']}\n\n"
        "REPOSITORY EVIDENCE (deterministic, AST-derived):\n"
        f"{render_context(context)}"
    )


def code_analyst_prompt(base: dict, summary: RepositorySummary, plan: dict) -> str:
    targets = plan.get("investigation_targets") or [base["primary_target"]]
    focus = [t for t in targets if t.endswith(".py")] or [base["primary_target"]]
    graph, reverse = _relevant_graph(summary, [f for f in focus if f])

    context = {
        **base,
        "planner_output": plan,
        "focus_files": focus,
        "import_graph": graph,
        "imported_by": reverse,
        "target_symbols": [
            {"name": s.name, "kind": s.kind, "file": s.file, "line": s.line}
            for s in summary.symbols
            if s.file in set(focus) | set(base["downstream_files"])
        ],
        "references": {
            file: refs
            for file, refs in summary.references.items()
            if file in set(focus) | set(base["downstream_files"])
        },
    }
    return (
        "Analyse the code impact of the following software change.\n\n"
        f"CHANGE DESCRIPTION:\n{base['change_description']}\n\n"
        "EVIDENCE:\n"
        f"{render_context(context)}"
    )


def docs_analyst_prompt(base: dict, summary: RepositorySummary, plan: dict) -> str:
    context = {
        **base,
        "planner_output": plan,
        "documents": [
            {
                "path": d.path,
                "headings": d.headings,
                "excerpt": d.excerpt[:MAX_DOC_EXCERPT],
            }
            for d in summary.documents[:MAX_DOCS]
        ],
    }
    return (
        "Identify documentation made stale by the following software change.\n\n"
        f"CHANGE DESCRIPTION:\n{base['change_description']}\n\n"
        "EVIDENCE:\n"
        f"{render_context(context)}"
    )


def dependency_analyst_prompt(base: dict, summary: RepositorySummary, plan: dict) -> str:
    focus = [base["primary_target"]] if base["primary_target"] else []
    graph, reverse = _relevant_graph(summary, focus or summary.files[:20])

    context = {
        **base,
        "planner_output": plan,
        "import_graph": graph,
        "imported_by": reverse,
        "raw_imports": {
            file: imports
            for file, imports in summary.imports.items()
            if file in set(graph) | set(reverse)
        },
    }
    return (
        "Interpret the dependency impact of the following software change. The "
        "import graph below is deterministic AST output — treat it as fact.\n\n"
        f"CHANGE DESCRIPTION:\n{base['change_description']}\n\n"
        "EVIDENCE:\n"
        f"{render_context(context)}"
    )


def impact_reviewer_prompt(
    base: dict,
    summary: RepositorySummary,
    plan: dict,
    code_output: dict | None,
    docs_output: dict | None,
    dependency_output: dict | None,
    unavailable_evidence: list[str],
) -> str:
    focus = [base["primary_target"]] if base["primary_target"] else []
    _, reverse = _relevant_graph(summary, focus)

    context = {
        **base,
        "planner_output": plan,
        "code_analyst_output": code_output,
        "documentation_analyst_output": docs_output,
        "dependency_analyst_output": dependency_output,
        "unavailable_evidence": unavailable_evidence,
        "imported_by": reverse,
    }

    warning = ""
    if unavailable_evidence:
        warning = (
            "\nIMPORTANT: the following agents failed and produced no evidence: "
            + ", ".join(unavailable_evidence)
            + ". Do not treat their areas as clear — mark the gap explicitly in "
            "`uncertain_findings` and `contradictions`.\n"
        )

    return (
        "Consolidate the analyst outputs below into a final software change "
        "impact report.\n\n"
        f"CHANGE DESCRIPTION:\n{base['change_description']}\n"
        f"{warning}\n"
        "EVIDENCE:\n"
        f"{render_context(context)}"
    )
