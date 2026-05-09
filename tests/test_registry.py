"""Tests for the paper registry module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_parser.registry import (
    get_registered_pdf,
    load_registry,
    paper_id_from_sha256,
    register_paper,
    save_registry,
)


# ---------------------------------------------------------------------------
# paper_id_from_sha256
# ---------------------------------------------------------------------------

class TestPaperIdFromSha256:
    def test_prefix_is_pdf(self):
        assert paper_id_from_sha256("abcdef1234567890" + "0" * 48).startswith("pdf_")

    def test_uses_first_16_hex_chars(self):
        sha = "abcdef1234567890" + "x" * 48
        assert paper_id_from_sha256(sha) == "pdf_abcdef1234567890"

    def test_deterministic(self):
        sha = "a" * 64
        assert paper_id_from_sha256(sha) == paper_id_from_sha256(sha)

    def test_different_sha256_gives_different_id(self):
        assert paper_id_from_sha256("a" * 64) != paper_id_from_sha256("b" * 64)


# ---------------------------------------------------------------------------
# load_registry / save_registry
# ---------------------------------------------------------------------------

class TestRegistryIO:
    def test_load_returns_empty_dict_when_file_missing(self, tmp_path):
        assert load_registry(tmp_path) == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        data = {"pdf_abc": {"paper_id": "pdf_abc", "sha256": "abc"}}
        save_registry(tmp_path, data)
        assert load_registry(tmp_path) == data

    def test_save_creates_parents(self, tmp_path):
        nested = tmp_path / "a" / "b"
        save_registry(nested, {})
        assert (nested / "registry.json").exists()

    def test_save_writes_valid_json(self, tmp_path):
        save_registry(tmp_path, {"x": {"y": 1}})
        text = (tmp_path / "registry.json").read_text(encoding="utf-8")
        parsed = json.loads(text)
        assert parsed == {"x": {"y": 1}}

    def test_save_ends_with_newline(self, tmp_path):
        save_registry(tmp_path, {})
        text = (tmp_path / "registry.json").read_text(encoding="utf-8")
        assert text.endswith("\n")


# ---------------------------------------------------------------------------
# register_paper
# ---------------------------------------------------------------------------

class TestRegisterPaper:
    def test_returns_paper_id(self, tmp_path):
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4 test")
        papers_dir = tmp_path / "registered"
        paper_id = register_paper(pdf, papers_dir)
        assert paper_id.startswith("pdf_")
        assert len(paper_id) == 4 + 16  # "pdf_" + 16 hex chars

    def test_moves_pdf_to_papers_dir(self, tmp_path):
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4 test")
        papers_dir = tmp_path / "registered"
        paper_id = register_paper(pdf, papers_dir)
        assert (papers_dir / f"{paper_id}.pdf").exists()
        assert not pdf.exists()

    def test_writes_registry_json(self, tmp_path):
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4 test")
        papers_dir = tmp_path / "registered"
        paper_id = register_paper(pdf, papers_dir)
        registry = load_registry(papers_dir)
        assert paper_id in registry
        assert registry[paper_id]["original_filename"] == "paper.pdf"
        assert registry[paper_id]["paper_id"] == paper_id

    def test_registry_entry_has_sha256(self, tmp_path):
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4 test")
        papers_dir = tmp_path / "registered"
        paper_id = register_paper(pdf, papers_dir)
        registry = load_registry(papers_dir)
        sha = registry[paper_id]["sha256"]
        assert len(sha) == 64
        assert all(c in "0123456789abcdef" for c in sha)

    def test_idempotent_same_content(self, tmp_path):
        content = b"%PDF-1.4 idempotency test"
        pdf1 = tmp_path / "a.pdf"
        pdf1.write_bytes(content)
        papers_dir = tmp_path / "registered"
        id1 = register_paper(pdf1, papers_dir)

        # Register a second file with identical content
        pdf2 = tmp_path / "b.pdf"
        pdf2.write_bytes(content)
        id2 = register_paper(pdf2, papers_dir)

        assert id1 == id2
        # Only one entry in the registry
        assert len(load_registry(papers_dir)) == 1

    def test_different_content_gives_different_id(self, tmp_path):
        papers_dir = tmp_path / "registered"
        pdf1 = tmp_path / "a.pdf"
        pdf1.write_bytes(b"%PDF-1.4 aaa")
        id1 = register_paper(pdf1, papers_dir)

        pdf2 = tmp_path / "b.pdf"
        pdf2.write_bytes(b"%PDF-1.4 bbb")
        id2 = register_paper(pdf2, papers_dir)

        assert id1 != id2
        assert len(load_registry(papers_dir)) == 2

    def test_missing_pdf_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            register_paper(tmp_path / "missing.pdf", tmp_path / "registered")

    def test_non_pdf_suffix_raises_value_error(self, tmp_path):
        f = tmp_path / "paper.txt"
        f.write_bytes(b"not a pdf")
        with pytest.raises(ValueError):
            register_paper(f, tmp_path / "registered")

    def test_creates_papers_dir(self, tmp_path):
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4 test")
        papers_dir = tmp_path / "new" / "dir"
        register_paper(pdf, papers_dir)
        assert papers_dir.exists()


# ---------------------------------------------------------------------------
# get_registered_pdf
# ---------------------------------------------------------------------------

class TestGetRegisteredPdf:
    def test_returns_correct_path(self, tmp_path):
        papers_dir = tmp_path / "registered"
        papers_dir.mkdir()
        pdf = papers_dir / "pdf_abc12345678901a.pdf"
        pdf.write_bytes(b"%PDF")
        result = get_registered_pdf("pdf_abc12345678901a", papers_dir)
        assert result == pdf

    def test_missing_paper_id_raises_file_not_found(self, tmp_path):
        papers_dir = tmp_path / "registered"
        papers_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="pdf_notexist"):
            get_registered_pdf("pdf_notexist", papers_dir)

    def test_roundtrip_register_then_get(self, tmp_path):
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4 roundtrip")
        papers_dir = tmp_path / "registered"
        paper_id = register_paper(pdf, papers_dir)
        retrieved = get_registered_pdf(paper_id, papers_dir)
        assert retrieved.exists()
        assert retrieved.name == f"{paper_id}.pdf"
