# Apple Books

This repository owns the `apple-books` CLI and `skills/apple-books/SKILL.md`.
Match the standalone src-layout Python CLI conventions of own-chrome/inotes-mcp.
Keep operations read-only. Open Apple SQLite stores with mode=ro and query_only;
do not use immutable mode on live WAL databases. Never commit personal books,
metadata, or annotations. Test with synthetic files and temporary databases.

Run `uv run pytest` and `uv build` after implementation/package changes.
Keep skill commands and README aligned with the actual CLI. Do not change
superai-skills or other central agent repositories as part of this project.
