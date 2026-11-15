"""MCP server exposing Profili 2.x (legacy airfoil software) to AI agents.

Profili was retired by its author and exposes no COM/OLE automation
interface. This server controls it through the three channels that do
exist:

1. its Jet database (Profili.mdb) via a 32-bit ODBC bridge,
2. the bundled Xfoil.exe batch engine (the same recipes Profili itself uses),
3. the process itself (launch / detect running instance).

Run ``python -m profili_mcp --selftest`` to validate the whole chain
against your installation before wiring it into an MCP client.
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
from pathlib import Path

from fastmcp import FastMCP

from .config import get_paths, platform_notes
from .db import BridgeError, PolarPoint, ProfiliDB
from .formats import AirfoilGeometry, format_dat, parse_dat
from .xfoil import redesign_thickness_camber, run_polar

mcp = FastMCP("profili-mcp")

_DEFAULT_INSTALL: str | None = os.environ.get("PROFILI_DIR") or None


def _db(install_dir: str | None = None, writable: bool = False) -> ProfiliDB:
    return ProfiliDB(install_dir=install_dir or _DEFAULT_INSTALL, writable=writable)


def _ok(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _err(exc: Exception) -> str:
    return json.dumps({"error": type(exc).__name__, "message": str(exc)},
                      ensure_ascii=False, indent=2)


def _geom(db: ProfiliDB, name: str) -> AirfoilGeometry:
    coords = db.coordinates(name)
    return AirfoilGeometry(name=name, upper=coords["upper"], lower=coords["lower"])


# ---------------------------------------------------------------------------
# status / process
# ---------------------------------------------------------------------------

@mcp.tool()
def get_status(install_dir: str | None = None) -> str:
    """Probe the Profili installation: paths, database row counts, whether the
    GUI is running, and platform notes. Call this first."""
    try:
        p = get_paths(install_dir)
        db = _db(install_dir)
        counts = db.counts()
        return _ok({
            "install_dir": str(p.install_dir),
            "exe": str(p.exe),
            "mdb": str(p.mdb),
            "xfoil": str(p.xfoil),
            "gui_running": p.running,
            "database": counts,
            "platform": platform_notes(),
        })
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def launch_profili(install_dir: str | None = None) -> str:
    """Start the Profili GUI."""
    try:
        p = get_paths(install_dir)
        subprocess.Popen([str(p.exe)], cwd=str(p.install_dir))
        return _ok({"launched": True, "pid_path": str(p.exe)})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def close_profili() -> str:
    """Close all running Profili GUI instances."""
    try:
        subprocess.run(["taskkill", "/IM", "Profili.exe", "/F"],
                       capture_output=True, timeout=30)
        return _ok({"closed": True})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# airfoil library (database)
# ---------------------------------------------------------------------------

@mcp.tool()
def list_libraries(install_dir: str | None = None) -> str:
    """List airfoil libraries defined in the Profili database."""
    try:
        return _ok({"libraries": _db(install_dir).libraries()})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def search_airfoils(name: str | None = None, library: int | None = None,
                    thickness_min: float | None = None, thickness_max: float | None = None,
                    camber_min: float | None = None, camber_max: float | None = None,
                    limit: int = 100, install_dir: str | None = None) -> str:
    """Search the 2200+ airfoil library. ``name`` is a SQL LIKE substring
    (e.g. 'NACA 24' or 'AG '). Thickness/camber bounds use the database's own
    units for MaxWidthSuCorda / MaxCamberSuCorda (see docs/SCHEMA.md)."""
    try:
        rows = _db(install_dir).search_airfoils(
            name=name, library=library, thickness_min=thickness_min,
            thickness_max=thickness_max, camber_min=camber_min,
            camber_max=camber_max, limit=limit)
        return _ok({"count": len(rows), "airfoils": rows})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_airfoil_geometry(name: str, install_dir: str | None = None) -> str:
    """Get an airfoil's metadata + full coordinates (chord fractions, LE->TE
    for both surfaces)."""
    try:
        db = _db(install_dir)
        meta = db.airfoil_meta(name)
        coords = db.coordinates(name)
        return _ok({
            "meta": meta,
            "upper": [[round(x, 6), round(y, 6)] for x, y in coords["upper"]],
            "lower": [[round(x, 6), round(y, 6)] for x, y in coords["lower"]],
            "n_upper": len(coords["upper"]),
            "n_lower": len(coords["lower"]),
        })
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def export_airfoil_dat(name: str, output_path: str | None = None,
                       install_dir: str | None = None) -> str:
    """Export an airfoil from the library to a Profili .dat coordinate file."""
    try:
        db = _db(install_dir)
        geom = _geom(db, name)
        text = format_dat(geom)
        if output_path:
            Path(output_path).write_text(text, encoding="utf-8")
            return _ok({"name": name, "path": output_path,
                        "n_points": geom.n_points})
        return _ok({"name": name, "dat": text})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def import_airfoil_dat(file_path: str, name: str | None = None,
                       library: int = 0, note: str = "",
                       backup: bool = True, install_dir: str | None = None) -> str:
    """Import a .dat coordinate file into the Profili library. The database is
    backed up first unless backup=False. Restart Profili afterwards if it was
    already running."""
    try:
        db = _db(install_dir, writable=True)
        geom = parse_dat(Path(file_path).read_text(encoding="utf-8", errors="replace"),
                         fallback_name=name or Path(file_path).stem)
        if name:
            geom.name = name
        if not geom.name:
            raise ValueError("airfoil name required")
        aid = db.insert_airfoil(geom.name, geom.upper, geom.lower,
                                library=library, note=note, backup=backup)
        return _ok({"inserted": geom.name, "airfoil_id": aid,
                    "backup_done": backup})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# polars (database + XFOIL)
# ---------------------------------------------------------------------------

@mcp.tool()
def list_polars(name: str, install_dir: str | None = None) -> str:
    """List the Reynolds numbers for which stored polars exist."""
    try:
        res = _db(install_dir).polars_available(name)
        return _ok({"airfoil": name, "reynolds_numbers": res})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def get_polar(name: str, re: int, install_dir: str | None = None) -> str:
    """Get the stored polar (CL/CD/CM vs alpha, degrees) at the Reynolds number
    closest to ``re``."""
    try:
        pol = _db(install_dir).polar(name, re)
        return _ok({
            "airfoil": pol["airfoil"], "re": pol["re"], "polar_id": pol["polar_id"],
            "points": [{"alfa": round(p.alfa, 2), "cl": round(p.cl, 5),
                        "cd": round(p.cd, 5), "cm": round(p.cm, 5)}
                       for p in pol["points"]],
        })
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def find_airfoils_by_polar(name_prefix: str, re: int, alfa: float,
                           min_cl: float | None = None,
                           max_cd: float | None = None,
                           min_cl_over_cd: float | None = None,
                           limit: int = 50, install_dir: str | None = None) -> str:
    """Search airfoils by aerodynamic performance at one operating point.

    Narrows by name prefix first (the polar table is huge), then evaluates the
    polar at ``alfa`` (linear interpolation) and applies the criteria."""
    try:
        db = _db(install_dir)
        candidates = db.search_airfoils(name=name_prefix, limit=500)
        results = []
        for cand in candidates:
            try:
                pol = db.polar(cand["Nome"], re)
            except (KeyError, BridgeError):
                continue
            pts = sorted(pol["points"], key=lambda p: p.alfa)
            # interpolate at requested alpha
            val = None
            for a, b in itertools.pairwise(pts):
                if a.alfa <= alfa <= b.alfa and b.alfa > a.alfa:
                    t = (alfa - a.alfa) / (b.alfa - a.alfa)
                    val = PolarPoint(alfa, a.cl + t * (b.cl - a.cl),
                                     a.cd + t * (b.cd - a.cd),
                                     a.cm + t * (b.cm - a.cm))
                    break
            if val is None or val.cd <= 0:
                continue
            if min_cl is not None and val.cl < min_cl:
                continue
            if max_cd is not None and val.cd > max_cd:
                continue
            if min_cl_over_cd is not None and (val.cl / val.cd) < min_cl_over_cd:
                continue
            results.append({"airfoil": cand["Nome"], "re": pol["re"],
                            "alfa": alfa, "cl": round(val.cl, 4),
                            "cd": round(val.cd, 5), "cm": round(val.cm, 4),
                            "cl_over_cd": round(val.cl / val.cd, 2)})
            if len(results) >= limit:
                break
        results.sort(key=lambda r: -r["cl_over_cd"])
        return _ok({"count": len(results), "matches": results})
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def analyze_airfoil(name: str, re: int = 100_000, mach: float = 0.0,
                    ncrit: float = 9.0, alfa_start: float = -4.0,
                    alfa_end: float = 10.0, alfa_step: float = 0.5,
                    save_to_db: bool = False, backup: bool = True,
                    install_dir: str | None = None) -> str:
    """Compute a fresh viscous polar with the bundled XFOIL (same recipe as
    Profili's own solver). If save_to_db=True the result is written into the
    Profili library and appears in the GUI after restart."""
    try:
        p = get_paths(install_dir)
        db = _db(install_dir)
        geom = _geom(db, name)
        rows = run_polar(p.xfoil, geom=geom, re=re, mach=mach, ncrit=ncrit,
                         alfa_start=alfa_start, alfa_end=alfa_end,
                         alfa_step=alfa_step)
        payload = {
            "airfoil": name, "re": re, "mach": mach, "ncrit": ncrit,
            "points": [{"alfa": round(r.alfa, 2), "cl": round(r.cl, 5),
                        "cd": round(r.cd, 6), "cm": round(r.cm, 5),
                        "xtr_top": round(r.xtr_top, 4),
                        "xtr_bot": round(r.xtr_bot, 4)} for r in rows],
        }
        if save_to_db:
            pdb = _db(install_dir, writable=True)
            pts = [PolarPoint(r.alfa, r.cl, r.cd, r.cm) for r in rows]
            payload["saved_polar_id"] = pdb.insert_polar(name, re, pts, backup=backup)
        return _ok(payload)
    except Exception as exc:
        return _err(exc)


@mcp.tool()
def analyze_naca(naca_code: str, re: int = 100_000, mach: float = 0.0,
                 ncrit: float = 9.0, alfa_start: float = -4.0,
                 alfa_end: float = 10.0, alfa_step: float = 0.5,
                 install_dir: str | None = None) -> str:
    """Compute a polar for any NACA 4/5-digit airfoil without touching the
    library (XFOIL generates the geometry itself)."""
    try:
        p = get_paths(install_dir)
        rows = run_polar(p.xfoil, naca=naca_code, re=re, mach=mach, ncrit=ncrit,
                         alfa_start=alfa_start, alfa_end=alfa_end,
                         alfa_step=alfa_step)
        return _ok({
            "naca": naca_code, "re": re, "mach": mach, "ncrit": ncrit,
            "points": [{"alfa": round(r.alfa, 2), "cl": round(r.cl, 5),
                        "cd": round(r.cd, 6), "cm": round(r.cm, 5)} for r in rows],
        })
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# redesign
# ---------------------------------------------------------------------------

@mcp.tool()
def redesign_airfoil(name: str, thickness: float | None = None,
                     camber: float | None = None, x_thickness: float = 0.30,
                     x_camber: float = 0.30,
                     save_as: str | None = None, backup: bool = True,
                     install_dir: str | None = None) -> str:
    """Rescale max thickness and/or camber (chord fractions) via XFOIL GDES
    TSET — the same 'modify airfoil' recipe Profili uses internally.
    If save_as is given, the new geometry is saved into the library under
    that name (and as a .dat file next to it)."""
    try:
        p = get_paths(install_dir)
        db = _db(install_dir)
        geom = _geom(db, name)
        new_geom = redesign_thickness_camber(p.xfoil, geom, thickness=thickness,
                                             camber=camber, x_thickness=x_thickness,
                                             x_camber=x_camber)
        out_name = save_as or f"{name} mod"
        new_geom.name = out_name
        dat_path = p.install_dir / (out_name.replace(" ", "_") + ".dat")
        dat_path.write_text(format_dat(new_geom), encoding="ascii")
        payload = {"source": name, "result": out_name, "dat_path": str(dat_path),
                   "n_points": new_geom.n_points,
                   "max_thickness": round(new_geom.thickness_max(), 5)}
        if save_as:
            pdb = _db(install_dir, writable=True)
            payload["airfoil_id"] = pdb.insert_airfoil(
                out_name, new_geom.upper, new_geom.lower, backup=backup)
        return _ok(payload)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# self test
# ---------------------------------------------------------------------------

def selftest(install_dir: str | None = None) -> dict:
    """Exercise every channel end to end and cross-validate the scale
    conventions against live XFOIL output."""
    report: dict = {"steps": []}

    def step(name: str, ok: bool, detail: str = ""):
        report["steps"].append({"step": name, "ok": ok, "detail": detail})
        print(f"[{'OK' if ok else 'FAIL'}] {name} {('- ' + detail) if detail else ''}")
        if not ok:
            report["ok"] = False

    report["ok"] = True
    try:
        p = get_paths(install_dir)
        step("paths", True, str(p.install_dir))
    except Exception as exc:
        step("paths", False, str(exc))
        return report

    try:
        db = _db(install_dir)
        counts = db.counts()
        step("database", counts.get("Profili", 0) > 0, json.dumps(counts))
    except Exception as exc:
        step("database", False, str(exc))
        return report

    try:
        db = _db(install_dir)
        pol = db.polar("NACA 2412", 400_000)
        at0 = min(pol["points"], key=lambda q: abs(q.alfa))
        ok = abs(at0.cl - 0.2232) < 0.02 and abs(at0.cm + 0.0493) < 0.01
        step("scale_conventions", ok,
             f"NACA2412 Re=400k @alpha=0: CL={at0.cl:.4f} CM={at0.cm:.4f} "
             f"(expect CL~0.2232, CM~-0.0493)")
    except Exception as exc:
        step("scale_conventions", False, str(exc))

    try:
        rows = run_polar(p.xfoil, naca="2412", re=100_000,
                         alfa_start=0.0, alfa_end=0.0, alfa_step=1.0)
        r = rows[0]
        ok = abs(r.cl - 0.25) < 0.15  # NACA2412 CL(0deg) ~ 0.25 inviscid-ish
        step("xfoil", ok, f"NACA2412 Re=100k @alpha=0: CL={r.cl:.4f} CD={r.cd:.5f}")
    except Exception as exc:
        step("xfoil", False, str(exc))

    try:
        geom = _geom(db, "AG 16")
        t = geom.thickness_max()
        ok = 0.06 < t < 0.08
        step("geometry", ok, f"AG 16 max thickness = {t:.4f} (expect ~0.071)")
    except Exception as exc:
        step("geometry", False, str(exc))

    return report


def main() -> None:
    import sys
    if "--selftest" in sys.argv:
        report = selftest()
        raise SystemExit(0 if report.get("ok") else 1)
    mcp.run()


if __name__ == "__main__":
    main()
