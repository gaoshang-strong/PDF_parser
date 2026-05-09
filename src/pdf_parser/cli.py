"""Command-line interface for pdf-parser."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pdf_parser.grobid.runtime import (
    check_grobid_alive,
    process_pdf_directory_to_tei,
    process_pdf_to_tei,
)
from pdf_parser.parsers.mineru_api_adapter import run_mineru_api
from pdf_parser.registry import get_registered_pdf, register_paper

_DEFAULT_URL = "http://localhost:8070"
_DEFAULT_PAPERS_DIR = "data/registered_pdfs"
_DEFAULT_GROBID_DIR = "data/grobid"
_DEFAULT_MINERU_DIR = "data/mineru"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-parser",
        description="PDF parsing pipeline (GROBID + MinerU)",
    )
    subparsers = parser.add_subparsers(dest="command")

    # ---- register -----------------------------------------------------------
    reg = subparsers.add_parser("register", help="Register a PDF and assign a paper ID")
    reg.add_argument("--pdf", required=True, help="Path to PDF to register")
    reg.add_argument(
        "--papers-dir",
        default=_DEFAULT_PAPERS_DIR,
        help=f"Registered PDFs directory (default: {_DEFAULT_PAPERS_DIR})",
    )

    # ---- grobid -------------------------------------------------------------
    grobid = subparsers.add_parser("grobid", help="GROBID-related commands")
    grobid_sub = grobid.add_subparsers(dest="grobid_command")

    # grobid check
    check = grobid_sub.add_parser("check", help="Check if GROBID service is alive")
    check.add_argument("--url", default=_DEFAULT_URL, help="GROBID base URL")

    # grobid process
    process = grobid_sub.add_parser(
        "process", help="Convert a registered PDF to TEI XML via GROBID"
    )
    process.add_argument("--paper-id", required=True, help="Registered paper ID")
    process.add_argument(
        "--papers-dir",
        default=_DEFAULT_PAPERS_DIR,
        help=f"Registered PDFs directory (default: {_DEFAULT_PAPERS_DIR})",
    )
    process.add_argument(
        "--out-dir",
        default=_DEFAULT_GROBID_DIR,
        help=f"Output directory for TEI XML (default: {_DEFAULT_GROBID_DIR})",
    )
    process.add_argument("--url", default=_DEFAULT_URL, help="GROBID base URL")

    # grobid batch
    batch = grobid_sub.add_parser(
        "batch", help="Convert a directory of PDFs to TEI XML via GROBID"
    )
    batch.add_argument("--input-dir", required=True, help="Directory containing PDFs")
    batch.add_argument("--out-dir", required=True, help="Output directory for TEI XML files")
    batch.add_argument("--url", default=_DEFAULT_URL, help="GROBID base URL")

    # ---- mineru -------------------------------------------------------------
    mineru = subparsers.add_parser("mineru", help="MinerU API-related commands")
    mineru_sub = mineru.add_subparsers(dest="mineru_command")

    # mineru run
    mn_run = mineru_sub.add_parser(
        "run", help="Process a registered PDF via the MinerU cloud API"
    )
    mn_run.add_argument("--paper-id", required=True, help="Registered paper ID")
    mn_run.add_argument(
        "--papers-dir",
        default=_DEFAULT_PAPERS_DIR,
        help=f"Registered PDFs directory (default: {_DEFAULT_PAPERS_DIR})",
    )
    mn_run.add_argument(
        "--out-dir",
        default=_DEFAULT_MINERU_DIR,
        help=f"Output base directory (default: {_DEFAULT_MINERU_DIR})",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "register":
        paper_id = register_paper(Path(args.pdf), Path(args.papers_dir))
        print(paper_id)

    elif args.command == "grobid":
        if args.grobid_command == "check":
            alive = check_grobid_alive(args.url)
            if alive:
                print("GROBID is alive.")
                sys.exit(0)
            else:
                print("GROBID is not reachable.")
                sys.exit(1)

        elif args.grobid_command == "process":
            pdf_path = get_registered_pdf(args.paper_id, Path(args.papers_dir))
            out_path = Path(args.out_dir) / f"{args.paper_id}.tei.xml"
            output = process_pdf_to_tei(pdf_path, out_path, args.url)
            print(f"TEI written to: {output}")

        elif args.grobid_command == "batch":
            outputs = process_pdf_directory_to_tei(
                Path(args.input_dir), Path(args.out_dir), args.url
            )
            for p in outputs:
                print(str(p))

        else:
            parser.parse_args(["grobid", "--help"])

    elif args.command == "mineru":
        if args.mineru_command == "run":
            pdf_path = get_registered_pdf(args.paper_id, Path(args.papers_dir))
            out_dir = Path(args.out_dir) / args.paper_id
            result = run_mineru_api(pdf_path, out_dir)
            print(f"MinerU output: {result}")

        else:
            parser.parse_args(["mineru", "--help"])

    else:
        parser.print_help()
