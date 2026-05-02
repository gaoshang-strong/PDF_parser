"""Tests for GROBID runtime module — no real GROBID server required."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from pdf_parser.grobid.runtime import (
    check_grobid_alive,
    process_pdf_directory_to_tei,
    process_pdf_to_tei,
)


def _fake_pdf(tmp_path: Path, name: str = "sample.pdf") -> Path:
    p = tmp_path / name
    p.write_bytes(b"%PDF-1.4 fake content")
    return p


def _mock_ok_response(text: str = "<TEI/>") -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.text = text
    r.raise_for_status = MagicMock()
    return r


class TestCheckGrobidAlive:
    def test_returns_true_when_service_alive(self):
        with patch("requests.get", return_value=_mock_ok_response("true")):
            assert check_grobid_alive("http://localhost:8070") is True

    def test_returns_false_when_body_is_false(self):
        with patch("requests.get", return_value=_mock_ok_response("false")):
            assert check_grobid_alive("http://localhost:8070") is False

    def test_returns_false_on_connection_error(self):
        with patch("requests.get", side_effect=requests.ConnectionError()):
            assert check_grobid_alive("http://localhost:8070") is False

    def test_returns_false_on_timeout(self):
        with patch("requests.get", side_effect=requests.Timeout()):
            assert check_grobid_alive("http://localhost:8070") is False

    def test_returns_false_on_non_200_status(self):
        r = MagicMock()
        r.status_code = 503
        r.text = ""
        with patch("requests.get", return_value=r):
            assert check_grobid_alive("http://localhost:8070") is False

    def test_strips_whitespace_from_body(self):
        with patch("requests.get", return_value=_mock_ok_response("  true\n")):
            assert check_grobid_alive("http://localhost:8070") is True


class TestProcessPdfToTei:
    def test_missing_pdf_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="PDF not found"):
            process_pdf_to_tei(tmp_path / "ghost.pdf", tmp_path / "out.tei.xml")

    def test_non_pdf_suffix_raises_value_error(self, tmp_path):
        txt = tmp_path / "file.txt"
        txt.write_text("not a pdf")
        with pytest.raises(ValueError, match="PDF"):
            process_pdf_to_tei(txt, tmp_path / "out.tei.xml")

    def test_creates_output_directory(self, tmp_path):
        pdf = _fake_pdf(tmp_path)
        out = tmp_path / "nested" / "deep" / "out.tei.xml"
        with patch("requests.post", return_value=_mock_ok_response("<TEI/>")):
            process_pdf_to_tei(pdf, out)
        assert out.parent.exists()

    def test_writes_tei_content(self, tmp_path):
        pdf = _fake_pdf(tmp_path)
        out = tmp_path / "out.tei.xml"
        tei = "<TEI><text>Hello world</text></TEI>"
        with patch("requests.post", return_value=_mock_ok_response(tei)):
            process_pdf_to_tei(pdf, out)
        assert out.read_text(encoding="utf-8") == tei

    def test_returns_output_path(self, tmp_path):
        pdf = _fake_pdf(tmp_path)
        out = tmp_path / "out.tei.xml"
        with patch("requests.post", return_value=_mock_ok_response()):
            result = process_pdf_to_tei(pdf, out)
        assert result == out

    def test_http_error_raises(self, tmp_path):
        pdf = _fake_pdf(tmp_path)
        out = tmp_path / "out.tei.xml"
        r = MagicMock()
        r.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        with patch("requests.post", return_value=r):
            with pytest.raises(requests.HTTPError):
                process_pdf_to_tei(pdf, out)

    def test_posts_to_correct_endpoint(self, tmp_path):
        pdf = _fake_pdf(tmp_path)
        out = tmp_path / "out.tei.xml"
        with patch("requests.post", return_value=_mock_ok_response()) as mock_post:
            process_pdf_to_tei(pdf, out, base_url="http://localhost:8070")
        url = mock_post.call_args[0][0]
        assert url == "http://localhost:8070/api/processFulltextDocument"

    def test_accepts_path_as_string(self, tmp_path):
        pdf = _fake_pdf(tmp_path)
        out = tmp_path / "out.tei.xml"
        with patch("requests.post", return_value=_mock_ok_response()):
            result = process_pdf_to_tei(str(pdf), str(out))
        assert result == out


class TestProcessPdfDirectoryToTei:
    def test_processes_only_pdf_files(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "paper1.pdf").write_bytes(b"%PDF fake")
        (input_dir / "paper2.pdf").write_bytes(b"%PDF fake")
        (input_dir / "notes.txt").write_text("ignore me")
        (input_dir / "image.png").write_bytes(b"\x89PNG")

        with patch("requests.post", return_value=_mock_ok_response()):
            results = process_pdf_directory_to_tei(input_dir, tmp_path / "out")

        assert len(results) == 2

    def test_output_filenames_use_tei_xml_suffix(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "mypaper.pdf").write_bytes(b"%PDF fake")

        with patch("requests.post", return_value=_mock_ok_response()):
            results = process_pdf_directory_to_tei(input_dir, tmp_path / "out")

        assert results[0].name == "mypaper.tei.xml"

    def test_missing_input_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Input directory not found"):
            process_pdf_directory_to_tei(tmp_path / "ghost", tmp_path / "out")

    def test_empty_directory_returns_empty_list(self, tmp_path):
        input_dir = tmp_path / "empty"
        input_dir.mkdir()
        results = process_pdf_directory_to_tei(input_dir, tmp_path / "out")
        assert results == []

    def test_returns_list_of_paths(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "a.pdf").write_bytes(b"%PDF fake")

        with patch("requests.post", return_value=_mock_ok_response()):
            results = process_pdf_directory_to_tei(input_dir, tmp_path / "out")

        assert all(isinstance(p, Path) for p in results)
