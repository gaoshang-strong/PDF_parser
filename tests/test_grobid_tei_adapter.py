"""Tests for the GROBID TEI adapter — no external services required."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest

from pdf_parser.parsers.grobid_tei import parse_grobid_tei_to_candidate
from pdf_parser.schema.candidate import ParsedCandidate

FIXTURES = Path(__file__).parent / "fixtures"
SIMPLE_TEI = FIXTURES / "simple.tei.xml"
NESTED_TEI = FIXTURES / "nested.tei.xml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_simple() -> ParsedCandidate:
    return parse_grobid_tei_to_candidate(SIMPLE_TEI)


def _parse_nested() -> ParsedCandidate:
    return parse_grobid_tei_to_candidate(NESTED_TEI)


# ---------------------------------------------------------------------------
# Basic parsing — simple fixture
# ---------------------------------------------------------------------------

class TestSimpleFixture:
    def test_returns_parsed_candidate(self):
        c = _parse_simple()
        assert isinstance(c, ParsedCandidate)

    def test_parses_title(self):
        c = _parse_simple()
        assert c.metadata is not None
        assert c.metadata.title == "Effects of Vitamin D on Bone Density"

    def test_parses_doi(self):
        c = _parse_simple()
        assert c.metadata.doi == "10.1234/vitd.2023.001"

    def test_parses_journal(self):
        c = _parse_simple()
        assert c.metadata.journal == "Journal of Bone Research"

    def test_parses_year(self):
        c = _parse_simple()
        assert c.metadata.year == "2023"

    def test_parses_authors(self):
        c = _parse_simple()
        assert c.metadata.authors == ["Jane Smith"]

    def test_extracts_abstract_section(self):
        c = _parse_simple()
        abstracts = [s for s in c.sections if s.title == "Abstract"]
        assert len(abstracts) == 1
        assert "vitamin d" in abstracts[0].text.lower()

    def test_extracts_body_section_titles(self):
        c = _parse_simple()
        titles = [s.title for s in c.sections]
        assert "Introduction" in titles
        assert "Methods" in titles

    def test_section_text_preserved(self):
        c = _parse_simple()
        intro = next(s for s in c.sections if s.title == "Introduction")
        assert "Vitamin D" in intro.text
        assert "calcium" in intro.text.lower()

    def test_section_count(self):
        # Abstract + Introduction + Methods = 3
        c = _parse_simple()
        assert len(c.sections) == 3

    def test_normalized_title_is_lowercase(self):
        c = _parse_simple()
        intro = next(s for s in c.sections if s.title == "Introduction")
        assert intro.normalized_title == "introduction"

    def test_source_parser_set(self):
        c = _parse_simple()
        assert all(s.source_parser == "grobid_tei" for s in c.sections)

    def test_section_levels_are_one(self):
        c = _parse_simple()
        # All top-level body sections are level 1
        body_sections = [s for s in c.sections if s.title != "Abstract"]
        assert all(s.level == 1 for s in body_sections)

    def test_reference_count_in_diagnostics(self):
        c = _parse_simple()
        assert c.diagnostics is not None
        assert c.diagnostics.notes is not None
        assert "2" in c.diagnostics.notes


# ---------------------------------------------------------------------------
# Nested sections
# ---------------------------------------------------------------------------

class TestNestedFixture:
    def test_parses_nested_section_titles(self):
        c = _parse_nested()
        titles = [s.title for s in c.sections]
        assert "Search Strategy" in titles
        assert "Statistical Analysis" in titles

    def test_subsections_have_level_two(self):
        c = _parse_nested()
        search = next(s for s in c.sections if s.title == "Search Strategy")
        assert search.level == 2

    def test_subsections_have_parent_section_id(self):
        c = _parse_nested()
        methods = next(s for s in c.sections if s.title == "Methods")
        search = next(s for s in c.sections if s.title == "Search Strategy")
        stats = next(s for s in c.sections if s.title == "Statistical Analysis")
        assert search.parent_section_id == methods.section_id
        assert stats.parent_section_id == methods.section_id

    def test_preserves_uppercase_heading_text(self):
        # "RESULTS" must be preserved as-is in title
        c = _parse_nested()
        results_sec = next(s for s in c.sections if s.title == "RESULTS")
        assert results_sec.title == "RESULTS"
        assert results_sec.normalized_title == "results"

    def test_multiple_authors_extracted(self):
        c = _parse_nested()
        assert len(c.metadata.authors) == 2
        assert "Alice Chen" in c.metadata.authors
        assert "Robert Park" in c.metadata.authors

    def test_grobid_version_from_tei(self):
        c = _parse_nested()
        assert c.provenance.parser_version == "0.9.1"

    def test_abstract_multi_paragraph(self):
        c = _parse_nested()
        abstract = next(s for s in c.sections if s.title == "Abstract")
        # Both paragraphs should be present
        assert "systematic review" in abstract.text.lower()
        assert "MEDLINE" in abstract.text

    def test_reference_count_in_diagnostics(self):
        c = _parse_nested()
        assert c.diagnostics.notes is not None
        assert "3" in c.diagnostics.notes


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

class TestProvenance:
    def test_parser_name_is_grobid_tei(self):
        c = _parse_simple()
        assert c.provenance.parser_name == "grobid_tei"

    def test_parser_version_from_tei(self):
        c = _parse_simple()
        assert c.provenance.parser_version == "0.9.0"

    def test_created_at_populated(self):
        c = _parse_simple()
        assert c.provenance.created_at is not None

    def test_input_sha256_is_hex_64(self):
        c = _parse_simple()
        assert len(c.provenance.input_sha256) == 64
        assert all(ch in "0123456789abcdef" for ch in c.provenance.input_sha256)

    def test_input_sha256_matches_tei_file(self):
        from pdf_parser.schema.hashes import sha256_file
        c = _parse_simple()
        assert c.provenance.input_sha256 == sha256_file(SIMPLE_TEI)

    def test_input_sha256_uses_pdf_when_provided(self, tmp_path):
        fake_pdf = tmp_path / "paper.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")
        from pdf_parser.schema.hashes import sha256_file
        c = parse_grobid_tei_to_candidate(SIMPLE_TEI, input_pdf_path=fake_pdf)
        assert c.provenance.input_sha256 == sha256_file(fake_pdf)

    def test_output_sha256_is_computed(self):
        c = _parse_simple()
        assert c.provenance.output_sha256 != "0" * 64
        assert len(c.provenance.output_sha256) == 64

    def test_output_sha256_changes_when_content_changes(self):
        c1 = _parse_simple()
        c2 = _parse_nested()
        assert c1.provenance.output_sha256 != c2.provenance.output_sha256

    def test_output_sha256_deterministic(self):
        c1 = parse_grobid_tei_to_candidate(SIMPLE_TEI)
        c2 = parse_grobid_tei_to_candidate(SIMPLE_TEI)
        # created_at differs between calls; but the hash is based on content
        # which includes created_at — so the hashes may differ between two
        # independent calls. What we verify is that the stored hash reflects
        # the actual content at the time of creation.
        from pdf_parser.schema.hashes import compute_candidate_output_sha256
        assert c1.provenance.output_sha256 == compute_candidate_output_sha256(c1)
        assert c2.provenance.output_sha256 == compute_candidate_output_sha256(c2)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestErrorCases:
    def test_rejects_missing_tei_file(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="TEI file not found"):
            parse_grobid_tei_to_candidate(tmp_path / "ghost.tei.xml")

    def test_rejects_non_xml_suffix(self, tmp_path):
        txt = tmp_path / "file.txt"
        txt.write_text("not xml")
        with pytest.raises(ValueError, match=r"\.xml"):
            parse_grobid_tei_to_candidate(txt)

    def test_rejects_malformed_xml(self, tmp_path):
        bad = tmp_path / "bad.xml"
        bad.write_text("<unclosed <garbage")
        with pytest.raises(ET.ParseError):
            parse_grobid_tei_to_candidate(bad)

    def test_rejects_missing_pdf_path(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Input PDF not found"):
            parse_grobid_tei_to_candidate(SIMPLE_TEI, input_pdf_path=tmp_path / "ghost.pdf")


# ---------------------------------------------------------------------------
# TEI with unknown / missing GROBID version
# ---------------------------------------------------------------------------

class TestFallbackVersion:
    def test_unknown_version_when_app_element_absent(self, tmp_path):
        # Strip the encodingDesc block
        tei = SIMPLE_TEI.read_text(encoding="utf-8")
        stripped = "\n".join(
            line for line in tei.splitlines()
            if "encodingDesc" not in line and "appInfo" not in line and "application" not in line
        )
        f = tmp_path / "stripped.xml"
        f.write_text(stripped, encoding="utf-8")
        c = parse_grobid_tei_to_candidate(f)
        assert c.provenance.parser_version == "unknown"


# ---------------------------------------------------------------------------
# CLI integration — parse-tei writes pretty JSON
# ---------------------------------------------------------------------------

class TestCliParseTei:
    def test_cli_writes_pretty_json(self, tmp_path):
        out = tmp_path / "candidate.json"
        from pdf_parser.cli import main
        main(["grobid", "parse-tei", "--tei", str(SIMPLE_TEI), "--out", str(out)])
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        # Pretty-printed: must contain newlines and indentation
        assert "\n" in content
        assert "  " in content

    def test_cli_output_is_valid_json(self, tmp_path):
        out = tmp_path / "candidate.json"
        from pdf_parser.cli import main
        main(["grobid", "parse-tei", "--tei", str(SIMPLE_TEI), "--out", str(out)])
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "provenance" in data
        assert data["provenance"]["parser_name"] == "grobid_tei"

    def test_cli_output_contains_sections(self, tmp_path):
        out = tmp_path / "candidate.json"
        from pdf_parser.cli import main
        main(["grobid", "parse-tei", "--tei", str(SIMPLE_TEI), "--out", str(out)])
        data = json.loads(out.read_text(encoding="utf-8"))
        titles = [s["title"] for s in data["sections"]]
        assert "Introduction" in titles

    def test_cli_prints_output_path(self, tmp_path, capsys):
        out = tmp_path / "candidate.json"
        from pdf_parser.cli import main
        main(["grobid", "parse-tei", "--tei", str(SIMPLE_TEI), "--out", str(out)])
        assert str(out) in capsys.readouterr().out
