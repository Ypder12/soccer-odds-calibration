"""Pre-specified edge tests. Rules fixed before looking at results.
Train 2015/16-2020/21, test 2021/22-2025/26. Only timing-consistent prices.

H1 value vs sharp (pre-match): fair prob = Pinnacle OPENING (Shin); bet at the BEST
   pre-match price across books when EV > edge. Same snapshot, so no look-ahead.
H2 value vs sharp at Bet365 only (one realistic account), pre-match.
H3 home-win line shopping at the close: back every home win at best closing price.
H4 skip draws: back the favourite at best closing price only when draw prob < 25%.
"""
import sys, numpy as np
sys.path.insert(0, "src")
from load import load_all, odds, outcome_matrix
from devig import shin

RNG = np.random.default_rng(11)
df = load_all().dropna(subset=["pin_open_H", "pin_close_H", "b365_open_H", "best_open_H"])
ok = lambda b: ((odds(df, b) > 1) & np.isfinite(odds(df, b))).all(1)
df = df[ok("pin_open") & ok("pin_close") & ok("b365_open") & ok("best_open")]
tr = df.season.isin([f"20{y:02d}/{y+1:02d}" for y in range(15, 21)]).to_numpy()

def roi(pick, o, y, mask):
    pick = pick & mask[:, None]
    pnl = np.where(pick, np.where(y == 1, o - 1, -1.0), 0.0)
    pm, pn = pnl.sum(1)[mask], pick.sum(1)[mask]
    n = pn.sum()
    if n == 0: return "0 bets"
    bs = [pm[i].sum() / max(pn[i].sum(), 1) for i in (RNG.integers(0, len(pm), len(pm)) for _ in range(2000))]
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return f"{n:5d} bets  ROI {pm.sum()/n:+6.1%}  CI [{lo:+.1%}, {hi:+.1%}]"

y = outcome_matrix(df)
p_open = shin(odds(df, "pin_open"))[0]
p_close = shin(odds(df, "pin_close"))[0]
best_open, b365, best_close = odds(df, "best_open"), odds(df, "b365_open"), odds(df, "best_close")
has_bc = np.isfinite(best_close).all(1)

tests = {}
for e in [0.02, 0.05]:
    tests[f"H1 best pre-match vs Pinnacle open, edge>{e:.0%}"] = (p_open * best_open - 1 > e, best_open, np.ones(len(y), bool))
    tests[f"H2 Bet365 vs Pinnacle open, edge>{e:.0%}"] = (p_open * b365 - 1 > e, b365, np.ones(len(y), bool))
home = np.zeros_like(y, bool); home[:, 0] = True
tests["H3 every home win at best close"] = (home, best_close, has_bc)
fav = (p_close == p_close.max(1, keepdims=True)) & (p_close[:, [1]] < 0.25)
fav[:, 1] = False
tests["H4 favourite at best close, low-draw games"] = (fav, best_close, has_bc)

for name, (pick, o, m) in tests.items():
    print(f"{name}\n   train: {roi(pick, o, y, m & tr)}\n   test:  {roi(pick, o, y, m & ~tr)}")
