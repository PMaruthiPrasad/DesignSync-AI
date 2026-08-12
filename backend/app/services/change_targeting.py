"""Deterministic change -> candidate-file targeting.

Given a natural-language change description and a `RepositorySummary`, score
repository files by how likely they are to be the site of the change. This is
pure keyword/symbol matching — no LLM involved.

It serves two purposes:
  1. It gives the Planner concrete candidates instead of a blank slate.
  2. It is the fallback plan when the Planner agent fails, so the workflow can
     continue safely rather than collapsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas import RepositorySummary

STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "from", "of", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "it", "its", "this", "that", "we",
    "our", "changed", "change", "changes", "update", "updated", "updates", "now",
    "based", "using", "use", "used", "instead", "new", "old", "into", "by", "at",
    "how", "when", "made", "make", "should", "will", "has", "have", "had",
}

MIN_TOKEN_LENGTH = 3


@dataclass
class TargetCandidate:
    """A file that may be involved in the change, with the reason why."""

    file: str
    score: float
    reasons: list[str]


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, minus stopwords and very short words."""
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text.lower())
    return [w for w in words if len(w) >= MIN_TOKEN_LENGTH and w not in STOPWORDS]


def find_candidates(
    change_description: str, summary: RepositorySummary, limit: int = 8
) -> list[TargetCandidate]:
    """Rank repository files by textual relevance to the change description."""
    tokens = set(tokenize(change_description))
    if not tokens:
        return []

    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}

    def add(file: str, points: float, reason: str) -> None:
        scores[file] = scores.get(file, 0.0) + points
        bucket = reasons.setdefault(file, [])
        if reason not in bucket:
            bucket.append(reason)

    # 1. Path / filename matches are the strongest signal.
    for file in summary.files:
        path_tokens = set(tokenize(file.replace("/", " ").replace(".", " ")))
        for token in tokens & path_tokens:
            weight = 4.0 if file.endswith(".py") else 2.5
            add(file, weight, f"path mentions '{token}'")

    # 2. Defined symbols matching the description.
    for symbol in summary.symbols:
        symbol_tokens = set(tokenize(symbol.name.replace(".", " ")))
        for token in tokens & symbol_tokens:
            add(symbol.file, 3.0, f"defines '{symbol.name}' matching '{token}'")

    # 3. Documentation mentioning the concept — for doc drift.
    for document in summary.documents:
        doc_tokens = set(tokenize(document.excerpt))
        overlap = tokens & doc_tokens
        if overlap:
            add(
                document.path,
                1.0 + 0.5 * min(len(overlap), 4),
                f"documents {sorted(overlap)[:3]}",
            )

    # 4. Files importing a high-scoring implementation file inherit relevance,
    #    which is how downstream consumers surface as candidates.
    seeded = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:3]
    for file, _ in seeded:
        for importer in summary.imported_by.get(file, []):
            add(importer, 1.5, f"imports {file}")

    candidates = [
        TargetCandidate(file=file, score=round(score, 2), reasons=reasons.get(file, []))
        for file, score in scores.items()
    ]
    candidates.sort(key=lambda c: (-c.score, c.file))
    return candidates[:limit]


def primary_area(candidates: list[TargetCandidate]) -> str:
    """Infer the main software area (top-level package) from the candidates."""
    for candidate in candidates:
        if candidate.file.endswith(".py") and "/" in candidate.file:
            return candidate.file.split("/", 1)[0]
    if candidates:
        head = candidates[0].file
        return head.split("/", 1)[0] if "/" in head else "root"
    return "unknown"


def downstream_files(files: list[str], summary: RepositorySummary, depth: int = 2) -> list[str]:
    """Files that transitively import any of `files` — the real blast radius."""
    seen: set[str] = set()
    frontier = list(files)

    for _ in range(depth):
        next_frontier: list[str] = []
        for file in frontier:
            for importer in summary.imported_by.get(file, []):
                if importer not in seen and importer not in files:
                    seen.add(importer)
                    next_frontier.append(importer)
        frontier = next_frontier
        if not frontier:
            break

    return sorted(seen)
