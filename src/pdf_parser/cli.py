"""Command-line interface for pdf-parser."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pdf_parser.export.json_writer import write_pretty_json
from pdf_parser.grobid.runtime import (
    check_grobid_alive,
    process_pdf_directory_to_tei,
    process_pdf_to_tei,
)
from pdf_parser.parsers.grobid_tei import parse_grobid_tei_to_candidate
from pdf_parser.parsers.pymupdf_native import parse_pdf_with_pymupdf

_DEFAULT_URL = "http://localhost:8070"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-parser",
        description="PDF parser bake-off framework",
    )
    subparsers = parser.add_subparsers(dest="command")

    grobid = subparsers.add_parser("grobid", help="GROBID-related commands")
    grobid_sub = grobid.add_subparsers(dest="grobid_command")

    # grobid check
    check = grobid_sub.add_parser("check", help="Check if GROBID service is alive")
    check.add_argument("--url", default=_DEFAULT_URL, help="GROBID base URL")

    # grobid process
    process = grobid_sub.add_parser("process", help="Convert a single PDF to TEI XML")
    process.add_argument("--pdf", required=True, help="Path to input PDF")
    process.add_argument("--out", required=True, help="Path for output TEI XML")
    process.add_argument("--url", default=_DEFAULT_URL, help="GROBID base URL")

    # grobid batch
    batch = grobid_sub.add_parser("batch", help="Convert a directory of PDFs to TEI XML")
    batch.add_argument("--input-dir", required=True, help="Directory containing PDFs")
    batch.add_argument("--out-dir", required=True, help="Output directory for TEI XML files")
    batch.add_argument("--url", default=_DEFAULT_URL, help="GROBID base URL")

    # grobid parse-tei
    parse_tei = grobid_sub.add_parser(
        "parse-tei", help="Convert a GROBID TEI XML file to a ParsedCandidate JSON"
    )
    parse_tei.add_argument("--tei", required=True, help="Path to input .tei.xml file")
    parse_tei.add_argument("--out", required=True, help="Path for output JSON file")
    parse_tei.add_argument("--pdf", default=None, help="Original PDF path (for input_sha256)")

    # pymupdf
    pymupdf = subparsers.add_parser("pymupdf", help="PyMuPDF-related commands")
    pymupdf_sub = pymupdf.add_subparsers(dest="pymupdf_command")

    # pymupdf parse
    pm_parse = pymupdf_sub.add_parser("parse", help="Parse a PDF with native PyMuPDF")
    pm_parse.add_argument("--pdf", required=True, help="Path to input PDF")
    pm_parse.add_argument("--out", required=True, help="Path for output JSON file")

    # docling
    docling = subparsers.add_parser("docling", help="Docling-related commands")
    docling_sub = docling.add_subparsers(dest="docling_command")

    # docling parse
    dl_parse = docling_sub.add_parser("parse", help="Parse a PDF with Docling")
    dl_parse.add_argument("--pdf", required=True, help="Path to input PDF")
    dl_parse.add_argument("--out", required=True, help="Path for output JSON file")

    # marker
    marker = subparsers.add_parser("marker", help="Marker-related commands")
    marker_sub = marker.add_subparsers(dest="marker_command")

    # marker parse
    mk_parse = marker_sub.add_parser("parse", help="Parse a PDF with Marker")
    mk_parse.add_argument("--pdf", required=True, help="Path to input PDF")
    mk_parse.add_argument("--out", required=True, help="Path for output JSON file")

    # mineru
    mineru = subparsers.add_parser("mineru", help="MinerU API-related commands")
    mineru_sub = mineru.add_subparsers(dest="mineru_command")

    # mineru parse
    mn_parse = mineru_sub.add_parser("parse", help="Parse a PDF via the MinerU cloud API")
    mn_parse.add_argument("--pdf", required=True, help="Path to input PDF")
    mn_parse.add_argument("--work-dir", required=True, help="Working directory for raw API output")
    mn_parse.add_argument("--out", required=True, help="Path for output ParsedCandidate JSON")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "grobid":
        if args.grobid_command == "check":
            alive = check_grobid_alive(args.url)
            if alive:
                print("GROBID is alive.")
                sys.exit(0)
            else:
                print("GROBID is not reachable.")
                sys.exit(1)

        elif args.grobid_command == "process":
            output = process_pdf_to_tei(Path(args.pdf), Path(args.out), args.url)
            print(f"TEI written to: {output}")

        elif args.grobid_command == "batch":
            outputs = process_pdf_directory_to_tei(
                Path(args.input_dir), Path(args.out_dir), args.url
            )
            for p in outputs:
                print(str(p))

        elif args.grobid_command == "parse-tei":
            pdf_path = Path(args.pdf) if args.pdf else None
            candidate = parse_grobid_tei_to_candidate(Path(args.tei), pdf_path)
            out_path = Path(args.out)
            write_pretty_json(out_path, candidate.model_dump(mode="json"))
            print(f"ParsedCandidate written to: {out_path}")

        else:
            parser.parse_args(["grobid", "--help"])

    elif args.command == "pymupdf":
        if args.pymupdf_command == "parse":
            candidate = parse_pdf_with_pymupdf(Path(args.pdf))
            out_path = Path(args.out)
            write_pretty_json(out_path, candidate.model_dump(mode="json"))
            print(f"ParsedCandidate written to: {out_path}")

        else:
            parser.parse_args(["pymupdf", "--help"])

    elif args.command == "docling":
        if args.docling_command == "parse":
            from pdf_parser.parsers.docling_adapter import parse_pdf_with_docling
            candidate = parse_pdf_with_docling(Path(args.pdf))
            out_path = Path(args.out)
            write_pretty_json(out_path, candidate.model_dump(mode="json"))
            print(f"ParsedCandidate written to: {out_path}")

        else:
            parser.parse_args(["docling", "--help"])

    elif args.command == "marker":
        if args.marker_command == "parse":
            from pdf_parser.parsers.marker_adapter import parse_pdf_with_marker
            candidate = parse_pdf_with_marker(Path(args.pdf))
            out_path = Path(args.out)
            write_pretty_json(out_path, candidate.model_dump(mode="json"))
            print(f"ParsedCandidate written to: {out_path}")

        else:
            parser.parse_args(["marker", "--help"])

    elif args.command == "mineru":
        if args.mineru_command == "parse":
            from pdf_parser.parsers.mineru_api_adapter import parse_pdf_with_mineru_api
            candidate = parse_pdf_with_mineru_api(Path(args.pdf), Path(args.work_dir))
            out_path = Path(args.out)
            write_pretty_json(out_path, candidate.model_dump(mode="json"))
            print(f"ParsedCandidate written to: {out_path}")

        else:
            parser.parse_args(["mineru", "--help"])

    else:
        parser.print_help()
