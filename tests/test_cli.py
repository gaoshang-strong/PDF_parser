"""Tests for the pdf-parser CLI."""

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
        assert "not reachable" in capsys.readouterr().out.lower()

    def test_custom_url_passed_to_runtime(self):
        with patch("pdf_parser.cli.check_grobid_alive", return_value=True) as mock_fn:
            with pytest.raises(SystemExit):
                main(["grobid", "check", "--url", "http://myhost:9090"])
        mock_fn.assert_called_once_with("http://myhost:9090")


class TestGrobidProcessCommand:
    def test_calls_runtime_with_correct_args(self, tmp_path):
        fake_pdf = tmp_path / "pdf_abc12345678901a.pdf"
        expected_tei = Path("data/grobid") / "pdf_abc12345678901a.tei.xml"
        with patch("pdf_parser.cli.get_registered_pdf", return_value=fake_pdf) as mock_reg, \
             patch("pdf_parser.cli.process_pdf_to_tei", return_value=expected_tei) as mock_fn:
            main(["grobid", "process", "--paper-id", "pdf_abc12345678901a"])
        mock_reg.assert_called_once_with("pdf_abc12345678901a", Path("data/registered_pdfs"))
        mock_fn.assert_called_once_with(fake_pdf, expected_tei, "http://localhost:8070")

    def test_prints_output_path(self, tmp_path, capsys):
        fake_pdf = tmp_path / "pdf_abc12345678901a.pdf"
        tei_path = tmp_path / "pdf_abc12345678901a.tei.xml"
        with patch("pdf_parser.cli.get_registered_pdf", return_value=fake_pdf), \
             patch("pdf_parser.cli.process_pdf_to_tei", return_value=tei_path):
            main(["grobid", "process", "--paper-id", "pdf_abc12345678901a"])
        assert str(tei_path) in capsys.readouterr().out

    def test_custom_out_dir(self, tmp_path):
        fake_pdf = tmp_path / "pdf_abc12345678901a.pdf"
        out_dir = tmp_path / "my_grobid"
        with patch("pdf_parser.cli.get_registered_pdf", return_value=fake_pdf), \
             patch("pdf_parser.cli.process_pdf_to_tei", return_value=out_dir / "x.tei.xml") as mock_fn:
            main(["grobid", "process", "--paper-id", "pdf_abc12345678901a", "--out-dir", str(out_dir)])
        expected_tei = out_dir / "pdf_abc12345678901a.tei.xml"
        mock_fn.assert_called_once_with(fake_pdf, expected_tei, "http://localhost:8070")

    def test_custom_url(self, tmp_path):
        fake_pdf = tmp_path / "pdf_abc12345678901a.pdf"
        with patch("pdf_parser.cli.get_registered_pdf", return_value=fake_pdf), \
             patch("pdf_parser.cli.process_pdf_to_tei", return_value=tmp_path / "x.tei.xml") as mock_fn:
            main(["grobid", "process", "--paper-id", "pdf_abc12345678901a",
                  "--url", "http://remotehost:8070"])
        assert mock_fn.call_args.args[2] == "http://remotehost:8070"

    def test_custom_papers_dir(self, tmp_path):
        fake_pdf = tmp_path / "pdf_abc12345678901a.pdf"
        papers_dir = tmp_path / "my_papers"
        with patch("pdf_parser.cli.get_registered_pdf", return_value=fake_pdf) as mock_reg, \
             patch("pdf_parser.cli.process_pdf_to_tei", return_value=tmp_path / "x.tei.xml"):
            main(["grobid", "process", "--paper-id", "pdf_abc12345678901a",
                  "--papers-dir", str(papers_dir)])
        mock_reg.assert_called_once_with("pdf_abc12345678901a", papers_dir)


class TestGrobidBatchCommand:
    def test_calls_runtime_with_correct_args(self, tmp_path):
        outputs = [tmp_path / "a.tei.xml", tmp_path / "b.tei.xml"]
        with patch("pdf_parser.cli.process_pdf_directory_to_tei", return_value=outputs) as mock_fn:
            main(["grobid", "batch", "--input-dir", "data/raw_pdfs", "--out-dir", "data/grobid"])
        mock_fn.assert_called_once_with(
            Path("data/raw_pdfs"), Path("data/grobid"), "http://localhost:8070"
        )

    def test_prints_each_output_path(self, tmp_path, capsys):
        outputs = [tmp_path / "a.tei.xml", tmp_path / "b.tei.xml"]
        with patch("pdf_parser.cli.process_pdf_directory_to_tei", return_value=outputs):
            main(["grobid", "batch", "--input-dir", "data/raw_pdfs", "--out-dir", "data/grobid"])
        out = capsys.readouterr().out
        assert "a.tei.xml" in out
        assert "b.tei.xml" in out

    def test_empty_batch_produces_no_output(self, capsys):
        with patch("pdf_parser.cli.process_pdf_directory_to_tei", return_value=[]):
            main(["grobid", "batch", "--input-dir", "data/raw_pdfs", "--out-dir", "data/grobid"])
        assert capsys.readouterr().out.strip() == ""


class TestMineruRunCommand:
    def test_calls_run_with_correct_args(self, tmp_path):
        fake_pdf = tmp_path / "pdf_abc12345678901a.pdf"
        out_dir = Path("data/mineru") / "pdf_abc12345678901a"
        with patch("pdf_parser.cli.get_registered_pdf", return_value=fake_pdf) as mock_reg, \
             patch("pdf_parser.cli.run_mineru_api", return_value=out_dir) as mock_run:
            main(["mineru", "run", "--paper-id", "pdf_abc12345678901a"])
        mock_reg.assert_called_once_with("pdf_abc12345678901a", Path("data/registered_pdfs"))
        mock_run.assert_called_once_with(fake_pdf, out_dir)

    def test_prints_output_dir(self, tmp_path, capsys):
        fake_pdf = tmp_path / "pdf_abc12345678901a.pdf"
        out_dir = tmp_path / "mineru" / "pdf_abc12345678901a"
        with patch("pdf_parser.cli.get_registered_pdf", return_value=fake_pdf), \
             patch("pdf_parser.cli.run_mineru_api", return_value=out_dir):
            main(["mineru", "run", "--paper-id", "pdf_abc12345678901a",
                  "--out-dir", str(tmp_path / "mineru")])
        assert str(out_dir) in capsys.readouterr().out

    def test_custom_out_dir(self, tmp_path):
        fake_pdf = tmp_path / "pdf_abc12345678901a.pdf"
        out_dir = tmp_path / "my_mineru"
        with patch("pdf_parser.cli.get_registered_pdf", return_value=fake_pdf), \
             patch("pdf_parser.cli.run_mineru_api", return_value=out_dir / "pdf_abc12345678901a") as mock_run:
            main(["mineru", "run", "--paper-id", "pdf_abc12345678901a",
                  "--out-dir", str(out_dir)])
        mock_run.assert_called_once_with(fake_pdf, out_dir / "pdf_abc12345678901a")

    def test_custom_papers_dir(self, tmp_path):
        fake_pdf = tmp_path / "pdf_abc12345678901a.pdf"
        papers_dir = tmp_path / "my_papers"
        with patch("pdf_parser.cli.get_registered_pdf", return_value=fake_pdf) as mock_reg, \
             patch("pdf_parser.cli.run_mineru_api", return_value=tmp_path):
            main(["mineru", "run", "--paper-id", "pdf_abc12345678901a",
                  "--papers-dir", str(papers_dir)])
        mock_reg.assert_called_once_with("pdf_abc12345678901a", papers_dir)
