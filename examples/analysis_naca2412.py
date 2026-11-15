"""NACA 2412 极曲线分析：从缓存数据出图并提取参数。

数据来源：analysis_compute.py 已用 Profili 2.21 内嵌 XFOIL 完成计算
（Re=3e5, Mach=0, NCrit=9, alpha=-8..18 deg, step 0.5），
并读取了 Profili 自带翼型库中 NACA 2412 在 Re=300k 的存储极曲线作对比。
"""

from __future__ import annotations

import csv
import itertools
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA = Path(__file__).resolve().parent / "naca2412_data.json"
OUT = Path(r"D:\20-当前进行项目Active这周在做的任务\20-课程推进 备考\空气动力学\气动仿真报告")
OUT.mkdir(parents=True, exist_ok=True)

d = json.loads(DATA.read_text(encoding="utf-8"))
comp = d["computed"]           # alfa, cl, cd, cm, cdi, cdv, xtr_top, xtr_bot
stored = d["stored"]           # alfa, cl, cd, cm
geom = d["geometry"]
RE = d.get("stored_re", 300_000)

# --- extract parameters ------------------------------------------------------
def interp_zero_lift(pts):
    pts = sorted(pts, key=lambda r: r[0])
    for r1, r2 in itertools.pairwise(pts):
        a1, c1 = r1[0], r1[1]
        a2, c2 = r2[0], r2[1]
        if c1 == 0.0:
            return a1, r1[3]
        if c1 * c2 < 0 and c2 != c1:
            t = (0.0 - c1) / (c2 - c1)
            return a1 + t * (a2 - a1), r1[3] + t * (r2[3] - r1[3])
    return None, None

peak = max(comp, key=lambda r: r[1])
cl_max, alpha_stall = peak[1], peak[0]
alpha_0, cm_at_cl0 = interp_zero_lift(comp)
cm_at_0 = min(comp, key=lambda r: abs(r[0]))[3]
clcd = [(r[0], r[1], r[2], r[1] / r[2]) for r in comp if r[2] > 0]
ld_peak = max(clcd, key=lambda t: t[3])
cl_13 = min(comp, key=lambda r: abs(r[0] - 13.0))
stored_peak = max(stored, key=lambda r: r[1])

params = {
    "CLmax": round(cl_max, 4), "alpha_stall": alpha_stall,
    "alpha_0": round(alpha_0, 3), "Cm0_alpha0": round(cm_at_0, 4),
    "Cm_at_CL0": round(cm_at_cl0, 4),
    "CL_at_13": round(cl_13[1], 4),
    "LD_max": round(ld_peak[3], 1), "LD_max_alpha": ld_peak[0],
    "stored_CLmax_at_13": round(stored_peak[1], 4),
}
(OUT / "parameters.json").write_text(
    json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(params, ensure_ascii=False, indent=2))

# --- CSV ---------------------------------------------------------------------
with (OUT / "NACA2412_polar_data.csv").open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["alpha_deg", "CL", "CD", "CM", "CDi", "CDv", "Xtr_top", "Xtr_bot"])
    w.writerows([[f"{r[0]:.2f}", f"{r[1]:.5f}", f"{r[2]:.6f}", f"{r[3]:.5f}",
                  f"{r[4]:.6f}", f"{r[5]:.6f}", f"{r[6]:.4f}", f"{r[7]:.4f}"] for r in comp])

# --- figures -----------------------------------------------------------------
plt.rcParams.update({"font.size": 11})

fig, ax = plt.subplots(figsize=(7, 3.0))
ax.plot([p[0] for p in geom["upper"]], [p[1] for p in geom["upper"]], "b-", lw=1.6, label="Upper")
ax.plot([p[0] for p in geom["lower"]], [p[1] for p in geom["lower"]], "r-", lw=1.6, label="Lower")
ax.set_aspect("equal", adjustable="box")
ax.set(xlabel="x/c", ylabel="y/c", xlim=(-0.05, 1.05), ylim=(-0.12, 0.2))
ax.set_title("NACA 2412 geometry (Profili library, t/c = 12%)")
ax.grid(alpha=0.3)
ax.legend(loc="lower right", fontsize=9)
ax.axhline(0, color="k", lw=0.5)
fig.tight_layout()
fig.savefig(OUT / "fig1_airfoil_geometry.png", dpi=200)
plt.close(fig)

fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
axes[0].plot([r[0] for r in comp], [r[1] for r in comp], "b.-", ms=4, label="XFOIL (this work)")
axes[0].plot([r[0] for r in stored], [r[1] for r in stored], "r.--", ms=3,
             label=f"Profili library (Re={RE//1000}k)")
axes[0].plot(alpha_stall, cl_max, "k*", ms=13,
             label=f"$C_{{lmax}}$={cl_max:.3f} @ $\\alpha_{{stall}}$={alpha_stall:.1f}°")
axes[0].plot(alpha_0, 0, "gs", ms=8, label=f"$\\alpha_0$={alpha_0:.2f}°")
axes[0].set(xlabel=r"$\alpha$ (deg)", ylabel=r"$C_l$", title=r"$C_l-\alpha$")
axes[0].grid(alpha=0.3)
axes[0].legend(fontsize=8.5, loc="lower right")

axes[1].plot([r[0] for r in comp], [r[2] for r in comp], "b.-", ms=4, label="XFOIL (this work)")
axes[1].plot([r[0] for r in stored], [r[2] for r in stored], "r.--", ms=3,
             label=f"Profili library (Re={RE//1000}k)")
axes[1].set(xlabel=r"$\alpha$ (deg)", ylabel=r"$C_d$", title=r"$C_d-\alpha$")
axes[1].grid(alpha=0.3)
axes[1].legend(fontsize=8.5)
fig.tight_layout()
fig.savefig(OUT / "fig2_cl_alpha_cd_alpha.png", dpi=200)
plt.close(fig)

fig, ax = plt.subplots(figsize=(5.8, 4.6))
ax.plot([r[2] for r in comp], [r[1] for r in comp], "b.-", ms=4, label="XFOIL (this work)")
ax.plot([r[2] for r in stored], [r[1] for r in stored], "r.--", ms=3,
        label=f"Profili library (Re={RE//1000}k)")
ax.plot(ld_peak[2], ld_peak[1], "k*", ms=13, label=f"$(L/D)_{{max}}$={ld_peak[3]:.0f}")
ax.annotate(f"$\\alpha$={ld_peak[0]:.1f}°", (ld_peak[2], ld_peak[1]),
            textcoords="offset points", xytext=(8, -14), fontsize=9)
ax.set(xlabel=r"$C_d$", ylabel=r"$C_l$", title=r"Drag polar  $C_l-C_d$")
ax.grid(alpha=0.3)
ax.legend(fontsize=9)
fig.tight_layout()
fig.savefig(OUT / "fig3_cl_cd_polar.png", dpi=200)
plt.close(fig)

fig, ax = plt.subplots(figsize=(5.8, 3.6))
ax.plot([r[0] for r in comp], [r[3] for r in comp], "g.-", ms=4)
ax.axhline(0, color="k", lw=0.5)
ax.plot(0, cm_at_0, "k*", ms=12, label=f"$C_{{m0}}$={cm_at_0:.4f}")
ax.set(xlabel=r"$\alpha$ (deg)", ylabel=r"$C_{m,c/4}$", title="Pitching moment coefficient")
ax.grid(alpha=0.3)
ax.legend(fontsize=9)
fig.tight_layout()
fig.savefig(OUT / "fig4_cm_alpha.png", dpi=200)
plt.close(fig)

print("figures + csv ->", OUT)
