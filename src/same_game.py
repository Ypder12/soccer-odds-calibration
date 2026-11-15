"""Same-game parlays in soccer: how wrong is independent pricing?

Question (fixed before running): for a two-leg same-game parlay combining the
match result with over/under 2.5 goals, how often does each combination
actually happen, compared with multiplying the two fair prices as if the legs
were independent? And does a simple goals model fitted only to the market's
own prices get the combination right?

Data: Pinnacle closing odds for 1X2 and over/under 2.5 (available from 2019/20),
Premier League + Championship, Shin margin removal on each market.

Six combinations per match, from the favourite's point of view:
    favourite wins / draw / favourite loses   x   over 2.5 / under 2.5

Goals model: per match, home and away goals are independent Poisson with
rates (lh, la) chosen so the model reproduces the market's fair 1X2 and
over 2.5 probabilities as closely as possible (least squares on 4 prices,
2 parameters). The model never sees results; its combo prices come purely
from the two single-market prices. All comparisons are therefore out of sample.
"""
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from scipy.stats import poisson

sys.path.insert(0, str(Path(__file__).parent))
from load import load_all, odds
from devig import shin

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
RNG = np.random.default_rng(5)
G = np.arange(11)  # goals 0..10
RES_LABELS = ["Fav wins", "Draw", "Fav loses"]
OU_LABELS = ["Over 2.5", "Under 2.5"]
BANDS = [(0, .45, "<45%"), (.45, .55, "45–55%"), (.55, .65, "55–65%"), (.65, .75, "65–75%"), (.75, 1.01, "75%+")]


def prepare():
    df = load_all()
    ou = df[["pin_close_ou_over", "pin_close_ou_under"]].to_numpy(float)
    o = odds(df, "pin_close")
    ok = ((o > 1) & np.isfinite(o)).all(1) & ((ou > 1) & np.isfinite(ou)).all(1) & df.hg.notna().to_numpy()
    df = df[ok].reset_index(drop=True)
    p1x2, _ = shin(odds(df, "pin_close"))
    pou, _ = shin(df[["pin_close_ou_over", "pin_close_ou_under"]].to_numpy(float))
    fav = p1x2.argmax(1)                      # 0 home, 1 draw, 2 away
    fav = np.where(fav == 1, 0, fav)          # draw favoured (very rare): treat home as fav
    dog = 2 - fav
    p_res = np.stack([p1x2[np.arange(len(df)), fav], p1x2[:, 1], p1x2[np.arange(len(df)), dog]], 1)
    hg, ag = df.hg.to_numpy(), df.ag.to_numpy()
    fav_goals = np.where(fav == 0, hg, ag); dog_goals = np.where(fav == 0, ag, hg)
    res = np.select([fav_goals > dog_goals, fav_goals == dog_goals], [0, 1], 2)
    over = (hg + ag) > 2.5
    return df, p1x2, pou[:, 0], fav, p_res, res, over


def fit_poisson(p1x2, p_over):
    """Per-match Poisson rates matching fair 1X2 + over 2.5 prices."""
    pm = poisson.pmf
    out = np.empty((len(p1x2), 2)); err = np.empty(len(p1x2))
    tri_h, tri_a = np.tril(np.ones((11, 11)), -1), np.triu(np.ones((11, 11)), 1)
    over_mask = (G[:, None] + G[None, :]) > 2.5

    def model(theta):
        lh, la = np.exp(theta)
        M = np.outer(pm(G, lh), pm(G, la))
        return np.array([(M * tri_h).sum(), np.trace(M), (M * tri_a).sum(), (M * over_mask).sum()])

    for i in range(len(p1x2)):
        target = np.r_[p1x2[i], p_over[i]]
        r = least_squares(lambda t: model(t) - target, x0=np.log([1.5, 1.1]))
        out[i] = np.exp(r.x); err[i] = np.abs(r.fun).max()
    return out, err


def model_joint(rates, fav):
    """(n, 3, 2) model probabilities: [fav win, draw, fav lose] x [over, under]."""
    over_mask = (G[:, None] + G[None, :]) > 2.5
    hwin, draw, awin = np.tril(np.ones((11, 11)), -1).astype(bool), np.eye(11, dtype=bool), np.triu(np.ones((11, 11)), 1).astype(bool)
    J = np.empty((len(rates), 3, 2))
    for i, (lh, la) in enumerate(rates):
        M = np.outer(poisson.pmf(G, lh), poisson.pmf(G, la))
        fw, fl = (hwin, awin) if fav[i] == 0 else (awin, hwin)
        for r, mask in enumerate([fw, draw, fl]):
            J[i, r, 0] = M[mask & over_mask].sum(); J[i, r, 1] = M[mask & ~over_mask].sum()
    return J / J.sum((1, 2), keepdims=True)


def ratio_ci(actual, priced, b=2000):
    n = len(actual)
    bs = [actual[i].sum() / priced[i].sum() for i in (RNG.integers(0, n, n) for _ in range(b))]
    return [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]


def main():
    df, p1x2, p_over, fav, p_res, res, over = prepare()
    n = len(df)
    p_ou = np.stack([p_over, 1 - p_over], 1)
    indep = p_res[:, :, None] * p_ou[:, None, :]                  # (n,3,2)
    actual = np.zeros((n, 3, 2)); actual[np.arange(n), res, (~over).astype(int)] = 1
    rates, fit_err = fit_poisson(p1x2, p_over)
    model = model_joint(rates, fav)

    out = {"matches": int(n), "seasons": f"{df.season.min()} to {df.season.max()}",
           "poisson_fit_max_abs_error_median": float(np.median(fit_err)),
           "over_rate": float(over.mean()), "over_priced": float(p_over.mean()), "cells": {}, "by_band": {}}
    for r in range(3):
        for o in range(2):
            key = f"{RES_LABELS[r]} & {OU_LABELS[o]}"
            a, ip, mp = actual[:, r, o], indep[:, r, o], model[:, r, o]
            out["cells"][key] = {
                "actual_rate": float(a.mean()), "independent_price": float(ip.mean()), "model_price": float(mp.mean()),
                "actual_vs_independent": float(a.sum() / ip.sum()), "ci": ratio_ci(a, ip),
                "model_vs_independent": float(mp.sum() / ip.sum()),
                "actual_vs_model": float(a.sum() / mp.sum()), "ci_model": ratio_ci(a, mp)}
    pf = p_res[:, 0]
    rows = []
    for lo, hi, lab in BANDS:
        m = (pf >= lo) & (pf < hi)
        for r in range(3):
            for o in range(2):
                a, ip, mp = actual[m, r, o], indep[m, r, o], model[m, r, o]
                rows.append({"band": lab, "n": int(m.sum()), "combo": f"{RES_LABELS[r]} & {OU_LABELS[o]}",
                             "actual": float(a.mean()), "independent": float(ip.mean()), "model": float(mp.mean()),
                             "actual_vs_independent": float(a.sum() / ip.sum()),
                             "ci_lo": ratio_ci(a, ip, 1000)[0], "ci_hi": ratio_ci(a, ip, 1000)[1],
                             "model_vs_independent": float(mp.sum() / ip.sum()),
                             "actual_vs_model": float(a.sum() / mp.sum())})
    tab = pd.DataFrame(rows)
    tab.to_csv(RES / "same_game_by_band.csv", index=False)

    # Overall scoring of the joint 6-way outcome: independence vs Poisson model
    def ll(P):
        return -np.log(np.clip((P * actual).sum((1, 2)), 1e-12, None))
    li, lm = ll(indep), ll(model)
    d = lm - li
    bs = [d[i].mean() for i in (RNG.integers(0, n, n) for _ in range(2000))]
    out["joint_log_loss"] = {"independent": float(li.mean()), "poisson_model": float(lm.mean()),
                             "model_minus_independent": float(d.mean()),
                             "ci": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]}
    # Draw check: Poisson fitted to prices vs market's own draw price
    out["model_draw_vs_market_draw"] = float(model[:, 1, :].sum(1).mean() / p1x2[:, 1].mean())

    (RES / "same_game.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    piv = tab.pivot_table(index="band", columns="combo", values="actual_vs_independent", sort=False)
    print("\nActual / independent price, by favourite strength\n", piv.round(2).to_string())
    print("\nModel / independent\n", tab.pivot_table(index="band", columns="combo", values="model_vs_independent", sort=False).round(2).to_string())


if __name__ == "__main__":
    main()
