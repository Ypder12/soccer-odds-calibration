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


def bet365_follows():
    """Binned: Pinnacle's open->close move vs Bet365's move over the same window."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from load import load_all, odds
    from devig import shin
    from scipy.special import logit
    df = load_all()
    ok = lambda b: ((odds(df, b) > 1) & np.isfinite(odds(df, b))).all(1)
    df = df[ok("pin_open") & ok("pin_close") & ok("b365_open") & ok("b365_close")]
    mv = lambda a, b: (logit(shin(odds(df, b))[0]) - logit(shin(odds(df, a))[0])).ravel()
    pin, b365 = mv("pin_open", "pin_close"), mv("b365_open", "b365_close")
    edges = np.array([-0.6, -0.3, -0.2, -0.1, -0.05, 0.05, 0.1, 0.2, 0.3, 0.6])
    idx = np.digitize(pin, edges) - 1
    keep = (idx >= 0) & (idx < len(edges) - 1)
    xs = np.array([pin[keep & (idx == k)].mean() for k in range(len(edges) - 1)])
    ys = np.array([b365[keep & (idx == k)].mean() for k in range(len(edges) - 1)])
    fig, ax = plt.subplots(figsize=(6.4, 5.6))
    lim = 0.45
    ax.plot([-lim, lim], [-lim, lim], color=INK2, lw=1, ls="--", label="Bet365 moves exactly as far")
    ax.plot(xs, ys, "o-", color=BLUE, ms=8, lw=2, label="Bet365's actual move (average per group)")
    ax.axhline(0, color=GRID, lw=1); ax.axvline(0, color=GRID, lw=1)
    ax.set(xlim=(-lim, lim), ylim=(-lim, lim),
           xlabel="Pinnacle's move, open to close (log-odds)", ylabel="Bet365's move, open to close (log-odds)")
    ax.set_title("Bet365 follows Pinnacle, but only about 90% of the way")
    ax.legend(frameon=False, loc="upper left", fontsize=9)
    fig.text(0.01, 0.005, "6,058 matches with Bet365 closing odds (2019/20-2025/26). Slope 0.90, 95% CI 0.88-0.91.",
             fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(FIG / "5_bet365_follows_pinnacle.png", dpi=180)


if __name__ == "__main__":
    bet365_follows()


def favourites_together():
    import json, sys
    sys.path.insert(0, str(Path(__file__).parent))
    from favourites_together import prepare
    res = json.loads((RES / "favourites_together.json").read_text())["all"]
    df = prepare()
    df["n_day"] = df.groupby("date")["p"].transform("size")
    df["r"] = df.won - df.p
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.6))
    ks = [2, 3, 4]
    x = np.arange(3)
    obs = [res[f"ratio_{k}leg"] for k in ks]
    lo = [res[f"ratio_{k}leg_null_95"][0] for k in ks]
    hi = [res[f"ratio_{k}leg_null_95"][1] for k in ks]
    a1.fill_between(x, lo, hi, color=GRID, alpha=0.9, label="Range if results were independent (95%)")
    a1.plot(x, obs, "o-", color=BLUE, ms=9, lw=2, label="Actual, same-day parlays")
    a1.axhline(1, color=INK2, lw=1, ls="--")
    for xi, v in zip(x, obs):
        a1.annotate(f"{v:.2f}", (xi, v), xytext=(10, -4), textcoords="offset points", fontsize=10)
    a1.set_xticks(x, [f"{k}-leg" for k in ks])
    a1.set(ylim=(0.8, 1.15), ylabel="Actual wins ÷ wins implied by price")
    a1.set_title("Favourite parlays win less, not more")
    a1.legend(frameon=False, fontsize=8.5, loc="upper left")
    bins = [(1, 1, "1"), (2, 4, "2–4"), (5, 9, "5–9"), (10, 13, "10–13"), (14, 30, "14+")]
    g, e, n = [], [], []
    rng = np.random.default_rng(0)
    for l, h, _ in bins:
        s = df[(df.n_day >= l) & (df.n_day <= h)].r.to_numpy()
        g.append(s.mean() * 100)
        bs = [rng.choice(s, len(s)).mean() * 100 for _ in range(500)]
        e.append([s.mean() * 100 - np.percentile(bs, 2.5), np.percentile(bs, 97.5) - s.mean() * 100])
        n.append(len(s))
    xb = np.arange(len(bins))
    a2.bar(xb, g, width=0.6, color=BLUE)
    a2.errorbar(xb, g, yerr=np.array(e).T, fmt="none", ecolor=INK2, elinewidth=1.5)
    a2.axhline(0, color=INK, lw=1)
    a2.set_xticks(xb, [f"{b[2]}\n({k:,})" for b, k in zip(bins, n)], fontsize=9)
    a2.set(xlabel="Matches played that day (favourites)", ylabel="Favourite won minus price (pp)")
    a2.set_title("Favourites do worse on busy days")
    fig.text(0.01, 0.005, "Pinnacle closing odds, Shin margin removal. 9,799 Premier League + Championship "
             "matches, 2015/16–2025/26. Bars: 95% bootstrap CI.", fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG / "6_favourites_together.png", dpi=180)


if __name__ == "__main__":
    favourites_together()


def same_game():
    import json
    r = json.loads((RES / "same_game.json").read_text())["cells"]
    tab = pd.read_csv(RES / "same_game_by_band.csv")
    order = ["Fav wins & Over 2.5", "Fav wins & Under 2.5", "Draw & Over 2.5",
             "Draw & Under 2.5", "Fav loses & Over 2.5", "Fav loses & Under 2.5"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5), gridspec_kw={"width_ratios": [1.25, 1]})
    y = np.arange(len(order))[::-1]
    act = np.array([r[k]["actual_vs_independent"] for k in order])
    lo = np.array([r[k]["ci"][0] for k in order]); hi = np.array([r[k]["ci"][1] for k in order])
    mod = np.array([r[k]["model_vs_independent"] for k in order])
    a1.axvline(1, color=INK, lw=1)
    a1.hlines(y, lo, hi, color=BLUE, lw=3, alpha=0.5)
    a1.plot(act, y, "o", color=BLUE, ms=9, label="Actually happened (95% CI)")
    a1.plot(mod, y, "D", color=ORANGE, ms=7, mfc="none", mew=2, label="Goals model, fitted to prices only")
    for yi, v in zip(y, act):
        a1.annotate(f"{v:.2f}×", (v, yi), xytext=(0, 10), textcoords="offset points", ha="center", fontsize=9)
    a1.set_yticks(y, [k.replace(" & ", " + ") for k in order])
    a1.set(xlim=(0.3, 1.65), xlabel="How often it happens ÷ independent price")
    a1.set_title("Independent pricing is wrong; a goals model fixes it")
    a1.set_ylim(-0.6, len(order) - 0.3)
    a1.legend(frameon=False, fontsize=8.5, loc="lower right")
    a1.grid(axis="y", visible=False)
    bands = list(dict.fromkeys(tab.band))
    xb = np.arange(len(bands))
    for combo, col, mk in [("Fav wins & Over 2.5", BLUE, "o"), ("Draw & Under 2.5", ORANGE, "s")]:
        t = tab[tab.combo == combo].set_index("band").loc[bands]
        a2.errorbar(xb, t.actual_vs_independent, yerr=[t.actual_vs_independent - t.ci_lo, t.ci_hi - t.actual_vs_independent],
                    fmt=mk + "-", color=col, ms=7, lw=2, capsize=0, elinewidth=1.5, label=combo.replace(" & ", " + "))
    a2.axhline(1, color=INK, lw=1)
    n = tab.groupby("band", sort=False).n.first().loc[bands]
    a2.set_xticks(xb, [f"{b}\n({k:,})" for b, k in zip(bands, n)], fontsize=9)
    a2.set(xlabel="Favourite's win probability (matches)", ylabel="Actual ÷ independent price")
    a2.set_title("The adjustment depends on the favourite")
    a2.legend(frameon=False, fontsize=8.5, loc="upper left")
    fig.text(0.01, 0.005, "Pinnacle closing 1X2 and over/under 2.5, Shin margin removal. 6,060 Premier League + Championship "
             "matches, 2019/20–2025/26.", fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG / "7_same_game.png", dpi=180)


if __name__ == "__main__":
    same_game()


def kalshi():
    """Kalshi vs bookmakers: (left) same probabilities, (right) very different cost to take them."""
    a = np.load(RES / "kalshi_arrays.npy", allow_pickle=True).item()
    res = json.loads((RES / "kalshi_vs_books.json").read_text())
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5.2))
    kp, bp = a["kp"].ravel(), a["bp"].ravel()
    ax1.plot([0, 1], [0, 1], color=INK2, lw=1, ls="--")
    ax1.scatter(bp, kp, s=9, alpha=0.45, color=BLUE, edgecolor="none")
    ax1.set(xlim=(0, 0.95), ylim=(0, 0.95), xlabel="Bookmaker closing probability (margin removed)",
            ylabel="Kalshi probability, 1h before kickoff")
    c = res["checks"]["1h"]
    ax1.set_title("Kalshi's prices match the bookmakers'")
    ax1.text(0.03, 0.88, f"{c['n']} EPL matches, {3*c['n']} prices\nAverage gap {c['mean_abs_gap_pp']:.1f} points\n"
             f"Same accuracy (log loss {c['logloss_kalshi']:.3f} vs {c['logloss_books']:.3f})",
             transform=ax1.transAxes, fontsize=9, color=INK2, va="top")
    b = [d for d in res["by_band"]]
    x = np.arange(len(b)); w = 0.38
    ax2.bar(x - w / 2, [d["kalshi_taker_cost_pct_pin_subset"] for d in b], w, color=ORANGE, label="Kalshi: ask + trading fee")
    ax2.bar(x + w / 2, [d["pinnacle_margin_pct"] for d in b], w, color=BLUE, label="Pinnacle: built-in margin")
    for xi, d in zip(x, b):
        ax2.annotate(f"{d['kalshi_taker_cost_pct_pin_subset']:.1f}%", (xi - w / 2, d["kalshi_taker_cost_pct_pin_subset"] + 0.3), ha="center", fontsize=8, color=INK)
        ax2.annotate(f"{d['pinnacle_margin_pct']:.1f}%", (xi + w / 2, d["pinnacle_margin_pct"] + 0.3), ha="center", fontsize=8, color=INK)
    ax2.set_xticks(x, [d["band"] for d in b])
    ax2.set(xlabel="Outcome's fair probability", ylabel="Cost above fair price (% of stake)")
    ax2.set_title("...but taking a price costs about twice as much")
    ax2.legend(frameon=False, fontsize=9, loc="upper right")
    fig.text(0.01, 0.01, "Kalshi EPL match-result markets, May 2025 to Nov 2026. Right panel: the matches where football-data has "
             "Pinnacle closing odds. Fee = 0.07 x P x (1 - P) per $1 contract.", fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(FIG / "8_kalshi_vs_books.png", dpi=180)


if __name__ == "__main__":
    kalshi()


def kalshi_inplay():
    """In-play: (left) average price path around a goal, (right) price after goal vs how often the scorer won."""
    E = pd.read_csv(RES / "inplay_goal_events.csv")
    res = json.loads((RES / "kalshi_inplay.json").read_text())
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5.2))
    lags = [-2, 1, 2, 3, 5, 10]
    d = E.dropna(subset=[f"s{l}" for l in lags])
    mean = [d[f"s{l}"].mean() for l in lags]
    ax1.plot(lags, mean, "o-", color=BLUE, lw=2, ms=7, label="Kalshi price: scoring team wins")
    ax1.axhline(d.y_scorer.mean(), color=ORANGE, lw=2, ls="--", label=f"How often they won ({d.y_scorer.mean():.0%})")
    ax1.axvline(0, color=INK2, lw=1)
    ax1.annotate("goal", (0, 0.42), xytext=(0.3, 0.42), fontsize=9, color=INK2)
    ax1.set(xlabel="Minutes from goal", ylabel="Average probability", ylim=(0.3, 0.7))
    ax1.set_title("Prices jump within a minute, to the right level")
    ax1.legend(frameon=False, fontsize=9, loc="lower right")
    ax1.text(0.02, 0.97, f"{len(d)} goals with prices at every minute shown\n(no second goal in the 10 minutes after)",
             transform=ax1.transAxes, fontsize=8, color=INK2, va="top")
    z = E.dropna(subset=["s2"]).copy()
    z["bin"] = pd.cut(z.s2, [0, .1, .25, .4, .55, .7, .85, .95, 1.0])
    g = z.groupby("bin", observed=True).agg(p=("s2", "mean"), y=("y_scorer", "mean"), n=("s2", "size")).reset_index()
    ax2.plot([0, 1], [0, 1], color=INK2, lw=1, ls="--", label="Perfectly priced")
    se = np.sqrt(g.y * (1 - g.y) / g.n) * 1.96
    ax2.errorbar(g.p, g.y, yerr=se, fmt="o", ms=7, color=BLUE, ecolor=BLUE, elinewidth=1.5, capsize=3, label="Goals grouped by price")
    for _, r in g.iterrows():
        ax2.annotate(f"n={r.n}", (r.p, r.y), textcoords="offset points", xytext=(8, -12), fontsize=7, color=INK2)
    ax2.set(xlim=(0, 1), ylim=(0, 1.05), xlabel="Kalshi price for the scoring team 2 min after the goal", ylabel="Share that went on to win")
    ax2.set_title("Post-goal prices are calibrated")
    ax2.legend(frameon=False, fontsize=9, loc="upper left")
    fig.text(0.01, 0.01, f"Kalshi EPL match-result markets, {res['n_matches']} matches, {res['n_goals']} goals (goal times from ESPN). "
             "Bars: 95% binomial intervals.", fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(FIG / "9_kalshi_inplay.png", dpi=180)


if __name__ == "__main__":
    kalshi_inplay()


def xvenue():
    """Kalshi vs Polymarket: (left) how far apart prices are, (right) which venue moves to close a gap."""
    D = pd.read_pickle(RES / "xvenue_panel.pkl"); R = json.loads((RES / "xvenue.json").read_text())
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5.2))
    bins = np.arange(0, 6.01, 0.5)
    for ph, col, lab in (("pre", BLUE, "Before kickoff"), ("inplay", ORANGE, "During the match")):
        g = (D[D.phase == ph].gap.abs() * 100).clip(upper=6)
        share = [((g >= lo) & (g < lo + 0.5)).mean() * 100 for lo in bins[:-1]]
        ax1.plot(bins[:-1] + 0.25, share, "o-", color=col, lw=2, ms=5, label=f"{lab} (avg {R[ph]['mean_abs_gap_c']:.1f}c)")
    ax1.set(xlabel="Gap between Kalshi mid and Polymarket price (cents, 6 = 6 or more)", ylabel="% of minutes", yscale="log", ylim=(0.01, 100))
    ax1.set_title("The two venues almost always agree")
    ax1.legend(frameon=False, fontsize=9)
    labs = ["Before kickoff", "During the match"]; x = np.arange(2); w = 0.36
    k = [R["gap_closing_pre"]["kalshi_moves_share"] * 100, R["gap_closing_inplay"]["kalshi_moves_share"] * 100]
    p = [R["gap_closing_pre"]["polymarket_moves_share"] * 100, R["gap_closing_inplay"]["polymarket_moves_share"] * 100]
    ax2.bar(x - w / 2, k, w, color=BLUE, label="Kalshi moves")
    ax2.bar(x + w / 2, p, w, color=ORANGE, label="Polymarket moves")
    for xi, a, b in zip(x, k, p):
        ax2.annotate(f"{a:.0f}%", (xi - w / 2, a + 1.5), ha="center", fontsize=9, color=INK)
        ax2.annotate(f"{b:.0f}%", (xi + w / 2, b + 1.5), ha="center", fontsize=9, color=INK)
    ax2.set_xticks(x, labs); ax2.set_ylim(0, 100)
    ax2.set(ylabel="Share of a 2c+ gap closed by each venue\nover the next 10 minutes")
    ax2.set_title("Who follows whom")
    ax2.legend(frameon=False, fontsize=9, loc="upper left")
    fig.text(0.01, 0.01, f"{R['matches']} EPL matches on both venues, Aug 2025 to Nov 2026; Kalshi best bid/ask mid vs Polymarket minute price. "
             "During matches Polymarket's minute price can lag, which may favour Kalshi here.", fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(FIG / "10_kalshi_vs_polymarket.png", dpi=180)


if __name__ == "__main__":
    xvenue()
