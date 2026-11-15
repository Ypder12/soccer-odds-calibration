"""Finding 6: how prices move between the opening and closing snapshot.

Questions fixed before running:
  Q1  Do big Pinnacle moves keep going (market underreacts) or reverse (overreacts)?
      Test: P(outcome) = sigmoid(a + b*logit(p_close) + g*move), move = logit(p_close) - logit(p_open).
      g > 0: underreaction (the close still hasn't moved far enough). g < 0: overreaction.
  Q2  How much of the move is information? Share of the open->close log-loss gain.
  Q3  Does Bet365 follow Pinnacle? Regress Bet365's move on Pinnacle's move (same snapshots).
      Then: at the close, is Bet365 still behind? Regress the gap (Bet365 close fair - Pinnacle close fair)
      on Pinnacle's move. Negative slope = Bet365 hasn't fully caught up.
  Q4  Is any of this bettable? Out of sample (train 2015-21, test 2021-26), timing-consistent prices.
"""
import json, sys
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logit
sys.path.insert(0, str(Path(__file__).parent))
from load import load_all, odds, outcome_matrix
from devig import shin

RES = Path(__file__).resolve().parent.parent / "results"
RNG = np.random.default_rng(3)

def ok(df, b):  # returns a numpy bool array
    o = odds(df, b); return ((o > 1) & np.isfinite(o)).all(1)

def fit(X, t):
    def nll(w):
        z = X @ w; return np.sum(np.logaddexp(0, z) - t * z)
    def grad(w):
        return X.T @ (expit(X @ w) - t)
    return minimize(nll, np.r_[0, 1, np.zeros(X.shape[1] - 2)], jac=grad, method="BFGS").x

def design(pc, mv):
    return np.column_stack([np.ones(pc.size), logit(np.clip(pc.ravel(), 1e-6, 1-1e-6)), mv.ravel()])

def boot(fn, n, b=500):
    v = np.array([fn(RNG.integers(0, n, n)) for _ in range(b)])
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]

def ll(p, y): return float(-np.mean(np.log((p * y).sum(1))))

def roi(pick, o, y, m=None):
    if m is not None: pick = pick & m[:, None]
    pnl = np.where(pick, np.where(y == 1, o - 1, -1.0), 0.0)
    pm, pn = pnl.sum(1), pick.sum(1)
    n = int(pn.sum())
    if n == 0: return {"bets": 0}
    keep = pn > 0 if m is None else m
    pm, pn = pm[keep], pn[keep]
    ci = boot(lambda i: pm[i].sum() / max(pn[i].sum(), 1), len(pm), 1500)
    return {"bets": n, "roi": float(pm.sum() / n), "ci": ci}

df = load_all().dropna(subset=["pin_open_H", "pin_close_H", "b365_open_H"])
df = df[ok(df, "pin_open") & ok(df, "pin_close") & ok(df, "b365_open")]
y = outcome_matrix(df)
po, pc = shin(odds(df, "pin_open"))[0], shin(odds(df, "pin_close"))[0]
mv = logit(pc) - logit(po)
out = {"matches": len(df)}

# Q1
w = fit(design(pc, mv), y.ravel())
ci = boot(lambda i: fit(design(pc[i], mv[i]), y[i].ravel())[2], len(y), 300)
out["Q1"] = {"b_close": float(w[1]), "g_move": float(w[2]), "g_ci": ci,
             "median_abs_move": float(np.median(np.abs(mv))),
             "share_moves_over_10pct_logodds": float((np.abs(mv) > 0.10).mean())}
# by move size: closing calibration for outcomes that shortened a lot / drifted a lot
bands = {"drifted a lot (move < -0.15)": mv < -0.15, "small move": np.abs(mv) <= 0.05,
         "shortened a lot (move > 0.15)": mv > 0.15}
match_of = np.repeat(np.arange(len(y)), 3).reshape(-1, 3)
cal = {}
for k, m in bands.items():
    gap = y[m].mean() - pc[m].mean()
    mids = np.unique(match_of[m])
    def stat(i, m=m, mids=mids):
        sel = np.zeros_like(m); sel[mids[i]] = m[mids[i]]
        return y[sel].mean() - pc[sel].mean()
    cal[k] = {"n": int(m.sum()), "priced_at_close": float(pc[m].mean()), "happened": float(y[m].mean()),
              "gap": float(gap), "gap_ci": boot(stat, len(mids), 500)}
out["Q1_by_move"] = cal

# Q2
out["Q2"] = {"logloss_open": ll(po, y), "logloss_close": ll(pc, y),
             "logloss_base_rates": ll(np.tile(y.mean(0), (len(y), 1)), y)}
out["Q2"]["share_of_total_info_added_open_to_close"] = (
    (out["Q2"]["logloss_open"] - out["Q2"]["logloss_close"]) /
    (out["Q2"]["logloss_base_rates"] - out["Q2"]["logloss_close"]))

# Q3: Bet365 follows Pinnacle? (needs Bet365 closing, 2019/20 on)
d3 = ok(df, "b365_close")
bo, bc = shin(odds(df[d3], "b365_open"))[0], shin(odds(df[d3], "b365_close"))[0]
pin_mv, b_mv = mv[d3].ravel(), (logit(bc) - logit(bo)).ravel()
gap_close = (logit(bc) - logit(pc[d3])).ravel()
gap_open = (logit(bo) - logit(po[d3])).ravel()
slope = lambda x, z: float(np.polyfit(x, z, 1)[0])
n3 = d3.sum()
idx3 = lambda i: (np.repeat(i, 3) * 3 + np.tile([0, 1, 2], len(i)))
out["Q3"] = {"matches": int(n3),
             "bet365_move_on_pinnacle_move_slope": slope(pin_mv, b_mv),
             "slope_ci": boot(lambda i: slope(pin_mv[idx3(i)], b_mv[idx3(i)]), n3, 300),
             "close_gap_on_pinnacle_move_slope": slope(pin_mv, gap_close),
             "close_gap_slope_ci": boot(lambda i: slope(pin_mv[idx3(i)], gap_close[idx3(i)]), n3, 300),
             "corr_moves": float(np.corrcoef(pin_mv, b_mv)[0, 1]),
             "median_abs_gap_open": float(np.median(np.abs(gap_open))),
             "median_abs_gap_close": float(np.median(np.abs(gap_close)))}

# Q4: out of sample, timing-consistent
tr = df.season.isin([f"20{a:02d}/{a+1:02d}" for a in range(15, 21)]).to_numpy()
te = ~tr
o_pc, o_bc = odds(df, "pin_close"), odds(df, "b365_close")
q4 = {}
# (a) back outcomes that shortened a lot, at Pinnacle close (momentum, if Q1 says underreaction)
for thr in [0.15, 0.30]:
    q4[f"back shortened >{thr} at Pinnacle close"] = {
        "train": roi(mv > thr, o_pc, y, tr), "test": roi(mv > thr, o_pc, y, te)}
    q4[f"back drifted <-{thr} at Pinnacle close"] = {
        "train": roi(mv < -thr, o_pc, y, tr), "test": roi(mv < -thr, o_pc, y, te)}
# (b) Bet365 stale at the close: Pinnacle close fair price vs Bet365 closing price
ok_b = ok(df, "b365_close")
for e in [0.0, 0.03]:
    pick = (pc * o_bc - 1 > e) & ok_b[:, None]
    q4[f"Bet365 close beats Pinnacle fair by >{e:.0%}"] = {
        "train": roi(pick, o_bc, y, tr & ok_b), "test": roi(pick, o_bc, y, te & ok_b)}
out["Q4"] = q4

(RES / "line_moves.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
