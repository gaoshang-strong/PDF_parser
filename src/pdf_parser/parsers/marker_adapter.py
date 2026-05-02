"""Marker adapter: convert a PDF via Marker to ParsedCandidate.

Marker is optional. If not installed, parse_pdf_with_marker raises ImportError.
Importing this module does not require Marker to be installed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

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

_PARSER_NAME = "marker"

# ---------------------------------------------------------------------------
# Optional Marker imports — kept in a try/except so the module can be loaded
# without Marker installed.
# ---------------------------------------------------------------------------

try:
    from marker.converters.pdf import PdfConverter as _PdfConverter
    from marker.models import create_model_dict as _create_model_dict
    _MARKER_AVAILABLE = True
except ImportError:
    _MARKER_AVAILABLE = False
    _PdfConverter = None  # type: ignore[assignment]
    _create_model_dict = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_marker_version() -> str:
    try:
        from importlib.metadata import version
        return version("marker-pdf")
    except Exception:
        return "unknown"


def _extract_pages(page_stats: list[dict]) -> list[ParsedPage]:
    """Build ParsedPage list from Marker page_stats (page_id is 0-based)."""
    pages = []
    for stat in page_stats:
        page_no = stat["page_id"] + 1  # convert to 1-based
        pages.append(ParsedPage(
            page_id=f"page_{page_no}",
            page_number=page_no,
        ))
    if not pages:
        pages = [ParsedPage(page_id="page_1", page_number=1)]
    return pages


def _build_section_page_map(toc: list) -> dict[str, int]:
    """Map lowercased section title -> 1-based page number from table_of_contents."""
    result: dict[str, int] = {}
    for item in toc:
        # item may be a TocItem Pydantic model or a plain dict (in tests)
        if hasattr(item, "title"):
            title = item.title.strip()
            page_no = item.page_id + 1
        else:
            title = item.get("title", "").strip()
            page_no = item.get("page_id", 0) + 1
        result[title.lower()] = page_no
    return result


def _parse_markdown(
    markdown: str,
    section_page_map: dict[str, int],
) -> tuple[
    list[ParsedBlock],
    list[ParsedSection],
    list[ParsedFigure],
    list[ParsedTable],
    list[ParsedCaption],
]:
    """Parse a Marker Markdown string into ParsedCandidate components.

    Page numbers come from section_page_map (built from TOC); blocks within a
    section inherit the section's start page.  No bounding boxes are available
    from Markdown output.
    """
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

        # ---- ATX heading ---------------------------------------------------
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

            page_no = section_page_map.get(title.lower(), current_page)
            current_page = page_no

            blk_n += 1
            block_id = f"blk_{blk_n}"
            blocks.append(ParsedBlock(
                block_id=block_id,
                page=page_no,
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
                start_page=page_no,
                end_page=page_no,
                source_parser=_PARSER_NAME,
            )
            sections.append(current_section)
            level_stack.append((level, current_section))
            current_body = []
            continue

        # ---- Markdown table row --------------------------------------------
        if stripped.startswith("|"):
            if not in_table:
                in_table = True
                table_lines = []
            table_lines.append(line)
            continue
        else:
            if in_table:
                _flush_table()

        # ---- Inline image reference ----------------------------------------
        if _IMAGE_RE.search(stripped):
            fig_n += 1
            figures.append(ParsedFigure(
                figure_id=f"fig_{fig_n}",
                page=current_page,
                source_parser=_PARSER_NAME,
            ))
            continue

        # ---- Paragraph text ------------------------------------------------
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_pdf_with_marker(pdf_path: Path) -> ParsedCandidate:
    """Parse a PDF with Marker and return a ParsedCandidate.

    Raises FileNotFoundError if pdf_path does not exist.
    Raises ValueError if pdf_path does not have a .pdf suffix.
    Raises ImportError if Marker is not installed.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(
            f"Expected a .pdf file (got '{pdf_path.suffix}'): {pdf_path}"
        )

    if not _MARKER_AVAILABLE:
        raise ImportError(
            "Marker is not installed. "
            "Install it with: pip install marker-pdf"
        )

    artifact_dict = _create_model_dict()
    converter = _PdfConverter(artifact_dict=artifact_dict)
    rendered = converter(str(pdf_path))

    metadata = rendered.metadata
    page_stats = metadata.get("page_stats", [])
    toc = metadata.get("table_of_contents") or []

    pages = _extract_pages(page_stats)
    section_page_map = _build_section_page_map(toc)
    blocks, sections, figures, tables, captions = _parse_markdown(
        rendered.markdown, section_page_map
    )

    candidate = ParsedCandidate(
        provenance=ParserProvenance(
            parser_name=_PARSER_NAME,
            parser_version=_get_marker_version(),
            input_sha256=sha256_file(pdf_path),
            output_sha256="0" * 64,
        ),
        pages=pages,
        blocks=blocks,
        sections=sections,
        figures=figures,
        tables=tables,
        captions=captions,
        diagnostics=CandidateDiagnostics(),
    )
    candidate.provenance.output_sha256 = compute_candidate_output_sha256(candidate)
    return candidate
