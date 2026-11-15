"""Drive the bundled Xfoil.exe exactly the way Profili does.

Two recipes ported from the scripts shipped with Profili 2.21:

* ``ScriptXFoil.cmd`` — viscous polar sweep: LOAD -> GDES/CADD -> PANE ->
  FILT -> PANE -> OPER (VPAR N, VACC, TYPE, VISC, MACH, ITER) -> ALFA/INIT ->
  PACC <polfile> -> ASEQ start end step -> QUIT
* ``ScriptThCa.cmd``  — thickness/camber redesign: LOAD -> GDES TSET ->
  HIGH -> exec -> save

XFOIL is fed the command script on stdin and its PACC dump is parsed with
:func:`profili_mcp.formats.parse_dati_pol`.
"""

from __future__ import annotations

import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from .formats import (AirfoilGeometry, XfoilPolarRow, format_dat, parse_dati_pol,
                      parse_dat)


class XfoilError(RuntimeError):
    pass


@dataclass
class XfoilPaths:
    exe: Path
    workdir: Path
    script: Path
    coords: Path
    pol: Path


def _new_workdir(base: Path | None = None) -> XfoilPaths:
    wd = Path(tempfile.mkdtemp(prefix="profili-mcp-xfoil-", dir=str(base) if base else None))
    pol_name = f"pol_{uuid.uuid4().hex[:8]}.pol"
    return XfoilPaths(
        exe=Path(),
        workdir=wd,
        script=wd / "script.cmd",
        coords=wd / "coords.dat",
        pol=wd / pol_name,
    )


def _run(xfoil_exe: Path, paths: XfoilPaths) -> str:
    script_text = paths.script.read_text(encoding="ascii")
    try:
        proc = subprocess.run(
            [str(xfoil_exe)],
            input=script_text,
            capture_output=True,
            text=True,
            encoding="ascii",
            errors="replace",
            timeout=600,
            cwd=str(paths.workdir),
        )
    except subprocess.TimeoutExpired as exc:
        raise XfoilError("XFOIL timed out (600s)") from exc
    return proc.stdout or ""


def run_polar(xfoil_exe: Path, geom: AirfoilGeometry | None = None,
              naca: str | None = None, re: int = 100_000, mach: float = 0.0,
              ncrit: float = 9.0, vacc: float = 0.01, iters: int = 100,
              alfa_start: float = -4.0, alfa_end: float = 10.0,
              alfa_step: float = 0.5, filter_bump: float | None = None) -> list[XfoilPolarRow]:
    """Compute a viscous polar sweep. Provide ``geom`` or a 4/5-digit ``naca`` code."""
    if geom is None and not naca:
        raise ValueError("provide either geom or naca")
    paths = _new_workdir()
    paths.exe = xfoil_exe

    lines: list[str] = []
    if naca:
        lines += [f"NACA {naca}", ""]
    else:
        paths.coords.write_text(format_dat(geom), encoding="ascii")
        lines += [f"LOAD {paths.coords.name}", ""]
    lines += [
        "GDES", "CADD", "", "", "", "",
        "PANE",
    ]
    if filter_bump:
        lines += [f"FILT {filter_bump:.2f}"]
    lines += [
        "PANE",
        "OPER",
        "VPAR",
        f"N {ncrit:.2f}",
        f"VACC {vacc:.4f}",
        "",
        "TYPE 1",
        f"VISC {re}",
        f"MACH {mach:.4f}",
        "ITER",
        str(iters),
        f"ALFA {alfa_start:.2f}",
        "INIT",
        f"ALFA {alfa_start:.2f}",
        "PACC",
        paths.pol.name,
        "",
        f"ASEQ {alfa_start:.2f} {alfa_end:.2f} {alfa_step:.2f}",
        "PACC",
        "",
        "QUIT",
    ]
    paths.script.write_text("\n".join(lines) + "\n", encoding="ascii")
    output = _run(xfoil_exe, paths)
    if not paths.pol.is_file():
        tail = "\n".join(output.splitlines()[-15:])
        raise XfoilError(f"XFOIL produced no polar dump.\n--- xfoil output tail ---\n{tail}")
    rows = parse_dati_pol(paths.pol.read_text(encoding="ascii", errors="replace"))
    if not rows:
        raise XfoilError("polar dump was parsed but contains no data points")
    return rows


def redesign_thickness_camber(xfoil_exe: Path, geom: AirfoilGeometry,
                              thickness: float | None = None,
                              camber: float | None = None,
                              x_thickness: float = 0.30,
                              x_camber: float = 0.30) -> AirfoilGeometry:
    """Rescale max thickness/camber (chord fractions) via GDES TSET, following
    Profili's ``ScriptThCa.cmd``. Unspecified parameters keep the input shape."""
    paths = _new_workdir()
    paths.exe = xfoil_exe
    paths.coords.write_text(format_dat(geom), encoding="ascii")
    out_name = "redesigned.dat"

    lines = [
        f"LOAD {paths.coords.name}",
        "GDES",
        "TSET",
    ]
    if thickness is not None:
        lines.append(f"{thickness * 100:.4f}")
    else:
        lines.append("")          # keep current thickness
    if camber is not None:
        lines.append(f"{camber * 100:.4f}")
    else:
        lines.append("")
    lines += [
        "HIGH",
        f"{x_thickness:.4f}",
        f"{x_camber:.4f}",
        "exec",
        "",
        f"save {out_name}",
        "",
        "QUIT",
    ]
    paths.script.write_text("\n".join(lines) + "\n", encoding="ascii")
    output = _run(xfoil_exe, paths)
    out_file = paths.workdir / out_name
    if not out_file.is_file():
        tail = "\n".join(output.splitlines()[-15:])
        raise XfoilError(f"TSET redesign failed (no output file).\n--- tail ---\n{tail}")
    return parse_dat(out_file.read_text(encoding="ascii", errors="replace"),
                     fallback_name=geom.name)
