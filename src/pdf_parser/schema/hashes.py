"""Hash utilities for PDF parser provenance tracking."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pdf_parser.schema.candidate import ParsedCandidate


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    """Return the hex SHA-256 digest of a UTF-8 encoded string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json_dumps(obj: Any) -> str:
    """Serialize obj to a canonical JSON string with sorted keys and no extra whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_candidate_output_sha256(candidate: ParsedCandidate) -> str:
    """Compute a SHA-256 hash over the candidate content, excluding output_sha256.

    Excludes provenance.output_sha256 to avoid circularity.  All other fields
    (including parser_name, parser_version, input_sha256) are included so the
    hash changes if either content or parser identity changes.
    """
    data = candidate.model_dump(mode="json")
    data["provenance"].pop("output_sha256", None)
    return sha256_text(canonical_json_dumps(data))
