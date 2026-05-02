"""Tests for core Pydantic schema models."""

import pytest
from pydantic import ValidationError

from pdf_parser.schema.candidate import (
    CandidateDiagnostics,
    ParsedBlock,
    ParsedCandidate,
    ParsedCaption,
    ParsedFigure,
    ParsedPage,
    ParsedSection,
    ParsedTable,
    ParserProvenance,
)


def make_provenance(**kwargs) -> ParserProvenance:
    defaults = dict(
        parser_name="test_parser",
        parser_version="1.0.0",
        input_sha256="a" * 64,
        output_sha256="b" * 64,
    )
    defaults.update(kwargs)
    return ParserProvenance(**defaults)


def make_candidate(**kwargs) -> ParsedCandidate:
    kwargs.setdefault("provenance", make_provenance())
    return ParsedCandidate(**kwargs)


class TestParserProvenance:
    def test_required_fields_present(self):
        prov = make_provenance()
        assert prov.parser_name == "test_parser"
        assert prov.parser_version == "1.0.0"
        assert prov.input_sha256 == "a" * 64
        assert prov.output_sha256 == "b" * 64
        assert prov.created_at is not None

    def test_missing_parser_name_raises(self):
        with pytest.raises(ValidationError):
            ParserProvenance(
                parser_version="1.0.0",
                input_sha256="a" * 64,
                output_sha256="b" * 64,
            )

    def test_missing_parser_version_raises(self):
        with pytest.raises(ValidationError):
            ParserProvenance(
                parser_name="test",
                input_sha256="a" * 64,
                output_sha256="b" * 64,
            )

    def test_missing_input_sha256_raises(self):
        with pytest.raises(ValidationError):
            ParserProvenance(
                parser_name="test",
                parser_version="1.0.0",
                output_sha256="b" * 64,
            )

    def test_missing_output_sha256_raises(self):
        with pytest.raises(ValidationError):
            ParserProvenance(
                parser_name="test",
                parser_version="1.0.0",
                input_sha256="a" * 64,
            )

    def test_created_at_auto_populated(self):
        prov = make_provenance()
        assert prov.created_at is not None

    def test_created_at_can_be_set_explicitly(self):
        from datetime import datetime, timezone

        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        prov = make_provenance(created_at=ts)
        assert prov.created_at == ts


class TestParsedCandidate:
    def test_construction_with_only_provenance(self):
        candidate = make_candidate()
        assert candidate.provenance.parser_name == "test_parser"
        assert candidate.pages == []
        assert candidate.blocks == []
        assert candidate.sections == []
        assert candidate.figures == []
        assert candidate.tables == []
        assert candidate.captions == []
        assert candidate.diagnostics is None

    def test_with_pages(self):
        page = ParsedPage(page_id="p1", page_number=1, width=612.0, height=792.0)
        candidate = make_candidate(pages=[page])
        assert len(candidate.pages) == 1
        assert candidate.pages[0].page_number == 1

    def test_with_blocks(self):
        block = ParsedBlock(
            block_id="b1",
            page=1,
            text="Introduction",
            block_type="heading",
            is_bold=True,
        )
        candidate = make_candidate(blocks=[block])
        assert len(candidate.blocks) == 1
        assert candidate.blocks[0].is_bold is True

    def test_block_bbox_optional(self):
        block = ParsedBlock(block_id="b1", page=1, text="text")
        assert block.bbox is None

    def test_block_bbox_four_floats(self):
        block = ParsedBlock(block_id="b1", page=1, text="text", bbox=[0.0, 0.0, 100.0, 20.0])
        assert len(block.bbox) == 4

    def test_with_sections(self):
        section = ParsedSection(
            section_id="s1",
            title="Methods",
            normalized_title="methods",
            level=1,
            block_ids=["b1", "b2"],
            start_page=3,
            end_page=5,
        )
        candidate = make_candidate(sections=[section])
        assert candidate.sections[0].title == "Methods"
        assert candidate.sections[0].block_ids == ["b1", "b2"]

    def test_section_hierarchy(self):
        parent = ParsedSection(section_id="s1", title="Methods", level=1)
        child = ParsedSection(
            section_id="s2",
            title="Statistical Analysis",
            level=2,
            parent_section_id="s1",
        )
        candidate = make_candidate(sections=[parent, child])
        assert candidate.sections[1].parent_section_id == "s1"

    def test_with_figures_and_tables(self):
        caption = ParsedCaption(caption_id="cap1", text="Figure 1.", page=2)
        figure = ParsedFigure(figure_id="fig1", page=2, caption_id="cap1")
        table = ParsedTable(table_id="tbl1", page=3, bbox=[0.0, 0.0, 400.0, 200.0])
        candidate = make_candidate(figures=[figure], tables=[table], captions=[caption])
        assert candidate.figures[0].caption_id == "cap1"
        assert candidate.tables[0].table_id == "tbl1"
        assert candidate.captions[0].text == "Figure 1."

    def test_diagnostics(self):
        diag = CandidateDiagnostics(
            parse_duration_seconds=1.23,
            warnings=["low confidence on page 4"],
            error_count=0,
        )
        candidate = make_candidate(diagnostics=diag)
        assert candidate.diagnostics.parse_duration_seconds == 1.23
        assert len(candidate.diagnostics.warnings) == 1

    def test_missing_provenance_raises(self):
        with pytest.raises(ValidationError):
            ParsedCandidate()
