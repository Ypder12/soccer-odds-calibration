"""Pre-match test of the combo pricer (src/combo_pricer.py) on English soccer.

Question (fixed before running): if a market maker prices same-game combos from the single-market
prices with a scoreline model, are the combo prices right? How wrong is multiplying the legs as if
they were independent, and which model gets the combos closest?

Data: Pinnacle closing 1X2 and over/under 2.5, Shin margin removal, Premier League + Championship,
2019/20 to 2025/26.

Models (see combo_pricer.py): "poisson" (2 parameters, best fit), "dc" (Dixon-Coles, matches all
four prices exactly), "tilt" (both-teams-score tilt, matches all four prices exactly). None has a
parameter learned from results, so every number is out of sample. (An earlier version also tried a
single rho / kappa for all matches, chosen on 2019/20-2022/23; the likelihood picked rho = kappa = 0,
i.e. plain Poisson, so the per-match versions are what is reported.)

Combos are written from the favourite's side: "fav" = the 1X2 favourite, "dog" = the other team.
"Independent" = the legs' fair prices (from the same grid) multiplied together.
"""
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from load import load_all, odds
from devig import shin
from combo_pricer import Pricer, mask, LEGS

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
RNG = np.random.default_rng(11)
MODELS = ["poisson", "dc", "tilt"]
EARLY = ["2019/20", "2020/21", "2021/22", "2022/23"]

F = {"fav": "home", "draw": "draw", "dog": "away", "btts": "btts", "no_btts": "no_btts",
     "fav_clean_sheet": "home_clean_sheet"}
for ln in (1.5, 2.5, 3.5):
    F[f"over{ln}"] = f"over{ln}"; F[f"under{ln}"] = f"under{ln}"
COMBOS = [
    ["fav", "over2.5"], ["fav", "under2.5"], ["draw", "over2.5"], ["draw", "under2.5"],
    ["dog", "over2.5"], ["dog", "under2.5"],
    ["fav", "btts"], ["fav", "no_btts"], ["draw", "btts"], ["draw", "no_btts"], ["dog", "btts"],
    ["over2.5", "btts"], ["under2.5", "no_btts"], ["over1.5", "btts"], ["over3.5", "btts"],
    ["fav", "fav_clean_sheet"],
    ["fav", "over2.5", "btts"], ["fav", "under2.5", "no_btts"], ["draw", "under2.5", "no_btts"],
    ["dog", "over2.5", "btts"],
]
SINGLES = [["draw"], ["btts"], ["over1.5"], ["over3.5"]]
SCORES = [(0, 0), (1, 1), (2, 2), (1, 0), (0, 1), (2, 1), (2, 0)]   # (fav goals, dog goals)


def prepare():
    df = load_all()
    ou = df[["pin_close_ou_over", "pin_close_ou_under"]].to_numpy(float)
    o = odds(df, "pin_close")
    ok = ((o > 1) & np.isfinite(o)).all(1) & ((ou > 1) & np.isfinite(ou)).all(1) & df.hg.notna().to_numpy()
    df = df[ok].reset_index(drop=True)
    p1x2, _ = shin(odds(df, "pin_close"))
    pou, _ = shin(df[["pin_close_ou_over", "pin_close_ou_under"]].to_numpy(float))
    return df, p1x2, pou[:, 0]


def fit_all(model, p1x2, p_over):
    P = Pricer(model)
    gs, ps, es = [], [], []
    for (ph, pd_, pa), po in zip(p1x2, p_over):
        g, p, e = P.fit(ph, pd_, pa, po)
        gs.append(g); ps.append(p); es.append(e)
    return np.array(gs), ps, np.array(es)


def fav_view(gr, fav_home):
    g = gr.copy()
    g[~fav_home] = np.transpose(g[~fav_home], (0, 2, 1))
    return g


def boot_ratio(a, p, b=2000):
    idx = RNG.integers(0, len(a), (b, len(a)))
    r = a[idx].sum(1) / p[idx].sum(1)
    return [float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))]


def boot_mean(d, b=2000):
    m = d[RNG.integers(0, len(d), (b, len(d)))].mean(1)
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def logloss(p, y):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def main():
    df, p1x2, p_over = prepare()
    n = len(df)
    fav_home = p1x2[:, 0] >= p1x2[:, 2]
    hg, ag = df.hg.to_numpy(int), df.ag.to_numpy(int)
    fg = np.minimum(np.where(fav_home, hg, ag), 10); dg = np.minimum(np.where(fav_home, ag, hg), 10)
    early = df.season.isin(EARLY).to_numpy()

    grids, params, errs = {}, {}, {}
    for m in MODELS:
        g, p, e = fit_all(m, p1x2, p_over)
        grids[m], params[m], errs[m] = fav_view(g, fav_home), p, e
        print(m, "fitted; median max pricing error", round(float(np.median(e)), 5))

    def evaluate(legs):
        mk = mask([F[l] for l in legs])
        y = mk[fg, dg].astype(float)
        row = {"combo": " + ".join(legs), "legs": len(legs), "actual": float(y.mean())}
        ind = np.prod([grids["tilt"][:, LEGS[F[l]]].sum(1) for l in legs], axis=0)
        row["independent"] = float(ind.mean())
        row["actual_vs_independent"] = float(y.sum() / ind.sum()); row["actual_vs_independent_ci"] = boot_ratio(y, ind)
        ll_ind = logloss(ind, y)
        for m in MODELS:
            p = grids[m][:, mk].sum(1)
            row[m] = float(p.mean())
            row[f"actual_vs_{m}"] = float(y.sum() / p.sum()); row[f"actual_vs_{m}_ci"] = boot_ratio(y, p)
            row[f"actual_vs_{m}_early"] = float(y[early].sum() / p[early].sum())
            row[f"actual_vs_{m}_late"] = float(y[~early].sum() / p[~early].sum())
            d = logloss(p, y) - ll_ind
            row[f"logloss_{m}_minus_indep"] = float(d.mean())
        d = logloss(grids["tilt"][:, mk].sum(1), y) - logloss(grids["poisson"][:, mk].sum(1), y)
        row["logloss_tilt_minus_poisson"] = float(d.mean()); row["logloss_tilt_minus_poisson_ci"] = boot_mean(d, 1000)
        return row

    combos = [evaluate(c) for c in COMBOS]
    singles = [evaluate(c) for c in SINGLES]
    scores = []
    for f_, d_ in SCORES:
        y = ((fg == f_) & (dg == d_)).astype(float)
        row = {"score": f"{f_}-{d_}", "actual": float(y.mean())}
        for m in MODELS:
            p = grids[m][:, f_, d_]
            row[m] = float(p.mean()); row[f"actual_vs_{m}"] = float(y.sum() / p.sum()); row[f"actual_vs_{m}_ci"] = boot_ratio(y, p)
        scores.append(row)

    # whole-distribution score: log-likelihood of the exact final score
    ll = {m: np.log(np.clip(grids[m][np.arange(n), fg, dg], 1e-12, None)) for m in MODELS}
    score_ll = {m: float(ll[m].mean()) for m in MODELS}
    score_ll["tilt_minus_poisson"] = float((ll["tilt"] - ll["poisson"]).mean()); score_ll["tilt_minus_poisson_ci"] = boot_mean(ll["tilt"] - ll["poisson"])
    score_ll["dc_minus_poisson"] = float((ll["dc"] - ll["poisson"]).mean()); score_ll["dc_minus_poisson_ci"] = boot_mean(ll["dc"] - ll["poisson"])
    score_ll["tilt_minus_dc"] = float((ll["tilt"] - ll["dc"]).mean()); score_ll["tilt_minus_dc_ci"] = boot_mean(ll["tilt"] - ll["dc"])

    # average absolute mispricing across the 20 combos
    def mean_abs_log(key):
        return float(np.mean([abs(np.log(c[key])) for c in combos]))
    summary = {f"mean_abs_mispricing_{k}": mean_abs_log(f"actual_vs_{k}") for k in MODELS + ["independent"]}

    # pooled calibration of all combos: Poisson model vs independent pricing
    py, pt, pi = [], [], []
    for legs in COMBOS:
        mk = mask([F[l] for l in legs])
        py.append(mk[fg, dg].astype(float)); pt.append(grids["poisson"][:, mk].sum(1))
        pi.append(np.prod([grids["tilt"][:, LEGS[F[l]]].sum(1) for l in legs], axis=0))
    py, pt, pi = map(np.concatenate, (py, pt, pi))
    bins = [0, .05, .10, .15, .20, .25, .30, .35, .40, .50, .70]
    calib = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        for name, pp in (("poisson", pt), ("independent", pi)):
            k = (pp >= lo) & (pp < hi)
            if k.sum() > 100:
                calib.append({"model": name, "bin": f"{lo:.2f}-{hi:.2f}", "n": int(k.sum()),
                              "predicted": float(pp[k].mean()), "actual": float(py[k].mean())})

    kap = np.array([p[2] for p in params["tilt"]]); rho = np.array([p[2] for p in params["dc"]])
    out = {"matches": int(n), "seasons": f"{df.season.min()} to {df.season.max()}",
           "fit_max_error_median": {m: float(np.median(errs[m])) for m in MODELS},
           "tilt_kappa": {"median": float(np.median(kap)), "p10": float(np.percentile(kap, 10)), "p90": float(np.percentile(kap, 90))},
           "dc_rho": {"median": float(np.median(rho)), "p10": float(np.percentile(rho, 10)), "p90": float(np.percentile(rho, 90))},
           "score_loglik": score_ll, "summary": summary,
           "combos": combos, "singles": singles, "scores": scores, "calibration": calib}
    (RES / "combo_study.json").write_text(json.dumps(out, indent=2))
    pd.DataFrame(combos).to_csv(RES / "combo_study.csv", index=False)
    np.save(RES / "combo_calibration_points.npy", np.stack([pt, pi, py]))
    cols = ["combo", "actual", "independent", "poisson", "dc", "tilt", "actual_vs_independent", "actual_vs_poisson", "actual_vs_dc", "actual_vs_tilt"]
    pd.set_option("display.width", 250)
    print(pd.DataFrame(combos)[cols].round(3).to_string())
    print(pd.DataFrame(singles)[cols].round(3).to_string())
    print(pd.DataFrame(scores)[["score", "actual", "poisson", "dc", "tilt", "actual_vs_poisson", "actual_vs_dc", "actual_vs_tilt"]].round(3).to_string())
    print(pd.DataFrame(combos)[["combo", "actual_vs_tilt_early", "actual_vs_tilt_late", "actual_vs_poisson_early", "actual_vs_poisson_late"]].round(3).to_string())
    print(json.dumps({k: out[k] for k in ("matches", "fit_max_error_median", "tilt_kappa", "dc_rho", "score_loglik", "summary")}, indent=1))


if __name__ == "__main__":
    main()
