# PDF_parser

PDF_parser is a bake-off framework for comparing PDF parsers on scientific / biomedical PDFs, especially review papers.

The goal is to evaluate which parser output is most suitable for downstream LLM evidence extraction.

## Repository

GitHub:

```bash
git@github.com:gaoshang-strong/PDF_parser.git
```

Local path on the server:

```bash
/ShangGaoAIProjects/PDF_parser
```

## Python environments

### Main environment

```bash
micromamba activate PDF_parser
```

Used for:

- Base project code
- PyMuPDF
- GROBID TEI adapter
- Docling
- Marker
- Tests
- CLI
- Evidence XML export

### MinerU environment

```bash
micromamba activate PDF_parser_mineru
```

MinerU is kept in a separate environment because MinerU requires `pillow>=11`, while Marker / surya require `pillow<11`.

## Python package installation rule

Always install Python packages through the active environment's Python:

```bash
python -m pip install ...
```

Do not use plain `pip install ...`.

## Installed / planned tools

### PyMuPDF

Environment:

```text
PDF_parser
```

Purpose:

- Native PDF text extraction
- Text blocks
- Bounding boxes
- Font/layout signals
- Heading candidates
- Reading order analysis

### Docling

Environment:

```text
PDF_parser
```

Purpose:

- Optional parser backend
- Convert PDF into structured document / Markdown / JSON
- Convert Docling output into the unified `ParsedCandidate` schema

### Marker

Environment:

```text
PDF_parser
```

Purpose:

- Optional parser backend
- Convert PDF into Markdown / JSON
- Convert Marker output into the unified `ParsedCandidate` schema

### MinerU

Environment:

```text
PDF_parser_mineru
```

Purpose:

- Optional parser backend
- Run MinerU separately and export Markdown / JSON
- Main project reads MinerU output and converts it into the unified `ParsedCandidate` schema

Recommended way to call MinerU from the main project:

```bash
micromamba run -n PDF_parser_mineru mineru ...
```

## GROBID

GROBID is installed through Docker.

Docker image:

```bash
grobid/grobid:0.9.0
```

GROBID service URL:

```text
http://localhost:8070
```

### Start GROBID each time

If the container already exists:

```bash
docker start grobid
```

Check that it is running:

```bash
docker ps | grep -i grobid
```

Check the API:

```bash
curl http://localhost:8070/api/isalive
```

Expected output:

```text
true
```

### Create the GROBID container if it does not exist

```bash
docker run -d --init \
  --name grobid \
  -p 127.0.0.1:8070:8070 \
  grobid/grobid:0.9.0
```

### Convert one PDF to TEI XML

Example:

```bash
mkdir -p data/grobid_tei

curl -X POST \
  -F input=@data/raw_pdfs/test.pdf \
  http://localhost:8070/api/processFulltextDocument \
  -o data/grobid_tei/test.tei.xml
```

First version of this project reads external GROBID TEI files. It does not need to manage the GROBID server runtime inside the Python code.

## Data policy

The `data/` directory must not be committed to Git.

Expected local data layout:

```text
data/
├── raw_pdfs/
├── grobid_tei/
├── parsed_candidates/
├── reports/
└── selected_xml/
```

## Git rules

Do not commit:

- `data/`
- PDFs
- TEI XML files
- large parser outputs
- `.env`
- Python cache directories

Recommended `.gitignore` entries:

```gitignore
data/
*.pdf
*.tei.xml
*.jsonl
*.parquet
__pycache__/
.pytest_cache/
.venv/
.env
```

## Project rules

- Do not assume any parser is the ground truth.
- All parser outputs must be converted into a unified `ParsedCandidate` schema.
- Docling, Marker, and MinerU must remain optional backends.
- Missing optional backends should give clear errors.
- Tests must not depend on external APIs.
- Do not use broad `try/except` blocks to hide errors.
- Pretty-print all JSON outputs.
- Every parser output must record:
  - `parser_name`
  - `parser_version`
  - `created_at`
  - `input_sha256`
  - `output_sha256`
- Run `pytest` after each milestone.
- Do not auto-commit.

## Main milestones

1. Project skeleton and unified schema
2. GROBID TEI adapter
3. Native PyMuPDF adapter
4. Parsing quality metrics
5. Bake-off runner
6. Evidence XML exporter
7. Optional backends: Docling, Marker, MinerU

## Final output goal

The most important output is an XML file for downstream LLM evidence extraction.

The selected XML should preserve:

- Section hierarchy
- Section titles
- Reading order
- Page and block provenance
- Figure captions
- Table captions
- Parser provenance
- Recovered or disputed sections

