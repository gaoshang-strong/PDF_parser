# PDF Parser Project Instructions

This project builds a robust PDF parsing pipeline for research literature.

## Development goals

The parser should prioritize correctness, traceability, and testability over quick hacks.

Core pipeline goals:

1. Parse PDF or extracted text into structured article objects.
2. Preserve page numbers, section titles, and source spans when possible.
3. Classify sections such as abstract, introduction, methods, results, discussion, conclusion, references, tables, and figures.
4. Support review articles, original research articles, perspectives, editorials, and case reports when possible.
5. Produce machine-readable outputs suitable for downstream evidence extraction.

## Coding rules

- Do not silently skip errors with broad try/except.
- Do not introduce placeholder functions or fake test results.
- Prefer explicit data models and clear function boundaries.
- Keep parsing logic separated from I/O, CLI, and reporting.
- Add or update tests when changing parser behavior.
- For every non-trivial change, explain the design before editing many files.
- Do not modify raw data, original PDFs, secrets, or final outputs unless explicitly asked.

## Preferred Python style

- Use clear function and variable names.
- Prefer pathlib over raw string path manipulation.
- Prefer dataclasses or pydantic models for structured parser outputs.
- Keep modules small and focused.
- Avoid hidden global state.
- Let errors surface during development unless there is a strong reason to handle them.

## Testing

Before claiming a parser change is complete, run the relevant tests.


# PDF_parser notes for Claude Code

## Repo
- Local: `/ShangGaoAIProjects/PDF_parser`
- GitHub: `git@github.com:gaoshang-strong/PDF_parser.git`

## Environments
- `PDF_parser`: main env. Use for base project, PyMuPDF, GROBID TEI adapter, Docling, Marker, tests, CLI, XML export.
- `PDF_parser_mineru`: MinerU-only env, because MinerU needs `pillow>=11`, while Marker/surya need `pillow<11`.

