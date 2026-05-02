"""Native PyMuPDF adapter: extract pages, blocks, and sections from a PDF."""

from __future__ import annotations

import re
import statistics
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

from pdf_parser.schema.candidate import (
    CandidateDiagnostics,
    ParsedBlock,
    ParsedCandidate,
    ParsedFigure,
    ParsedPage,
    ParsedSection,
    ParserProvenance,
)
from pdf_parser.schema.hashes import compute_candidate_output_sha256, sha256_file

_PARSER_NAME = "pymupdf_native"
_HEADING_SIZE_RATIO = 1.10  # max span size / body median required to be a heading candidate
_MAX_HEADING_CHARS = 150
_MIN_HEADING_CHARS = 2

# Leading section numbers like "1", "1.1", "2.3.1"
_NUMBERED_HEADING_RE = re.compile(r"^(\d+)(\.\d+)*[\s\.\:\-]+")


# ---------------------------------------------------------------------------
# Low-level span / block helpers
# ---------------------------------------------------------------------------

def _span_is_bold(span: dict) -> bool:
    """Bold flag (bit 4) OR font name contains 'bold'."""
    return bool(span["flags"] & 16) or "bold" in span["font"].lower()


def _block_spans(block: dict) -> list[dict]:
    return [sp for ln in block.get("lines", []) for sp in ln.get("spans", [])]


def _block_text(block: dict) -> str:
    """Concatenate span texts within each line, join lines with newline."""
    parts = []
    for line in block.get("lines", []):
        line_text = "".join(sp["text"] for sp in line.get("spans", []))
        if line_text.strip():
            parts.append(line_text)
    return "\n".join(parts)


def _dominant_font_name(spans: list[dict]) -> Optional[str]:
    """Font name of the span contributing the most non-whitespace characters."""
    if not spans:
        return None
    best = max(spans, key=lambda sp: len(sp["text"].strip()))
    return best.get("font")


def _compute_body_median(doc: fitz.Document) -> float:
    """Compute the median font size of all non-empty text spans in the document."""
    sizes = [
        sp["size"]
        for page in doc
        for block in page.get_text("dict")["blocks"]
        if block.get("type") == 0
        for line in block.get("lines", [])
        for sp in line.get("spans", [])
        if sp["text"].strip()
    ]
    return statistics.median(sizes) if sizes else 10.0


# ---------------------------------------------------------------------------
# Heading detection
# ---------------------------------------------------------------------------

def _is_heading_candidate(text: str, max_size: float, body_median: float) -> bool:
    """Return True when a text block looks like a section heading."""
    text = text.strip()
    if len(text) < _MIN_HEADING_CHARS or len(text) > _MAX_HEADING_CHARS:
        return False
    # Skip URLs and DOIs
    if text.startswith("http") or "doi.org" in text.lower():
        return False
    # Skip bare numbers (page numbers, figure labels)
    if re.fullmatch(r"[\d\s\.\,]+", text):
        return False
    if body_median <= 0:
        return False
    return max_size / body_median >= _HEADING_SIZE_RATIO


def _heading_level(text: str) -> int:
    """Infer hierarchy level from leading numbering (1→L1, 1.1→L2, 1.1.1→L3)."""
    m = _NUMBERED_HEADING_RE.match(text.strip())
    if not m:
        return 1
    dots = m.group(0).count(".")
    return min(dots + 1, 3)


# ---------------------------------------------------------------------------
# Section builder
# ---------------------------------------------------------------------------

def _build_sections(blocks: list[ParsedBlock]) -> list[ParsedSection]:
    """Group blocks into sections; heading blocks start new sections."""
    sections: list[ParsedSection] = []
    counter = [0]
    level_stack: list[tuple[int, str]] = []  # (level, section_id)

    current_section: Optional[ParsedSection] = None
    current_body: list[ParsedBlock] = []
    preamble: list[ParsedBlock] = []

    def _finalize() -> None:
        if current_section is not None:
            current_section.text = "\n\n".join(b.text for b in current_body) or None

    for block in blocks:
        if block.block_type == "heading":
            _finalize()

            level = _heading_level(block.text)
            # Pop the stack to find the nearest ancestor at a higher level
            while level_stack and level_stack[-1][0] >= level:
                level_stack.pop()
            parent_id = level_stack[-1][1] if level_stack else None

            counter[0] += 1
            sec_id = f"sec_{counter[0]}"
            title = block.text.strip()

            current_section = ParsedSection(
                section_id=sec_id,
                title=title,
                normalized_title=title.lower(),
                level=level,
                parent_section_id=parent_id,
                block_ids=[block.block_id],
                start_page=block.page,
                end_page=block.page,
                source_parser=_PARSER_NAME,
            )
            sections.append(current_section)
            level_stack.append((level, sec_id))
            current_body = []

        else:
            if current_section is not None:
                current_section.block_ids.append(block.block_id)
                current_section.end_page = block.page
                current_body.append(block)
            else:
                preamble.append(block)

    _finalize()

    # If no headings were found, wrap all preamble into one anonymous section
    if preamble and not sections:
        counter[0] += 1
        sections.append(
            ParsedSection(
                section_id=f"sec_{counter[0]}",
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

    return sections


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_pdf_with_pymupdf(pdf_path: Path) -> ParsedCandidate:
    """Parse a PDF with native PyMuPDF and return a ParsedCandidate.

    Raises FileNotFoundError if pdf_path does not exist.
    Raises ValueError if pdf_path does not have a .pdf suffix.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(
            f"Expected a .pdf file (got '{pdf_path.suffix}'): {pdf_path}"
        )

    doc = fitz.open(str(pdf_path))
    body_median = _compute_body_median(doc)

    pages: list[ParsedPage] = []
    blocks: list[ParsedBlock] = []
    figures: list[ParsedFigure] = []

    reading_order = 0
    image_count = 0

    for page_idx, page in enumerate(doc):
        page_number = page_idx + 1
        rect = page.rect
        pages.append(
            ParsedPage(
                page_id=f"page_{page_number}",
                page_number=page_number,
                width=float(rect.width),
                height=float(rect.height),
            )
        )

        for raw_block in page.get_text("dict")["blocks"]:
            btype = raw_block.get("type", -1)
            bbox = [float(v) for v in raw_block["bbox"]]

            if btype == 1:  # image block
                image_count += 1
                figures.append(
                    ParsedFigure(
                        figure_id=f"fig_{image_count}",
                        page=page_number,
                        bbox=bbox,
                        source_parser=_PARSER_NAME,
                    )
                )
                continue

            if btype != 0:
                continue

            spans = _block_spans(raw_block)
            text = _block_text(raw_block)
            if not text.strip():
                continue

            non_empty_spans = [sp for sp in spans if sp["text"].strip()]
            max_size = max((sp["size"] for sp in non_empty_spans), default=0.0)
            total_chars = sum(len(sp["text"]) for sp in spans)
            bold_chars = sum(len(sp["text"]) for sp in spans if _span_is_bold(sp))
            is_bold = bold_chars > total_chars * 0.5 if total_chars else False

            is_heading = _is_heading_candidate(text, max_size, body_median)

            reading_order += 1
            blocks.append(
                ParsedBlock(
                    block_id=f"blk_{reading_order}",
                    page=page_number,
                    text=text,
                    bbox=bbox,
                    block_type="heading" if is_heading else "text",
                    reading_order=reading_order,
                    font_size=round(max_size, 3),
                    font_name=_dominant_font_name(non_empty_spans),
                    is_bold=is_bold,
                    source_parser=_PARSER_NAME,
                )
            )

    doc.close()

    sections = _build_sections(blocks)

    candidate = ParsedCandidate(
        provenance=ParserProvenance(
            parser_name=_PARSER_NAME,
            parser_version=fitz.__version__,
            input_sha256=sha256_file(pdf_path),
            output_sha256="0" * 64,
        ),
        pages=pages,
        blocks=blocks,
        sections=sections,
        figures=figures,
        diagnostics=CandidateDiagnostics(
            notes=(
                f"body_median_font_size={body_median:.3f}; "
                f"image_blocks={image_count}"
            )
        ),
    )
    candidate.provenance.output_sha256 = compute_candidate_output_sha256(candidate)
    return candidate
