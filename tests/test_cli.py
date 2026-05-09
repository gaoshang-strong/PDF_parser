"""Tests for the pdf-parser CLI — no real GROBID server required."""

from pathlib import Path
from unittest.mock import patch

import pytest

from pdf_parser.cli import main


class TestRegisterCommand:
    def test_prints_paper_id(self, capsys):
        with patch("pdf_parser.cli.register_paper", return_value="pdf_abc12345678901a"):
            main(["register", "--pdf", "paper.pdf"])
        assert "pdf_abc12345678901a" in capsys.readouterr().out

    def test_calls_register_with_correct_args(self, tmp_path):
        with patch("pdf_parser.cli.register_paper", return_value="pdf_abc12345678901a") as mock_fn:
            main(["register", "--pdf", "paper.pdf", "--papers-dir", str(tmp_path)])
        mock_fn.assert_called_once_with(Path("paper.pdf"), tmp_path)

    def test_default_papers_dir(self):
        with patch("pdf_parser.cli.register_paper", return_value="pdf_abc12345678901a") as mock_fn:
            main(["register", "--pdf", "paper.pdf"])
        mock_fn.assert_called_once_with(Path("paper.pdf"), Path("data/registered_pdfs"))


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
        fake_pdf = tmp_path / "pdf_abc12345678901a.pdf"
        with patch("pdf_parser.cli.get_registered_pdf", return_value=fake_pdf) as mock_reg, \
             patch("pdf_parser.cli.process_pdf_to_tei", return_value=out) as mock_fn:
            main(["grobid", "process", "--paper-id", "pdf_abc12345678901a", "--out", str(out)])
        mock_reg.assert_called_once_with("pdf_abc12345678901a", Path("data/registered_pdfs"))
        mock_fn.assert_called_once_with(fake_pdf, Path(str(out)), "http://localhost:8070")

    def test_prints_output_path(self, tmp_path, capsys):
        out = tmp_path / "result.tei.xml"
        fake_pdf = tmp_path / "pdf_abc12345678901a.pdf"
        with patch("pdf_parser.cli.get_registered_pdf", return_value=fake_pdf), \
             patch("pdf_parser.cli.process_pdf_to_tei", return_value=out):
            main(["grobid", "process", "--paper-id", "pdf_abc12345678901a", "--out", str(out)])
        assert str(out) in capsys.readouterr().out

    def test_custom_url_passed_to_runtime(self, tmp_path):
        out = tmp_path / "result.tei.xml"
        fake_pdf = tmp_path / "pdf_abc12345678901a.pdf"
        with patch("pdf_parser.cli.get_registered_pdf", return_value=fake_pdf), \
             patch("pdf_parser.cli.process_pdf_to_tei", return_value=out) as mock_fn:
            main([
                "grobid", "process",
                "--paper-id", "pdf_abc12345678901a",
                "--out", str(out),
                "--url", "http://remotehost:8070",
            ])
        mock_fn.assert_called_once_with(fake_pdf, Path(str(out)), "http://remotehost:8070")

    def test_custom_papers_dir(self, tmp_path):
        out = tmp_path / "result.tei.xml"
        fake_pdf = tmp_path / "pdf_abc12345678901a.pdf"
        papers_dir = tmp_path / "my_papers"
        with patch("pdf_parser.cli.get_registered_pdf", return_value=fake_pdf) as mock_reg, \
             patch("pdf_parser.cli.process_pdf_to_tei", return_value=out):
            main([
                "grobid", "process",
                "--paper-id", "pdf_abc12345678901a",
                "--papers-dir", str(papers_dir),
                "--out", str(out),
            ])
        mock_reg.assert_called_once_with("pdf_abc12345678901a", papers_dir)


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
