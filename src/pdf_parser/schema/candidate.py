"""Core Pydantic schema models for parsed PDF candidates."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class ParserProvenance(BaseModel):
    parser_name: str
    parser_version: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    input_sha256: str
    output_sha256: str


class ParsedPage(BaseModel):
    page_id: str
    page_number: int  # 1-based
    width: Optional[float] = None
    height: Optional[float] = None


class ParsedBlock(BaseModel):
    block_id: str
    page: int  # 1-based page number
    text: str
    bbox: Optional[list[float]] = None  # [x0, y0, x1, y1]
    block_type: str = "text"
    reading_order: Optional[int] = None
    font_size: Optional[float] = None
    font_name: Optional[str] = None
    is_bold: Optional[bool] = None
    source_parser: Optional[str] = None


class ParsedSection(BaseModel):
    section_id: str
    title: str
    normalized_title: Optional[str] = None
    level: int = 1
    parent_section_id: Optional[str] = None
    block_ids: list[str] = Field(default_factory=list)
    text: Optional[str] = None
    start_page: Optional[int] = None
    end_page: Optional[int] = None
    confidence: Optional[float] = None
    source_parser: Optional[str] = None


class ParsedCaption(BaseModel):
    caption_id: str
    text: str
    page: int  # 1-based
    bbox: Optional[list[float]] = None
    source_parser: Optional[str] = None


class ParsedFigure(BaseModel):
    figure_id: str
    page: int  # 1-based
    bbox: Optional[list[float]] = None
    caption_id: Optional[str] = None
    source_parser: Optional[str] = None


class ParsedTable(BaseModel):
    table_id: str
    page: int  # 1-based
    bbox: Optional[list[float]] = None
    caption_id: Optional[str] = None
    source_parser: Optional[str] = None


class CandidateDiagnostics(BaseModel):
    parse_duration_seconds: Optional[float] = None
    warnings: list[str] = Field(default_factory=list)
    error_count: int = 0
    notes: Optional[str] = None


class ParsedCandidate(BaseModel):
    provenance: ParserProvenance
    pages: list[ParsedPage] = Field(default_factory=list)
    blocks: list[ParsedBlock] = Field(default_factory=list)
    sections: list[ParsedSection] = Field(default_factory=list)
    figures: list[ParsedFigure] = Field(default_factory=list)
    tables: list[ParsedTable] = Field(default_factory=list)
    captions: list[ParsedCaption] = Field(default_factory=list)
    diagnostics: Optional[CandidateDiagnostics] = None
