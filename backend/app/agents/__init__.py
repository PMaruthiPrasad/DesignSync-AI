"""The five analysis agents and their shared execution wrapper."""

PLANNER = "planner"
CODE_ANALYST = "code_analyst"
DOCS_ANALYST = "documentation_analyst"
DEPENDENCY_ANALYST = "dependency_analyst"
IMPACT_REVIEWER = "impact_reviewer"

# The three independent branches that run concurrently between the Planner and
# the Impact Reviewer.
PARALLEL_AGENTS = (CODE_ANALYST, DOCS_ANALYST, DEPENDENCY_ANALYST)

ALL_AGENTS = (PLANNER, *PARALLEL_AGENTS, IMPACT_REVIEWER)

AGENT_LABELS = {
    PLANNER: "Planner",
    CODE_ANALYST: "Code Analyst",
    DOCS_ANALYST: "Documentation Analyst",
    DEPENDENCY_ANALYST: "Dependency Analyst",
    IMPACT_REVIEWER: "Impact Reviewer",
}
