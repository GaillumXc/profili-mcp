# Changelog

## v0.1.1 — 2026-11-15

Packaging/metadata release: adds the `mcp-name` marker required by the MCP
Registry's PyPI ownership validation; published to PyPI and the MCP Registry.

## v0.1.0 — 2026-11-15

Initial release.

- 14 MCP tools over three control channels: Jet database (`Profili.mdb`)
  read/write via a 32-bit PowerShell ODBC bridge, the bundled XFOIL batch
  engine using Profili's own script recipes, and GUI process control.
- Empirically validated storage conventions (alpha offset, CL/Re scaling)
  documented in `docs/SCHEMA.md` with verification evidence.
- Write path with automatic backup, single-transaction batching, and
  same-connection identity capture.
- Worked example: NACA 2412 @ Re=3×10⁵ polar analysis with parameter
  extraction, matching both the built-in library polar and textbook values.
- `python -m profili_mcp --selftest` end-to-end check.
- Verified against Profili 2.21 only.
