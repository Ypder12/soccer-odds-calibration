"""Charts for the write-up. Run after analysis.py."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES, FIG = ROOT / "results", ROOT / "figures"
FIG.mkdir(exist_ok=True)

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE = "#2a78d6", "#eb6834"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "font.size": 11, "axes.titlesize": 13, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
})


def calibration():
    c = pd.read_csv(RES / "calibration_shin.csv")
    fig, ax = plt.subplots(figsize=(6.4, 6))
    ax.plot([0, 1], [0, 1], color=INK2, lw=1, ls="--", label="Perfect calibration")
    err = np.vstack([c.gap - c.gap_ci_lo, c.gap_ci_hi - c.gap])
    ax.errorbar(c.predicted, c.actual, yerr=err, fmt="o", ms=8, color=BLUE, ecolor=BLUE,
                elinewidth=2, capsize=0, label="Pinnacle closing odds, margin removed (Shin)")
    for _, r in c.iterrows():
        ax.annotate(f"n={r.n:,}", (r.predicted, r.actual), xytext=(8, -12),
                    textcoords="offset points", fontsize=8, color=INK2)
    ax.set(xlim=(0, 0.95), ylim=(0, 0.95), xlabel="Probability implied by the closing price",
           ylabel="How often it actually happened")
    ax.set_title("The closing line is well calibrated")
    ax.legend(frameon=False, loc="upper left", fontsize=9)
    fig.text(0.01, 0.005, "Premier League + Championship, 2015/16-2025/26, 9,784 matches x 3 outcomes. "
             "Bars: 95% bootstrap CI.", fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(FIG / "1_calibration.png", dpi=180)


def roi_bands():
    r = pd.read_csv(RES / "roi_pinnacle_close.csv")
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    x = np.arange(len(r))
    ax.bar(x, r.roi * 100, width=0.6, color=BLUE)
    ax.errorbar(x, r.roi * 100, yerr=np.vstack([r.roi - r.roi_ci_lo, r.roi_ci_hi - r.roi]) * 100,
                fmt="none", ecolor=INK2, elinewidth=1.5)
    ax.axhline(0, color=INK, lw=1)
    ax.set_xticks(x, [f"{b}\n({n:,} bets)" for b, n in zip(r.band, r.bets)], fontsize=9)
    ax.set(xlabel="Decimal odds taken", ylabel="Return per bet (%)")
    ax.set_title("Flat-betting every outcome at Pinnacle's closing price")
    for xi, v in zip(x, r.roi * 100):
        ax.annotate(f"{v:+.1f}%", (xi, 13), ha="center", fontsize=10, color=INK)
    ax.set_ylim(-55, 17)
    fig.text(0.01, 0.005, "Lines: 95% bootstrap CI (resampling matches). Longshots lose most, but the "
             "estimate is noisy.", fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(FIG / "2_roi_by_odds.png", dpi=180)


def outcomes(res):
    roi = res["roi_by_outcome_pinnacle_close"]
    fig, ax = plt.subplots(figsize=(6, 4))
    labels = ["Home win", "Draw", "Away win"]
    vals = [roi["H"] * 100, roi["D"] * 100, roi["A"] * 100]
    ax.bar(labels, vals, width=0.55, color=[BLUE, ORANGE, BLUE])
    ax.axhline(0, color=INK, lw=1)
    for i, v in enumerate(vals):
        ax.annotate(f"{v:+.1f}%", (i, v), xytext=(0, -14), textcoords="offset points",
                    ha="center", fontsize=10)
    ax.set(ylabel="Return per bet (%)", ylim=(min(vals) * 1.35, 1))
    ax.set_title("Draws lose the most at the closing price")
    fig.text(0.01, 0.005, "Pinnacle closing odds, all 9,784 matches. Draw 95% CI: -9.0% to -2.3%.",
             fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG / "3_roi_by_outcome.png", dpi=180)


def flb(res):
    f = res["flb_slope"]
    rows = [("All matches", "raw_implied_normalised (= multiplicative)", "shin"),
            ("Premier League", "multiplicative_E0", "shin_E0"),
            ("Championship", "multiplicative_E1", "shin_E1")]
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    for i, (lab, km, ks) in enumerate(rows):
        for off, k, col, name in [(0.13, km, ORANGE, "Proportional margin removal"),
                                  (-0.13, ks, BLUE, "Shin margin removal")]:
            d = f[k]
            ax.plot(d["b_ci"], [i + off] * 2, color=col, lw=2.5)
            ax.plot(d["b"], i + off, "o", ms=8, color=col, label=name if i == 0 else None)
    ax.axvline(1, color=INK, lw=1)
    ax.annotate("1 = no bias", (1, -0.45), xytext=(4, 0), textcoords="offset points",
                fontsize=9, color=INK2, va="center")
    ax.set_yticks(range(3), [r[0] for r in rows])
    ax.set_xlabel("Favourite-longshot slope b  (>1 means longshots overpriced)")
    ax.set_title("Little evidence of a favourite-longshot bias at the close", pad=28)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, fontsize=9)
    ax.set_ylim(2.5, -0.7)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(FIG / "4_flb_slope.png", dpi=180)


if __name__ == "__main__":
    res = json.loads((RES / "results.json").read_text())
    calibration(); roi_bands(); outcomes(res); flb(res)
    print("figures written to", FIG)
