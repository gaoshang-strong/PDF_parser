# PDF_parser

A pipeline for parsing scientific and biomedical PDFs using GROBID and the MinerU cloud API.

Every PDF is first **registered** to receive a stable `paper_id`. All subsequent steps use the paper ID to locate inputs and write outputs.

---

## Repository

```
GitHub: git@github.com:gaoshang-strong/PDF_parser.git
Local:  /ShangGaoAIProjects/PDF_parser
```

---

## Data layout

```
data/
├── raw_pdfs/              Original PDFs (before registration)
├── registered_pdfs/       Registered PDFs + registry.json
├── grobid/                {paper_id}.tei.xml
└── mineru/                {paper_id}/  (content_list.json, .md, images/)
```

---

## Setup

```bash
micromamba activate PDF_parser
cd /ShangGaoAIProjects/PDF_parser
python -m pip install -e ".[dev]"
```

### Run tests

```bash
/home/sgao30/micromamba/bin/micromamba run -n PDF_parser python -m pytest
```

---

## Workflow

### Step 1 — Register

Assign a stable `paper_id` to each PDF and move it into the registry:

```bash
pdf-parser register --pdf data/raw_pdfs/paper.pdf
# → pdf_16edbbde296287d6
```

The PDF is moved to `data/registered_pdfs/{paper_id}.pdf` and recorded in
`data/registered_pdfs/registry.json`. Registration is **idempotent** — the
same file content always produces the same `paper_id`.

```
data/registered_pdfs/
├── registry.json
├── pdf_16edbbde296287d6.pdf
└── pdf_1ee686107e655447.pdf
```

`registry.json` format:

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

### Step 2 — GROBID

GROBID runs as a Docker service:

```bash
# Create container (first time only)
docker run -d --init --name grobid -p 127.0.0.1:8070:8070 grobid/grobid:0.9.0

# Start if already created
docker start grobid

# Verify
pdf-parser grobid check
```

Process a registered PDF:

```bash
pdf-parser grobid process --paper-id pdf_16edbbde296287d6
# writes → data/grobid/pdf_16edbbde296287d6.tei.xml
```

Stop GROBID when done:

```bash
docker stop grobid
```

### Step 3 — MinerU API

Requires an API token from [mineru.net](https://mineru.net):

```bash
export MINERU_API_TOKEN="your-token-here"

pdf-parser mineru run --paper-id pdf_16edbbde296287d6
# writes → data/mineru/pdf_16edbbde296287d6/
```

Output directory contains `*_content_list.json`, `*.md`, and `images/`.

---

## Batch processing

### Register all PDFs

```bash
for pdf in data/raw_pdfs/*.pdf; do
  pdf-parser register --pdf "$pdf"
done
```

### GROBID — all registered papers

```bash
docker start grobid

for paper_id in $(jq -r 'keys[]' data/registered_pdfs/registry.json); do
  out="data/grobid/${paper_id}.tei.xml"
  [ -f "$out" ] && echo "skip $paper_id" && continue
  echo "=== grobid $paper_id ==="
  pdf-parser grobid process --paper-id "$paper_id"
done
```

### MinerU — all registered papers

```bash
export MINERU_API_TOKEN="your-token-here"

for paper_id in $(jq -r 'keys[]' data/registered_pdfs/registry.json); do
  out="data/mineru/${paper_id}"
  [ -d "$out" ] && echo "skip $paper_id" && continue
  echo "=== mineru $paper_id ==="
  pdf-parser mineru run --paper-id "$paper_id"
done
```

### Run both in sequence

```bash
export MINERU_API_TOKEN="your-token-here"
docker start grobid

for paper_id in $(jq -r 'keys[]' data/registered_pdfs/registry.json); do
  echo "=== $paper_id ==="

  [ -f "data/grobid/${paper_id}.tei.xml" ] || \
    pdf-parser grobid process --paper-id "$paper_id"

  [ -d "data/mineru/${paper_id}" ] || \
    pdf-parser mineru run --paper-id "$paper_id"
done
```

---

## CLI reference

```
pdf-parser register  --pdf <path> [--papers-dir data/registered_pdfs]

pdf-parser grobid check    [--url http://localhost:8070]
pdf-parser grobid process  --paper-id <id> [--papers-dir ...] [--out-dir data/grobid] [--url ...]
pdf-parser grobid batch    --input-dir <dir> --out-dir <dir> [--url ...]

pdf-parser mineru run      --paper-id <id> [--papers-dir ...] [--out-dir data/mineru]
```

---

## Project layout

```
src/pdf_parser/
├── cli.py                        # pdf-parser entry point
├── registry.py                   # register_paper, get_registered_pdf
├── parsers/
│   └── mineru_api_adapter.py     # MinerU cloud API workflow
└── grobid/
    └── runtime.py                # GROBID Docker service helpers

tests/
├── fixtures/                     # TEI XML fixtures for GROBID tests
└── test_*.py                     # One test file per module; all mocked
```

---

## Data policy

The `data/` directory is not committed to Git. Do not commit PDFs, TEI XML, MinerU outputs, or API tokens.

---

## Development rules

- No broad `try/except` to hide errors — let them surface.
- No placeholder functions or fake test results.
- Add or update tests when changing parser behaviour.
- Run `pytest` before claiming a change is complete.
