"""Tests for write_pretty_json utility."""

import json
import tempfile
from pathlib import Path

import pytest

from pdf_parser.export.json_writer import write_pretty_json


class TestWritePrettyJson:
    def test_creates_file(self, tmp_path):
        out = tmp_path / "output.json"
        write_pretty_json(out, {"key": "value"})
        assert out.exists()

    def test_valid_json(self, tmp_path):
        out = tmp_path / "output.json"
        data = {"a": 1, "b": [1, 2, 3], "c": None}
        write_pretty_json(out, data)
        parsed = json.loads(out.read_text(encoding="utf-8"))
        assert parsed == data

    def test_pretty_printed(self, tmp_path):
        out = tmp_path / "output.json"
        write_pretty_json(out, {"key": "value", "nested": {"x": 1}})
        content = out.read_text(encoding="utf-8")
        assert "\n" in content
        assert "  " in content  # indented with spaces

    def test_sorted_keys(self, tmp_path):
        out = tmp_path / "output.json"
        write_pretty_json(out, {"z": 3, "a": 1, "m": 2})
        parsed = json.loads(out.read_text(encoding="utf-8"))
        assert list(parsed.keys()) == ["a", "m", "z"]

    def test_ends_with_newline(self, tmp_path):
        out = tmp_path / "output.json"
        write_pretty_json(out, {"x": 1})
        content = out.read_text(encoding="utf-8")
        assert content.endswith("\n")

    def test_creates_parent_directories(self, tmp_path):
        out = tmp_path / "nested" / "dir" / "output.json"
        write_pretty_json(out, {"key": "value"})
        assert out.exists()

    def test_overwrites_existing_file(self, tmp_path):
        out = tmp_path / "output.json"
        write_pretty_json(out, {"first": True})
        write_pretty_json(out, {"second": True})
        parsed = json.loads(out.read_text(encoding="utf-8"))
        assert "second" in parsed
        assert "first" not in parsed

    def test_unicode_preserved(self, tmp_path):
        out = tmp_path / "output.json"
        data = {"text": "café résumé naïve"}
        write_pretty_json(out, data)
        parsed = json.loads(out.read_text(encoding="utf-8"))
        assert parsed["text"] == "café résumé naïve"

    def test_large_nested_structure(self, tmp_path):
        out = tmp_path / "output.json"
        data = {
            "sections": [
                {"id": str(i), "title": f"Section {i}", "blocks": list(range(10))}
                for i in range(50)
            ]
        }
        write_pretty_json(out, data)
        parsed = json.loads(out.read_text(encoding="utf-8"))
        assert len(parsed["sections"]) == 50
