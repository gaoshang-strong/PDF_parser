"""Tests for the Marker adapter.

All tests mock the Marker dependency — no model downloads or GPU required.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared Markdown fixture
# ---------------------------------------------------------------------------

_SIMPLE_MARKDOWN = """\
# Introduction

This is the introduction paragraph.

# Methods

We used a novel approach here.

## Subsection

Details of the subsection.
"""

_TABLE_MARKDOWN = """\
# Results

| Col A | Col B |
|-------|-------|
| 1     | 2     |

More text after table.
"""

_IMAGE_MARKDOWN = """\
# Figures

![Figure 1](fig1.png)

Caption text here.
"""


def _make_rendered(markdown: str, page_count: int = 1, toc=None) -> MagicMock:
    """Build a mock MarkdownOutput with the given content."""
    rendered = MagicMock()
    rendered.markdown = markdown
    rendered.metadata = {
        "page_stats": [
            {"page_id": i, "text_extraction_method": "pdftext", "block_counts": [], "block_metadata": {}}
            for i in range(page_count)
        ],
        "table_of_contents": toc or [],
    }
    return rendered


def _make_mock_converter(rendered: MagicMock) -> MagicMock:
    """Return a mock _PdfConverter class whose instances return rendered.

    _PdfConverter(artifact_dict=...) returns an instance.
    instance(pdf_path) returns rendered.
    """
    instance = MagicMock(return_value=rendered)
    MockDC = MagicMock(return_value=instance)
    return MockDC


def _make_mock_create_model_dict() -> MagicMock:
    return MagicMock(return_value={})


# ---------------------------------------------------------------------------
# Module-import test
# ---------------------------------------------------------------------------

def test_module_imports_without_marker():
    import pdf_parser.parsers.marker_adapter as mod
    assert hasattr(mod, "parse_pdf_with_marker")


def test_missing_marker_raises_import_error(tmp_path):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("pdf_parser.parsers.marker_adapter._MARKER_AVAILABLE", False):
        from pdf_parser.parsers.marker_adapter import parse_pdf_with_marker
        with pytest.raises(ImportError, match="pip install marker-pdf"):
            parse_pdf_with_marker(pdf)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_missing_pdf_raises_file_not_found(tmp_path):
    from pdf_parser.parsers.marker_adapter import parse_pdf_with_marker
    with pytest.raises(FileNotFoundError):
        parse_pdf_with_marker(tmp_path / "nonexistent.pdf")


def test_non_pdf_suffix_raises_value_error(tmp_path):
    txt = tmp_path / "doc.txt"
    txt.write_text("hello")
    from pdf_parser.parsers.marker_adapter import parse_pdf_with_marker
    with pytest.raises(ValueError, match=r"\.pdf"):
        parse_pdf_with_marker(txt)


# ---------------------------------------------------------------------------
# Successful conversion fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def marker_candidate(tmp_path):
    rendered = _make_rendered(_SIMPLE_MARKDOWN, page_count=2)
    MockDC = _make_mock_converter(rendered)
    mock_models = _make_mock_create_model_dict()

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("pdf_parser.parsers.marker_adapter._PdfConverter", MockDC), \
         patch("pdf_parser.parsers.marker_adapter._create_model_dict", mock_models):
        from pdf_parser.parsers.marker_adapter import parse_pdf_with_marker
        return parse_pdf_with_marker(pdf)


def test_returns_parsed_candidate(marker_candidate):
    from pdf_parser.schema.candidate import ParsedCandidate
    assert isinstance(marker_candidate, ParsedCandidate)


def test_provenance_parser_name(marker_candidate):
    assert marker_candidate.provenance.parser_name == "marker"


def test_provenance_parser_version_set(marker_candidate):
    assert isinstance(marker_candidate.provenance.parser_version, str)
    assert marker_candidate.provenance.parser_version != ""


def test_provenance_input_sha256_set(marker_candidate):
    h = marker_candidate.provenance.input_sha256
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_output_sha256_is_64_hex(marker_candidate):
    h = marker_candidate.provenance.output_sha256
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_output_sha256_not_placeholder(marker_candidate):
    assert marker_candidate.provenance.output_sha256 != "0" * 64


def test_output_sha256_matches_recomputed(marker_candidate):
    from pdf_parser.schema.hashes import compute_candidate_output_sha256
    assert marker_candidate.provenance.output_sha256 == compute_candidate_output_sha256(marker_candidate)


def test_pages_extracted(marker_candidate):
    assert len(marker_candidate.pages) == 2


def test_page_numbers_are_one_based(marker_candidate):
    numbers = [p.page_number for p in marker_candidate.pages]
    assert numbers == [1, 2]


def test_blocks_extracted(marker_candidate):
    assert len(marker_candidate.blocks) >= 3  # headings + body blocks


def test_sections_extracted(marker_candidate):
    assert len(marker_candidate.sections) >= 2


def test_section_titles(marker_candidate):
    titles = [s.title for s in marker_candidate.sections]
    assert "Introduction" in titles
    assert "Methods" in titles


def test_section_levels(marker_candidate):
    intro = next(s for s in marker_candidate.sections if s.title == "Introduction")
    assert intro.level == 1


def test_section_has_block_ids(marker_candidate):
    for sec in marker_candidate.sections:
        assert len(sec.block_ids) >= 1


def test_section_normalized_title(marker_candidate):
    for sec in marker_candidate.sections:
        assert sec.normalized_title == sec.title.lower()


def test_section_source_parser(marker_candidate):
    for sec in marker_candidate.sections:
        assert sec.source_parser == "marker"


def test_blocks_source_parser(marker_candidate):
    for blk in marker_candidate.blocks:
        assert blk.source_parser == "marker"


def test_blocks_have_reading_order(marker_candidate):
    for blk in marker_candidate.blocks:
        assert blk.reading_order is not None


def test_heading_blocks_typed_correctly(marker_candidate):
    heading_blocks = [b for b in marker_candidate.blocks if b.block_type == "heading"]
    assert len(heading_blocks) >= 2


def test_diagnostics_present(marker_candidate):
    assert marker_candidate.diagnostics is not None


# ---------------------------------------------------------------------------
# Section hierarchy
# ---------------------------------------------------------------------------

def test_subsection_parent_id(tmp_path):
    md = "# Top\n\nBody.\n\n## Sub\n\nSub body.\n"
    rendered = _make_rendered(md)
    MockDC = _make_mock_converter(rendered)
    mock_models = _make_mock_create_model_dict()
    pdf = tmp_path / "hier.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("pdf_parser.parsers.marker_adapter._PdfConverter", MockDC), \
         patch("pdf_parser.parsers.marker_adapter._create_model_dict", mock_models):
        from pdf_parser.parsers.marker_adapter import parse_pdf_with_marker
        candidate = parse_pdf_with_marker(pdf)

    top = next(s for s in candidate.sections if s.title == "Top")
    sub = next(s for s in candidate.sections if s.title == "Sub")
    assert sub.parent_section_id == top.section_id


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------

def test_table_extracted(tmp_path):
    rendered = _make_rendered(_TABLE_MARKDOWN)
    MockDC = _make_mock_converter(rendered)
    mock_models = _make_mock_create_model_dict()
    pdf = tmp_path / "tbl.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("pdf_parser.parsers.marker_adapter._PdfConverter", MockDC), \
         patch("pdf_parser.parsers.marker_adapter._create_model_dict", mock_models):
        from pdf_parser.parsers.marker_adapter import parse_pdf_with_marker
        candidate = parse_pdf_with_marker(pdf)

    assert len(candidate.tables) == 1
    assert candidate.tables[0].table_id == "tbl_1"
    assert candidate.tables[0].source_parser == "marker"


# ---------------------------------------------------------------------------
# Figure extraction
# ---------------------------------------------------------------------------

def test_figure_extracted(tmp_path):
    rendered = _make_rendered(_IMAGE_MARKDOWN)
    MockDC = _make_mock_converter(rendered)
    mock_models = _make_mock_create_model_dict()
    pdf = tmp_path / "fig.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("pdf_parser.parsers.marker_adapter._PdfConverter", MockDC), \
         patch("pdf_parser.parsers.marker_adapter._create_model_dict", mock_models):
        from pdf_parser.parsers.marker_adapter import parse_pdf_with_marker
        candidate = parse_pdf_with_marker(pdf)

    assert len(candidate.figures) == 1
    assert candidate.figures[0].figure_id == "fig_1"
    assert candidate.figures[0].source_parser == "marker"


# ---------------------------------------------------------------------------
# TOC page map
# ---------------------------------------------------------------------------

def test_toc_page_assignment(tmp_path):
    """Sections whose titles appear in the TOC get the correct page number."""
    toc = [
        {"title": "Introduction", "page_id": 2, "heading_level": 1, "polygon": []},
        {"title": "Methods", "page_id": 5, "heading_level": 1, "polygon": []},
    ]
    rendered = _make_rendered(_SIMPLE_MARKDOWN, page_count=8, toc=toc)
    MockDC = _make_mock_converter(rendered)
    mock_models = _make_mock_create_model_dict()
    pdf = tmp_path / "toc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("pdf_parser.parsers.marker_adapter._PdfConverter", MockDC), \
         patch("pdf_parser.parsers.marker_adapter._create_model_dict", mock_models):
        from pdf_parser.parsers.marker_adapter import parse_pdf_with_marker
        candidate = parse_pdf_with_marker(pdf)

    intro = next(s for s in candidate.sections if s.title == "Introduction")
    methods = next(s for s in candidate.sections if s.title == "Methods")
    assert intro.start_page == 3   # page_id=2 → 1-based=3
    assert methods.start_page == 6  # page_id=5 → 1-based=6


# ---------------------------------------------------------------------------
# Empty Markdown (edge case)
# ---------------------------------------------------------------------------

def test_empty_markdown_produces_valid_candidate(tmp_path):
    rendered = _make_rendered("", page_count=1)
    MockDC = _make_mock_converter(rendered)
    mock_models = _make_mock_create_model_dict()
    pdf = tmp_path / "empty.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("pdf_parser.parsers.marker_adapter._PdfConverter", MockDC), \
         patch("pdf_parser.parsers.marker_adapter._create_model_dict", mock_models):
        from pdf_parser.parsers.marker_adapter import parse_pdf_with_marker
        candidate = parse_pdf_with_marker(pdf)

    assert candidate.provenance.parser_name == "marker"
    assert candidate.blocks == []
    assert candidate.sections == []
    assert len(candidate.pages) == 1


# ---------------------------------------------------------------------------
# No page_stats — falls back to single page
# ---------------------------------------------------------------------------

def test_no_page_stats_produces_one_page(tmp_path):
    rendered = MagicMock()
    rendered.markdown = "# Intro\n\nText.\n"
    rendered.metadata = {"page_stats": [], "table_of_contents": []}

    MockDC = _make_mock_converter(rendered)
    mock_models = _make_mock_create_model_dict()
    pdf = tmp_path / "nopages.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    with patch("pdf_parser.parsers.marker_adapter._PdfConverter", MockDC), \
         patch("pdf_parser.parsers.marker_adapter._create_model_dict", mock_models):
        from pdf_parser.parsers.marker_adapter import parse_pdf_with_marker
        candidate = parse_pdf_with_marker(pdf)

    assert len(candidate.pages) == 1
    assert candidate.pages[0].page_number == 1


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

def test_cli_marker_parse_writes_json(tmp_path):
    rendered = _make_rendered("# Intro\n\nBody here.\n")
    MockDC = _make_mock_converter(rendered)
    mock_models = _make_mock_create_model_dict()
    pdf = tmp_path / "cli.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "out.json"

    with patch("pdf_parser.parsers.marker_adapter._PdfConverter", MockDC), \
         patch("pdf_parser.parsers.marker_adapter._create_model_dict", mock_models):
        from pdf_parser.cli import main
        main(["marker", "parse", "--pdf", str(pdf), "--out", str(out)])

    assert out.exists()
    data = json.loads(out.read_text())
    assert "provenance" in data
    assert data["provenance"]["parser_name"] == "marker"


def test_cli_marker_parse_pretty_json(tmp_path):
    rendered = _make_rendered("Just a paragraph.\n")
    MockDC = _make_mock_converter(rendered)
    mock_models = _make_mock_create_model_dict()
    pdf = tmp_path / "pretty.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "pretty.json"

    with patch("pdf_parser.parsers.marker_adapter._PdfConverter", MockDC), \
         patch("pdf_parser.parsers.marker_adapter._create_model_dict", mock_models):
        from pdf_parser.cli import main
        main(["marker", "parse", "--pdf", str(pdf), "--out", str(out)])

    raw = out.read_text()
    assert "\n" in raw
    assert "  " in raw
