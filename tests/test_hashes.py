"""Tests for hash utilities."""

import json
import tempfile
from pathlib import Path

import pytest

from pdf_parser.schema.candidate import ParsedBlock, ParsedCandidate, ParserProvenance
from pdf_parser.schema.hashes import (
    canonical_json_dumps,
    compute_candidate_output_sha256,
    sha256_file,
    sha256_text,
)


def make_candidate(parser_name="test", extra_blocks=None) -> ParsedCandidate:
    blocks = extra_blocks or []
    return ParsedCandidate(
        provenance=ParserProvenance(
            parser_name=parser_name,
            parser_version="1.0.0",
            input_sha256="a" * 64,
            output_sha256="b" * 64,
        ),
        blocks=blocks,
    )


class TestSha256Text:
    def test_known_hash(self):
        # echo -n "" | sha256sum => e3b0c44298fc1c149afb...
        assert sha256_text("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_deterministic(self):
        assert sha256_text("hello world") == sha256_text("hello world")

    def test_different_inputs_differ(self):
        assert sha256_text("hello") != sha256_text("world")

    def test_returns_hex_string(self):
        result = sha256_text("test")
        assert isinstance(result, str)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestSha256File:
    def test_file_hash_matches_content_hash(self):
        content = b"hello, file"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(content)
            tmp_path = Path(f.name)
        try:
            expected = sha256_text(content.decode("utf-8"))
            assert sha256_file(tmp_path) == expected
        finally:
            tmp_path.unlink()

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            tmp_path = Path(f.name)
        try:
            assert sha256_file(tmp_path) == sha256_text("")
        finally:
            tmp_path.unlink()

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            sha256_file(Path("/nonexistent/path/file.txt"))

    def test_deterministic(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"deterministic content")
            tmp_path = Path(f.name)
        try:
            assert sha256_file(tmp_path) == sha256_file(tmp_path)
        finally:
            tmp_path.unlink()


class TestCanonicalJsonDumps:
    def test_sorts_keys(self):
        obj = {"z": 1, "a": 2, "m": 3}
        result = canonical_json_dumps(obj)
        parsed = json.loads(result)
        assert list(parsed.keys()) == ["a", "m", "z"]

    def test_no_extra_whitespace(self):
        result = canonical_json_dumps({"key": "value"})
        assert " " not in result

    def test_deterministic_across_calls(self):
        obj = {"b": [3, 1, 2], "a": {"z": 9, "y": 8}}
        assert canonical_json_dumps(obj) == canonical_json_dumps(obj)

    def test_nested_objects_sorted(self):
        obj = {"outer": {"z": 1, "a": 2}}
        result = canonical_json_dumps(obj)
        # nested keys should also be sorted
        parsed = json.loads(result)
        assert list(parsed["outer"].keys()) == ["a", "z"]

    def test_valid_json(self):
        obj = {"list": [1, 2, 3], "num": 3.14, "flag": True, "nothing": None}
        result = canonical_json_dumps(obj)
        parsed = json.loads(result)
        assert parsed == obj


class TestComputeCandidateOutputSha256:
    def test_returns_hex_string(self):
        candidate = make_candidate()
        result = compute_candidate_output_sha256(candidate)
        assert isinstance(result, str)
        assert len(result) == 64

    def test_changes_when_block_added(self):
        c1 = make_candidate()
        c2 = make_candidate(
            extra_blocks=[ParsedBlock(block_id="b1", page=1, text="new content")]
        )
        assert compute_candidate_output_sha256(c1) != compute_candidate_output_sha256(c2)

    def test_changes_when_text_changes(self):
        c1 = make_candidate(
            extra_blocks=[ParsedBlock(block_id="b1", page=1, text="original")]
        )
        c2 = make_candidate(
            extra_blocks=[ParsedBlock(block_id="b1", page=1, text="modified")]
        )
        assert compute_candidate_output_sha256(c1) != compute_candidate_output_sha256(c2)

    def test_deterministic(self):
        candidate = make_candidate(
            extra_blocks=[ParsedBlock(block_id="b1", page=1, text="stable")]
        )
        assert (
            compute_candidate_output_sha256(candidate)
            == compute_candidate_output_sha256(candidate)
        )

    def test_excludes_output_sha256_from_hash(self):
        # Two candidates identical except for output_sha256 should hash the same.
        # Pin created_at so the two provenances are otherwise identical.
        from datetime import datetime, timezone

        fixed_ts = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        prov1 = ParserProvenance(
            parser_name="p",
            parser_version="1.0",
            created_at=fixed_ts,
            input_sha256="a" * 64,
            output_sha256="b" * 64,
        )
        prov2 = ParserProvenance(
            parser_name="p",
            parser_version="1.0",
            created_at=fixed_ts,
            input_sha256="a" * 64,
            output_sha256="c" * 64,  # different — should not affect the hash
        )
        c1 = ParsedCandidate(provenance=prov1)
        c2 = ParsedCandidate(provenance=prov2)
        assert compute_candidate_output_sha256(c1) == compute_candidate_output_sha256(c2)

    def test_changes_when_parser_name_changes(self):
        c1 = make_candidate(parser_name="grobid")
        c2 = make_candidate(parser_name="pymupdf")
        assert compute_candidate_output_sha256(c1) != compute_candidate_output_sha256(c2)
