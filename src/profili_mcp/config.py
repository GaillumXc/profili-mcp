"""Locate the Profili installation and runtime resources.

Resolution order for the install directory:

1. Explicit argument passed to a tool.
2. ``PROFILI_DIR`` environment variable.
3. Cached value in ``%APPDATA%\\profili-mcp\\config.json`` (written after a
   successful probe).
4. Auto-discovery: search a set of shallow glob patterns for ``Profili.exe``
   together with ``Profili.mdb`` and ``Xfoil.exe``.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "profili-mcp"
CONFIG_FILE = CONFIG_DIR / "config.json"

ENV_VAR = "PROFILI_DIR"

# Shallow discovery globs. Kept deliberately narrow: Profili is a small,
# self-contained directory and we never want to walk a whole drive.
DISCOVERY_GLOBS = [
    "profili*/ProfiliV2",
    "profili*/**/Profili.exe",
]


@dataclass(frozen=True)
class ProfiliPaths:
    install_dir: Path
    exe: Path
    mdb: Path
    xfoil: Path
    ini: Path

    @property
    def running(self) -> bool:
        try:
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Profili.exe", "/nh"],
                capture_output=True, text=True, timeout=15, check=False,
            )
        except Exception:
            return False
        return "Profili.exe" in (out.stdout or "")


def _cache_read() -> Path | None:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        p = Path(data["install_dir"])
        return p if p.is_dir() else None
    except Exception:
        return None


def _cache_write(install_dir: Path) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps({"install_dir": str(install_dir)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        contextlib.suppress(Exception)  # caching is best-effort only


def _looks_like_profili(directory: Path) -> bool:
    return (
        (directory / "Profili.exe").is_file()
        and (directory / "Profili.mdb").is_file()
        and (directory / "Xfoil.exe").is_file()
    )


def _discover() -> Path | None:
    roots: list[Path] = []
    for drive in "CDEFGH":
        root = Path(f"{drive}:/")
        if root.is_dir():
            roots.append(root)
    # Common install parents first (fast path), then shallow recursive search.
    candidates: list[Path] = []
    for root in roots:
        for parent in (root, root / "Program Files", root / "Program Files (x86)"):
            if not parent.is_dir():
                continue
            try:
                for child in parent.iterdir():
                    if child.is_dir() and "profili" in child.name.lower():
                        candidates.append(child)
            except OSError:
                continue
    for base in candidates:
        try:
            for dirpath, dirnames, filenames in os.walk(base):
                # keep the search shallow and skip junk
                depth = Path(dirpath).relative_to(base).parts
                if len(depth) > 3:
                    dirnames[:] = []
                    continue
                if "Profili.exe" in filenames:
                    p = Path(dirpath)
                    if _looks_like_profili(p):
                        return p
        except OSError:
            continue
    return None


def resolve_install_dir(explicit: str | None = None) -> Path:
    """Resolve and validate the Profili install directory."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get(ENV_VAR)
    if env:
        candidates.append(Path(env))
    cached = _cache_read()
    if cached:
        candidates.append(cached)

    for cand in candidates:
        if cand.is_dir() and (cand / "Profili.exe").is_file():
            return _finalize(cand)

    found = _discover()
    if found:
        return _finalize(found)

    searched = [str(c) for c in candidates]
    raise FileNotFoundError(
        "Could not locate a Profili installation (need Profili.exe + Profili.mdb "
        f"+ Xfoil.exe in one directory). Set the {ENV_VAR} environment variable or "
        f"pass install_dir explicitly. Tried: {searched or '(nothing)'}"
    )


def _finalize(install_dir: Path) -> Path:
    mdb = install_dir / "Profili.mdb"
    if not mdb.is_file():
        raise FileNotFoundError(f"Profili.mdb not found in {install_dir}")
    _cache_write(install_dir)
    return install_dir


def get_paths(explicit: str | None = None) -> ProfiliPaths:
    install_dir = resolve_install_dir(explicit)
    return ProfiliPaths(
        install_dir=install_dir,
        exe=install_dir / "Profili.exe",
        mdb=install_dir / "Profili.mdb",
        xfoil=install_dir / "Xfoil.exe",
        ini=install_dir / "Profili.INI",
    )


def default_bridge_ps1() -> Path:
    return Path(__file__).with_name("bridge.ps1")


def platform_notes() -> str:
    bits = "64-bit" if sys.maxsize > 2**32 else "32-bit"
    return (
        f"Python {sys.version.split()[0]} ({bits}). The bundled Profili database "
        "requires the 32-bit 'Microsoft Access Driver (*.mdb)' ODBC driver; the "
        "bridge shells out to 32-bit Windows PowerShell automatically."
    )
