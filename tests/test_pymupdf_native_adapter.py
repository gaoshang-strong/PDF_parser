"""Tests for the native PyMuPDF adapter — no real PDFs required."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from pdf_parser.parsers.pymupdf_native import (
    _heading_level,
    _is_heading_candidate,
    parse_pdf_with_pymupdf,
)
from pdf_parser.schema.candidate import ParsedCandidate


# ---------------------------------------------------------------------------
# Fixture: minimal test PDF built in-memory with PyMuPDF
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_pdf(tmp_path) -> Path:
    """Two-page PDF: heading (16 pt) + body (10 pt) on each page."""
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.Document()

    # Page 1
    page = doc.new_page(width=612, height=792)
    page.insert_text((50, 80), "Introduction", fontsize=16, fontname="helv")
    page.insert_text((50, 115), "Body text on the first page.", fontsize=10, fontname="helv")
    page.insert_text((50, 135), "Another sentence in the introduction.", fontsize=10, fontname="helv")

    # Page 2
    page2 = doc.new_page(width=612, height=792)
    page2.insert_text((50, 80), "Methods", fontsize=16, fontname="helv")
    page2.insert_text((50, 115), "We describe our methods here.", fontsize=10, fontname="helv")

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def numbered_sections_pdf(tmp_path) -> Path:
    """PDF with numbered section headings for hierarchy testing."""
    pdf_path = tmp_path / "numbered.pdf"
    doc = fitz.Document()
    page = doc.new_page(width=612, height=792)
    page.insert_text((50, 80),  "1 Background",          fontsize=16, fontname="helv")
    page.insert_text((50, 115), "Body of background.",   fontsize=10, fontname="helv")
    page.insert_text((50, 155), "1.1 Prior Work",        fontsize=14, fontname="helv")
    page.insert_text((50, 190), "Details of prior work.", fontsize=10, fontname="helv")
    page.insert_text((50, 230), "2 Methods",             fontsize=16, fontname="helv")
    page.insert_text((50, 265), "Method description.",   fontsize=10, fontname="helv")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestErrorCases:
    def test_rejects_missing_pdf(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="PDF not found"):
            parse_pdf_with_pymupdf(tmp_path / "ghost.pdf")

    def test_rejects_non_pdf_suffix(self, tmp_path):
        txt = tmp_path / "file.txt"
        txt.write_text("not a pdf")
        with pytest.raises(ValueError, match=r"\.pdf"):
            parse_pdf_with_pymupdf(txt)

    def test_accepts_path_as_string(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(str(minimal_pdf))
        assert isinstance(c, ParsedCandidate)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

class TestPages:
    def test_extracts_correct_page_count(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        assert len(c.pages) == 2

    def test_page_numbers_are_one_based(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        numbers = [p.page_number for p in c.pages]
        assert numbers == [1, 2]

    def test_page_ids_match_numbers(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        assert c.pages[0].page_id == "page_1"
        assert c.pages[1].page_id == "page_2"

    def test_page_dimensions_populated(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        for page in c.pages:
            assert page.width is not None and page.width > 0
            assert page.height is not None and page.height > 0


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

class TestBlocks:
    def test_extracts_blocks(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        assert len(c.blocks) > 0

    def test_blocks_have_bbox(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        for block in c.blocks:
            assert block.bbox is not None
            assert len(block.bbox) == 4
            assert all(isinstance(v, float) for v in block.bbox)

    def test_blocks_have_page_numbers(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        for block in c.blocks:
            assert block.page >= 1

    def test_blocks_span_both_pages(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        pages_seen = {b.page for b in c.blocks}
        assert 1 in pages_seen
        assert 2 in pages_seen

    def test_reading_order_sequential(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        orders = [b.reading_order for b in c.blocks]
        assert orders == list(range(1, len(c.blocks) + 1))

    def test_blocks_have_font_size(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        for block in c.blocks:
            assert block.font_size is not None
            assert block.font_size > 0

    def test_blocks_have_font_name(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        for block in c.blocks:
            assert block.font_name is not None

    def test_blocks_have_is_bold_field(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        for block in c.blocks:
            assert isinstance(block.is_bold, bool)

    def test_blocks_have_source_parser(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        assert all(b.source_parser == "pymupdf_native" for b in c.blocks)

    def test_block_ids_are_unique(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        ids = [b.block_id for b in c.blocks]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Heading detection
# ---------------------------------------------------------------------------

class TestHeadingDetection:
    def test_detects_heading_candidates(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        headings = [b for b in c.blocks if b.block_type == "heading"]
        assert len(headings) >= 1

    def test_heading_text_preserved_exactly(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        headings = [b for b in c.blocks if b.block_type == "heading"]
        heading_texts = [h.text.strip() for h in headings]
        assert "Introduction" in heading_texts or any("Intro" in t for t in heading_texts)

    def test_body_blocks_are_text_type(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        text_blocks = [b for b in c.blocks if b.block_type == "text"]
        assert len(text_blocks) > 0

    def test_heading_blocks_have_larger_font(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        headings = [b for b in c.blocks if b.block_type == "heading"]
        texts = [b for b in c.blocks if b.block_type == "text"]
        if headings and texts:
            avg_heading_size = sum(h.font_size for h in headings) / len(headings)
            avg_text_size = sum(t.font_size for t in texts) / len(texts)
            assert avg_heading_size > avg_text_size


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

class TestSections:
    def test_sections_are_built(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        assert len(c.sections) > 0

    def test_section_titles_match_headings(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        titles = [s.title for s in c.sections]
        assert any("Introduction" in t or "Methods" in t for t in titles)

    def test_section_has_block_ids(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        for sec in c.sections:
            assert isinstance(sec.block_ids, list)

    def test_section_start_page_set(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        for sec in c.sections:
            assert sec.start_page is not None and sec.start_page >= 1

    def test_section_source_parser(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        assert all(s.source_parser == "pymupdf_native" for s in c.sections)

    def test_numbered_heading_levels(self, numbered_sections_pdf):
        c = parse_pdf_with_pymupdf(numbered_sections_pdf)
        # "1 Background" and "2 Methods" → level 1; "1.1 Prior Work" → level 2
        level_map = {s.title.strip(): s.level for s in c.sections}
        background = next((t for t in level_map if t.startswith("1 ") or "Background" in t), None)
        subsection = next((t for t in level_map if "Prior" in t or "1.1" in t), None)
        if background:
            assert level_map[background] == 1
        if subsection:
            assert level_map[subsection] == 2

    def test_subsection_has_parent(self, numbered_sections_pdf):
        c = parse_pdf_with_pymupdf(numbered_sections_pdf)
        subsections = [s for s in c.sections if s.level == 2]
        if subsections:
            assert subsections[0].parent_section_id is not None


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

class TestProvenance:
    def test_parser_name(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        assert c.provenance.parser_name == "pymupdf_native"

    def test_parser_version_is_fitz_version(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        assert c.provenance.parser_version == fitz.__version__

    def test_input_sha256_matches_file(self, minimal_pdf):
        from pdf_parser.schema.hashes import sha256_file
        c = parse_pdf_with_pymupdf(minimal_pdf)
        assert c.provenance.input_sha256 == sha256_file(minimal_pdf)

    def test_output_sha256_is_computed(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        assert c.provenance.output_sha256 != "0" * 64
        assert len(c.provenance.output_sha256) == 64

    def test_output_sha256_reflects_content(self, minimal_pdf):
        from pdf_parser.schema.hashes import compute_candidate_output_sha256
        c = parse_pdf_with_pymupdf(minimal_pdf)
        assert c.provenance.output_sha256 == compute_candidate_output_sha256(c)

    def test_created_at_populated(self, minimal_pdf):
        c = parse_pdf_with_pymupdf(minimal_pdf)
        assert c.provenance.created_at is not None


# ---------------------------------------------------------------------------
# Unit tests for internal helpers
# ---------------------------------------------------------------------------

class TestIsHeadingCandidate:
    def test_large_font_is_heading(self):
        assert _is_heading_candidate("Introduction", 16.0, 10.0) is True

    def test_body_size_not_heading(self):
        assert _is_heading_candidate("Regular body text", 10.0, 10.0) is False

    def test_too_long_is_not_heading(self):
        assert _is_heading_candidate("x" * 200, 16.0, 10.0) is False

    def test_too_short_is_not_heading(self):
        assert _is_heading_candidate("x", 16.0, 10.0) is False

    def test_url_is_not_heading(self):
        assert _is_heading_candidate("https://example.com", 16.0, 10.0) is False

    def test_pure_number_is_not_heading(self):
        assert _is_heading_candidate("42", 16.0, 10.0) is False

    def test_uppercase_heading_accepted(self):
        assert _is_heading_candidate("RESULTS", 16.0, 10.0) is True


class TestHeadingLevel:
    def test_unnumbered_is_level_1(self):
        assert _heading_level("Introduction") == 1

    def test_single_number_is_level_1(self):
        assert _heading_level("1 Introduction") == 1

    def test_dotted_number_is_level_2(self):
        assert _heading_level("1.1 Background") == 2

    def test_triple_dotted_is_level_3(self):
        assert _heading_level("1.1.1 Details") == 3

    def test_uppercase_unnumbered_is_level_1(self):
        assert _heading_level("RESULTS") == 1


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

class TestCliPyMuPDF:
    def test_cli_writes_pretty_json(self, minimal_pdf, tmp_path):
        out = tmp_path / "output.json"
        from pdf_parser.cli import main
        main(["pymupdf", "parse", "--pdf", str(minimal_pdf), "--out", str(out)])
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "\n" in content
        assert "  " in content

    def test_cli_output_is_valid_json(self, minimal_pdf, tmp_path):
        out = tmp_path / "output.json"
        from pdf_parser.cli import main
        main(["pymupdf", "parse", "--pdf", str(minimal_pdf), "--out", str(out)])
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["provenance"]["parser_name"] == "pymupdf_native"

    def test_cli_output_contains_pages_and_blocks(self, minimal_pdf, tmp_path):
        out = tmp_path / "output.json"
        from pdf_parser.cli import main
        main(["pymupdf", "parse", "--pdf", str(minimal_pdf), "--out", str(out)])
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["pages"]) == 2
        assert len(data["blocks"]) > 0

    def test_cli_prints_output_path(self, minimal_pdf, tmp_path, capsys):
        out = tmp_path / "output.json"
        from pdf_parser.cli import main
        main(["pymupdf", "parse", "--pdf", str(minimal_pdf), "--out", str(out)])
        assert str(out) in capsys.readouterr().out
