"""GROBID runtime: submit PDFs to a local GROBID Docker service and retrieve TEI XML."""

from __future__ import annotations

from pathlib import Path

import requests

_DEFAULT_URL = "http://localhost:8070"


def check_grobid_alive(base_url: str = _DEFAULT_URL) -> bool:
    """Return True only when the GROBID service responds with 'true' on /api/isalive."""
    try:
        response = requests.get(f"{base_url}/api/isalive", timeout=5)
        return response.status_code == 200 and response.text.strip() == "true"
    except requests.RequestException:
        return False


def process_pdf_to_tei(
    pdf_path: Path,
    output_tei_path: Path,
    base_url: str = _DEFAULT_URL,
) -> Path:
    """Submit a single PDF to GROBID and write the TEI XML response to output_tei_path.

    Raises FileNotFoundError if pdf_path does not exist.
    Raises ValueError if pdf_path is not a .pdf file.
    Raises requests.HTTPError if GROBID returns a non-2xx status.
    """
    pdf_path = Path(pdf_path)
    output_tei_path = Path(output_tei_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Input must be a PDF file (got '{pdf_path.suffix}'): {pdf_path}")

    output_tei_path.parent.mkdir(parents=True, exist_ok=True)

    with open(pdf_path, "rb") as f:
        response = requests.post(
            f"{base_url}/api/processFulltextDocument",
            files={"input": (pdf_path.name, f, "application/pdf")},
            timeout=120,
        )
    response.raise_for_status()

    output_tei_path.write_text(response.text, encoding="utf-8")
    return output_tei_path


def process_pdf_directory_to_tei(
    input_dir: Path,
    output_dir: Path,
    base_url: str = _DEFAULT_URL,
) -> list[Path]:
    """Process every .pdf in input_dir through GROBID and write TEI XML files to output_dir.

    Output files are named <stem>.tei.xml to match the input stem.
    Raises FileNotFoundError if input_dir does not exist.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    pdf_files = sorted(input_dir.glob("*.pdf"))
    results: list[Path] = []
    for pdf_path in pdf_files:
        output_tei_path = output_dir / (pdf_path.stem + ".tei.xml")
        results.append(process_pdf_to_tei(pdf_path, output_tei_path, base_url))
    return results
