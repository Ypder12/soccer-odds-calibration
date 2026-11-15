"""Do favourites win together?

Question (fixed before running): when several matches are played on the same
day, are the favourites' results positively correlated? If so, a parlay of
favourites priced as independent legs (multiply the leg probabilities) is
underpriced: it wins more often than the price says.

Method
  * Fair probabilities from Pinnacle closing odds, Shin margin removal.
  * Favourite = outcome with the highest fair probability in each match.
  * Group matches by calendar date (both leagues together, as a parlay would).
  * k-leg parlays: over every set of k favourites playing on the same day,
    compare how often all k won with the sum of the products of their prices.
    Ratio > 1 means favourite parlays win more often than independent pricing
    implies. (Computed exactly with elementary symmetric polynomials per day.)
  * Overdispersion: per day, S = sum(won - p). If results are independent,
    Var(S) = sum p(1-p). Ratio > 1 means favourites move together.
  * Null: shuffle dates among matches within each season (keeps calibration
    and season effects, breaks same-day links), 2,000 times.
"""
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from load import load_all, odds
from devig import shin

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
RNG = np.random.default_rng(42)
N_PERM = 2000


def prepare():
    df = load_all().dropna(subset=["pin_close_H", "date"])
    o = odds(df, "pin_close")
    df = df[((o > 1) & np.isfinite(o)).all(1)].copy()
    p, _ = shin(odds(df, "pin_close"))
    fav = p.argmax(1)
    df["p"] = p[np.arange(len(p)), fav]
    df["fav_side"] = np.array(list("HDA"))[fav]
    df["won"] = (df["result"].to_numpy() == df["fav_side"].to_numpy()).astype(float)
    return df.reset_index(drop=True)


def esym(x, codes, n_days):
    """Elementary symmetric polynomials e2..e4 of x within each day, summed over days."""
    s = [np.bincount(codes, weights=x ** k, minlength=n_days) for k in (1, 2, 3, 4)]
    p1, p2, p3, p4 = s
    e2 = (p1 ** 2 - p2) / 2
    e3 = (p1 ** 3 - 3 * p1 * p2 + 2 * p3) / 6
    e4 = (p1 ** 4 - 6 * p1 ** 2 * p2 + 3 * p2 ** 2 + 8 * p1 * p3 - 6 * p4) / 24
    return {2: e2.sum(), 3: e3.sum(), 4: e4.sum()}


def stats(codes, p, y, n_days):
    ep, ey = esym(p, codes, n_days), esym(y, codes, n_days)
    out = {f"ratio_{k}leg": float(ey[k] / ep[k]) for k in (2, 3, 4)}
    out.update({f"priced_{k}leg": float(ep[k]) for k in (2, 3, 4)})
    out.update({f"actual_{k}leg": float(ey[k]) for k in (2, 3, 4)})
    r, v = y - p, p * (1 - p)
    n = np.bincount(codes, minlength=n_days)
    S = np.bincount(codes, weights=r, minlength=n_days)
    V = np.bincount(codes, weights=v, minlength=n_days)
    keep = n >= 2
    out["overdispersion"] = float((S[keep] ** 2).sum() / V[keep].sum())
    # average within-day correlation of the favourites' results
    R2 = np.bincount(codes, weights=r ** 2, minlength=n_days)
    sv = np.bincount(codes, weights=np.sqrt(v), minlength=n_days)
    num = ((S ** 2 - R2) / 2).sum()
    den = ((sv ** 2 - V) / 2).sum()
    out["rho"] = float(num / den)
    out["pairs"] = int(((n * (n - 1)) / 2).sum())
    return out


def run(df, label):
    codes = pd.factorize(df["date"])[0]
    n_days = codes.max() + 1
    p, y = df["p"].to_numpy(), df["won"].to_numpy()
    obs = stats(codes, p, y, n_days)
    seasons = [idx for idx in df.groupby("season").indices.values()]
    null = []
    for _ in range(N_PERM):
        c = codes.copy()
        for idx in seasons:
            c[idx] = RNG.permutation(c[idx])
        null.append(stats(c, p, y, n_days))
    out = {"label": label, "matches": int(len(df)), "days": int(n_days),
           "favourite_win_rate": float(y.mean()), "favourite_priced": float(p.mean()), **obs}
    for key in ["ratio_2leg", "ratio_3leg", "ratio_4leg", "overdispersion", "rho"]:
        nv = np.array([n[key] for n in null])
        out[f"{key}_null_mean"] = float(nv.mean())
        out[f"{key}_null_95"] = [float(np.percentile(nv, 2.5)), float(np.percentile(nv, 97.5))]
        out[f"{key}_p_value"] = float((np.sum(nv >= obs[key]) + 1) / (len(nv) + 1))
    return out, null


def main():
    df = prepare()
    results, nulls = {}, {}
    results["all"], nulls["all"] = run(df, "All matches, both leagues")
    for lg, name in [("E0", "Premier League only"), ("E1", "Championship only")]:
        results[lg], _ = run(df[df.league == lg].reset_index(drop=True), name)
    heavy = df[df.p >= 0.60].reset_index(drop=True)
    results["heavy_fav"], nulls["heavy"] = run(heavy, "Favourites priced 60%+")
    # first half vs second half of the sample (stability check)
    early = df.season.isin([f"20{a:02d}/{a+1:02d}" for a in range(15, 21)])
    results["2015_21"], _ = run(df[early].reset_index(drop=True), "2015/16-2020/21")
    results["2021_26"], _ = run(df[~early].reset_index(drop=True), "2021/22-2025/26")

    (RES / "favourites_together.json").write_text(json.dumps(results, indent=2))
    np.save(RES / "favourites_null_ratio_2leg.npy", np.array([n["ratio_2leg"] for n in nulls["all"]]))
    np.save(RES / "favourites_null_heavy_ratio_2leg.npy", np.array([n["ratio_2leg"] for n in nulls["heavy"]]))
    for k, v in results.items():
        print(f"\n== {v['label']}: {v['matches']} matches, {v['days']} days, {v['pairs']} pairs")
        print(f"   fav won {v['favourite_win_rate']:.3f} vs priced {v['favourite_priced']:.3f}")
        for key in ["ratio_2leg", "ratio_3leg", "ratio_4leg", "overdispersion", "rho"]:
            print(f"   {key:15s} {v[key]:.4f}  null {v[key+'_null_mean']:.4f} "
                  f"[{v[key+'_null_95'][0]:.4f}, {v[key+'_null_95'][1]:.4f}]  p={v[key+'_p_value']:.3f}")


if __name__ == "__main__":
    main()
