"""Tests for the MinerU API adapter.

All tests use mocks or fixture files — no real API calls are made.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_SIMPLE_MD = """\
# Introduction

This is the introduction paragraph.

## Background

Some background text.

# Methods

We used a robust approach.
"""

_SIMPLE_CONTENT_LIST = [
    {"type": "text", "text": "Introduction", "text_level": 1, "page_idx": 0},
    {"type": "text", "text": "This is the introduction paragraph.", "page_idx": 0},
    {"type": "text", "text": "Methods", "text_level": 1, "page_idx": 1},
    {"type": "text", "text": "We used a robust approach.", "page_idx": 1},
]

_CONTENT_LIST_WITH_ASSETS = [
    {"type": "text", "text": "Results", "text_level": 1, "page_idx": 2},
    {"type": "image", "img_path": "img/fig1.png", "img_caption": ["Figure 1. Example."], "page_idx": 2},
    {"type": "table", "table_body": "| A | B |", "table_caption": ["Table 1. Data."], "page_idx": 3},
    {"type": "equation", "text": "E = mc^2", "page_idx": 3},
]


def _make_zip_with_content_list(tmp_path: Path, content: list) -> Path:
    """Build a ZIP containing {stem}_content_list.json."""
    extract_dir = tmp_path / "extracted"
    extract_dir.mkdir(parents=True)
    cl_file = extract_dir / "paper_content_list.json"
    cl_file.write_text(json.dumps(content), encoding="utf-8")
    zip_path = tmp_path / "result.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(cl_file, arcname="paper_content_list.json")
    return zip_path


def _make_zip_with_markdown(tmp_path: Path, md: str) -> Path:
    """Build a ZIP containing paper.md."""
    extract_dir = tmp_path / "extracted_md"
    extract_dir.mkdir(parents=True)
    md_file = extract_dir / "paper.md"
    md_file.write_text(md, encoding="utf-8")
    zip_path = tmp_path / "result_md.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(md_file, arcname="paper.md")
    return zip_path


def _batch_upload_ok_response(
    batch_id: str = "batch-abc",
    put_url: str = "https://mineru.oss-cn-shanghai.aliyuncs.com/upload?sig=x",
) -> dict:
    return {
        "code": 0,
        "msg": "ok",
        "data": {
            "batch_id": batch_id,
            "file_urls": [put_url],
        },
    }


def _batch_poll_done_response(
    batch_id: str = "batch-abc",
    zip_url: str = "https://cdn.example.com/result.zip",
) -> dict:
    return {
        "code": 0,
        "data": {
            "batch_id": batch_id,
            "extract_result": [
                {
                    "file_name": "paper.pdf",
                    "state": "done",
                    "err_msg": "",
                    "full_zip_url": zip_url,
                }
            ],
        },
    }


def _batch_poll_state_response(state: str, err_msg: str = "") -> dict:
    return {
        "code": 0,
        "data": {
            "extract_result": [
                {
                    "file_name": "paper.pdf",
                    "state": state,
                    "err_msg": err_msg,
                    "full_zip_url": "",
                }
            ]
        },
    }


# ---------------------------------------------------------------------------
# Module import test
# ---------------------------------------------------------------------------

def test_module_imports_without_mineru_package():
    """Importing the adapter must not require the mineru Python package."""
    import pdf_parser.parsers.mineru_api_adapter as mod
    assert hasattr(mod, "parse_pdf_with_mineru_api")
    assert hasattr(mod, "parse_mineru_output_to_candidate")


# ---------------------------------------------------------------------------
# Token tests
# ---------------------------------------------------------------------------

def test_missing_token_raises_runtime_error():
    from pdf_parser.parsers.mineru_api_adapter import get_mineru_api_token
    with patch.dict("os.environ", {}, clear=True):
        import os
        os.environ.pop("MINERU_API_TOKEN", None)
        with pytest.raises(RuntimeError, match="MINERU_API_TOKEN"):
            get_mineru_api_token()


def test_token_read_from_environment():
    from pdf_parser.parsers.mineru_api_adapter import get_mineru_api_token
    with patch.dict("os.environ", {"MINERU_API_TOKEN": "test-token-xyz"}):
        assert get_mineru_api_token() == "test-token-xyz"


def test_empty_token_raises_runtime_error():
    from pdf_parser.parsers.mineru_api_adapter import get_mineru_api_token
    with patch.dict("os.environ", {"MINERU_API_TOKEN": "   "}):
        with pytest.raises(RuntimeError, match="MINERU_API_TOKEN"):
            get_mineru_api_token()


# ---------------------------------------------------------------------------
# Input validation tests
# ---------------------------------------------------------------------------

def test_missing_pdf_raises_file_not_found(tmp_path):
    from pdf_parser.parsers.mineru_api_adapter import parse_pdf_with_mineru_api
    with pytest.raises(FileNotFoundError):
        parse_pdf_with_mineru_api(tmp_path / "missing.pdf", tmp_path / "work", token="tok")


def test_non_pdf_suffix_raises_value_error(tmp_path):
    txt = tmp_path / "doc.txt"
    txt.write_text("hello")
    from pdf_parser.parsers.mineru_api_adapter import parse_pdf_with_mineru_api
    with pytest.raises(ValueError, match=r"\.pdf"):
        parse_pdf_with_mineru_api(txt, tmp_path / "work", token="tok")


# ---------------------------------------------------------------------------
# request_mineru_batch_upload_url tests
# ---------------------------------------------------------------------------

def test_batch_upload_url_uses_authorization_header():
    from pdf_parser.parsers.mineru_api_adapter import request_mineru_batch_upload_url
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = _batch_upload_ok_response()
    with patch("requests.post", return_value=mock_response) as mock_post:
        put_url, batch_id = request_mineru_batch_upload_url("paper.pdf", "secret-token")
    headers = mock_post.call_args.kwargs["headers"]
    assert "Authorization" in headers
    assert headers["Authorization"] == "Bearer secret-token"
    assert put_url == "https://mineru.oss-cn-shanghai.aliyuncs.com/upload?sig=x"
    assert batch_id == "batch-abc"


def test_batch_upload_url_sends_filename_in_files_list():
    """Batch request must send files=[{"name": pdf_name}], not filenames=[...]."""
    from pdf_parser.parsers.mineru_api_adapter import request_mineru_batch_upload_url
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = _batch_upload_ok_response()
    with patch("requests.post", return_value=mock_response) as mock_post:
        request_mineru_batch_upload_url("paper.pdf", "tok")
    sent_json = mock_post.call_args.kwargs.get("json") or mock_post.call_args.args[1]
    assert "files" in sent_json
    assert sent_json["files"] == [{"name": "paper.pdf"}]


def test_batch_upload_url_sends_model_version():
    from pdf_parser.parsers.mineru_api_adapter import (
        request_mineru_batch_upload_url,
        _DEFAULT_MODEL_VERSION,
    )
    assert _DEFAULT_MODEL_VERSION == "vlm"
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = _batch_upload_ok_response()
    with patch("requests.post", return_value=mock_response) as mock_post:
        request_mineru_batch_upload_url("paper.pdf", "tok")
    sent_json = mock_post.call_args.kwargs.get("json") or mock_post.call_args.args[1]
    assert sent_json.get("model_version") == "vlm"


def test_batch_upload_url_non_200_raises():
    from pdf_parser.parsers.mineru_api_adapter import request_mineru_batch_upload_url
    mock_response = MagicMock()
    mock_response.status_code = 401
    with patch("requests.post", return_value=mock_response):
        with pytest.raises(RuntimeError, match="401"):
            request_mineru_batch_upload_url("paper.pdf", "bad-token")


def test_batch_upload_url_api_error_code_raises():
    from pdf_parser.parsers.mineru_api_adapter import request_mineru_batch_upload_url
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"code": 4001, "msg": "invalid token"}
    with patch("requests.post", return_value=mock_response):
        with pytest.raises(RuntimeError, match="4001"):
            request_mineru_batch_upload_url("paper.pdf", "tok")


def test_batch_upload_url_missing_batch_id_raises():
    from pdf_parser.parsers.mineru_api_adapter import request_mineru_batch_upload_url
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "code": 0,
        "data": {"file_urls": ["https://oss.example.com/upload"]},
    }
    with patch("requests.post", return_value=mock_response):
        with pytest.raises(RuntimeError, match="batch_id"):
            request_mineru_batch_upload_url("paper.pdf", "tok")


def test_batch_upload_url_missing_file_urls_raises():
    from pdf_parser.parsers.mineru_api_adapter import request_mineru_batch_upload_url
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"code": 0, "data": {"batch_id": "b1"}}
    with patch("requests.post", return_value=mock_response):
        with pytest.raises(RuntimeError, match="file_urls"):
            request_mineru_batch_upload_url("paper.pdf", "tok")


# ---------------------------------------------------------------------------
# upload_pdf_to_mineru_upload_url tests
# ---------------------------------------------------------------------------

def test_upload_success(tmp_path):
    from pdf_parser.parsers.mineru_api_adapter import upload_pdf_to_mineru_upload_url
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    mock_response = MagicMock()
    mock_response.status_code = 200
    with patch("requests.put", return_value=mock_response):
        upload_pdf_to_mineru_upload_url(pdf, "https://mineru.oss-cn-shanghai.aliyuncs.com/upload?sig=x")


def test_upload_sends_bytes_not_file_handle(tmp_path):
    """PUT must send in-memory bytes so requests sets Content-Length correctly."""
    from pdf_parser.parsers.mineru_api_adapter import upload_pdf_to_mineru_upload_url
    content = b"%PDF-1.4 this-is-the-content"
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(content)
    mock_response = MagicMock()
    mock_response.status_code = 200
    with patch("requests.put", return_value=mock_response) as mock_put:
        upload_pdf_to_mineru_upload_url(pdf, "https://mineru.oss-cn-shanghai.aliyuncs.com/upload?sig=x")
    sent_data = mock_put.call_args.kwargs.get("data") or mock_put.call_args.args[1]
    assert isinstance(sent_data, bytes), "PUT data must be bytes, not a file handle"
    assert sent_data == content


def test_upload_sends_no_content_type_header(tmp_path):
    """Batch PUT URL signature does not include Content-Type.
    Sending any Content-Type causes HTTP 403, so none must be sent.
    """
    from pdf_parser.parsers.mineru_api_adapter import upload_pdf_to_mineru_upload_url
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    mock_response = MagicMock()
    mock_response.status_code = 200
    with patch("requests.put", return_value=mock_response) as mock_put:
        upload_pdf_to_mineru_upload_url(pdf, "https://mineru.oss-cn-shanghai.aliyuncs.com/upload?sig=x")
    call_kwargs = mock_put.call_args.kwargs
    headers = call_kwargs.get("headers", {})
    assert "Content-Type" not in (headers or {}), (
        "Must not send Content-Type header for batch PUT URL"
    )


def test_upload_failure_raises(tmp_path):
    from pdf_parser.parsers.mineru_api_adapter import upload_pdf_to_mineru_upload_url
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    mock_response = MagicMock()
    mock_response.status_code = 403
    with patch("requests.put", return_value=mock_response):
        with pytest.raises(RuntimeError, match="403"):
            upload_pdf_to_mineru_upload_url(pdf, "https://mineru.oss-cn-shanghai.aliyuncs.com/upload?sig=x")


# ---------------------------------------------------------------------------
# poll_mineru_batch_result tests
# ---------------------------------------------------------------------------

def test_poll_batch_success_immediately():
    from pdf_parser.parsers.mineru_api_adapter import poll_mineru_batch_result
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = _batch_poll_done_response(zip_url="https://cdn.example.com/result.zip")
    with patch("requests.get", return_value=mock_response):
        zip_url = poll_mineru_batch_result("batch-1", "tok", poll_interval=0)
    assert zip_url == "https://cdn.example.com/result.zip"


def test_poll_batch_failure_raises():
    from pdf_parser.parsers.mineru_api_adapter import poll_mineru_batch_result
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = _batch_poll_state_response("failed", "model crash")
    with patch("requests.get", return_value=mock_response):
        with pytest.raises(RuntimeError, match="failed"):
            poll_mineru_batch_result("batch-1", "tok", poll_interval=0)


def test_poll_batch_error_state_raises():
    from pdf_parser.parsers.mineru_api_adapter import poll_mineru_batch_result
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = _batch_poll_state_response("error", "internal error")
    with patch("requests.get", return_value=mock_response):
        with pytest.raises(RuntimeError, match="batch_id=batch-1 failed"):
            poll_mineru_batch_result("batch-1", "tok", poll_interval=0)


def test_poll_batch_timeout_raises():
    from pdf_parser.parsers.mineru_api_adapter import poll_mineru_batch_result
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = _batch_poll_state_response("running")
    with patch("requests.get", return_value=mock_response):
        with pytest.raises(RuntimeError, match="timed out"):
            poll_mineru_batch_result("batch-1", "tok", poll_interval=0, timeout=0.001)


def test_poll_batch_waiting_then_running_then_done():
    from pdf_parser.parsers.mineru_api_adapter import poll_mineru_batch_result
    responses = [
        MagicMock(status_code=200, json=MagicMock(return_value=_batch_poll_state_response("waiting-file"))),
        MagicMock(status_code=200, json=MagicMock(return_value=_batch_poll_state_response("running"))),
        MagicMock(status_code=200, json=MagicMock(return_value=_batch_poll_done_response(
            zip_url="https://cdn.example.com/r.zip"
        ))),
    ]
    with patch("requests.get", side_effect=responses):
        zip_url = poll_mineru_batch_result("batch-1", "tok", poll_interval=0)
    assert zip_url == "https://cdn.example.com/r.zip"


def test_poll_batch_http_error_raises():
    from pdf_parser.parsers.mineru_api_adapter import poll_mineru_batch_result
    mock_response = MagicMock()
    mock_response.status_code = 500
    with patch("requests.get", return_value=mock_response):
        with pytest.raises(RuntimeError, match="500"):
            poll_mineru_batch_result("batch-1", "tok", poll_interval=0)


def test_poll_batch_uses_authorization_header():
    from pdf_parser.parsers.mineru_api_adapter import poll_mineru_batch_result
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = _batch_poll_done_response()
    with patch("requests.get", return_value=mock_response) as mock_get:
        poll_mineru_batch_result("batch-1", "secret-token", poll_interval=0)
    headers = mock_get.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer secret-token"


def test_poll_batch_missing_full_zip_url_raises():
    from pdf_parser.parsers.mineru_api_adapter import poll_mineru_batch_result
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "code": 0,
        "data": {
            "extract_result": [{"file_name": "paper.pdf", "state": "done", "full_zip_url": ""}]
        },
    }
    with patch("requests.get", return_value=mock_response):
        with pytest.raises(RuntimeError, match="full_zip_url"):
            poll_mineru_batch_result("batch-1", "tok", poll_interval=0)


# ---------------------------------------------------------------------------
# ZIP extraction tests
# ---------------------------------------------------------------------------

def test_extract_mineru_zip(tmp_path):
    from pdf_parser.parsers.mineru_api_adapter import extract_mineru_zip
    zip_path = _make_zip_with_content_list(tmp_path, _SIMPLE_CONTENT_LIST)
    out = tmp_path / "out"
    extract_mineru_zip(zip_path, out)
    assert (out / "paper_content_list.json").exists()


def test_extract_unsafe_zip_raises(tmp_path):
    from pdf_parser.parsers.mineru_api_adapter import extract_mineru_zip
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../evil.txt", "evil content")
    with pytest.raises(RuntimeError, match="unsafe"):
        extract_mineru_zip(zip_path, tmp_path / "out")


# ---------------------------------------------------------------------------
# parse_mineru_output_to_candidate — content_list.json path
# ---------------------------------------------------------------------------

@pytest.fixture
def content_list_candidate(tmp_path):
    cl_file = tmp_path / "paper_content_list.json"
    cl_file.write_text(json.dumps(_SIMPLE_CONTENT_LIST), encoding="utf-8")
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    from pdf_parser.parsers.mineru_api_adapter import parse_mineru_output_to_candidate
    return parse_mineru_output_to_candidate(tmp_path, input_pdf_path=pdf)


def test_content_list_returns_parsed_candidate(content_list_candidate):
    from pdf_parser.schema.candidate import ParsedCandidate
    assert isinstance(content_list_candidate, ParsedCandidate)


def test_content_list_parser_name(content_list_candidate):
    assert content_list_candidate.provenance.parser_name == "mineru_api"


def test_content_list_input_sha256_set(content_list_candidate):
    h = content_list_candidate.provenance.input_sha256
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_content_list_output_sha256_not_placeholder(content_list_candidate):
    assert content_list_candidate.provenance.output_sha256 != "0" * 64


def test_content_list_output_sha256_matches_recomputed(content_list_candidate):
    from pdf_parser.schema.hashes import compute_candidate_output_sha256
    assert content_list_candidate.provenance.output_sha256 == compute_candidate_output_sha256(content_list_candidate)


def test_content_list_sections_extracted(content_list_candidate):
    titles = [s.title for s in content_list_candidate.sections]
    assert "Introduction" in titles
    assert "Methods" in titles


def test_content_list_section_levels(content_list_candidate):
    intro = next(s for s in content_list_candidate.sections if s.title == "Introduction")
    assert intro.level == 1


def test_content_list_section_page_numbers(content_list_candidate):
    intro = next(s for s in content_list_candidate.sections if s.title == "Introduction")
    assert intro.start_page == 1  # page_idx=0 → 1-based=1
    methods = next(s for s in content_list_candidate.sections if s.title == "Methods")
    assert methods.start_page == 2  # page_idx=1 → 1-based=2


def test_content_list_blocks_extracted(content_list_candidate):
    assert len(content_list_candidate.blocks) >= 2


def test_content_list_section_has_block_ids(content_list_candidate):
    for sec in content_list_candidate.sections:
        assert len(sec.block_ids) >= 1


def test_content_list_source_parser(content_list_candidate):
    for blk in content_list_candidate.blocks:
        assert blk.source_parser == "mineru_api"


# ---------------------------------------------------------------------------
# parse_mineru_output_to_candidate — image, table, caption, equation
# ---------------------------------------------------------------------------

def test_content_list_figures_extracted(tmp_path):
    cl_file = tmp_path / "doc_content_list.json"
    cl_file.write_text(json.dumps(_CONTENT_LIST_WITH_ASSETS), encoding="utf-8")
    from pdf_parser.parsers.mineru_api_adapter import parse_mineru_output_to_candidate
    candidate = parse_mineru_output_to_candidate(tmp_path)
    assert len(candidate.figures) == 1
    assert candidate.figures[0].source_parser == "mineru_api"


def test_content_list_tables_extracted(tmp_path):
    cl_file = tmp_path / "doc_content_list.json"
    cl_file.write_text(json.dumps(_CONTENT_LIST_WITH_ASSETS), encoding="utf-8")
    from pdf_parser.parsers.mineru_api_adapter import parse_mineru_output_to_candidate
    candidate = parse_mineru_output_to_candidate(tmp_path)
    assert len(candidate.tables) == 1
    assert candidate.tables[0].source_parser == "mineru_api"


def test_content_list_captions_extracted(tmp_path):
    cl_file = tmp_path / "doc_content_list.json"
    cl_file.write_text(json.dumps(_CONTENT_LIST_WITH_ASSETS), encoding="utf-8")
    from pdf_parser.parsers.mineru_api_adapter import parse_mineru_output_to_candidate
    candidate = parse_mineru_output_to_candidate(tmp_path)
    assert len(candidate.captions) == 2
    texts = [c.text for c in candidate.captions]
    assert any("Figure 1" in t for t in texts)
    assert any("Table 1" in t for t in texts)


# ---------------------------------------------------------------------------
# parse_mineru_output_to_candidate — Markdown fallback
# ---------------------------------------------------------------------------

def test_markdown_fallback_used_when_no_content_list(tmp_path):
    md_file = tmp_path / "paper.md"
    md_file.write_text(_SIMPLE_MD, encoding="utf-8")
    from pdf_parser.parsers.mineru_api_adapter import parse_mineru_output_to_candidate
    candidate = parse_mineru_output_to_candidate(tmp_path)
    titles = [s.title for s in candidate.sections]
    assert "Introduction" in titles
    assert "Methods" in titles


def test_no_output_files_raises(tmp_path):
    from pdf_parser.parsers.mineru_api_adapter import parse_mineru_output_to_candidate
    with pytest.raises(FileNotFoundError, match="No MinerU output"):
        parse_mineru_output_to_candidate(tmp_path)


# ---------------------------------------------------------------------------
# Section hierarchy in content_list
# ---------------------------------------------------------------------------

def test_subsection_parent_id(tmp_path):
    items = [
        {"type": "text", "text": "Top", "text_level": 1, "page_idx": 0},
        {"type": "text", "text": "Sub", "text_level": 2, "page_idx": 0},
    ]
    cl_file = tmp_path / "doc_content_list.json"
    cl_file.write_text(json.dumps(items), encoding="utf-8")
    from pdf_parser.parsers.mineru_api_adapter import parse_mineru_output_to_candidate
    candidate = parse_mineru_output_to_candidate(tmp_path)
    top = next(s for s in candidate.sections if s.title == "Top")
    sub = next(s for s in candidate.sections if s.title == "Sub")
    assert sub.parent_section_id == top.section_id


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

def test_cli_mineru_parse_writes_pretty_json(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    work = tmp_path / "work"
    out = tmp_path / "out.json"

    cl_items = _SIMPLE_CONTENT_LIST
    extract_dir = work / "paper"
    extract_dir.mkdir(parents=True)
    (extract_dir / "paper_content_list.json").write_text(
        json.dumps(cl_items), encoding="utf-8"
    )
    zip_path = work / "paper.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(extract_dir / "paper_content_list.json", arcname="paper_content_list.json")

    def fake_parse(pdf_path, work_dir, token=None, base_url=None):
        from pdf_parser.parsers.mineru_api_adapter import parse_mineru_output_to_candidate
        return parse_mineru_output_to_candidate(extract_dir, input_pdf_path=pdf_path)

    with patch("pdf_parser.parsers.mineru_api_adapter.parse_pdf_with_mineru_api", side_effect=fake_parse):
        from pdf_parser.cli import main
        main(["mineru", "parse", "--pdf", str(pdf), "--work-dir", str(work), "--out", str(out)])

    assert out.exists()
    raw = out.read_text()
    assert "\n" in raw
    assert "  " in raw
    data = json.loads(raw)
    assert data["provenance"]["parser_name"] == "mineru_api"
