"""Do NFL favourites (and overs) win together in the same week?

Question (fixed before running): within an NFL week, are the results of favourites (moneyline),
spread favourites (covering) and overs positively correlated beyond what their prices imply?
If they are, a parlay maker who treats games as independent underestimates how often bad weeks
like 2026 weeks 9 and 10 happen.

Data: nflverse game file (github.com/nflverse/nfldata, games.csv), regular season 2006-2026,
closing moneylines, spreads and totals with their odds. Margin removed proportionally (two-way).

Tests, for each market:
  * calibration: did favourites win what the prices implied?
  * within-week correlation of (result - price), overdispersion of weekly totals, and k-leg parlay
    ratios (how often all k legs from the same week won vs the product of their prices).
  * null: shuffle games across weeks within each season, 2,000 times (keeps prices and outcomes,
    breaks same-week links).
  * how rare 2026 weeks 9 and 10 were, under independence (exact) and against history.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
RNG = np.random.default_rng(10)
N_PERM = 2000


def implied(odds):
    o = np.asarray(odds, float)
    return np.where(o < 0, -o / (-o + 100), 100 / (o + 100))


def load():
    g = pd.read_csv(ROOT / "data" / "nfl" / "games.csv")
    g = g[(g.game_type == "REG") & g.result.notna()].copy()
    out = {}
    # moneyline favourite
    m = g.dropna(subset=["home_moneyline", "away_moneyline"]).copy()
    ph, pa = implied(m.home_moneyline), implied(m.away_moneyline); s = ph + pa
    m["p_home"] = ph / s
    m = m[m.result != 0]
    fav_home = m.p_home >= 0.5
    m["p"] = np.where(fav_home, m.p_home, 1 - m.p_home)
    m["y"] = np.where(fav_home, m.result > 0, m.result < 0).astype(float)
    out["moneyline"] = m
    # spread favourite covers (spread_line > 0 means home favoured by that many points)
    sp = g.dropna(subset=["spread_line", "home_spread_odds", "away_spread_odds"]).copy()
    sp = sp[sp.spread_line != 0]
    margin = sp.result - sp.spread_line
    sp = sp[margin != 0]; margin = margin[margin != 0]
    ph, pa = implied(sp.home_spread_odds), implied(sp.away_spread_odds); s = ph + pa
    home_fav = sp.spread_line > 0
    sp["p"] = np.where(home_fav, ph / s, pa / s)
    sp["y"] = np.where(home_fav, margin > 0, margin < 0).astype(float)
    out["spread"] = sp
    # overs
    t = g.dropna(subset=["total_line", "over_odds", "under_odds"]).copy()
    t = t[t.total != t.total_line]
    po, pu = implied(t.over_odds), implied(t.under_odds)
    t["p"] = po / (po + pu); t["y"] = (t.total > t.total_line).astype(float)
    out["over"] = t
    for k in out:
        out[k] = out[k].assign(wk=out[k].season.astype(str) + "-" + out[k].week.astype(int).astype(str).str.zfill(2)).reset_index(drop=True)
    return out


def esym(x, codes, n):
    s = [np.bincount(codes, weights=x ** k, minlength=n) for k in (1, 2, 3, 4)]
    p1, p2, p3, p4 = s
    e2 = (p1 ** 2 - p2) / 2
    e3 = (p1 ** 3 - 3 * p1 * p2 + 2 * p3) / 6
    e4 = (p1 ** 4 - 6 * p1 ** 2 * p2 + 3 * p2 ** 2 + 8 * p1 * p3 - 6 * p4) / 24
    return {2: e2.sum(), 3: e3.sum(), 4: e4.sum()}


def stats(codes, p, y, n):
    ep, ey = esym(p, codes, n), esym(y, codes, n)
    r, v = y - p, p * (1 - p)
    S = np.bincount(codes, weights=r, minlength=n); V = np.bincount(codes, weights=v, minlength=n)
    R2 = np.bincount(codes, weights=r ** 2, minlength=n); sv = np.bincount(codes, weights=np.sqrt(v), minlength=n)
    return {"ratio_2leg": ey[2] / ep[2], "ratio_3leg": ey[3] / ep[3], "ratio_4leg": ey[4] / ep[4],
            "overdispersion": (S ** 2).sum() / V.sum(),
            "rho": ((S ** 2 - R2) / 2).sum() / ((sv ** 2 - V) / 2).sum()}


def week_z(df):
    w = df.groupby("wk").apply(lambda z: pd.Series({"n": len(z), "won": z.y.sum(), "exp": z.p.sum(), "var": (z.p * (1 - z.p)).sum(),
                                                   "season": z.season.iloc[0], "week": int(z.week.iloc[0])}), include_groups=False)
    w["z"] = (w.won - w.exp) / np.sqrt(w["var"])
    return w


def poisson_binomial_tail(p, k):
    """P(at least k successes) for independent Bernoulli(p)."""
    dist = np.array([1.0])
    for q in p:
        dist = np.convolve(dist, [1 - q, q])
    return float(dist[k:].sum())


def run(df):
    codes = pd.factorize(df.wk)[0]; n = codes.max() + 1
    p, y = df.p.to_numpy(), df.y.to_numpy()
    obs = stats(codes, p, y, n)
    seasons = list(df.groupby("season").indices.values())
    null = []
    for _ in range(N_PERM):
        c = codes.copy()
        for idx in seasons: c[idx] = RNG.permutation(c[idx])
        null.append(stats(c, p, y, n))
    res = {"games": int(len(df)), "weeks": int(n), "seasons": f"{df.season.min()}-{df.season.max()}",
           "win_rate": float(y.mean()), "priced": float(p.mean())}
    for k, v in obs.items():
        nv = np.array([x[k] for x in null])
        res[k] = float(v); res[k + "_null_95"] = [float(np.percentile(nv, 2.5)), float(np.percentile(nv, 97.5))]
        res[k + "_p_upper"] = float((np.sum(nv >= v) + 1) / (len(nv) + 1))
    w = week_z(df)
    res["weekly_z_sd"] = float(w.z.std())  # 1.0 if weeks behave like independent games
    res["share_weeks_z_over_2"] = float((w.z > 2).mean()); res["share_expected_under_normal"] = 0.0228
    for wk in ("2026-09", "2026-10"):
        if wk in w.index:
            z = df[df.wk == wk]
            r = w.loc[wk]
            res[f"week_{wk}"] = dict(games=int(r.n), won=int(r.won), expected=float(r.exp), win_rate=float(r.won / r.n), priced=float(z.p.mean()),
                                    z=float(r.z), p_at_least_this_many_if_independent=poisson_binomial_tail(z.p.to_numpy(), int(r.won)),
                                    rank_among_all_weeks=int((w.z >= r.z).sum()), all_weeks=int(len(w)))
    return res, w


def main():
    data = load()
    out = {}
    weeks = {}
    for name, df in data.items():
        out[name], weeks[name] = run(df)
        print(name, json.dumps(out[name], indent=1))
    # do favourites and overs move together across weeks? (a book long both is doubly exposed)
    z = pd.concat([weeks["moneyline"].z.rename("fav"), weeks["over"].z.rename("over"), weeks["spread"].z.rename("cover")], axis=1).dropna()
    out["weekly_z_correlations"] = {"fav_vs_over": float(z.fav.corr(z.over)), "fav_vs_cover": float(z.fav.corr(z.cover)), "cover_vs_over": float(z.cover.corr(z.over)), "weeks": int(len(z))}
    (RES / "nfl_weeks.json").write_text(json.dumps(out, indent=2))
    pd.concat(weeks, names=["market"]).to_csv(RES / "nfl_weekly.csv")


if __name__ == "__main__":
    main()
