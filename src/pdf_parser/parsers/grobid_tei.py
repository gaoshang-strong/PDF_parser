"""Adapter: convert a GROBID TEI XML file into a ParsedCandidate."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from pdf_parser.schema.candidate import (
    ArticleMetadata,
    CandidateDiagnostics,
    ParsedCandidate,
    ParsedSection,
    ParserProvenance,
)
from pdf_parser.schema.hashes import compute_candidate_output_sha256, sha256_file

_TEI_NS = "http://www.tei-c.org/ns/1.0"
_NS = {"tei": _TEI_NS}
_PARSER_NAME = "grobid_tei"


def _element_text(elem: ET.Element) -> str:
    """Collapse all text content of an element (including descendants) to one line."""
    return " ".join("".join(elem.itertext()).split())


def _extract_grobid_version(root: ET.Element) -> str:
    app = root.find(".//tei:appInfo/tei:application", _NS)
    if app is not None:
        version = app.get("version")
        if version:
            return version
    return "unknown"


def _extract_metadata(root: ET.Element) -> ArticleMetadata:
    # Title: prefer analytic title, fall back to titleStmt
    title: Optional[str] = None
    analytic = root.find(".//tei:sourceDesc/tei:biblStruct/tei:analytic", _NS)
    if analytic is not None:
        title_elem = analytic.find("tei:title[@type='main']", _NS)
        if title_elem is None:
            title_elem = analytic.find("tei:title", _NS)
        if title_elem is not None:
            title = _element_text(title_elem) or None
    if title is None:
        title_stmt_elem = root.find(".//tei:titleStmt/tei:title", _NS)
        if title_stmt_elem is not None:
            title = _element_text(title_stmt_elem) or None

    # DOI
    doi: Optional[str] = None
    doi_elem = root.find(".//tei:idno[@type='DOI']", _NS)
    if doi_elem is not None:
        doi = _element_text(doi_elem) or None

    # Journal
    journal: Optional[str] = None
    journal_elem = root.find(".//tei:monogr/tei:title[@level='j']", _NS)
    if journal_elem is not None:
        journal = _element_text(journal_elem) or None

    # Year — from the first "published" date's `when` attribute
    year: Optional[str] = None
    date_elem = root.find(".//tei:imprint/tei:date[@type='published']", _NS)
    if date_elem is not None:
        when = date_elem.get("when", "")
        year = when[:4] if len(when) >= 4 else None

    # Authors
    authors: list[str] = []
    for author in root.findall(".//tei:analytic/tei:author", _NS):
        persname = author.find("tei:persName", _NS)
        if persname is None:
            continue
        forename_elem = persname.find("tei:forename", _NS)
        surname_elem = persname.find("tei:surname", _NS)
        parts = [
            _element_text(e)
            for e in (forename_elem, surname_elem)
            if e is not None
        ]
        name = " ".join(p for p in parts if p)
        if name:
            authors.append(name)

    return ArticleMetadata(title=title, doi=doi, journal=journal, year=year, authors=authors)


def _extract_div(
    div: ET.Element,
    sections: list[ParsedSection],
    counter: list[int],
    parent_id: Optional[str],
    level: int,
) -> None:
    head = div.find("tei:head", _NS)
    title = _element_text(head) if head is not None else ""

    counter[0] += 1
    section_id = f"sec_{counter[0]}"

    # Collect text from direct <p> children only; nested divs are handled recursively
    paragraphs = [_element_text(p) for p in div.findall("tei:p", _NS)]
    text = "\n\n".join(p for p in paragraphs if p) or None

    sections.append(
        ParsedSection(
            section_id=section_id,
            title=title,
            normalized_title=title.lower().strip() if title else None,
            level=level,
            parent_section_id=parent_id,
            text=text,
            source_parser=_PARSER_NAME,
        )
    )

    for child_div in div.findall("tei:div", _NS):
        _extract_div(child_div, sections, counter, parent_id=section_id, level=level + 1)


def _extract_sections(root: ET.Element) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    counter = [0]

    # Abstract (profileDesc → abstract → p)
    abstract_elem = root.find(".//tei:profileDesc/tei:abstract", _NS)
    if abstract_elem is not None:
        paragraphs = [_element_text(p) for p in abstract_elem.findall(".//tei:p", _NS)]
        text = "\n\n".join(p for p in paragraphs if p) or None
        if text:
            counter[0] += 1
            sections.append(
                ParsedSection(
                    section_id=f"sec_{counter[0]}",
                    title="Abstract",
                    normalized_title="abstract",
                    level=1,
                    text=text,
                    source_parser=_PARSER_NAME,
                )
            )

    # Body divs
    body = root.find(".//tei:text/tei:body", _NS)
    if body is not None:
        for div in body.findall("tei:div", _NS):
            _extract_div(div, sections, counter, parent_id=None, level=1)

    return sections


def _count_references(root: ET.Element) -> int:
    return len(root.findall(".//tei:listBibl/tei:biblStruct", _NS))


def parse_grobid_tei_to_candidate(
    tei_path: Path,
    input_pdf_path: Optional[Path] = None,
) -> ParsedCandidate:
    """Parse a GROBID TEI XML file into a ParsedCandidate.

    Raises FileNotFoundError if tei_path does not exist.
    Raises ValueError if tei_path does not have a .xml suffix.
    Raises xml.etree.ElementTree.ParseError if the file is not valid XML.
    If input_pdf_path is provided, its SHA-256 is used as input_sha256;
    otherwise the TEI file itself is hashed.
    """
    tei_path = Path(tei_path)
    if not tei_path.exists():
        raise FileNotFoundError(f"TEI file not found: {tei_path}")
    if tei_path.suffix.lower() != ".xml":
        raise ValueError(
            f"Expected a .xml file (got '{tei_path.suffix}'): {tei_path}"
        )

    # ParseError propagates naturally — it is a specific, actionable error
    tree = ET.parse(tei_path)
    root = tree.getroot()

    parser_version = _extract_grobid_version(root)
    metadata = _extract_metadata(root)
    sections = _extract_sections(root)
    ref_count = _count_references(root)

    if input_pdf_path is not None:
        input_pdf_path = Path(input_pdf_path)
        if not input_pdf_path.exists():
            raise FileNotFoundError(f"Input PDF not found: {input_pdf_path}")
        input_sha256 = sha256_file(input_pdf_path)
    else:
        input_sha256 = sha256_file(tei_path)

    candidate = ParsedCandidate(
        provenance=ParserProvenance(
            parser_name=_PARSER_NAME,
            parser_version=parser_version,
            input_sha256=input_sha256,
            output_sha256="0" * 64,  # placeholder; replaced below after content is fixed
        ),
        metadata=metadata,
        sections=sections,
        diagnostics=CandidateDiagnostics(
            notes=(
                f"Extracted {ref_count} references from TEI bibliography."
                if ref_count
                else None
            ),
        ),
    )

    candidate.provenance.output_sha256 = compute_candidate_output_sha256(candidate)
    return candidate
