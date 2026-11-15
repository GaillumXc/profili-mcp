"""Step 1 of the NACA 2412 example: compute the polar with Profili's bundled
XFOIL and stash everything needed for plotting into a JSON file.

Run from the repo root with the project venv:

    PROFILI_DIR=D:\\path\\to\\ProfiliV2 PYTHONPATH=src python examples/analysis_compute.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from profili_mcp.config import get_paths
from profili_mcp.db import open_db
from profili_mcp.formats import AirfoilGeometry
from profili_mcp.xfoil import run_polar

CACHE = Path(__file__).resolve().parent / "naca2412_data.json"

RE = 300_000
NC = 9.0


def main() -> None:
    paths = get_paths()
    db = open_db()
    coords = db.coordinates("NACA 2412")
    geom = AirfoilGeometry(name="NACA 2412", upper=coords["upper"], lower=coords["lower"])
    rows = run_polar(paths.xfoil, geom=geom, re=RE, mach=0.0, ncrit=NC,
                     alfa_start=-8.0, alfa_end=18.0, alfa_step=0.5)
    stored = db.polar("NACA 2412", RE)
    data = {
        "computed": [[r.alfa, r.cl, r.cd, r.cm, r.cdi, r.cdv, r.xtr_top, r.xtr_bot]
                     for r in rows],
        "geometry": {"upper": geom.upper, "lower": geom.lower},
        "stored": [[p.alfa, p.cl, p.cd, p.cm] for p in stored["points"]],
        "stored_re": stored["re"],
    }
    CACHE.write_text(json.dumps(data), encoding="utf-8")
    peak = max(rows, key=lambda r: r.cl)
    print(f"{len(rows)} points -> {CACHE}")
    print(f"CLmax={peak.cl:.4f} @ alpha={peak.alfa}")


if __name__ == "__main__":
    main()
