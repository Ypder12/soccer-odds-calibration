"""Is Kalshi's Premier League market as good as the bookmakers'?

Question (fixed before looking at results): for EPL matches, compare Kalshi's
pre-kickoff prices with bookmaker closing odds on
  1. accuracy (log loss, Brier) against results,
  2. bias (draws, favourites/longshots, over 2.5),
  3. cost to someone who takes the price (Kalshi ask + Kalshi's trading fee,
     vs the bookmaker's built-in margin),
  4. whether buying on Kalshi when its ask (plus fee) is below the bookmakers'
     fair price would have made money.

Kalshi price = mid of best bid/ask in the last hourly candle ending at least
1 hour before kickoff, using only candles with a spread of 5 cents or less;
the three mids are rescaled to sum to 1. Robustness: same at 0h, 3h, 24h.
Bookmaker benchmark = Pinnacle closing odds where football-data has them,
otherwise the market-average closing odds, margin removed with Shin's method.
Kalshi fee = 0.07 * P * (1 - P) per $1 contract (standard schedule, before
rounding up to the cent).
"""
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from devig import shin

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
K = ROOT / "data" / "kalshi"
RNG = np.random.default_rng(11)
S = "HDA"
fee = lambda p: 0.07 * p * (1 - p)
CHECK = {"0h": 0, "1h": 1, "3h": 2, "24h": 3}


def boot(x, B=4000):
    x = np.asarray(x); m = x[RNG.integers(0, len(x), (B, len(x)))].mean(1)
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def main():
    kx = json.load(open(K / "kalshi_1x2.json")); mk = kx["markets"]
    M = pd.read_csv(K / "matches.csv")  # football-data closing odds + result for each Kalshi event
    out = {"checks": {}}
    for check, ci in CHECK.items():
        rows = []
        for r in M.itertuples():
            q = [mk.get(f"KXEPLGAME-{r.event}-{s}") for s in (r.event[-6:-3], r.event[-3:], "TIE")]
            q = [v[ci] if isinstance(v, list) else None for v in q]
            if any(v is None for v in q): continue
            rows.append((r.Index, *[v[1] for v in q], *[v[2] for v in q]))
        T = pd.DataFrame(rows, columns=["i", "bH", "bA", "bD", "aH", "aA", "aD"]).set_index("i")
        D = M.loc[T.index].join(T)
        bid = D[["bH", "bD", "bA"]].to_numpy(); ask = D[["aH", "aD", "aA"]].to_numpy()
        pin = D[["PSCH", "PSCD", "PSCA"]].to_numpy(float); avg = D[["AvgCH", "AvgCD", "AvgCA"]].to_numpy(float)
        has_pin = np.isfinite(pin).all(1) & (pin > 1).all(1)
        odds = np.where(has_pin[:, None], pin, avg)
        ok = np.isfinite(odds).all(1) & (odds > 1).all(1)
        D, bid, ask, odds, has_pin = D[ok], bid[ok], ask[ok], odds[ok], has_pin[ok]
        Y = np.stack([(D.FTR == s).to_numpy() for s in S], 1).astype(float)
        mid = (bid + ask) / 2; kp = mid / mid.sum(1, keepdims=True)
        bp, _ = shin(odds)
        ll = lambda P: -np.log(np.clip((P * Y).sum(1), 1e-9, 1))
        d = ll(kp) - ll(bp)
        c = dict(n=int(len(D)), n_pinnacle=int(has_pin.sum()),
                 logloss_kalshi=float(ll(kp).mean()), logloss_books=float(ll(bp).mean()),
                 logloss_diff=float(d.mean()), logloss_diff_ci=boot(d),
                 logloss_diff_pinnacle_only=float(d[has_pin].mean()), logloss_diff_pinnacle_only_ci=boot(d[has_pin]),
                 mean_abs_gap_pp=float(np.abs(kp - bp).mean() * 100), share_gap_over_2pp=float((np.abs(kp - bp) > .02).mean()))
        for j, s in enumerate(S):
            c[f"kalshi_{s}"] = float(kp[:, j].mean()); c[f"books_{s}"] = float(bp[:, j].mean()); c[f"actual_{s}"] = float(Y[:, j].mean())
            c[f"gap_{s}_pp"] = float((kp[:, j] - bp[:, j]).mean() * 100); c[f"gap_{s}_ci_pp"] = [x * 100 for x in boot(kp[:, j] - bp[:, j])]
        out["checks"][check] = c
        if check != "1h": continue
        # favourite-longshot: Kalshi vs books by bookmaker-probability band
        P, KP, A = bp.ravel(), kp.ravel(), Y.ravel()
        cost_k = (ask + fee(ask)).ravel(); cost_b = (1 / odds).ravel(); H = np.repeat(has_pin, 3)
        bands = []
        for lo, hi in [(0, .15), (.15, .3), (.3, .45), (.45, .6), (.6, 1.01)]:
            m = (P >= lo) & (P < hi); mp = m & H
            bands.append(dict(band=f"{int(lo*100)}-{min(int(hi*100),100)}%", n=int(m.sum()), books=float(P[m].mean()), kalshi=float(KP[m].mean()),
                              actual=float(A[m].mean()),
                              kalshi_taker_cost_pct=float((cost_k[m] / P[m] - 1).mean() * 100),
                              books_margin_pct=float((cost_b[m] / P[m] - 1).mean() * 100),
                              n_pinnacle=int(mp.sum()),
                              kalshi_taker_cost_pct_pin_subset=float((cost_k[mp] / P[mp] - 1).mean() * 100),
                              pinnacle_margin_pct=float((cost_b[mp] / P[mp] - 1).mean() * 100)))
        out["by_band"] = bands
        out["costs"] = dict(spread_c=float((ask - bid).mean() * 100), fee_c=float(fee(ask).mean() * 100),
                            sum_of_asks=float(ask.sum(1).mean()),
                            kalshi_taker_cost_pct=float(((ask + fee(ask)) / bp - 1).mean() * 100),
                            books_margin_pct=float(((1 / odds) / bp - 1).mean() * 100),
                            kalshi_taker_cost_pct_pin=float(((ask + fee(ask)) / bp - 1)[has_pin].mean() * 100),
                            pinnacle_margin_pct=float(((1 / odds) / bp - 1)[has_pin].mean() * 100),
                            fee_share_of_kalshi_cost=float((fee(ask) / (ask + fee(ask) - bp)).mean()))
        # betting: buy at Kalshi ask when books' fair prob beats ask + fee
        cost = ask + fee(ask); edge = bp - cost; bets = {}
        for thr in (0, .01):
            m = edge > thr
            if not m.any(): continue
            rows_ = np.where(m.any(1))[0]
            pnl = ((Y - cost) * m).sum(1)[rows_]; stk = (cost * m).sum(1)[rows_]
            bs = [(lambda k: pnl[k].sum() / stk[k].sum())(RNG.integers(0, len(rows_), len(rows_))) for _ in range(4000)]
            bets[f"edge>{thr}"] = dict(bets=int(m.sum()), mean_expected_edge=float(edge[m].mean()), roi=float(pnl.sum() / stk.sum()),
                                      ci=[float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))])
        out["bets"] = bets
        np.save(RES / "kalshi_arrays.npy", dict(kp=kp, bp=bp, Y=Y, ask=ask, odds=odds, has_pin=has_pin), allow_pickle=True)
    # over/under 2.5
    ou = json.load(open(K / "kalshi_ou25.json")); rows = []
    for r in M.itertuples():
        v = ou.get(r.event)
        if not isinstance(v, list): continue
        q = v[2][CHECK["1h"]] or v[2][0]
        if q is None: continue
        o = np.array([r._asdict().get("PSCO", np.nan), r._asdict().get("PSCU", np.nan)], float)
        if not np.isfinite(o).all(): o = np.array([r.AvgCO, r.AvgCU], float)
        if not np.isfinite(o).all(): continue
        rows.append((q[1], q[2], *o, int(r.FTHG + r.FTAG > 2.5), v[1]))
    T = pd.DataFrame(rows, columns=["b", "a", "oo", "ou", "over", "kres"])
    bo, _ = shin(T[["oo", "ou"]].to_numpy()); kpo = ((T.b + T.a) / 2).to_numpy(); y = T.over.to_numpy()
    l = lambda p: -np.log(np.where(y == 1, p, 1 - p)); d = l(kpo) - l(bo[:, 0])
    out["over25"] = dict(n=int(len(T)), kalshi=float(kpo.mean()), books=float(bo[:, 0].mean()), actual=float(y.mean()),
                         gap_pp=float((kpo - bo[:, 0]).mean() * 100), gap_ci_pp=[x * 100 for x in boot(kpo - bo[:, 0])],
                         mean_abs_gap_pp=float(np.abs(kpo - bo[:, 0]).mean() * 100),
                         logloss_diff=float(d.mean()), logloss_diff_ci=boot(d),
                         settlement_agrees_with_score=float(((T.kres == "yes") == (T.over == 1)).mean()))
    (RES / "kalshi_vs_books.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
