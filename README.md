# PDF_parser

A bake-off framework for comparing PDF parsers on scientific and biomedical PDFs, especially review articles. All parser backends produce a single unified `ParsedCandidate` schema, suitable for downstream LLM evidence extraction.

Supported backends:

| Backend | What it does | Requires |
|---|---|---|
| PyMuPDF | Native text/block extraction, font/layout signals, heading detection | `PDF_parser` env |
| GROBID | Academic-document parser via Docker service, produces TEI XML | Docker + `PDF_parser` env |
| Docling | Optional; structured document/Markdown parsing | `PDF_parser` env |
| Marker | Optional; Markdown/JSON output from PDF layout | `PDF_parser` env |
| MinerU API | Optional; cloud API, no local GPU needed | `PDF_parser` env + API token |

---

## Repository

```
GitHub: git@github.com:gaoshang-strong/PDF_parser.git
Local:  /ShangGaoAIProjects/PDF_parser
```

---

## Setup

### Python environments

Two micromamba environments are used because MinerU requires `pillow>=11` while Marker requires `pillow<11`.

**Main environment** — used for everything except local MinerU:

```bash
micromamba activate PDF_parser
```

**MinerU environment** — only needed if running MinerU locally (not needed for the API adapter):

```bash
micromamba activate PDF_parser_mineru
```

### Install the package (editable)

```bash
micromamba activate PDF_parser
cd /ShangGaoAIProjects/PDF_parser
python -m pip install -e ".[dev]"
```

This installs the `pdf-parser` CLI entry point.

> Always install packages with `python -m pip install`, not plain `pip install`.

### Run tests

```bash
/home/sgao30/micromamba/bin/micromamba run -n PDF_parser python -m pytest
```

All tests use mocks. No external services or API tokens are required.

---

## CLI reference

The entry point is `pdf-parser`. Every command writes a pretty-printed JSON file conforming to `ParsedCandidate`.

### PyMuPDF

Parse a PDF with native PyMuPDF (no external services needed):

```bash
pdf-parser pymupdf parse \
  --pdf  data/raw_pdfs/paper.pdf \
  --out  data/parsed_candidates/pymupdf_native/paper.json
```

### GROBID

GROBID runs as a Docker service. Start it first:

```bash
# Create container (first time only)
docker run -d --init --name grobid -p 127.0.0.1:8070:8070 grobid/grobid:0.9.0

# Start if already created
docker start grobid

# Verify
pdf-parser grobid check
# or: curl http://localhost:8070/api/isalive  →  true
```

Convert one PDF to TEI XML, then parse it:

```bash
pdf-parser grobid process \
  --pdf  data/raw_pdfs/paper.pdf \
  --out  data/grobid_tei/paper.tei.xml

pdf-parser grobid parse-tei \
  --tei  data/grobid_tei/paper.tei.xml \
  --pdf  data/raw_pdfs/paper.pdf \
  --out  data/parsed_candidates/grobid/paper.json
```

Batch convert a directory of PDFs to TEI XML:

```bash
pdf-parser grobid batch \
  --input-dir  data/raw_pdfs \
  --out-dir    data/grobid_tei
```

Stop GROBID when done:

```bash
docker stop grobid
```

### Docling (optional)

```bash
pdf-parser docling parse \
  --pdf  data/raw_pdfs/paper.pdf \
  --out  data/parsed_candidates/docling/paper.json
```

Raises `ImportError` with a clear message if Docling is not installed.

### Marker (optional)

```bash
pdf-parser marker parse \
  --pdf  data/raw_pdfs/paper.pdf \
  --out  data/parsed_candidates/marker/paper.json
```

Raises `ImportError` with a clear message if Marker is not installed.

### MinerU API (optional)

Requires an API token from [mineru.net](https://mineru.net). Set it as an environment variable — never hard-code it.

```bash
export MINERU_API_TOKEN="your-token-here"

pdf-parser mineru parse \
  --pdf       data/raw_pdfs/paper.pdf \
  --work-dir  data/mineru_work \
  --out       data/parsed_candidates/mineru_api/paper.json
```

`--work-dir` is a scratch directory where the raw result ZIP is downloaded and extracted before parsing. It is safe to reuse across runs.

The adapter prints progress:

```
[mineru] Registering paper.pdf (1,313,897 bytes, model=vlm)...
[mineru] Uploading to OSS (batch_id=d13d548c-...)...
[mineru] Upload complete. Polling for extraction result...
[mineru] batch_id=d13d548c-... state='pending'
[mineru] batch_id=d13d548c-... state='running'
[mineru] batch_id=d13d548c-... state='done'
[mineru] Extraction done. Downloading result ZIP...
[mineru] ZIP downloaded (1,214,663 bytes). Extracting...
[mineru] Extraction complete. Parsing output...
ParsedCandidate written to: data/parsed_candidates/mineru_api/paper.json
```

#### Run all PDFs

```bash
for pdf in data/raw_pdfs/*.pdf; do
  stem=$(basename "$pdf" .pdf)
  out="data/parsed_candidates/mineru_api/${stem}.json"
  if [ -f "$out" ]; then
    echo "=== $stem — already done, skipping ==="
    continue
  fi
  echo "=== $stem ==="
  pdf-parser mineru parse \
    --pdf      "$pdf" \
    --work-dir data/mineru_work \
    --out      "$out"
done
```

---

## Output schema

Every parser writes a JSON file with this structure:

```json
{
  "provenance": {
    "parser_name": "mineru_api",
    "parser_version": "unknown",
    "created_at": "2026-05-02T10:25:43.123456+00:00",
    "input_sha256": "abc123...",
    "output_sha256": "def456..."
  },
  "metadata": {
    "title": null,
    "doi": null,
    "journal": null,
    "year": null,
    "authors": []
  },
  "pages": [
    {"page_id": "page_1", "page_number": 1, "width": 612.0, "height": 792.0}
  ],
  "blocks": [
    {
      "block_id": "blk_1",
      "page": 1,
      "text": "Introduction",
      "bbox": [72.0, 100.0, 300.0, 115.0],
      "block_type": "heading",
      "reading_order": 1,
      "font_size": 14.0,
      "font_name": "Arial-Bold",
      "is_bold": true,
      "source_parser": "pymupdf_native"
    }
  ],
  "sections": [
    {
      "section_id": "sec_1",
      "title": "Introduction",
      "normalized_title": "introduction",
      "level": 1,
      "parent_section_id": null,
      "block_ids": ["blk_1", "blk_2"],
      "text": "Introduction\n\nThis paper presents...",
      "start_page": 1,
      "end_page": 2,
      "confidence": null,
      "source_parser": "pymupdf_native"
    }
  ],
  "figures": [
    {"figure_id": "fig_1", "page": 3, "bbox": null, "caption_id": "cap_1", "source_parser": "mineru_api"}
  ],
  "tables": [
    {"table_id": "tbl_1", "page": 4, "bbox": null, "caption_id": "cap_2", "source_parser": "mineru_api"}
  ],
  "captions": [
    {"caption_id": "cap_1", "text": "Figure 1. Overview of the pipeline.", "page": 3, "bbox": null}
  ],
  "diagnostics": {
    "parse_duration_seconds": null,
    "warnings": [],
    "error_count": 0,
    "notes": null
  }
}
```

Field notes:

- `block_type`: `"text"` | `"heading"` | `"image"` | `"table"`
- `bbox`: `[x0, y0, x1, y1]` in PDF points; `null` when not available from that parser
- `sections[].block_ids`: ordered list of block IDs belonging to this section
- `sections[].text`: concatenated text of all body blocks under this section
- `provenance.output_sha256`: SHA-256 of the canonical (sorted-keys) JSON of the output, computed at write time

---

## Batch processing all PDFs (all five parsers)

The commands below skip any PDF that already has an output JSON, so they are safe to re-run after a partial run.

Run everything from the repo root with the `PDF_parser` environment active (or prefix each command with `/home/sgao30/micromamba/bin/micromamba run -n PDF_parser`).

### 1. PyMuPDF

```bash
mkdir -p data/parsed_candidates/pymupdf_native

for pdf in data/raw_pdfs/*.pdf; do
  stem=$(basename "$pdf" .pdf)
  out="data/parsed_candidates/pymupdf_native/${stem}.json"
  [ -f "$out" ] && echo "skip $stem" && continue
  echo "=== pymupdf $stem ==="
  pdf-parser pymupdf parse --pdf "$pdf" --out "$out"
done
```

### 2. GROBID

Start the Docker service first (see the GROBID section above), then:

```bash
mkdir -p data/grobid_tei data/parsed_candidates/grobid

for pdf in data/raw_pdfs/*.pdf; do
  stem=$(basename "$pdf" .pdf)
  out="data/parsed_candidates/grobid/${stem}.json"
  [ -f "$out" ] && echo "skip $stem" && continue
  echo "=== grobid $stem ==="
  pdf-parser grobid process --pdf "$pdf" --out "data/grobid_tei/${stem}.tei.xml"
  pdf-parser grobid parse-tei \
    --tei "data/grobid_tei/${stem}.tei.xml" \
    --pdf "$pdf" \
    --out "$out"
done
```

### 3. Docling

```bash
mkdir -p data/parsed_candidates/docling

for pdf in data/raw_pdfs/*.pdf; do
  stem=$(basename "$pdf" .pdf)
  out="data/parsed_candidates/docling/${stem}.json"
  [ -f "$out" ] && echo "skip $stem" && continue
  echo "=== docling $stem ==="
  pdf-parser docling parse --pdf "$pdf" --out "$out"
done
```

### 4. Marker

```bash
mkdir -p data/parsed_candidates/marker

for pdf in data/raw_pdfs/*.pdf; do
  stem=$(basename "$pdf" .pdf)
  out="data/parsed_candidates/marker/${stem}.json"
  [ -f "$out" ] && echo "skip $stem" && continue
  echo "=== marker $stem ==="
  pdf-parser marker parse --pdf "$pdf" --out "$out"
done
```

### 5. MinerU API

Requires `MINERU_API_TOKEN`. Each PDF takes ~30–60 s (upload + cloud processing). Run sequentially to stay within rate limits.

```bash
export MINERU_API_TOKEN="your-token-here"
mkdir -p data/parsed_candidates/mineru_api data/mineru_work

for pdf in data/raw_pdfs/*.pdf; do
  stem=$(basename "$pdf" .pdf)
  out="data/parsed_candidates/mineru_api/${stem}.json"
  [ -f "$out" ] && echo "skip $stem" && continue
  echo "=== mineru $stem ==="
  pdf-parser mineru parse \
    --pdf      "$pdf" \
    --work-dir data/mineru_work \
    --out      "$out"
done
```

### Run all five in sequence

```bash
export MINERU_API_TOKEN="your-token-here"

mkdir -p data/parsed_candidates/{pymupdf_native,grobid,docling,marker,mineru_api} \
         data/grobid_tei data/mineru_work

for pdf in data/raw_pdfs/*.pdf; do
  stem=$(basename "$pdf" .pdf)
  echo ""
  echo "==============================="
  echo "PDF: $stem"
  echo "==============================="

  out="data/parsed_candidates/pymupdf_native/${stem}.json"
  if [ ! -f "$out" ]; then
    pdf-parser pymupdf parse --pdf "$pdf" --out "$out"
  fi

  tei="data/grobid_tei/${stem}.tei.xml"
  out="data/parsed_candidates/grobid/${stem}.json"
  if [ ! -f "$out" ]; then
    pdf-parser grobid process --pdf "$pdf" --out "$tei"
    pdf-parser grobid parse-tei --tei "$tei" --pdf "$pdf" --out "$out"
  fi

  out="data/parsed_candidates/docling/${stem}.json"
  if [ ! -f "$out" ]; then
    pdf-parser docling parse --pdf "$pdf" --out "$out"
  fi

  out="data/parsed_candidates/marker/${stem}.json"
  if [ ! -f "$out" ]; then
    pdf-parser marker parse --pdf "$pdf" --out "$out"
  fi

  out="data/parsed_candidates/mineru_api/${stem}.json"
  if [ ! -f "$out" ]; then
    pdf-parser mineru parse --pdf "$pdf" --work-dir data/mineru_work --out "$out"
  fi
done
```

> GROBID must be running before the loop starts. Docling and Marker raise `ImportError` if the packages are not installed — the loop will abort on that PDF; install the package and re-run (already-done PDFs are skipped).

---

## Project layout

```
src/pdf_parser/
├── cli.py                   # pdf-parser entry point
├── schema/
│   ├── candidate.py         # ParsedCandidate and all sub-models (Pydantic v2)
│   └── hashes.py            # sha256_file, compute_candidate_output_sha256
├── parsers/
│   ├── pymupdf_native.py    # PyMuPDF adapter
│   ├── grobid_tei.py        # GROBID TEI XML → ParsedCandidate
│   ├── docling_adapter.py   # Docling → ParsedCandidate (optional)
│   ├── marker_adapter.py    # Marker → ParsedCandidate (optional)
│   └── mineru_api_adapter.py# MinerU cloud API → ParsedCandidate (optional)
├── grobid/
│   └── runtime.py           # GROBID Docker service helpers
└── export/
    └── json_writer.py       # write_pretty_json (indent=2, sorted keys, UTF-8)

tests/
├── fixtures/                # TEI XML fixtures for GROBID tests
└── test_*.py                # One test file per module; all mocked

data/                        # Not committed to Git
├── raw_pdfs/
├── grobid_tei/
├── parsed_candidates/
│   ├── pymupdf_native/
│   ├── docling/
│   ├── marker/
│   └── mineru_api/
├── mineru_work/
└── reports/
```

---

## Using the Python API directly

```python
from pathlib import Path
from pdf_parser.parsers.pymupdf_native import parse_pdf_with_pymupdf
from pdf_parser.parsers.mineru_api_adapter import parse_pdf_with_mineru_api
from pdf_parser.export.json_writer import write_pretty_json

# PyMuPDF
candidate = parse_pdf_with_pymupdf(Path("paper.pdf"))

# MinerU API (token from MINERU_API_TOKEN env var)
candidate = parse_pdf_with_mineru_api(
    pdf_path=Path("paper.pdf"),
    work_dir=Path("mineru_work"),
)

# Inspect
print(candidate.provenance.parser_name)
print(len(candidate.blocks), "blocks")
print(len(candidate.sections), "sections")
for sec in candidate.sections:
    print(f"  {'  ' * (sec.level - 1)}{sec.title}")

# Save
write_pretty_json(Path("output.json"), candidate.model_dump(mode="json"))
```

---

## Data policy

The `data/` directory is not committed to Git. Do not commit PDFs, TEI XML, parsed JSON outputs, or API tokens.

---

## Development rules

- No broad `try/except` to hide errors — let them surface.
- No placeholder functions or fake test results.
- Parsing logic is kept separate from I/O, CLI, and reporting.
- Add or update tests when changing parser behaviour.
- All outputs record `parser_name`, `parser_version`, `created_at`, `input_sha256`, `output_sha256`.
- Run `pytest` before claiming a change is complete.
