"""Deterministic repository analysis.

Design decision: basic facts about a repository — which files exist, which
modules import which, what functions and classes are defined — are *parsing
problems*, not reasoning problems. Asking an LLM to discover them is slow,
expensive and unreliable. We derive them with Python's `ast` module and hand
the result to the agents as evidence, so the LLM spends its budget on
interpretation instead of rediscovery.

Security: analysed repositories are untrusted input. Files are read as **text**
and parsed with `ast.parse`. Nothing here imports a module, executes a file, or
runs a setup script.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.config import get_settings
from app.schemas import DocumentInfo, RepositorySummary, SymbolInfo

SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    ".pytest_cache", ".mypy_cache", "dist", "build", ".idea", ".vscode",
    ".ruff_cache", ".tox", "site-packages", ".next", "coverage",
}

DOC_SUFFIXES = {".md", ".rst", ".txt"}
MAX_FILES = 3000
DOC_EXCERPT_CHARS = 4000


def analyze_repository(root: Path, name: str | None = None) -> RepositorySummary:
    """Build a structured summary of the repository at `root`."""
    settings = get_settings()
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"Repository path is not a directory: {root}")

    summary = RepositorySummary(name=name or root.name, root=str(root))

    module_by_path: dict[str, str] = {}
    raw_imports: dict[str, list[str]] = {}

    for path in _walk(root):
        rel = path.relative_to(root).as_posix()
        summary.files.append(rel)

        if path.suffix == ".py":
            module = _module_name(rel)
            module_by_path[rel] = module
            summary.python_modules.append(module)
            if _is_test_file(rel):
                summary.test_files.append(rel)

            source = _read_text(path, settings.max_source_file_bytes)
            if source is None:
                summary.malformed_files.append(rel)
                continue

            try:
                tree = ast.parse(source, filename=rel)
            except (SyntaxError, ValueError, RecursionError):
                # A file we cannot parse is recorded and skipped — never fatal.
                summary.malformed_files.append(rel)
                continue

            imports, symbols, references = _inspect_module(tree, rel)
            raw_imports[rel] = imports
            summary.symbols.extend(symbols)
            if references:
                summary.references[rel] = references

        elif path.suffix.lower() in DOC_SUFFIXES:
            summary.documentation_files.append(rel)
            text = _read_text(path, settings.max_source_file_bytes)
            if text is None:
                summary.malformed_files.append(rel)
                continue
            summary.documents.append(
                DocumentInfo(
                    path=rel,
                    headings=_markdown_headings(text),
                    excerpt=text[:DOC_EXCERPT_CHARS],
                )
            )

    summary.imports = raw_imports
    summary.import_graph = _build_import_graph(raw_imports, module_by_path)
    summary.imported_by = _reverse_graph(summary.import_graph)

    summary.files.sort()
    summary.python_modules.sort()
    summary.documentation_files.sort()
    summary.test_files.sort()
    return summary


# --------------------------------------------------------------------------
# Walking / reading
# --------------------------------------------------------------------------


def _walk(root: Path):
    """Yield analysable files, skipping vendor/build directories."""
    count = 0
    for path in sorted(root.rglob("*")):
        if count >= MAX_FILES:
            break
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        if path.name.startswith("."):
            continue
        count += 1
        yield path


def _read_text(path: Path, max_bytes: int) -> str | None:
    """Read a file as UTF-8 text. Returns None if too large or undecodable."""
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _is_test_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    parts = rel.split("/")[:-1]
    return name.startswith("test_") or name.endswith("_test.py") or "tests" in parts


def _module_name(rel: str) -> str:
    """`pricing/discount.py` -> `pricing.discount`; `pkg/__init__.py` -> `pkg`."""
    stem = rel[:-3] if rel.endswith(".py") else rel
    if stem.endswith("/__init__"):
        stem = stem[: -len("/__init__")]
    return stem.replace("/", ".")


# --------------------------------------------------------------------------
# AST inspection
# --------------------------------------------------------------------------


def _inspect_module(tree: ast.AST, rel: str) -> tuple[list[str], list[SymbolInfo], list[str]]:
    """Extract imports, defined symbols and call references from one module."""
    imports: list[str] = []
    symbols: list[SymbolInfo] = []
    references: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.class_stack: list[str] = []

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                imports.append(alias.name)
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module:
                # Record the module, and each imported name as `module.name`
                # so symbol-level references resolve too.
                imports.append(node.module)
                for alias in node.names:
                    imports.append(f"{node.module}.{alias.name}")
            self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            symbols.append(
                SymbolInfo(name=node.name, kind="class", file=rel, line=node.lineno)
            )
            self.class_stack.append(node.name)
            self.generic_visit(node)
            self.class_stack.pop()

        def _function(self, node) -> None:
            if self.class_stack:
                name = f"{self.class_stack[-1]}.{node.name}"
                kind = "method"
            else:
                name = node.name
                kind = "function"
            symbols.append(SymbolInfo(name=name, kind=kind, file=rel, line=node.lineno))
            self.generic_visit(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._function(node)

        def visit_Call(self, node: ast.Call) -> None:
            name = _call_name(node.func)
            if name:
                references.add(name)
            self.generic_visit(node)

    Visitor().visit(tree)
    return sorted(set(imports)), symbols, sorted(references)


def _call_name(node: ast.AST) -> str | None:
    """Best-effort dotted name for a call target."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


# --------------------------------------------------------------------------
# Import graph
# --------------------------------------------------------------------------


def _build_import_graph(
    raw_imports: dict[str, list[str]], module_by_path: dict[str, str]
) -> dict[str, list[str]]:
    """Map file -> the repository files it imports.

    Only *internal* imports are kept. Third-party and stdlib imports are
    discarded: they say nothing about this repository's blast radius.
    """
    module_to_path = {module: path for path, module in module_by_path.items()}
    graph: dict[str, list[str]] = {}

    for path, imports in raw_imports.items():
        targets: set[str] = set()
        for imported in imports:
            target = _resolve_internal(imported, module_to_path)
            if target and target != path:
                targets.add(target)
        graph[path] = sorted(targets)

    return graph


def _resolve_internal(imported: str, module_to_path: dict[str, str]) -> str | None:
    """Resolve a dotted import to a repository file, if it is internal.

    Handles `pricing.discount` (module) and `pricing.discount.calculate_discount`
    (symbol imported from a module) by trimming trailing components.
    """
    parts = imported.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in module_to_path:
            return module_to_path[candidate]
        parts.pop()
    return None


def _reverse_graph(graph: dict[str, list[str]]) -> dict[str, list[str]]:
    """Invert the import graph: file -> files that import it (its callers)."""
    reverse: dict[str, set[str]] = {}
    for source, targets in graph.items():
        for target in targets:
            reverse.setdefault(target, set()).add(source)
    return {key: sorted(value) for key, value in sorted(reverse.items())}


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------


def _markdown_headings(text: str) -> list[str]:
    headings = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.append(stripped.lstrip("#").strip())
    return headings
