"""Access the Profili Jet (.mdb) database through a 32-bit PowerShell bridge.

Profili stores everything in ``Profili.mdb`` (Jet 4.0). The only ODBC driver
for Jet on modern Windows is 32-bit, so queries are executed by
``bridge.ps1`` running under 32-bit ``powershell.exe`` (SysWOW64). Python
talks to the bridge over argv (Unicode-safe) and JSON on stdout (UTF-8).

Storage conventions discovered empirically (validated against textbook
NACA 2412 values and symmetric Joukowski profiles):

* ``alfa``   stored as ``(alpha_deg + 10) * 10``  -> decode: raw/10 - 10
* ``CL/CD/CM`` stored as value * 10000
* ``Re``     stored as Re / 1000
* ``Coordinate.X/Y`` stored in percent chord; ``FlagSopraSotto`` 0 = upper
  surface, 1 = lower surface.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import ProfiliPaths, default_bridge_ps1, get_paths

# --- scale conventions -------------------------------------------------------
ALFA_OFFSET_DEG = -10.0
ALFA_SCALE = 10.0
COEF_SCALE = 10000.0
RE_DIVISOR = 1000.0
COORD_PERCENT = 100.0

FLAG_UPPER = 0
FLAG_LOWER = 1

DRIVER_NAME = "Microsoft Access Driver (*.mdb)"


class BridgeError(RuntimeError):
    pass


def _powershell32() -> list[str]:
    syswow64 = Path(r"C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe")
    if syswow64.is_file():
        return [str(syswow64)]
    return ["powershell.exe"]


def run_bridge(dbq: Path, sql: str, mode: str = "query", timeout: int = 300) -> Any:
    """Run one SQL statement through the 32-bit bridge and return the result.

    mode='query'  -> list[dict]
    mode='scalar' -> scalar or None
    mode='exec'   -> rows affected (int)
    """
    argv = [
        *_powershell32(),
        "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(default_bridge_ps1()),
        "-Dbq", str(dbq),
        "-Sql", sql,
        "-Mode", mode,
        "-TimeoutSec", str(timeout),
    ]
    if sql == "" and mode in ("query", "scalar", "exec"):
        raise BridgeError("empty SQL statement")
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=timeout + 30, check=False)
    except subprocess.TimeoutExpired as exc:
        raise BridgeError(f"bridge timed out after {timeout}s: {sql[:120]}") from exc
    if proc.returncode != 0:
        # bridge.ps1 emits BRIDGE_ERROR on stdout (UTF-8); stderr may hold
        # PowerShell's own locale-encoded messages as a fallback only.
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        err = proc.stderr.decode("gbk", errors="replace").strip()
        raise BridgeError(f"bridge error: {out or err or '(no output)'}")
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    if not out:
        return [] if mode == "query" else None
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise BridgeError(f"bridge returned non-JSON: {out[:400]}") from exc
    if mode == "query":
        if isinstance(data, dict):
            data = [data]
        # bridge wraps single-row results; unwrap accidental nesting
        while data and isinstance(data[0], list):
            data = data[0]
        return [{k.lower(): v for k, v in row.items()} for row in data]
    if mode == "exec":
        return data  # dict with affected + identity
    return data


def esc(value: str) -> str:
    """Escape a string literal for Jet SQL (ODBC)."""
    return value.replace("'", "''")


def decode_alfa(raw: float) -> float:
    return raw / ALFA_SCALE + ALFA_OFFSET_DEG


def encode_alfa(alpha_deg: float) -> int:
    return round((alpha_deg - ALFA_OFFSET_DEG) * ALFA_SCALE)


def decode_coef(raw: float) -> float:
    return raw / COEF_SCALE


def encode_coef(value: float) -> int:
    return round(value * COEF_SCALE)


def decode_re(raw: float) -> int:
    return round(raw * RE_DIVISOR)


def encode_re(re: int) -> int:
    return round(re / RE_DIVISOR)


# --- database ----------------------------------------------------------------

@dataclass
class PolarPoint:
    alfa: float      # degrees
    cl: float
    cd: float
    cm: float


class ProfiliDB:
    """Typed access layer over Profili.mdb."""

    def __init__(self, paths: ProfiliPaths | None = None, install_dir: str | None = None,
                 writable: bool = False):
        self.paths = paths or get_paths(install_dir)
        self.writable = writable

    # -- low level -----------------------------------------------------------
    def query(self, sql: str) -> list[dict]:
        return run_bridge(self.paths.mdb, sql, "query")

    def scalar(self, sql: str) -> Any:
        return run_bridge(self.paths.mdb, sql, "scalar")

    def exec(self, sql: str) -> int:
        if not self.writable:
            raise PermissionError("ProfiliDB opened read-only; pass writable=True for write tools")
        data = run_bridge(self.paths.mdb, sql, "exec")
        return int(data.get("affected", 0)) if isinstance(data, dict) else 0

    def exec_insert(self, sql: str) -> int | None:
        """INSERT and return @@IDENTITY from the same connection (Jet resets
        it per connection, so a separate SELECT would return garbage)."""
        if not self.writable:
            raise PermissionError("ProfiliDB opened read-only; pass writable=True for write tools")
        data = run_bridge(self.paths.mdb, sql, "exec")
        if isinstance(data, dict):
            ident = data.get("identity")
            return int(ident) if ident is not None else None
        return None

    def exec_many(self, statements: list[str]) -> int:
        """Execute many non-query statements in ONE bridge call, inside a
        single transaction (Jet does not support multi-row VALUES inserts,
        and constant derived tables are forbidden)."""
        if not self.writable:
            raise PermissionError("ProfiliDB opened read-only; pass writable=True for write tools")
        if not statements:
            return 0
        try:
            with tempfile.NamedTemporaryFile(
                    "w", suffix=".json", encoding="utf-8", delete=False) as tmp:
                json.dump(statements, tmp, ensure_ascii=False)
                tmp_name = tmp.name
            argv = [
                *_powershell32(),
                "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", str(default_bridge_ps1()),
                "-Dbq", str(self.paths.mdb),
                "-SqlFile", tmp_name,
                "-Mode", "batch",
                "-TimeoutSec", "300",
            ]
            proc = subprocess.run(argv, capture_output=True, timeout=360, check=False)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
        if proc.returncode != 0:
            out = proc.stdout.decode("utf-8", errors="replace").strip()
            err = proc.stderr.decode("gbk", errors="replace").strip()
            raise BridgeError(f"bridge batch error: {out or err or '(no output)'}")
        data = json.loads(proc.stdout.decode("utf-8", errors="replace").strip())
        return int(data.get("affected", 0))

    # -- status --------------------------------------------------------------
    def counts(self) -> dict:
        out = {}
        for table in ("Profili", "Coordinate", "PolariHeader", "PolariCoordinate", "Librerie"):
            out[table] = int(self.scalar(f"SELECT COUNT(*) FROM {table}"))
        return out

    def libraries(self) -> list[dict]:
        return self.query("SELECT * FROM Librerie")

    # -- airfoils ------------------------------------------------------------
    def search_airfoils(self, name: str | None = None, library: int | None = None,
                        thickness_min: float | None = None, thickness_max: float | None = None,
                        camber_min: float | None = None, camber_max: float | None = None,
                        limit: int = 100) -> list[dict]:
        """Search the Profili table. Thickness/camber filters use the same
        units stored in MaxWidthSuCorda / MaxCamberSuCorda (see SCHEMA.md)."""
        where: list[str] = []
        if name:
            where.append(f"Nome LIKE '%{esc(name)}%'")
        if library is not None:
            where.append(f"CodiceLibreria = {int(library)}")
        if thickness_min is not None:
            where.append(f"MaxWidthSuCorda >= {thickness_min}")
        if thickness_max is not None:
            where.append(f"MaxWidthSuCorda <= {thickness_max}")
        if camber_min is not None:
            where.append(f"MaxCamberSuCorda >= {camber_min}")
        if camber_max is not None:
            where.append(f"MaxCamberSuCorda <= {camber_max}")
        sql = ("SELECT Id, Nome, Note, MaxWidth, MaxWidthSuCorda, MaxCamber, MaxCamberSuCorda, "
               "CodiceLibreria, IdInLibreria FROM Profili")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY Nome"
        if limit and limit > 0:
            sql = sql.replace("SELECT", f"SELECT TOP {int(limit)}", 1)
        return self.query(sql)

    def airfoil_id_by_name(self, name: str) -> int:
        rows = self.query(
            f"SELECT Id, Nome FROM Profili WHERE Nome = '{esc(name)}' ORDER BY Id")
        if not rows:
            raise KeyError(f"airfoil not found: {name!r} (search is exact; try search_airfoils)")
        if len(rows) > 1:
            # pick the first but make the caller aware
            pass
        return int(rows[0]["id"])

    def airfoil_meta(self, name: str) -> dict:
        rows = self.query(
            "SELECT Id, Nome, Note, MaxWidth, MaxWidthSuCorda, MaxCamber, MaxCamberSuCorda, "
            f"CodiceLibreria, IdInLibreria FROM Profili WHERE Nome = '{esc(name)}' ORDER BY Id")
        if not rows:
            raise KeyError(f"airfoil not found: {name!r}")
        return rows[0]

    # -- geometry ------------------------------------------------------------
    def coordinates(self, name: str) -> dict:
        """Return {'upper': [(x,y),...], 'lower': [...]} as chord fractions,
        each ordered LE -> TE."""
        aid = self.airfoil_id_by_name(name)
        rows = self.query(
            "SELECT FlagSopraSotto, X, Y FROM Coordinate "
            f"WHERE Fk_Id_Profilo = {aid} ORDER BY FlagSopraSotto, X")
        upper: list[tuple[float, float]] = []
        lower: list[tuple[float, float]] = []
        for r in rows:
            x = float(r["x"]) / COORD_PERCENT
            y = float(r["y"]) / COORD_PERCENT
            (upper if int(r["flagsoprasotto"]) == FLAG_UPPER else lower).append((x, y))
        return {"airfoil_id": aid, "upper": upper, "lower": lower}

    # -- polars --------------------------------------------------------------
    def polars_available(self, name: str) -> list[int]:
        aid = self.airfoil_id_by_name(name)
        rows = self.query(
            f"SELECT Re FROM PolariHeader WHERE Fk_Id_Profilo = {aid} ORDER BY Re")
        return [decode_re(r["re"]) for r in rows]

    def polar(self, name: str, re: int) -> dict:
        """Polar at the closest available Reynolds number."""
        aid = self.airfoil_id_by_name(name)
        header = self.query(
            "SELECT TOP 1 Id, Re FROM PolariHeader "
            f"WHERE Fk_Id_Profilo = {aid} ORDER BY ABS(Re - {encode_re(re)})")
        if not header:
            raise KeyError(f"no polars stored for {name!r}")
        hid = int(header[0]["id"])
        rows = self.query(
            "SELECT Alfa, CL, CD, CM FROM PolariCoordinate "
            f"WHERE Fk_Id_Polare = {hid} ORDER BY Alfa")
        points = [
            PolarPoint(
                alfa=decode_alfa(float(r["alfa"])),
                cl=decode_coef(float(r["cl"])),
                cd=decode_coef(float(r["cd"])),
                cm=decode_coef(float(r["cm"])),
            )
            for r in rows
        ]
        return {
            "airfoil": name,
            "airfoil_id": aid,
            "polar_id": hid,
            "re": decode_re(header[0]["re"]),
            "points": points,
        }

    # -- write ---------------------------------------------------------------
    def backup(self) -> Path:
        """Copy the live .mdb next to itself with a timestamp suffix."""
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = self.paths.mdb.with_name(f"{self.paths.mdb.stem}.bak-{ts}{self.paths.mdb.suffix}")
        shutil.copy2(self.paths.mdb, dest)
        return dest

    def insert_airfoil(self, name: str, upper: list[tuple[float, float]],
                       lower: list[tuple[float, float]], library: int = 0,
                       note: str = "", backup: bool = True) -> int:
        """Insert a new airfoil (coordinates as chord fractions). Returns new Id.

        Jet multi-row INSERT .. SELECT .. UNION ALL is used for speed.
        """
        if backup:
            self.backup()
        ys_u = [y for _, y in upper]
        ys_l = [y for _, y in lower]
        max_thick = max(ys_u) - min(ys_l)
        max_camber = (max(ys_u) + min(ys_l)) / 2.0 if ys_u and ys_l else 0.0
        if not note:
            note = " "  # Profili.Note disallows zero-length strings
        next_in_lib = self.scalar(
            "SELECT MAX(IdInLibreria) FROM Profili "
            f"WHERE CodiceLibreria = {int(library)}")
        next_in_lib = (int(next_in_lib) + 1) if next_in_lib is not None else 1
        ident = self.exec_insert(
            "INSERT INTO [Profili] ([Nome], [Note], [MaxWidth], [MaxWidthSuCorda], [MaxCamber], "
            "[MaxCamberSuCorda], [CodiceLibreria], [IdInLibreria]) VALUES "
            f"('{esc(name)}', '{esc(note)}', {max_thick * COORD_PERCENT:.6f}, {max_thick:.6f}, "
            f"{max_camber * COORD_PERCENT:.6f}, {max_camber:.6f}, {int(library)}, {next_in_lib})")
        if ident is None:
            raise BridgeError("INSERT INTO Profili succeeded but @@IDENTITY is unavailable")
        aid = ident
        self._insert_coordinate_rows(aid, upper, lower)
        return aid

    def _insert_coordinate_rows(self, aid: int, upper: list[tuple[float, float]],
                                lower: list[tuple[float, float]]) -> None:
        stmts: list[str] = []
        for flag, pts in ((FLAG_UPPER, upper), (FLAG_LOWER, lower)):
            for x, y in pts:
                stmts.append(
                    "INSERT INTO [Coordinate] ([Fk_Id_Profilo], [FlagSopraSotto], [X], [Y]) "
                    f"VALUES ({aid}, {flag}, {x * COORD_PERCENT:.6f}, {y * COORD_PERCENT:.6f})")
        self.exec_many(stmts)

    def insert_polar(self, name: str, re: int, points: Iterable[PolarPoint],
                     backup: bool = True) -> int:
        """Insert a computed polar so it appears inside Profili. Returns header Id."""
        if backup:
            self.backup()
        aid = self.airfoil_id_by_name(name)
        hid = self.exec_insert(
            "INSERT INTO [PolariHeader] ([Fk_Id_Profilo], [Re]) VALUES "
            f"({aid}, {encode_re(re)})")
        if hid is None:
            raise BridgeError("INSERT INTO PolariHeader succeeded but @@IDENTITY is unavailable")
        stmts = [
            "INSERT INTO [PolariCoordinate] ([Fk_Id_Polare], [Alfa], [CL], [CD], [CM]) VALUES "
            f"({hid}, {encode_alfa(p.alfa)}, {encode_coef(p.cl)}, "
            f"{encode_coef(p.cd)}, {encode_coef(p.cm)})"
            for p in points
        ]
        self.exec_many(stmts)
        return hid


def open_db(install_dir: str | None = None, writable: bool = False) -> ProfiliDB:
    return ProfiliDB(install_dir=install_dir, writable=writable)
