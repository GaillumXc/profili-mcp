"""Parsers and serializers for the file formats Profili exchanges.

* ``.dat`` coordinate files (name line + upper surface TE->LE, then lower
  surface LE->TE). This is exactly the layout Profili writes for XFOIL.
* XFOIL ``Dati.pol`` polar dump files (PACC output).
* ``.cor`` files are byte-compatible with ``.dat`` in Profili.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class AirfoilGeometry:
    name: str = ""
    upper: list[tuple[float, float]] = field(default_factory=list)  # LE -> TE
    lower: list[tuple[float, float]] = field(default_factory=list)  # LE -> TE

    @property
    def n_points(self) -> int:
        return len(self.upper) + len(self.lower)

    def thickness_max(self) -> float:
        """Max thickness as chord fraction, evaluated on a dense common x-grid
        with linear interpolation between the two surfaces."""
        if not self.upper or not self.lower:
            return 0.0
        up = sorted(self.upper)
        lo = sorted(self.lower)

        def interp(surf: list[tuple[float, float]], x: float) -> float | None:
            xs = [p[0] for p in surf]
            if x < xs[0] or x > xs[-1]:
                return None
            import bisect
            i = bisect.bisect_left(xs, x)
            if i < len(xs) and xs[i] == x:
                return surf[i][1]
            i = max(1, min(i, len(xs) - 1))
            x0, y0 = surf[i - 1]
            x1, y1 = surf[i]
            t = (x - x0) / (x1 - x0) if x1 > x0 else 0.0
            return y0 + t * (y1 - y0)

        best = 0.0
        for i in range(1001):
            x = i / 1000.0
            yu, yl = interp(up, x), interp(lo, x)
            if yu is not None and yl is not None:
                best = max(best, yu - yl)
        return best

    def camber_max(self) -> float:
        if not self.upper or not self.lower:
            return 0.0
        return max((yu + min(self.lower, key=lambda p: abs(p[0] - xu))[1]) / 2
                   for xu, yu in self.upper)


def parse_dat(text: str, fallback_name: str = "") -> AirfoilGeometry:
    """Parse a Profili/XFOIL .dat file.

    Accepts both the canonical order (upper TE->LE then lower LE->TE) and
    reversed/merged orderings by detecting the leading edge (min x).
    """
    lines = text.splitlines()
    name = fallback_name
    pts: list[tuple[float, float]] = []
    for i, line in enumerate(lines):
        parts = line.split()
        if len(parts) >= 2:
            try:
                x, y = float(parts[0]), float(parts[1])
            except ValueError:
                if not pts and not name:
                    name = line.strip()
                continue
            pts.append((x, y))
        elif line.strip() and not pts and not name:
            name = line.strip()
    if len(pts) < 6:
        raise ValueError("not a valid coordinate file (need >= 6 numeric points)")

    le = min(range(len(pts)), key=lambda i: pts[i][0])
    # TE appears at both ends in canonical files; detect orientation
    first, last = pts[0], pts[-1]
    te_at_ends = abs(first[0] - 1.0) < 1e-3 and abs(last[0] - 1.0) < 1e-3
    if te_at_ends:
        # LE belongs to the upper surface only (stable roundtrip)
        upper = list(reversed(pts[: le + 1]))      # LE..TE
        lower = list(pts[le + 1:])                 # (LE)..TE
    else:
        # unknown ordering: split at LE, then sort each half by x
        upper = sorted(pts[: le + 1], key=lambda p: p[0])
        lower = sorted(pts[le + 1:], key=lambda p: p[0])
    return AirfoilGeometry(name=name, upper=upper, lower=lower)


def format_dat(geom: AirfoilGeometry) -> str:
    """Serialize in Profili's canonical layout: name, upper TE->LE, lower LE->TE.
    A duplicated leading-edge point at the start of the lower surface is
    dropped so the file contains the LE exactly once."""
    out = [geom.name or "airfoil"]
    out += [f"{x:9.5f}\t{y:9.5f}" for x, y in reversed(geom.upper)]
    lower = geom.lower
    if (geom.upper and lower
            and abs(lower[0][0] - geom.upper[0][0]) < 1e-9
            and abs(lower[0][1] - geom.upper[0][1]) < 1e-9):
        lower = lower[1:]
    out += [f"{x:9.5f}\t{y:9.5f}" for x, y in lower]
    return "\n".join(out) + "\n"


# --- XFOIL polar dump (Dati.pol) ---------------------------------------------

@dataclass
class XfoilPolarRow:
    alfa: float
    cl: float
    cdi: float
    cdv: float
    cd: float
    cdf: float
    cm: float
    xtr_top: float
    xtr_bot: float


def parse_dati_pol(text: str) -> list[XfoilPolarRow]:
    """Parse an XFOIL PACC dump file.

    Layout: several header lines, a column header line (``alpha CL CDi ...``),
    a dashed separator, then whitespace-separated floats.
    """
    col_header: list[str] | None = None
    rows: list[XfoilPolarRow] = []

    def slug(s: str) -> str:
        return re.sub(r"[^a-z_]", "", s.lower())

    for line in text.splitlines():
        low = line.lower()
        if low.lstrip().startswith("alpha") or (" cl" in low and "cd" in low):
            col_header = [slug(tok) for tok in line.split()]
            continue
        if col_header and ("---" in line or not line.strip()):
            if "---" in line:
                continue
            continue
        if not col_header:
            continue
        parts = line.split()
        if len(parts) < len(col_header):
            continue
        try:
            vals = [float(v) for v in parts[: len(col_header)]]
        except ValueError:
            continue
        rec = dict(zip(col_header, vals))

        def g(*names: str, default: float = 0.0) -> float:
            for n in names:
                if n in rec:
                    return rec[n]
            return default

        rows.append(XfoilPolarRow(
            alfa=g("alpha", "alfa"),
            cl=g("cl"),
            cdi=g("cdi"),
            cdv=g("cdv"),
            cd=g("cd"),
            cdf=g("cdf", "cdf_"),
            cm=g("cm"),
            xtr_top=g("top_xtr", "xtrtop", "xtr_top"),
            xtr_bot=g("bot_xtr", "xtrbot", "xtr_bot"),
        ))
    return rows
