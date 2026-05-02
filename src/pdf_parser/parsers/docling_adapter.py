"""Docling adapter: convert a PDF via Docling to ParsedCandidate.

Docling is optional. If not installed, parse_pdf_with_docling raises ImportError.
Importing this module does not require Docling to be installed.
"""

from __future__ import annotations

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

_PARSER_NAME = "docling"

# ---------------------------------------------------------------------------
# Optional Docling imports — kept in a try/except so the module can be loaded
# without Docling installed.  All private names are set to None on failure.
# ---------------------------------------------------------------------------

try:
    from docling.document_converter import DocumentConverter as _DocumentConverter
    from docling.datamodel.base_models import ConversionStatus as _ConversionStatus
    from docling_core.types.doc import (
        DocItemLabel as _DocItemLabel,
        PictureItem as _PictureItem,
        SectionHeaderItem as _SectionHeaderItem,
        TableItem as _TableItem,
    )
    _DOCLING_AVAILABLE = True
except ImportError:
    _DOCLING_AVAILABLE = False
    _DocumentConverter = None  # type: ignore[assignment]
    _ConversionStatus = None  # type: ignore[assignment]
    _DocItemLabel = None  # type: ignore[assignment]
    _SectionHeaderItem = None  # type: ignore[assignment]
    _PictureItem = None  # type: ignore[assignment]
    _TableItem = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_docling_version() -> str:
    try:
        from importlib.metadata import version
        return version("docling")
    except Exception:
        return "unknown"


def _get_page_no(item) -> int:
    """Return 1-based page number from item provenance, defaulting to 1."""
    if item.prov:
        return item.prov[0].page_no
    return 1


def _get_bbox(item) -> Optional[list[float]]:
    if item.prov:
        bb = item.prov[0].bbox
        return [float(bb.l), float(bb.t), float(bb.r), float(bb.b)]
    return None


def _extract_pages(doc) -> list[ParsedPage]:
    if doc.pages:
        return [
            ParsedPage(
                page_id=f"page_{page_no}",
                page_number=page_no,
                width=float(page_item.size.width) if page_item.size else None,
                height=float(page_item.size.height) if page_item.size else None,
            )
            for page_no, page_item in sorted(doc.pages.items())
        ]
    # Docling returns no page metadata for programmatically constructed docs
    return [ParsedPage(page_id="page_1", page_number=1)]


def _process_items(doc) -> tuple[
    list[ParsedBlock],
    list[ParsedSection],
    list[ParsedFigure],
    list[ParsedTable],
    list[ParsedCaption],
]:
    """Walk a DoclingDocument and convert items to ParsedCandidate components."""
    blocks: list[ParsedBlock] = []
    sections: list[ParsedSection] = []
    figures: list[ParsedFigure] = []
    tables: list[ParsedTable] = []
    captions: list[ParsedCaption] = []

    current_section: Optional[ParsedSection] = None
    current_body: list[ParsedBlock] = []
    preamble: list[ParsedBlock] = []
    level_stack: list[tuple[int, ParsedSection]] = []

    blk_n = fig_n = tbl_n = cap_n = 0

    _TEXT_LABELS = {
        _DocItemLabel.TEXT,
        _DocItemLabel.LIST_ITEM,
        _DocItemLabel.FORMULA,
        _DocItemLabel.CODE,
        _DocItemLabel.FOOTNOTE,
    }
    _SKIP_LABELS = {_DocItemLabel.PAGE_HEADER, _DocItemLabel.PAGE_FOOTER}

    def _finalize() -> None:
        if current_section is not None:
            current_section.text = "\n\n".join(b.text for b in current_body) or None

    for item, _depth in doc.iterate_items():
        label = item.label
        if label in _SKIP_LABELS:
            continue

        page_no = _get_page_no(item)
        bbox = _get_bbox(item)

        # ---- Section header ------------------------------------------------
        if label == _DocItemLabel.SECTION_HEADER:
            _finalize()
            heading_level = int(getattr(item, "level", 1) or 1)

            while level_stack and level_stack[-1][0] >= heading_level:
                level_stack.pop()
            parent_id = level_stack[-1][1].section_id if level_stack else None

            blk_n += 1
            block_id = f"blk_{blk_n}"
            blocks.append(
                ParsedBlock(
                    block_id=block_id,
                    page=page_no,
                    text=item.text,
                    bbox=bbox,
                    block_type="heading",
                    reading_order=blk_n,
                    source_parser=_PARSER_NAME,
                )
            )
            title = item.text.strip()
            sec_id = f"sec_{len(sections) + 1}"
            current_section = ParsedSection(
                section_id=sec_id,
                title=title,
                normalized_title=title.lower(),
                level=heading_level,
                parent_section_id=parent_id,
                block_ids=[block_id],
                start_page=page_no,
                end_page=page_no,
                source_parser=_PARSER_NAME,
            )
            sections.append(current_section)
            level_stack.append((heading_level, current_section))
            current_body = []

        # ---- Document title ------------------------------------------------
        elif label == _DocItemLabel.TITLE:
            blk_n += 1
            block_id = f"blk_{blk_n}"
            blocks.append(
                ParsedBlock(
                    block_id=block_id,
                    page=page_no,
                    text=item.text,
                    bbox=bbox,
                    block_type="heading",
                    reading_order=blk_n,
                    source_parser=_PARSER_NAME,
                )
            )

        # ---- Body text -----------------------------------------------------
        elif label in _TEXT_LABELS:
            text = item.text.strip() if hasattr(item, "text") else ""
            if not text:
                continue
            blk_n += 1
            block_id = f"blk_{blk_n}"
            blk = ParsedBlock(
                block_id=block_id,
                page=page_no,
                text=item.text,
                bbox=bbox,
                block_type="text",
                reading_order=blk_n,
                source_parser=_PARSER_NAME,
            )
            blocks.append(blk)
            if current_section is not None:
                current_section.block_ids.append(block_id)
                current_section.end_page = page_no
                current_body.append(blk)
            else:
                preamble.append(blk)

        # ---- Figures -------------------------------------------------------
        elif label == _DocItemLabel.PICTURE:
            fig_n += 1
            figures.append(
                ParsedFigure(
                    figure_id=f"fig_{fig_n}",
                    page=page_no,
                    bbox=bbox,
                    source_parser=_PARSER_NAME,
                )
            )

        # ---- Tables --------------------------------------------------------
        elif label == _DocItemLabel.TABLE:
            tbl_n += 1
            tables.append(
                ParsedTable(
                    table_id=f"tbl_{tbl_n}",
                    page=page_no,
                    bbox=bbox,
                    source_parser=_PARSER_NAME,
                )
            )

        # ---- Captions ------------------------------------------------------
        elif label == _DocItemLabel.CAPTION:
            text = getattr(item, "text", "").strip()
            if text:
                cap_n += 1
                captions.append(
                    ParsedCaption(
                        caption_id=f"cap_{cap_n}",
                        text=item.text,
                        page=page_no,
                        bbox=bbox,
                        source_parser=_PARSER_NAME,
                    )
                )

    _finalize()

    # Wrap pre-heading content if there are no sections
    if preamble and not sections:
        sections.append(
            ParsedSection(
                section_id="sec_1",
                title="",
                normalized_title="",
                level=1,
                block_ids=[b.block_id for b in preamble],
                text="\n\n".join(b.text for b in preamble) or None,
                start_page=preamble[0].page,
                end_page=preamble[-1].page,
                source_parser=_PARSER_NAME,
            )
        )

    return blocks, sections, figures, tables, captions


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_pdf_with_docling(pdf_path: Path) -> ParsedCandidate:
    """Parse a PDF with Docling and return a ParsedCandidate.

    Raises FileNotFoundError if pdf_path does not exist.
    Raises ValueError if pdf_path does not have a .pdf suffix.
    Raises ImportError if Docling is not installed.
    Raises RuntimeError if Docling conversion fails.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(
            f"Expected a .pdf file (got '{pdf_path.suffix}'): {pdf_path}"
        )

    if not _DOCLING_AVAILABLE:
        raise ImportError(
            "Docling is not installed. "
            "Install it with: pip install docling"
        )

    result = _DocumentConverter().convert(str(pdf_path))

    if result.status not in (
        _ConversionStatus.SUCCESS,
        _ConversionStatus.PARTIAL_SUCCESS,
    ):
        raise RuntimeError(
            f"Docling conversion failed with status: {result.status}. "
            f"Errors: {getattr(result, 'errors', [])}"
        )

    doc = result.document
    pages = _extract_pages(doc)
    blocks, sections, figures, tables, captions = _process_items(doc)

    warnings: list[str] = []
    if result.status == _ConversionStatus.PARTIAL_SUCCESS:
        warnings.append(f"Docling returned PARTIAL_SUCCESS for {pdf_path.name}")

    candidate = ParsedCandidate(
        provenance=ParserProvenance(
            parser_name=_PARSER_NAME,
            parser_version=_get_docling_version(),
            input_sha256=sha256_file(pdf_path),
            output_sha256="0" * 64,
        ),
        pages=pages,
        blocks=blocks,
        sections=sections,
        figures=figures,
        tables=tables,
        captions=captions,
        diagnostics=CandidateDiagnostics(warnings=warnings),
    )
    candidate.provenance.output_sha256 = compute_candidate_output_sha256(candidate)
    return candidate
