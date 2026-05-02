"""MinerU API adapter: submit a PDF to the MinerU cloud API and convert the
result into a ParsedCandidate.

No local MinerU or ML packages are required.  Only `requests` is used.

Token is read from the MINERU_API_TOKEN environment variable.  It is never
written to logs, error messages, or JSON outputs.

Verified API workflow (mineru.net) — batch upload flow:
  1. POST  {base_url}/api/v4/file-urls/batch  →  put_url + batch_id
  2. PUT   {put_url}  (no Content-Type header) →  upload raw PDF bytes
  3. GET   {base_url}/api/v4/extract-results/batch/{batch_id}  →  poll per-file state
  4. On state="done": GET {full_zip_url}       →  download result ZIP
  5. Safe-extract ZIP into work_dir
  6. Read {stem}_content_list.json (preferred) or {stem}.md (fallback)
  7. Convert to ParsedCandidate

Notes:
- The batch PUT URL signature does NOT include Content-Type; sending any
  Content-Type header causes HTTP 403.
- The /api/v4/file + /api/v4/extract/task flow (older single-file API) is NOT
  used because MinerU's processing backend cannot access the resulting signed
  CDN download URL — it always fails with "failed to read file".
"""

from __future__ import annotations

import os
import re
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Optional

import requests

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
from pdf_parser.schema.hashes import compute_candidate_output_sha256, sha256_file

_PARSER_NAME = "mineru_api"
_DEFAULT_BASE_URL = "https://mineru.net"
_DEFAULT_MODEL_VERSION = "vlm"
_POLL_INTERVAL_SECONDS = 5.0
_POLL_TIMEOUT_SECONDS = 600.0


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------

def get_mineru_api_token() -> str:
    """Return the MinerU API token from MINERU_API_TOKEN.

    Raises RuntimeError if the variable is not set or empty.
    """
    token = os.environ.get("MINERU_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "MINERU_API_TOKEN environment variable is not set. "
            "Set it to your MinerU API token before calling this function."
        )
    return token


# ---------------------------------------------------------------------------
# Step 1: register file and get presigned upload URL via batch API
# ---------------------------------------------------------------------------

def request_mineru_batch_upload_url(
    pdf_name: str,
    token: str,
    base_url: str = _DEFAULT_BASE_URL,
    model_version: str = _DEFAULT_MODEL_VERSION,
) -> tuple[str, str]:
    """POST /api/v4/file-urls/batch to register a file and get (put_url, batch_id).

    put_url  — Alibaba OSS presigned URL to PUT the raw PDF bytes to (no CT header).
    batch_id — identifier used to poll /api/v4/extract-results/batch/{batch_id}.

    Raises RuntimeError on non-0 code or missing fields.
    Token is never included in exception messages.
    """
    endpoint = f"{base_url.rstrip('/')}/api/v4/file-urls/batch"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = requests.post(
        endpoint,
        json={
            "files": [{"name": pdf_name}],
            "model_version": model_version,
            "enable_formula": True,
            "enable_table": True,
        },
        headers=headers,
        timeout=30,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"MinerU batch upload URL request failed: HTTP {response.status_code} "
            f"from {endpoint}"
        )

    data = response.json()
    code = data.get("code")
    if code != 0:
        raise RuntimeError(
            f"MinerU batch upload URL request returned code={code}: "
            f"{data.get('msg', 'unknown error')}"
        )

    inner = data.get("data", {})
    batch_id = inner.get("batch_id")
    file_urls = inner.get("file_urls", [])

    if not batch_id:
        raise RuntimeError("MinerU batch upload URL response missing batch_id")
    if not file_urls:
        raise RuntimeError("MinerU batch upload URL response missing file_urls")

    put_url = file_urls[0]
    if not put_url:
        raise RuntimeError("MinerU batch upload URL response has empty file_urls[0]")

    return str(put_url), str(batch_id)


# ---------------------------------------------------------------------------
# Step 2: upload PDF to presigned URL
# ---------------------------------------------------------------------------

def upload_pdf_to_mineru_upload_url(pdf_path: Path, put_url: str) -> None:
    """PUT the raw PDF bytes to the Alibaba OSS presigned URL.

    The batch PUT URL signature does NOT include Content-Type, so no
    Content-Type header must be sent — adding one causes HTTP 403.

    Reads the file into memory so that requests sets Content-Length correctly.

    Raises RuntimeError if the upload fails.
    """
    pdf_bytes = Path(pdf_path).read_bytes()
    response = requests.put(
        put_url,
        data=pdf_bytes,
        timeout=120,
    )
    if response.status_code not in (200, 204):
        raise RuntimeError(
            f"PDF upload to presigned URL failed: HTTP {response.status_code}"
        )


# ---------------------------------------------------------------------------
# Step 3: poll batch result until done or failed
# ---------------------------------------------------------------------------

def poll_mineru_batch_result(
    batch_id: str,
    token: str,
    base_url: str = _DEFAULT_BASE_URL,
    poll_interval: float = _POLL_INTERVAL_SECONDS,
    timeout: float = _POLL_TIMEOUT_SECONDS,
) -> str:
    """Poll GET /api/v4/extract-results/batch/{batch_id} until the first file is done.

    Returns the full_zip_url for the first file in the batch on success.
    Raises RuntimeError on failure or timeout.
    Token is never included in exception messages.
    """
    endpoint = f"{base_url.rstrip('/')}/api/v4/extract-results/batch/{batch_id}"
    headers = {"Authorization": f"Bearer {token}"}
    deadline = time.monotonic() + timeout
    last_state = ""

    while time.monotonic() < deadline:
        response = requests.get(endpoint, headers=headers, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(
                f"MinerU batch result check failed: HTTP {response.status_code} "
                f"for batch_id={batch_id}"
            )

        data = response.json()
        results = data.get("data", {}).get("extract_result", [])
        if not results:
            time.sleep(poll_interval)
            continue

        file_result = results[0]
        state = file_result.get("state", "")

        if state != last_state:
            print(f"[mineru] batch_id={batch_id} state={state!r}")
            last_state = state

        if state == "done":
            zip_url = file_result.get("full_zip_url", "")
            if not zip_url:
                raise RuntimeError(
                    f"MinerU batch_id={batch_id} completed but full_zip_url is missing"
                )
            return str(zip_url)

        if state in ("failed", "error"):
            err = file_result.get("err_msg") or file_result.get("message") or "unknown error"
            raise RuntimeError(
                f"MinerU batch_id={batch_id} failed: {err}"
            )

        time.sleep(poll_interval)

    raise RuntimeError(
        f"MinerU batch_id={batch_id} timed out after {timeout:.0f}s"
    )


# ---------------------------------------------------------------------------
# Step 4: download result ZIP
# ---------------------------------------------------------------------------

def download_mineru_result_zip(zip_url: str, dest_path: Path) -> None:
    """Stream the result ZIP from the CDN URL (no auth needed) to dest_path.

    Raises RuntimeError on non-200 response or wrong content-type.
    """
    with requests.get(zip_url, stream=True, timeout=120) as response:
        if response.status_code != 200:
            raise RuntimeError(
                f"MinerU result ZIP download failed: HTTP {response.status_code}"
            )
        content_type = response.headers.get("content-type", "")
        if "zip" not in content_type and "octet-stream" not in content_type:
            raise RuntimeError(
                f"Expected ZIP from MinerU result URL, "
                f"got content-type={content_type!r}"
            )
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as fh:
            for chunk in response.iter_content(chunk_size=65536):
                fh.write(chunk)


# ---------------------------------------------------------------------------
# Step 5: safe-extract ZIP
# ---------------------------------------------------------------------------

def extract_mineru_zip(zip_path: Path, output_dir: Path) -> None:
    """Extract zip_path into output_dir, refusing path-traversal entries."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_root = output_dir.resolve()

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            member_path = PurePosixPath(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise RuntimeError(
                    f"Refusing unsafe ZIP entry: {member.filename}"
                )
            target = (output_root / Path(*member_path.parts)).resolve()
            if target != output_root and output_root not in target.parents:
                raise RuntimeError(
                    f"Refusing unsafe ZIP entry: {member.filename}"
                )
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                dst.write(src.read())


# ---------------------------------------------------------------------------
# Step 6+7: convert MinerU output to ParsedCandidate
# ---------------------------------------------------------------------------

def _locate_output_files(output_dir: Path) -> tuple[Optional[Path], Optional[Path]]:
    """Return (content_list_path, markdown_path) searching output_dir recursively.

    content_list_v2 is preferred over content_list.
    """
    content_list: Optional[Path] = None
    markdown: Optional[Path] = None

    for p in sorted(output_dir.rglob("*_content_list_v2.json")):
        content_list = p
        break
    if content_list is None:
        for p in sorted(output_dir.rglob("*_content_list.json")):
            content_list = p
            break

    for p in sorted(output_dir.rglob("*.md")):
        markdown = p
        break

    return content_list, markdown


def _parse_content_list(items: list[dict]) -> tuple[
    list[ParsedBlock],
    list[ParsedSection],
    list[ParsedFigure],
    list[ParsedTable],
    list[ParsedCaption],
]:
    blocks: list[ParsedBlock] = []
    sections: list[ParsedSection] = []
    figures: list[ParsedFigure] = []
    tables: list[ParsedTable] = []
    captions: list[ParsedCaption] = []

    blk_n = fig_n = tbl_n = cap_n = 0
    current_section: Optional[ParsedSection] = None
    current_body: list[ParsedBlock] = []
    level_stack: list[tuple[int, ParsedSection]] = []

    def _finalize_section() -> None:
        if current_section is not None:
            current_section.text = "\n\n".join(b.text for b in current_body) or None

    for item in items:
        item_type = item.get("type", "")
        text = (item.get("text") or "").strip()
        page_no = int(item.get("page_idx", 0)) + 1  # 0-based → 1-based

        text_level = item.get("text_level")
        if item_type in ("text", "title") and text_level and text:
            level = int(text_level)
            _finalize_section()

            while level_stack and level_stack[-1][0] >= level:
                level_stack.pop()
            parent_id = level_stack[-1][1].section_id if level_stack else None

            blk_n += 1
            block_id = f"blk_{blk_n}"
            blocks.append(ParsedBlock(
                block_id=block_id,
                page=page_no,
                text=text,
                block_type="heading",
                reading_order=blk_n,
                source_parser=_PARSER_NAME,
            ))

            sec_id = f"sec_{len(sections) + 1}"
            current_section = ParsedSection(
                section_id=sec_id,
                title=text,
                normalized_title=text.lower(),
                level=level,
                parent_section_id=parent_id,
                block_ids=[block_id],
                start_page=page_no,
                end_page=page_no,
                source_parser=_PARSER_NAME,
            )
            sections.append(current_section)
            level_stack.append((level, current_section))
            current_body = []

        elif item_type in ("text", "list") and text:
            blk_n += 1
            block_id = f"blk_{blk_n}"
            blk = ParsedBlock(
                block_id=block_id,
                page=page_no,
                text=text,
                block_type="text",
                reading_order=blk_n,
                source_parser=_PARSER_NAME,
            )
            blocks.append(blk)
            if current_section is not None:
                current_section.block_ids.append(block_id)
                current_section.end_page = page_no
                current_body.append(blk)

        elif item_type == "image":
            fig_n += 1
            figures.append(ParsedFigure(
                figure_id=f"fig_{fig_n}",
                page=page_no,
                source_parser=_PARSER_NAME,
            ))
            for cap_text in (item.get("img_caption") or []):
                if isinstance(cap_text, str) and cap_text.strip():
                    cap_n += 1
                    captions.append(ParsedCaption(
                        caption_id=f"cap_{cap_n}",
                        text=cap_text.strip(),
                        page=page_no,
                        source_parser=_PARSER_NAME,
                    ))

        elif item_type == "table":
            tbl_n += 1
            tables.append(ParsedTable(
                table_id=f"tbl_{tbl_n}",
                page=page_no,
                source_parser=_PARSER_NAME,
            ))
            for cap_text in (item.get("table_caption") or []):
                if isinstance(cap_text, str) and cap_text.strip():
                    cap_n += 1
                    captions.append(ParsedCaption(
                        caption_id=f"cap_{cap_n}",
                        text=cap_text.strip(),
                        page=page_no,
                        source_parser=_PARSER_NAME,
                    ))

        elif item_type == "equation" and text:
            blk_n += 1
            block_id = f"blk_{blk_n}"
            blk = ParsedBlock(
                block_id=block_id,
                page=page_no,
                text=text,
                block_type="text",
                reading_order=blk_n,
                source_parser=_PARSER_NAME,
            )
            blocks.append(blk)
            if current_section is not None:
                current_section.block_ids.append(block_id)
                current_section.end_page = page_no
                current_body.append(blk)

    _finalize_section()
    return blocks, sections, figures, tables, captions


def _parse_markdown_fallback(markdown: str) -> tuple[
    list[ParsedBlock],
    list[ParsedSection],
    list[ParsedFigure],
    list[ParsedTable],
    list[ParsedCaption],
]:
    """Minimal Markdown parser used when content_list.json is absent."""
    blocks: list[ParsedBlock] = []
    sections: list[ParsedSection] = []
    figures: list[ParsedFigure] = []
    tables: list[ParsedTable] = []
    captions: list[ParsedCaption] = []

    blk_n = fig_n = tbl_n = 0
    current_section: Optional[ParsedSection] = None
    current_body: list[ParsedBlock] = []
    current_page = 1
    level_stack: list[tuple[int, ParsedSection]] = []
    in_table = False
    table_lines: list[str] = []

    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)")
    _IMAGE_RE = re.compile(r"!\[.*?\]\(.*?\)")

    def _finalize_section() -> None:
        if current_section is not None:
            current_section.text = "\n\n".join(b.text for b in current_body) or None

    def _flush_table() -> None:
        nonlocal tbl_n, in_table, table_lines
        if table_lines:
            tbl_n += 1
            tables.append(ParsedTable(
                table_id=f"tbl_{tbl_n}",
                page=current_page,
                source_parser=_PARSER_NAME,
            ))
        table_lines = []
        in_table = False

    for line in markdown.splitlines():
        stripped = line.strip()

        m = _HEADING_RE.match(stripped)
        if m:
            if in_table:
                _flush_table()
            _finalize_section()
            level = len(m.group(1))
            title = m.group(2).strip()
            while level_stack and level_stack[-1][0] >= level:
                level_stack.pop()
            parent_id = level_stack[-1][1].section_id if level_stack else None
            blk_n += 1
            block_id = f"blk_{blk_n}"
            blocks.append(ParsedBlock(
                block_id=block_id,
                page=current_page,
                text=title,
                block_type="heading",
                reading_order=blk_n,
                source_parser=_PARSER_NAME,
            ))
            sec_id = f"sec_{len(sections) + 1}"
            current_section = ParsedSection(
                section_id=sec_id,
                title=title,
                normalized_title=title.lower(),
                level=level,
                parent_section_id=parent_id,
                block_ids=[block_id],
                start_page=current_page,
                end_page=current_page,
                source_parser=_PARSER_NAME,
            )
            sections.append(current_section)
            level_stack.append((level, current_section))
            current_body = []
            continue

        if stripped.startswith("|"):
            if not in_table:
                in_table = True
                table_lines = []
            table_lines.append(line)
            continue
        else:
            if in_table:
                _flush_table()

        if _IMAGE_RE.search(stripped):
            fig_n += 1
            figures.append(ParsedFigure(
                figure_id=f"fig_{fig_n}",
                page=current_page,
                source_parser=_PARSER_NAME,
            ))
            continue

        if stripped:
            blk_n += 1
            block_id = f"blk_{blk_n}"
            blk = ParsedBlock(
                block_id=block_id,
                page=current_page,
                text=stripped,
                block_type="text",
                reading_order=blk_n,
                source_parser=_PARSER_NAME,
            )
            blocks.append(blk)
            if current_section is not None:
                current_section.block_ids.append(block_id)
                current_section.end_page = current_page
                current_body.append(blk)

    if in_table:
        _flush_table()
    _finalize_section()
    return blocks, sections, figures, tables, captions


def parse_mineru_output_to_candidate(
    output_dir: Path,
    input_pdf_path: Optional[Path] = None,
) -> ParsedCandidate:
    """Convert a MinerU output directory to a ParsedCandidate.

    Prefers content_list.json over Markdown.
    input_pdf_path is used only to compute input_sha256.
    Raises FileNotFoundError if no usable output files are found.
    """
    import json as _json

    output_dir = Path(output_dir)
    content_list_path, markdown_path = _locate_output_files(output_dir)

    if content_list_path is None and markdown_path is None:
        raise FileNotFoundError(
            f"No MinerU output files found in {output_dir}. "
            "Expected *_content_list.json or *.md."
        )

    input_sha256 = sha256_file(input_pdf_path) if input_pdf_path else "0" * 64

    if content_list_path is not None:
        items = _json.loads(content_list_path.read_text(encoding="utf-8"))
        blocks, sections, figures, tables, captions = _parse_content_list(items)
    else:
        assert markdown_path is not None
        md_text = markdown_path.read_text(encoding="utf-8")
        blocks, sections, figures, tables, captions = _parse_markdown_fallback(md_text)

    candidate = ParsedCandidate(
        provenance=ParserProvenance(
            parser_name=_PARSER_NAME,
            parser_version="unknown",
            input_sha256=input_sha256,
            output_sha256="0" * 64,
        ),
        pages=[ParsedPage(page_id="page_1", page_number=1)],
        blocks=blocks,
        sections=sections,
        figures=figures,
        tables=tables,
        captions=captions,
        diagnostics=CandidateDiagnostics(),
    )
    candidate.provenance.output_sha256 = compute_candidate_output_sha256(candidate)
    return candidate


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------

def parse_pdf_with_mineru_api(
    pdf_path: Path,
    work_dir: Path,
    token: Optional[str] = None,
    base_url: str = _DEFAULT_BASE_URL,
    model_version: str = _DEFAULT_MODEL_VERSION,
) -> ParsedCandidate:
    """Parse a PDF via the MinerU cloud API and return a ParsedCandidate.

    Raises FileNotFoundError if pdf_path does not exist.
    Raises ValueError if pdf_path is not a .pdf file.
    Raises RuntimeError on API errors, task failure, timeout, or missing output.
    Token is read from MINERU_API_TOKEN if not passed explicitly.
    Token is never written to logs, error messages, or output JSON.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(
            f"Expected a .pdf file (got '{pdf_path.suffix}'): {pdf_path}"
        )

    if token is None:
        token = get_mineru_api_token()

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    pdf_name = pdf_path.name
    pdf_size = pdf_path.stat().st_size
    print(f"[mineru] Registering {pdf_name} ({pdf_size:,} bytes, model={model_version})...")
    put_url, batch_id = request_mineru_batch_upload_url(pdf_name, token, base_url, model_version)
    print(f"[mineru] Uploading to OSS (batch_id={batch_id})...")
    upload_pdf_to_mineru_upload_url(pdf_path, put_url)
    print(f"[mineru] Upload complete. Polling for extraction result...")
    zip_url = poll_mineru_batch_result(batch_id, token, base_url)
    print(f"[mineru] Extraction done. Downloading result ZIP...")

    zip_path = work_dir / f"{pdf_path.stem}.zip"
    download_mineru_result_zip(zip_url, zip_path)
    print(f"[mineru] ZIP downloaded ({zip_path.stat().st_size:,} bytes). Extracting...")

    extract_dir = work_dir / pdf_path.stem
    extract_mineru_zip(zip_path, extract_dir)
    print(f"[mineru] Extraction complete. Parsing output...")

    return parse_mineru_output_to_candidate(extract_dir, input_pdf_path=pdf_path)
