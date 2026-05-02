"""Tests for the Docling adapter.

All tests mock the Docling dependency so no ML pipeline download is needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to build minimal DoclingDocument fixtures without running the
# full Docling pipeline.  We use the real docling_core types so the adapter
# sees real objects — but skip _DocumentConverter entirely.
# ---------------------------------------------------------------------------

def _make_docling_doc(name: str = "test"):
    """Return a real DoclingDocument with a few synthetic items."""
    from docling_core.types.doc import DoclingDocument, DocItemLabel
    doc = DoclingDocument(name=name)
    doc.add_heading(text="Introduction", level=1)
    doc.add_text(text="This is the introduction body text.", label=DocItemLabel.TEXT)
    doc.add_heading(text="Methods", level=1)
    doc.add_text(text="We used a novel approach.", label=DocItemLabel.TEXT)
    return doc


def _make_mock_converter(doc, status=None):
    """Return a mock _DocumentConverter class whose .convert() returns a mock result."""
    from docling.datamodel.base_models import ConversionStatus

    result = MagicMock()
    result.status = status or ConversionStatus.SUCCESS
    result.document = doc
    result.errors = []

    converter_instance = MagicMock()
    converter_instance.convert.return_value = result

    MockDC = MagicMock(return_value=converter_instance)
    return MockDC


# ---------------------------------------------------------------------------
# Module-import tests (no Docling required)
# ---------------------------------------------------------------------------

def test_module_imports_without_docling():
    """Importing pdf_parser.parsers.docling_adapter must not raise even if Docling absent."""
    import importlib
    import pdf_parser.parsers.docling_adapter as mod
    assert hasattr(mod, "parse_pdf_with_docling")


def test_missing_docling_raises_import_error(tmp_path):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("pdf_parser.parsers.docling_adapter._DOCLING_AVAILABLE", False):
        from pdf_parser.parsers.docling_adapter import parse_pdf_with_docling
        with pytest.raises(ImportError, match="pip install docling"):
            parse_pdf_with_docling(pdf)


# ---------------------------------------------------------------------------
# Input validation tests
# ---------------------------------------------------------------------------

def test_missing_pdf_raises_file_not_found(tmp_path):
    from pdf_parser.parsers.docling_adapter import parse_pdf_with_docling
    with pytest.raises(FileNotFoundError):
        parse_pdf_with_docling(tmp_path / "nonexistent.pdf")


def test_non_pdf_suffix_raises_value_error(tmp_path):
    txt = tmp_path / "doc.txt"
    txt.write_text("hello")
    from pdf_parser.parsers.docling_adapter import parse_pdf_with_docling
    with pytest.raises(ValueError, match=r"\.pdf"):
        parse_pdf_with_docling(txt)


# ---------------------------------------------------------------------------
# Successful conversion tests
# ---------------------------------------------------------------------------

@pytest.fixture
def docling_candidate(tmp_path):
    """ParsedCandidate produced by the adapter with a minimal DoclingDocument."""
    doc = _make_docling_doc()
    MockDC = _make_mock_converter(doc)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("pdf_parser.parsers.docling_adapter._DocumentConverter", MockDC):
        from pdf_parser.parsers.docling_adapter import parse_pdf_with_docling
        return parse_pdf_with_docling(pdf)


def test_returns_parsed_candidate(docling_candidate):
    from pdf_parser.schema.candidate import ParsedCandidate
    assert isinstance(docling_candidate, ParsedCandidate)


def test_provenance_parser_name(docling_candidate):
    assert docling_candidate.provenance.parser_name == "docling"


def test_provenance_parser_version_set(docling_candidate):
    assert isinstance(docling_candidate.provenance.parser_version, str)
    assert docling_candidate.provenance.parser_version != ""


def test_provenance_input_sha256_set(docling_candidate):
    assert len(docling_candidate.provenance.input_sha256) == 64
    assert all(c in "0123456789abcdef" for c in docling_candidate.provenance.input_sha256)


def test_output_sha256_is_64_hex_chars(docling_candidate):
    h = docling_candidate.provenance.output_sha256
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_output_sha256_differs_from_placeholder(docling_candidate):
    assert docling_candidate.provenance.output_sha256 != "0" * 64


def test_blocks_extracted(docling_candidate):
    assert len(docling_candidate.blocks) >= 2


def test_sections_extracted(docling_candidate):
    assert len(docling_candidate.sections) >= 2


def test_section_titles(docling_candidate):
    titles = [s.title for s in docling_candidate.sections]
    assert "Introduction" in titles
    assert "Methods" in titles


def test_section_level_one(docling_candidate):
    for sec in docling_candidate.sections:
        assert sec.level == 1


def test_section_has_block_ids(docling_candidate):
    for sec in docling_candidate.sections:
        assert len(sec.block_ids) >= 1


def test_section_source_parser(docling_candidate):
    for sec in docling_candidate.sections:
        assert sec.source_parser == "docling"


def test_blocks_have_reading_order(docling_candidate):
    orders = [b.reading_order for b in docling_candidate.blocks if b.reading_order is not None]
    assert len(orders) == len(docling_candidate.blocks)


def test_blocks_source_parser(docling_candidate):
    for blk in docling_candidate.blocks:
        assert blk.source_parser == "docling"


def test_pages_extracted(docling_candidate):
    assert len(docling_candidate.pages) >= 1


def test_page_numbers_are_positive(docling_candidate):
    for page in docling_candidate.pages:
        assert page.page_number >= 1


def test_diagnostics_present(docling_candidate):
    assert docling_candidate.diagnostics is not None


def test_no_warnings_on_success(docling_candidate):
    assert docling_candidate.diagnostics.warnings == []


# ---------------------------------------------------------------------------
# PARTIAL_SUCCESS adds a warning
# ---------------------------------------------------------------------------

def test_partial_success_adds_warning(tmp_path):
    from docling.datamodel.base_models import ConversionStatus

    doc = _make_docling_doc()
    MockDC = _make_mock_converter(doc, status=ConversionStatus.PARTIAL_SUCCESS)
    pdf = tmp_path / "partial.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("pdf_parser.parsers.docling_adapter._DocumentConverter", MockDC):
        from pdf_parser.parsers.docling_adapter import parse_pdf_with_docling
        candidate = parse_pdf_with_docling(pdf)

    assert len(candidate.diagnostics.warnings) == 1
    assert "PARTIAL_SUCCESS" in candidate.diagnostics.warnings[0]


# ---------------------------------------------------------------------------
# Conversion failure raises RuntimeError
# ---------------------------------------------------------------------------

def test_conversion_failure_raises_runtime_error(tmp_path):
    from docling.datamodel.base_models import ConversionStatus

    doc = _make_docling_doc()
    MockDC = _make_mock_converter(doc, status=ConversionStatus.FAILURE)
    pdf = tmp_path / "fail.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("pdf_parser.parsers.docling_adapter._DocumentConverter", MockDC):
        from pdf_parser.parsers.docling_adapter import parse_pdf_with_docling
        with pytest.raises(RuntimeError, match="failed"):
            parse_pdf_with_docling(pdf)


# ---------------------------------------------------------------------------
# output_sha256 determinism
# ---------------------------------------------------------------------------

def test_output_sha256_matches_recomputed(tmp_path):
    """output_sha256 stored on the candidate must match a fresh recomputation."""
    from pdf_parser.schema.hashes import compute_candidate_output_sha256

    doc = _make_docling_doc()
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    MockDC = _make_mock_converter(doc)
    with patch("pdf_parser.parsers.docling_adapter._DocumentConverter", MockDC):
        from pdf_parser.parsers.docling_adapter import parse_pdf_with_docling
        candidate = parse_pdf_with_docling(pdf)

    assert candidate.provenance.output_sha256 == compute_candidate_output_sha256(candidate)


# ---------------------------------------------------------------------------
# Figures, tables, captions
# ---------------------------------------------------------------------------

def test_figure_extracted(tmp_path):
    from docling_core.types.doc import DoclingDocument, DocItemLabel
    doc = DoclingDocument(name="fig_test")
    doc.add_picture(annotations=[])

    MockDC = _make_mock_converter(doc)
    pdf = tmp_path / "fig.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("pdf_parser.parsers.docling_adapter._DocumentConverter", MockDC):
        from pdf_parser.parsers.docling_adapter import parse_pdf_with_docling
        candidate = parse_pdf_with_docling(pdf)

    assert len(candidate.figures) == 1
    assert candidate.figures[0].figure_id == "fig_1"
    assert candidate.figures[0].source_parser == "docling"


def test_table_extracted(tmp_path):
    from docling_core.types.doc import DoclingDocument
    from docling_core.types.doc.document import TableData

    doc = DoclingDocument(name="tbl_test")
    doc.add_table(data=TableData(num_rows=1, num_cols=1, table_cells=[]))

    MockDC = _make_mock_converter(doc)
    pdf = tmp_path / "tbl.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("pdf_parser.parsers.docling_adapter._DocumentConverter", MockDC):
        from pdf_parser.parsers.docling_adapter import parse_pdf_with_docling
        candidate = parse_pdf_with_docling(pdf)

    assert len(candidate.tables) == 1
    assert candidate.tables[0].table_id == "tbl_1"
    assert candidate.tables[0].source_parser == "docling"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

def test_cli_docling_parse_writes_json(tmp_path):
    from docling_core.types.doc import DoclingDocument, DocItemLabel

    doc = DoclingDocument(name="cli_test")
    doc.add_heading(text="Intro", level=1)
    doc.add_text(text="Body text here.", label=DocItemLabel.TEXT)

    MockDC = _make_mock_converter(doc)
    pdf = tmp_path / "cli_paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "out.json"

    with patch("pdf_parser.parsers.docling_adapter._DocumentConverter", MockDC):
        from pdf_parser.cli import main
        main(["docling", "parse", "--pdf", str(pdf), "--out", str(out)])

    assert out.exists()
    data = json.loads(out.read_text())
    assert "provenance" in data
    assert data["provenance"]["parser_name"] == "docling"


def test_cli_docling_parse_pretty_json(tmp_path):
    from docling_core.types.doc import DoclingDocument, DocItemLabel

    doc = DoclingDocument(name="cli_pretty")
    doc.add_text(text="Just a paragraph.", label=DocItemLabel.TEXT)

    MockDC = _make_mock_converter(doc)
    pdf = tmp_path / "pretty.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "pretty.json"

    with patch("pdf_parser.parsers.docling_adapter._DocumentConverter", MockDC):
        from pdf_parser.cli import main
        main(["docling", "parse", "--pdf", str(pdf), "--out", str(out)])

    raw = out.read_text()
    assert "\n" in raw
    assert "  " in raw
