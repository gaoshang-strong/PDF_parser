# PDF_parser

A pipeline for parsing scientific and biomedical PDFs using GROBID and the MinerU cloud API. Both parsers produce a unified `ParsedCandidate` schema suitable for downstream LLM evidence extraction.

Every PDF is first **registered** to receive a stable `paper_id`. The paper ID is the identity of the paper throughout the pipeline.

Supported backends:

| Backend | What it does | Requires |
|---|---|---|
| GROBID | Academic-document parser via Docker service, produces TEI XML | Docker + `PDF_parser` env |
| MinerU API | Cloud API, no local GPU needed | `PDF_parser` env + API token |

---

## Repository

```
GitHub: git@github.com:gaoshang-strong/PDF_parser.git
Local:  /ShangGaoAIProjects/PDF_parser
```

---

## Setup

### Python environment

```bash
micromamba activate PDF_parser
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

The entry point is `pdf-parser`. Every parse command writes a pretty-printed JSON file conforming to `ParsedCandidate`.

### Step 1 — Register a PDF

Before parsing, register the PDF to assign it a stable `paper_id`:

```bash
pdf-parser register --pdf data/raw_pdfs/paper.pdf
# → pdf_16edbbde296287d6
```

The PDF is **moved** to `data/registered_pdfs/{paper_id}.pdf` and recorded in `data/registered_pdfs/registry.json`.

Registration is **idempotent**: the same file content always produces the same `paper_id`.

```bash
# Custom papers directory
pdf-parser register \
  --pdf        data/raw_pdfs/paper.pdf \
  --papers-dir data/registered_pdfs
```

#### `registry.json` format

```json
{
  "pdf_16edbbde296287d6": {
    "original_filename": "paper.pdf",
    "paper_id": "pdf_16edbbde296287d6",
    "registered_at": "2026-05-08T10:00:00+00:00",
    "sha256": "16edbbde296287d6..."
  }
}
```

---

### Step 2 — Parse

All parse commands take `--paper-id` (and optionally `--papers-dir`).

#### GROBID

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

Convert a registered PDF to TEI XML, then parse to `ParsedCandidate`:

```bash
pdf-parser grobid process \
  --paper-id pdf_16edbbde296287d6 \
  --out      data/grobid_tei/pdf_16edbbde296287d6.tei.xml

pdf-parser grobid parse-tei \
  --tei      data/grobid_tei/pdf_16edbbde296287d6.tei.xml \
  --paper-id pdf_16edbbde296287d6 \
  --out      data/parsed_candidates/grobid/pdf_16edbbde296287d6.json
```

Batch convert a directory of raw PDFs to TEI XML (does not use the registry):

```bash
pdf-parser grobid batch \
  --input-dir  data/raw_pdfs \
  --out-dir    data/grobid_tei
```

Stop GROBID when done:

```bash
docker stop grobid
```

#### MinerU API

Requires an API token from [mineru.net](https://mineru.net). Set it as an environment variable — never hard-code it.

```bash
export MINERU_API_TOKEN="your-token-here"

pdf-parser mineru parse \
  --paper-id pdf_16edbbde296287d6 \
  --work-dir data/mineru_work \
  --out      data/parsed_candidates/mineru_api/pdf_16edbbde296287d6.json
```

`--work-dir` is a scratch directory where the raw result ZIP is downloaded and extracted before parsing. It is safe to reuse across runs.

The adapter prints progress:

```
[mineru] Registering pdf_16edbbde296287d6.pdf (1,313,897 bytes, model=vlm)...
[mineru] Uploading to OSS (batch_id=d13d548c-...)...
[mineru] Upload complete. Polling for extraction result...
[mineru] batch_id=d13d548c-... state='pending'
[mineru] batch_id=d13d548c-... state='running'
[mineru] batch_id=d13d548c-... state='done'
[mineru] Extraction done. Downloading result ZIP...
[mineru] ZIP downloaded (1,214,663 bytes). Extracting...
[mineru] Extraction complete. Parsing output...
ParsedCandidate written to: data/parsed_candidates/mineru_api/pdf_16edbbde296287d6.json
```

---

## Batch processing all PDFs

The commands below skip any PDF that already has an output JSON, so they are safe to re-run after a partial run.

Run everything from the repo root with the `PDF_parser` environment active (or prefix each command with `/home/sgao30/micromamba/bin/micromamba run -n PDF_parser`).

### Register all PDFs

```bash
mkdir -p data/registered_pdfs

for pdf in data/raw_pdfs/*.pdf; do
  echo "=== register $(basename "$pdf") ==="
  pdf-parser register --pdf "$pdf"
done
```

### 1. GROBID

Start the Docker service first (see above), then:

```bash
mkdir -p data/grobid_tei data/parsed_candidates/grobid

for paper_id in $(jq -r 'keys[]' data/registered_pdfs/registry.json); do
  out="data/parsed_candidates/grobid/${paper_id}.json"
  [ -f "$out" ] && echo "skip $paper_id" && continue
  echo "=== grobid $paper_id ==="
  pdf-parser grobid process \
    --paper-id "$paper_id" \
    --out      "data/grobid_tei/${paper_id}.tei.xml"
  pdf-parser grobid parse-tei \
    --tei      "data/grobid_tei/${paper_id}.tei.xml" \
    --paper-id "$paper_id" \
    --out      "$out"
done
```

### 2. MinerU API

Requires `MINERU_API_TOKEN`. Each PDF takes ~30–60 s (upload + cloud processing). Run sequentially to stay within rate limits.

```bash
export MINERU_API_TOKEN="your-token-here"
mkdir -p data/parsed_candidates/mineru_api data/mineru_work

for paper_id in $(jq -r 'keys[]' data/registered_pdfs/registry.json); do
  out="data/parsed_candidates/mineru_api/${paper_id}.json"
  [ -f "$out" ] && echo "skip $paper_id" && continue
  echo "=== mineru $paper_id ==="
  pdf-parser mineru parse \
    --paper-id "$paper_id" \
    --work-dir data/mineru_work \
    --out      "$out"
done
```

### Run both in sequence

```bash
export MINERU_API_TOKEN="your-token-here"

mkdir -p data/parsed_candidates/{grobid,mineru_api} \
         data/grobid_tei data/mineru_work

for paper_id in $(jq -r 'keys[]' data/registered_pdfs/registry.json); do
  echo ""
  echo "==============================="
  echo "Paper: $paper_id"
  echo "==============================="

  tei="data/grobid_tei/${paper_id}.tei.xml"
  out="data/parsed_candidates/grobid/${paper_id}.json"
  if [ ! -f "$out" ]; then
    pdf-parser grobid process --paper-id "$paper_id" --out "$tei"
    pdf-parser grobid parse-tei --tei "$tei" --paper-id "$paper_id" --out "$out"
  fi

  out="data/parsed_candidates/mineru_api/${paper_id}.json"
  if [ ! -f "$out" ]; then
    pdf-parser mineru parse --paper-id "$paper_id" --work-dir data/mineru_work --out "$out"
  fi
done
```

> GROBID must be running before the loop starts.

---

## Output schema

Every parser writes a JSON file with this structure:

```json
{
  "provenance": {
    "parser_name": "mineru_api",
    "parser_version": "unknown",
    "created_at": "2026-05-08T10:25:43.123456+00:00",
    "input_sha256": "16edbbde296287d6...",
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
      "font_size": null,
      "font_name": null,
      "is_bold": null,
      "source_parser": "grobid_tei"
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
      "source_parser": "grobid_tei"
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

- `block_type`: `"text"` | `"heading"`
- `bbox`: `[x0, y0, x1, y1]` in PDF points; `null` when not available from that parser
- `sections[].block_ids`: ordered list of block IDs belonging to this section
- `sections[].text`: concatenated text of all body blocks under this section
- `provenance.output_sha256`: SHA-256 of the canonical (sorted-keys) JSON of the output, computed at write time

---

## Project layout

```
src/pdf_parser/
├── cli.py                   # pdf-parser entry point
├── registry.py              # register_paper, get_registered_pdf
├── schema/
│   ├── candidate.py         # ParsedCandidate and all sub-models (Pydantic v2)
│   └── hashes.py            # sha256_file, compute_candidate_output_sha256
├── parsers/
│   ├── grobid_tei.py        # GROBID TEI XML → ParsedCandidate
│   └── mineru_api_adapter.py# MinerU cloud API → ParsedCandidate
├── grobid/
│   └── runtime.py           # GROBID Docker service helpers
└── export/
    └── json_writer.py       # write_pretty_json (indent=2, sorted keys, UTF-8)

tests/
├── fixtures/                # TEI XML fixtures for GROBID tests
└── test_*.py                # One test file per module; all mocked

data/                        # Not committed to Git
├── raw_pdfs/                # Original PDFs (before registration)
├── registered_pdfs/         # Registered PDFs named by paper_id; registry.json
├── grobid_tei/
├── parsed_candidates/
│   ├── grobid/
│   └── mineru_api/
├── mineru_work/
└── reports/
```

---

## Using the Python API directly

```python
from pathlib import Path
from pdf_parser.registry import register_paper, get_registered_pdf
from pdf_parser.parsers.grobid_tei import parse_grobid_tei_to_candidate
from pdf_parser.parsers.mineru_api_adapter import parse_pdf_with_mineru_api
from pdf_parser.export.json_writer import write_pretty_json

# Register
paper_id = register_paper(Path("paper.pdf"), Path("data/registered_pdfs"))
pdf_path = get_registered_pdf(paper_id, Path("data/registered_pdfs"))

# GROBID (TEI XML already produced by grobid process)
candidate = parse_grobid_tei_to_candidate(
    Path(f"data/grobid_tei/{paper_id}.tei.xml"), pdf_path
)

# MinerU API (token from MINERU_API_TOKEN env var)
candidate = parse_pdf_with_mineru_api(
    pdf_path=pdf_path,
    work_dir=Path("data/mineru_work"),
)

# Inspect
print(candidate.provenance.parser_name)
print(len(candidate.blocks), "blocks")
print(len(candidate.sections), "sections")
for sec in candidate.sections:
    print(f"  {'  ' * (sec.level - 1)}{sec.title}")

# Save
write_pretty_json(Path(f"output/{paper_id}.json"), candidate.model_dump(mode="json"))
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
