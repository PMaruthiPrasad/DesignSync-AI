"""Deterministic repository analysis.

These tests assert the facts the agents are given as evidence. If this layer is
wrong, every downstream finding is wrong.
"""

from app.services.change_targeting import downstream_files, find_candidates, primary_area
from app.services.repo_analysis import analyze_repository

from tests.conftest import DEMO_CHANGE


def test_detects_python_files(demo_summary):
    assert "pricing/discount.py" in demo_summary.files
    assert "checkout/service.py" in demo_summary.files
    assert "api/pricing_api.py" in demo_summary.files


def test_detects_python_modules(demo_summary):
    assert "pricing.discount" in demo_summary.python_modules
    assert "pricing.pricing_service" in demo_summary.python_modules
    # `pricing/__init__.py` becomes the package name, not `pricing.__init__`
    assert "pricing" in demo_summary.python_modules


def test_detects_markdown_files(demo_summary):
    assert set(demo_summary.documentation_files) == {
        "README.md",
        "docs/API_REFERENCE.md",
        "docs/pricing.md",
    }


def test_detects_test_files(demo_summary):
    assert set(demo_summary.test_files) == {
        "tests/test_discount.py",
        "tests/test_pricing_service.py",
    }


def test_detects_functions(demo_summary):
    functions = {s.name for s in demo_summary.symbols if s.kind == "function"}
    assert "calculate_discount" in functions
    assert "apply_discount" in functions
    assert "get_loyalty_rate" in functions


def test_detects_classes(demo_summary):
    classes = {s.name for s in demo_summary.symbols if s.kind == "class"}
    assert "PricingService" in classes
    assert "CheckoutService" in classes
    assert "Customer" in classes


def test_detects_methods_with_qualified_names(demo_summary):
    methods = {s.name for s in demo_summary.symbols if s.kind == "method"}
    assert "PricingService.price_order" in methods
    assert "CheckoutService.checkout" in methods


def test_symbols_carry_file_and_line(demo_summary):
    discount = next(s for s in demo_summary.symbols if s.name == "calculate_discount")
    assert discount.file == "pricing/discount.py"
    assert discount.line > 0


def test_detects_imports(demo_summary):
    imports = demo_summary.imports["pricing/pricing_service.py"]
    assert "pricing.discount" in imports
    assert "pricing.discount.calculate_discount" in imports


def test_import_graph_resolves_internal_modules(demo_summary):
    assert demo_summary.import_graph["pricing/pricing_service.py"] == ["pricing/discount.py"]
    assert "pricing/pricing_service.py" in demo_summary.import_graph["checkout/service.py"]


def test_import_graph_excludes_stdlib_and_third_party(demo_summary):
    """`dataclasses` is imported but is not a repository file."""
    for targets in demo_summary.import_graph.values():
        assert all(target.endswith(".py") for target in targets)
        assert "dataclasses" not in targets


def test_reverse_import_graph_identifies_callers(demo_summary):
    """This is the fact that makes 'callers of discount.py' evidence, not a guess."""
    callers = demo_summary.imported_by["pricing/discount.py"]
    assert "pricing/pricing_service.py" in callers
    assert "checkout/service.py" in callers
    assert "tests/test_discount.py" in callers


def test_captures_document_headings_and_excerpt(demo_summary):
    pricing_doc = next(d for d in demo_summary.documents if d.path == "docs/pricing.md")
    assert "Pricing and Discounts" in pricing_doc.headings
    assert "purchase history" in pricing_doc.excerpt.lower()


def test_no_malformed_files_in_demo_repository(demo_summary):
    assert demo_summary.malformed_files == []


def test_malformed_python_file_is_recorded_not_fatal(tmp_path):
    """A syntax error must degrade gracefully, not abort the whole analysis."""
    (tmp_path / "good.py").write_text("def works():\n    return 1\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def oops(:\n    this is not python\n", encoding="utf-8")

    summary = analyze_repository(tmp_path, name="mixed")

    assert "broken.py" in summary.malformed_files
    assert "works" in {s.name for s in summary.symbols}


def test_empty_directory_produces_empty_summary(tmp_path):
    summary = analyze_repository(tmp_path, name="empty")
    assert summary.files == []
    assert summary.python_modules == []


def test_skips_vendor_directories(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "app.py").write_text("y = 2", encoding="utf-8")

    summary = analyze_repository(tmp_path, name="with-vendor")

    assert summary.files == ["app.py"]


# --------------------------------------------------------------------------
# Change targeting
# --------------------------------------------------------------------------


def test_targeting_ranks_the_changed_file_first(demo_summary):
    candidates = find_candidates(DEMO_CHANGE, demo_summary)
    assert candidates[0].file == "pricing/discount.py"


def test_targeting_surfaces_the_documentation(demo_summary):
    candidates = find_candidates(DEMO_CHANGE, demo_summary)
    files = {c.file for c in candidates}
    assert "docs/pricing.md" in files
    assert "docs/API_REFERENCE.md" in files


def test_targeting_explains_itself(demo_summary):
    candidates = find_candidates(DEMO_CHANGE, demo_summary)
    assert candidates[0].reasons, "every candidate must carry its evidence"


def test_primary_area_is_the_pricing_package(demo_summary):
    assert primary_area(find_candidates(DEMO_CHANGE, demo_summary)) == "pricing"


def test_downstream_files_walks_the_import_graph(demo_summary):
    downstream = downstream_files(["pricing/discount.py"], demo_summary)
    assert "pricing/pricing_service.py" in downstream
    assert "checkout/service.py" in downstream
    assert "api/pricing_api.py" in downstream


def test_targeting_on_unrelated_change_returns_little(demo_summary):
    candidates = find_candidates("Upgraded the CI runner image to Ubuntu 24.04", demo_summary)
    assert all(c.file != "pricing/discount.py" for c in candidates[:1]) or not candidates
