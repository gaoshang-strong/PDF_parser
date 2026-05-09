"""Paper registry: assign stable IDs to PDFs and track them in a registry."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pdf_parser.schema.hashes import sha256_file

_REGISTRY_FILENAME = "registry.json"


def paper_id_from_sha256(sha256: str) -> str:
    return f"pdf_{sha256[:16]}"


def load_registry(papers_dir: Path) -> dict[str, dict]:
    path = Path(papers_dir) / _REGISTRY_FILENAME
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_registry(papers_dir: Path, registry: dict[str, dict]) -> None:
    papers_dir = Path(papers_dir)
    papers_dir.mkdir(parents=True, exist_ok=True)
    path = papers_dir / _REGISTRY_FILENAME
    path.write_text(
        json.dumps(registry, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def register_paper(pdf_path: Path, papers_dir: Path) -> str:
    """Register a PDF: move it to papers_dir/{paper_id}.pdf and record it in registry.json.

    Returns the paper_id.  Idempotent: if a paper with the same content is
    already registered, returns the existing paper_id without moving or writing.

    Raises FileNotFoundError if pdf_path does not exist.
    Raises ValueError if pdf_path is not a .pdf file.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file (got '{pdf_path.suffix}'): {pdf_path}")

    papers_dir = Path(papers_dir)
    sha256 = sha256_file(pdf_path)
    paper_id = paper_id_from_sha256(sha256)

    registry = load_registry(papers_dir)
    if paper_id in registry:
        return paper_id

    papers_dir.mkdir(parents=True, exist_ok=True)
    dest = papers_dir / f"{paper_id}.pdf"
    shutil.move(str(pdf_path), dest)

    registry[paper_id] = {
        "original_filename": pdf_path.name,
        "paper_id": paper_id,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "sha256": sha256,
    }
    save_registry(papers_dir, registry)
    return paper_id


def get_registered_pdf(paper_id: str, papers_dir: Path) -> Path:
    """Return the path to a registered PDF.

    Raises FileNotFoundError if the paper_id is not found in papers_dir.
    """
    path = Path(papers_dir) / f"{paper_id}.pdf"
    if not path.exists():
        raise FileNotFoundError(
            f"No registered PDF for {paper_id!r}. Expected: {path}"
        )
    return path
