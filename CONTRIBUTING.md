# Contributing

Thanks for your interest in profili-mcp. This is a small project maintained by a
student; focused contributions are very welcome.

## Getting set up

```bash
git clone https://github.com/GaillumXc/profili-mcp.git
cd profili-mcp
uv sync --all-extras          # installs runtime + dev dependencies (ruff, pytest)
```

Clone to an **ASCII-only path** — CPython reads `.pth` files with the locale
encoding, so an editable install from a non-ASCII path fails (see README,
"Known issues").

## Before submitting a PR

1. `uv run ruff check src tests examples` — must pass. The ruff configuration in
   `pyproject.toml` documents which warnings are intentionally ignored and why
   (e.g. MCP tool wrappers convert all exceptions to JSON payloads by design).
2. `uv run pytest tests/` — the offline suite must pass everywhere; the live
   suite (database + XFOIL) runs only when a Profili installation is reachable
   and self-skips otherwise.
3. If you have a Profili installation, also run
   `python -m profili_mcp --selftest` and paste its output into the PR — it
   proves your change against real data.

## Reporting bugs

Use the bug report template. Please always include:

- Profili version (the project is verified against **2.21**; behavior on other
  releases is useful information even when things break)
- the output of `python -m profili_mcp --selftest`
- the exact tool call (or script) and the full error message

## Scope notes

- The repository must never contain Profili binaries or its database — it only
  talks to an existing installation.
- Storage-format findings belong in `docs/SCHEMA.md` with the empirical
  evidence that validates them (see the existing entries for the convention).
