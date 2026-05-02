"""Tests for the pdf-parser CLI — no real GROBID server required."""

from pathlib import Path
from unittest.mock import patch

import pytest

from pdf_parser.cli import main


class TestGrobidCheckCommand:
    def test_alive_prints_message_and_exits_zero(self, capsys):
        with patch("pdf_parser.cli.check_grobid_alive", return_value=True):
            with pytest.raises(SystemExit) as exc:
                main(["grobid", "check"])
        assert exc.value.code == 0
        assert "alive" in capsys.readouterr().out.lower()

    def test_not_alive_prints_message_and_exits_nonzero(self, capsys):
        with patch("pdf_parser.cli.check_grobid_alive", return_value=False):
            with pytest.raises(SystemExit) as exc:
                main(["grobid", "check"])
        assert exc.value.code != 0
        out = capsys.readouterr().out
        assert "not reachable" in out.lower()

    def test_custom_url_passed_to_runtime(self):
        with patch("pdf_parser.cli.check_grobid_alive", return_value=True) as mock_fn:
            with pytest.raises(SystemExit):
                main(["grobid", "check", "--url", "http://myhost:9090"])
        mock_fn.assert_called_once_with("http://myhost:9090")


class TestGrobidProcessCommand:
    def test_calls_runtime_with_correct_args(self, tmp_path):
        out = tmp_path / "result.tei.xml"
        with patch("pdf_parser.cli.process_pdf_to_tei", return_value=out) as mock_fn:
            main(["grobid", "process", "--pdf", "paper.pdf", "--out", str(out)])
        mock_fn.assert_called_once_with(
            Path("paper.pdf"), Path(str(out)), "http://localhost:8070"
        )

    def test_prints_output_path(self, tmp_path, capsys):
        out = tmp_path / "result.tei.xml"
        with patch("pdf_parser.cli.process_pdf_to_tei", return_value=out):
            main(["grobid", "process", "--pdf", "paper.pdf", "--out", str(out)])
        assert str(out) in capsys.readouterr().out

    def test_custom_url_passed_to_runtime(self, tmp_path):
        out = tmp_path / "result.tei.xml"
        with patch("pdf_parser.cli.process_pdf_to_tei", return_value=out) as mock_fn:
            main([
                "grobid", "process",
                "--pdf", "paper.pdf",
                "--out", str(out),
                "--url", "http://remotehost:8070",
            ])
        mock_fn.assert_called_once_with(
            Path("paper.pdf"), Path(str(out)), "http://remotehost:8070"
        )


class TestGrobidBatchCommand:
    def test_calls_runtime_with_correct_args(self, tmp_path):
        outputs = [tmp_path / "a.tei.xml", tmp_path / "b.tei.xml"]
        with patch("pdf_parser.cli.process_pdf_directory_to_tei", return_value=outputs) as mock_fn:
            main([
                "grobid", "batch",
                "--input-dir", "data/raw_pdfs",
                "--out-dir", "data/grobid_tei",
            ])
        mock_fn.assert_called_once_with(
            Path("data/raw_pdfs"), Path("data/grobid_tei"), "http://localhost:8070"
        )

    def test_prints_each_output_path(self, tmp_path, capsys):
        outputs = [tmp_path / "a.tei.xml", tmp_path / "b.tei.xml"]
        with patch("pdf_parser.cli.process_pdf_directory_to_tei", return_value=outputs):
            main([
                "grobid", "batch",
                "--input-dir", "data/raw_pdfs",
                "--out-dir", "data/grobid_tei",
            ])
        out = capsys.readouterr().out
        assert "a.tei.xml" in out
        assert "b.tei.xml" in out

    def test_empty_batch_produces_no_output(self, capsys):
        with patch("pdf_parser.cli.process_pdf_directory_to_tei", return_value=[]):
            main([
                "grobid", "batch",
                "--input-dir", "data/raw_pdfs",
                "--out-dir", "data/grobid_tei",
            ])
        assert capsys.readouterr().out.strip() == ""
