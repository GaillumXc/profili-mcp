# profili-mcp

English | [中文](README.zh.md)

MCP server for the legacy [Profili 2.x](https://www.profili2.com/) airfoil software.

[Profili](https://www.profili2.com/eng/) is a classic airfoil design and analysis tool (2200+ airfoils, 1.26M polar data points) whose development ended around 2015. It has no scripting API and no COM/OLE automation interface, so this project works with the three interfaces it does have:

- its Jet database (`Profili.mdb`) — read *and* write, even while the GUI is running
- its bundled XFOIL solver — the same batch recipes Profili itself uses
- the application process — start / stop / detect

All of it is exposed as 14 MCP tools. As far as I can tell this is the first MCP server for Profili; the storage format findings that make it possible are documented in [docs/SCHEMA.md](docs/SCHEMA.md).

![NACA 2412 polar at Re=300k: computed vs Profili library](examples/figures/fig2_cl_alpha_cd_alpha.png)

*Worked example ([examples/](examples/)): NACA 2412 @ Re=3×10⁵ — computed polar vs the built-in library polar.*

## Tools

| Tool | What it does |
|---|---|
| `get_status` | Probe the installation: paths, database row counts, GUI state |
| `launch_profili` / `close_profili` | Start / stop the Profili GUI |
| `list_libraries` | List airfoil libraries |
| `search_airfoils` | Filter the library by name / thickness / camber / library |
| `get_airfoil_geometry` | Metadata + surface coordinates (chord fractions, LE→TE) |
| `export_airfoil_dat` | Export a `.dat` coordinate file |
| `import_airfoil_dat` | Import a `.dat` into the library (auto-backup) |
| `list_polars` | Reynolds numbers available for an airfoil |
| `get_polar` | Stored polar (CL/CD/CM vs α, SI units) |
| `find_airfoils_by_polar` | Search airfoils by performance at a given Re and α |
| `analyze_airfoil` | Fresh viscous polar via the bundled XFOIL; optional write-back into the library |
| `analyze_naca` | Polar for any NACA 4/5-digit airfoil without touching the library |
| `redesign_airfoil` | Rescale max thickness / camber (XFOIL GDES TSET); optional save as new airfoil |

## Install

Requires Windows, a Profili 2.x installation (`Profili.exe`, `Profili.mdb`, `Xfoil.exe` in one directory), and the 32-bit `Microsoft Access Driver (*.mdb)` ODBC driver (present by default on Windows 10/11; otherwise install [MDAC](https://www.microsoft.com/en-us/download/details.aspx?id=5793)).

```bash
git clone https://github.com/cjl123bili/profili-mcp.git
cd profili-mcp
uv sync          # or: pip install .
```

Point the server at your Profili directory — environment variable, or pass `install_dir` to any tool:

```bash
set PROFILI_DIR=D:\path\to\ProfiliV2
python -m profili_mcp --selftest     # end-to-end check: DB + scale conventions + XFOIL
```

## MCP client configuration

```json
{
  "mcpServers": {
    "profili": {
      "command": "python",
      "args": ["-m", "profili_mcp"],
      "env": { "PROFILI_DIR": "D:\\path\\to\\ProfiliV2" }
    }
  }
}
```

Works with Kimi Code, Claude Desktop, Cursor, and any stdio-MCP client.

## Safety

- Write operations back up `Profili.mdb` first (timestamped copy next to the original); `backup=False` opts out.
- The database stays accessible while the GUI runs, but the GUI does not refresh on its own — restart it to see imported airfoils or saved polars.
- Polars are written with the exact table layout Profili's own library importer uses (`PolariHeader` + `PolariCoordinate`).

## Examples

[examples/](examples/) has a complete worked analysis (NACA 2412 @ Re=3×10⁵): library geometry → polar computation → parameter extraction (`C_lmax` 1.3234, `α_stall` 15.0°, `α₀` −2.19°, `C_m0` −0.0499) with figures, matching both the built-in library polar and textbook values.

```
python examples/analysis_compute.py && python examples/analysis_naca2412.py
```

## Related projects

- [Three-Little-Birds/xfoil-mcp](https://github.com/Three-Little-Birds/xfoil-mcp), [Saxeman/xfoil-mcp](https://github.com/Saxeman/xfoil-mcp) — MCP servers for bare XFOIL; they don't touch the Profili library or database.
- [YanYaoyuan/passwing](https://github.com/YanYaoyuan/passwing) — Qt/C++ aerodynamics suite that can import `Profili.mdb`; a desktop application, not an agent interface.
- [devFoil / devWing](https://www.devcad.com) — the author's newer commercial series that superseded Profili.

## Known issues

- **Non-ASCII project path + editable install**: CPython reads `.pth` files with the locale encoding, so an editable install breaks if the clone path contains non-ASCII characters. Clone to an ASCII path, or run with `PYTHONPATH=src python -m profili_mcp`.
- This repository does not ship Profili itself (commercial, retired software); it only talks to an existing installation.

## Author & verification scope

The account owner ([cjl123bili](https://github.com/cjl123bili)) is an undergraduate student majoring in **Uncrewed Aircraft Systems Engineering**; this project is a personal work from coursework. **Every feature has been verified against Profili 2.21 only** — other releases (2.0/2.2x revisions, XT, Pro) are untested and may behave differently; issues welcome. Kimi K2.8 (Moonshot AI coding assistant) contributed to the reverse engineering, code, docs and examples, credited via `Co-authored-by` trailers.

## License

MIT, see [LICENSE](LICENSE). Profili is © devCAD / Stefano Nardone; XFOIL is by Mark Drela and ships with Profili. This project is for personal study and research.
