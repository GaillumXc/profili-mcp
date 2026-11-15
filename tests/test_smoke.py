"""Smoke tests.

Offline tests always run. Live tests (database / xfoil) are skipped unless a
Profili installation is available via PROFILI_DIR or auto-discovery.

Run with:  python -m pytest tests/ -v     (or simply run this file directly)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from profili_mcp.formats import AirfoilGeometry, format_dat, parse_dat  # noqa: E402

DAT_SAMPLE = """TEST FOIL
   1.00000\t   0.00026
   0.99653\t   0.00063
   0.98981\t   0.00135
   0.50000\t   0.03000
   0.00000\t   0.00000
   0.50000\t  -0.01000
   0.98981\t  -0.00135
   1.00000\t  -0.00067
"""


def test_parse_dat_roundtrip():
    geom = parse_dat(DAT_SAMPLE)
    assert geom.name == "TEST FOIL"
    # sample: 4 upper points + LE, then 3 lower points (LE not repeated)
    assert len(geom.upper) == 5 and len(geom.lower) == 3
    # upper ordered LE -> TE
    assert geom.upper[0][0] == 0.0
    assert geom.upper[-1][0] == 1.0
    # lower ordered (LE)..TE, without the duplicated LE point
    assert geom.lower[0][0] == 0.5
    assert geom.lower[-1][0] == 1.0
    # roundtrip preserves point count
    geom2 = parse_dat(format_dat(geom))
    assert geom2.n_points == geom.n_points == 8
    assert abs(geom2.upper[1][1] - geom.upper[1][1]) < 1e-6


def test_thickness():
    geom = parse_dat(DAT_SAMPLE)
    t = geom.thickness_max()
    assert 0.03 < t < 0.06  # ~0.04 at mid-chord in the sample


# ---------------------------------------------------------------------------
# live tests (need a real Profili installation)
# ---------------------------------------------------------------------------

def _live():
    if os.environ.get("PROFILI_SKIP_LIVE"):
        return False
    try:
        from profili_mcp.config import get_paths
        get_paths()
        return True
    except Exception:
        return False


def test_live_database():
    if not _live():
        import pytest
        pytest.skip("no Profili installation found")
    from profili_mcp.db import open_db
    db = open_db()
    counts = db.counts()
    assert counts["Profili"] > 1000
    res = db.polars_available("NACA 2412")
    assert 400_000 in res or len(res) > 5


def test_live_xfoil():
    if not _live():
        import pytest
        pytest.skip("no Profili installation found")
    from profili_mcp.config import get_paths
    from profili_mcp.xfoil import run_polar
    rows = run_polar(get_paths().xfoil, naca="2412", re=100_000,
                     alfa_start=0.0, alfa_end=0.0, alfa_step=1.0)
    assert rows and abs(rows[0].cl - 0.25) < 0.15


if __name__ == "__main__":
    test_parse_dat_roundtrip()
    test_thickness()
    print("offline tests OK")
    if _live():
        test_live_database()
        test_live_xfoil()
        print("live tests OK")
    else:
        print("live tests SKIPPED (no Profili installation found)")
