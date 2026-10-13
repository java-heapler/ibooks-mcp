# apple-books

Read-only, JSON-first CLI for Apple Books on macOS. Find books by title or author,
read EPUB sections and PDF pages, search text, and retrieve saved annotations.

## Install

Requires Python 3.11+ and uv. PDF extraction additionally requires Poppler
(`brew install poppler`).

```sh
uv tool install .
apple-books --help
apple-books list --query "Cognition" --limit 10
apple-books toc ASSET_ID
apple-books read ASSET_ID --section 1 --chars 16000
apple-books search ASSET_ID "confirmation bias" --limit 10
apple-books notes ASSET_ID --limit 20
```

Use asset IDs from `list`. Text commands also accept quoted local file paths.
`read` returns `next_offset` for continuation. EPUB sections follow spine order;
PDF section numbers are physical file pages. Commands emit JSON, with exit 0 for
success and exit 1 plus a JSON error on failure; argument errors use argparse's
standard exit 2.

The library must be available to the process under macOS privacy permissions.
Cloud-only items need downloading in Books. A present iCloud path may hydrate on
read. Protected EPUBs are not decrypted. Image-only PDF pages require separate
OCR. Audiobooks are not supported. The CLI does not change reading progress,
annotations, or library records.

EbookLib handles EPUB packages; Beautiful Soup extracts their text. Expanded
EPUB folders are temporarily repackaged, then deleted. PDFs use `pdftotext`.
Text extraction may omit visual meaning from figures, tables, and equations.
Text commands currently parse the selected book on each invocation.

## Repository conventions

Follows the standalone `own-chrome` / `inotes-mcp` layout:

- `pyproject.toml`, `uv.lock`: installable CLI and reproducible dependencies
- `src/apple_books/`: implementation
- `skills/apple-books/SKILL.md`: agent instructions
- `tests/`: offline synthetic fixtures, no personal book content

The skill is owned here. An agent can link its skill directory to
`skills/apple-books`. Future superai-skills integration can reference this repo
as a package submodule and distribute that skill. No central integration is
required for standalone use. This version is CLI-only, like own-chrome; it does
not expose an MCP server.

## Development

```sh
uv sync --extra dev
uv run pytest
uv build
```

Tests use temporary catalogs and generated EPUBs, never the user's library.
Do not commit books, library databases, annotation exports, or private metadata.
