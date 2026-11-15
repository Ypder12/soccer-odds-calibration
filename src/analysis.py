"""Are soccer betting odds calibrated, and is there a favourite-longshot bias?

Run:  python src/analysis.py
Writes results/results.json and results/*.csv, used by figures.py and the brief.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit, logit

from load import load_all, odds, outcome_matrix
from devig import multiplicative, shin, overround

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
RES.mkdir(exist_ok=True)
RNG = np.random.default_rng(7)
B = 1000  # bootstrap resamples (resampling whole matches)

TRAIN_SEASONS = [f"20{y:02d}/{y+1:02d}" for y in range(15, 21)]   # 2015/16 - 2020/21
TEST_SEASONS = [f"20{y:02d}/{y+1:02d}" for y in range(21, 26)]    # 2021/22 - 2025/26
ODDS_BANDS = [1.0, 1.5, 2.0, 3.0, 5.0, 10.0, np.inf]
BAND_LABELS = ["1.0-1.5", "1.5-2", "2-3", "3-5", "5-10", "10+"]


# ---------- scoring ----------
def log_loss(p, y):
    return float(-np.mean(np.log(np.clip((p * y).sum(1), 1e-12, None))))


def brier(p, y):
    return float(np.mean(((p - y) ** 2).sum(1)))


def boot_ci(stat_fn, n, b=B):
    """Percentile CI from resampling match indices."""
    vals = np.array([stat_fn(RNG.integers(0, n, n)) for _ in range(b)])
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


# ---------- favourite-longshot regression ----------
def fit_recalibration(p, y):
    """MLE of  P(outcome) = sigmoid(a + b * logit(p))  pooled over H/D/A.

    b = 1, a = 0  -> perfectly calibrated.
    b > 1         -> true probabilities are MORE extreme than the price:
                     favourites underpriced, longshots overpriced (FLB).
    """
    x = logit(np.clip(p.ravel(), 1e-6, 1 - 1e-6))
    t = y.ravel()

    def nll(theta):
        z = theta[0] + theta[1] * x
        return np.sum(np.logaddexp(0, z) - t * z)

    def grad(theta):
        r = expit(theta[0] + theta[1] * x) - t
        return np.array([r.sum(), (r * x).sum()])

    return minimize(nll, [0.0, 1.0], jac=grad, method="BFGS").x


def recalibrate(p, theta):
    q = expit(theta[0] + theta[1] * logit(np.clip(p, 1e-6, 1 - 1e-6)))
    return q / q.sum(1, keepdims=True)  # renormalise so H+D+A = 1


def flb_with_ci(p, y):
    theta = fit_recalibration(p, y)
    ci = boot_ci(lambda idx: fit_recalibration(p[idx], y[idx])[1], len(p), b=300)
    return {"a": float(theta[0]), "b": float(theta[1]), "b_ci": ci}


# ---------- calibration table ----------
def calibration_table(p, y, bins):
    pf, yf = p.ravel(), y.ravel()
    match_of = np.repeat(np.arange(len(p)), 3)
    rows = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (pf >= lo) & (pf < hi)
        if m.sum() < 30:
            continue
        idx_matches = np.unique(match_of[m])

        def stat(i, lo=lo, hi=hi):
            pp, yy = p[idx_matches[i]].ravel(), y[idx_matches[i]].ravel()
            mm = (pp >= lo) & (pp < hi)
            return yy[mm].mean() - pp[mm].mean()

        ci = boot_ci(stat, len(idx_matches), b=400)
        rows.append({
            "bin": f"{lo:.2f}-{hi:.2f}", "n": int(m.sum()),
            "predicted": float(pf[m].mean()), "actual": float(yf[m].mean()),
            "gap": float(yf[m].mean() - pf[m].mean()), "gap_ci_lo": ci[0], "gap_ci_hi": ci[1],
        })
    return pd.DataFrame(rows)


# ---------- betting returns ----------
def roi_by_band(o, y):
    """Flat 1-unit stake on every outcome, grouped by the price taken."""
    of, yf = o.ravel(), y.ravel()
    match_of = np.repeat(np.arange(len(o)), 3)
    rows = []
    for (lo, hi), lab in zip(zip(ODDS_BANDS[:-1], ODDS_BANDS[1:]), BAND_LABELS):
        m = (of >= lo) & (of < hi) & np.isfinite(of)
        if m.sum() == 0:
            continue
        pnl = np.where(yf[m] == 1, of[m] - 1, -1.0)
        mids = match_of[m]
        # bootstrap over matches: group pnl by match
        uniq, inv = np.unique(mids, return_inverse=True)
        per_match_pnl = np.bincount(inv, weights=pnl)
        per_match_n = np.bincount(inv)

        def stat(i):
            return per_match_pnl[i].sum() / per_match_n[i].sum()

        ci = boot_ci(stat, len(uniq), b=1000)
        rows.append({"band": lab, "bets": int(m.sum()), "roi": float(pnl.mean()),
                     "roi_ci_lo": ci[0], "roi_ci_hi": ci[1]})
    return pd.DataFrame(rows)


def strategy_roi(p_model, o_bet, y, edge=0.0):
    """Bet 1 unit wherever model_prob * odds - 1 > edge. Returns ROI and CI."""
    ev = p_model * o_bet - 1
    pick = (ev > edge) & np.isfinite(o_bet)
    pnl = np.where(pick, np.where(y == 1, o_bet - 1, -1.0), 0.0)
    per_match = pnl.sum(1)
    per_n = pick.sum(1)
    n_bets = int(per_n.sum())
    if n_bets == 0:
        return {"bets": 0}
    ci = boot_ci(lambda i: per_match[i].sum() / max(per_n[i].sum(), 1), len(y))
    return {"bets": n_bets, "roi": float(per_match.sum() / n_bets), "roi_ci": ci}


def main():
    df_all = load_all()
    out = {}

    # Main sample: matches with Pinnacle opening AND closing odds
    df = df_all.dropna(subset=["pin_open_H", "pin_close_H", "b365_open_H"]).copy()
    valid = lambda b: ((odds(df, b) > 1) & np.isfinite(odds(df, b))).all(1)
    df = df[valid("pin_close") & valid("pin_open") & valid("b365_open")]
    y = outcome_matrix(df)
    o_close = odds(df, "pin_close")
    p_mult = multiplicative(o_close)
    p_shin, z = shin(o_close)
    out["sample"] = {
        "matches": int(len(df)),
        "by_league": df.groupby("league").size().to_dict(),
        "seasons": f"{df.season.min()} to {df.season.max()}",
        "dropped_no_pinnacle": int(len(df_all) - len(df)),
        "home_win_rate": float(y[:, 0].mean()), "draw_rate": float(y[:, 1].mean()),
        "away_win_rate": float(y[:, 2].mean()),
    }

    # 1. Margins
    margins = {}
    for book in ["pin_open", "pin_close", "b365_open"]:
        sub = df_all.dropna(subset=[f"{book}_H"])
        o = odds(sub, book)
        o = o[((o > 1) & np.isfinite(o)).all(1)]
        margins[book] = float(np.median(overround(o)))
    for lg in ["E0", "E1"]:
        s = df[df.league == lg]
        margins[f"pin_close_{lg}"] = float(np.median(overround(odds(s, "pin_close"))))
        margins[f"b365_open_{lg}"] = float(np.median(overround(odds(s, "b365_open"))))
    out["median_margin"] = margins
    out["shin_z_median"] = float(np.median(z))

    # 2. Accuracy of each source (same matches)
    acc = {}
    sources = {
        "Pinnacle closing (Shin)": p_shin,
        "Pinnacle closing (multiplicative)": p_mult,
        "Pinnacle opening (Shin)": shin(odds(df, "pin_open"))[0],
        "Bet365 opening (Shin)": shin(odds(df, "b365_open"))[0],
        "Base rates only": np.tile(y.mean(0), (len(y), 1)),
    }
    for name, p in sources.items():
        acc[name] = {"log_loss": log_loss(p, y), "brier": brier(p, y)}
    # is closing better than opening? bootstrap the difference
    p_open = sources["Pinnacle opening (Shin)"]
    d = boot_ci(lambda i: log_loss(p_open[i], y[i]) - log_loss(p_shin[i], y[i]), len(y))
    acc["close_minus_open_ci"] = d
    p_b365 = sources["Bet365 opening (Shin)"]
    d2 = boot_ci(lambda i: log_loss(p_b365[i], y[i]) - log_loss(p_open[i], y[i]), len(y))
    acc["b365open_minus_pinopen_ci"] = d2
    out["accuracy"] = acc

    # 3. Calibration tables (both de-vig methods)
    bins = np.array([0, .1, .2, .3, .4, .5, .6, .7, .8, 1.0])
    for name, p in [("shin", p_shin), ("mult", p_mult)]:
        calibration_table(p, y, bins).to_csv(RES / f"calibration_{name}.csv", index=False)
    # draws on their own
    draw_bins = np.array([0, .2, .24, .27, .30, 1.0])
    rows = []
    for lo, hi in zip(draw_bins[:-1], draw_bins[1:]):
        m = (p_shin[:, 1] >= lo) & (p_shin[:, 1] < hi)
        if m.sum():
            rows.append({"bin": f"{lo:.2f}-{hi:.2f}", "n": int(m.sum()),
                         "predicted": float(p_shin[m, 1].mean()), "actual": float(y[m, 1].mean())})
    pd.DataFrame(rows).to_csv(RES / "calibration_draws.csv", index=False)

    # 4. Favourite-longshot slope, by method, league and book
    flb = {
        "raw_implied_normalised (= multiplicative)": flb_with_ci(p_mult, y),
        "shin": flb_with_ci(p_shin, y),
    }
    for lg in ["E0", "E1"]:
        m = (df.league == lg).to_numpy()
        flb[f"multiplicative_{lg}"] = flb_with_ci(p_mult[m], y[m])
        flb[f"shin_{lg}"] = flb_with_ci(p_shin[m], y[m])
    flb["bet365_open_multiplicative"] = flb_with_ci(multiplicative(odds(df, "b365_open")), y)
    flb["bet365_open_shin"] = flb_with_ci(p_b365, y)
    out["flb_slope"] = flb

    # 5. Returns from flat betting, by price band
    roi_by_band(o_close, y).to_csv(RES / "roi_pinnacle_close.csv", index=False)
    roi_by_band(odds(df, "b365_open"), y).to_csv(RES / "roi_bet365_open.csv", index=False)
    bc = df.dropna(subset=["best_close_H"])
    roi_by_band(odds(bc, "best_close"), outcome_matrix(bc)).to_csv(RES / "roi_best_close.csv", index=False)

    # 6. Out-of-sample test: learn the bias on 2015-2021, try to exploit it 2021-2026
    tr = df.season.isin(TRAIN_SEASONS).to_numpy()
    te = df.season.isin(TEST_SEASONS).to_numpy()
    oos = {}
    for name, p in [("multiplicative", p_mult), ("shin", p_shin)]:
        theta = fit_recalibration(p[tr], y[tr])
        p_re = recalibrate(p[te], theta)
        diff_ci = boot_ci(lambda i: log_loss(p[te][i], y[te][i]) - log_loss(p_re[i], y[te][i]),
                          int(te.sum()))
        oos[name] = {
            "train_a": float(theta[0]), "train_b": float(theta[1]),
            "test_logloss_raw": log_loss(p[te], y[te]),
            "test_logloss_recalibrated": log_loss(p_re, y[te]),
            "improvement_ci": diff_ci,
        }
        oos[name]["p_recal_test"] = p_re  # kept for the betting tests below (dropped before saving)
    # Betting tests, test period only. Timing must be consistent: you can only
    # bet at a price using information available at that moment.
    #   (a) closing-line fair price -> best closing price across books ("line shopping")
    #   (b) same, but with the FLB correction learned on 2015-21 -> isolates the bias's value
    #   (c) pre-match: Pinnacle opening fair price -> Bet365 opening price
    dte = df[te]
    yt = y[te]
    p_open_te = shin(odds(dte, "pin_open"))[0]
    bets = {}
    for edge in [0.0, 0.02, 0.05]:
        bets[f"a_shin_close_to_best_close_edge{edge}"] = strategy_roi(p_shin[te], odds(dte, "best_close"), yt, edge)
        bets[f"b_recalibrated_to_best_close_edge{edge}"] = strategy_roi(oos["shin"]["p_recal_test"], odds(dte, "best_close"), yt, edge)
        bets[f"c_pin_open_to_b365_open_edge{edge}"] = strategy_roi(p_open_te, odds(dte, "b365_open"), yt, edge)
    for name in ["multiplicative", "shin"]:
        oos[name].pop("p_recal_test")
    oos["betting"] = bets

    # ROI of flat betting by outcome type at Pinnacle close (all seasons)
    out["roi_by_outcome_pinnacle_close"] = {
        s: float(np.where(y[:, j] == 1, o_close[:, j] - 1, -1.0).mean()) for j, s in enumerate("HDA")}
    out["margin_share_by_outcome"] = {  # raw implied minus Shin fair prob, averaged
        s: float(((1 / o_close)[:, j] - p_shin[:, j]).mean()) for j, s in enumerate("HDA")}

    # Baseline: bet every favourite / every longshot at best closing price, test period
    o_best = odds(dte, "best_close")
    fav = (o_close[te] == o_close[te].min(1, keepdims=True))
    pnl = np.where(y[te] == 1, o_best - 1, -1.0)
    oos["all_favourites_best_close_roi"] = float(pnl[fav].mean())
    oos["all_10plus_longshots_best_close_roi"] = float(pnl[o_close[te] >= 10].mean())
    out["out_of_sample"] = oos

    (RES / "results.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
