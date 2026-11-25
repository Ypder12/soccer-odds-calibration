"""In-play test of the combo pricer on Kalshi Premier League matches.

Question (fixed before running): during a match, can combo prices be built from the live 1X2 price
and the score alone? At each snapshot the pricer refits the rate of the goals still to come so the
grid reproduces Kalshi's live home / draw / away prices at the current score, then prices totals,
both-teams-score and same-game combos. Are those prices right, and how far is the independent
(multiply-the-legs) price off in-play?

Data: results/inplay_snapshots.csv from the in-play study (Kalshi minute prices every 5 minutes from
kick-off, skipping minutes right around a goal; score from ESPN goal times), 453 matches, 2025/26
and 2026/27. Final scores from data/kalshi/matches.csv. Snapshots where a combo is already settled
(model price < 1% or > 99%) are dropped for that combo. Intervals bootstrap whole matches.
"""
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from combo_pricer import Pricer, mask, LEGS

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
RNG = np.random.default_rng(12)
COMBOS = [["over2.5"], ["over3.5"], ["btts"], ["home", "over2.5"], ["away", "over2.5"], ["draw", "under2.5"],
          ["home", "btts"], ["away", "btts"], ["draw", "btts"], ["over2.5", "btts"],
          ["home", "home_clean_sheet"], ["away", "away_clean_sheet"]]


def boot_ratio(y, p, ev, b=1000):
    u = np.unique(ev); idx = {e: np.flatnonzero(ev == e) for e in u}
    out = []
    for _ in range(b):
        s = np.concatenate([idx[e] for e in RNG.choice(u, len(u))])
        out.append(y[s].sum() / p[s].sum())
    return [float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))]


def main():
    S = pd.read_csv(RES / "inplay_snapshots.csv")
    M = pd.read_csv(ROOT / "data" / "kalshi" / "matches.csv").set_index("event")
    S = S[S.event.isin(M.index)].copy()
    S["fh"] = M.loc[S.event, "FTHG"].to_numpy(int); S["fa"] = M.loc[S.event, "FTAG"].to_numpy(int)
    S = S[(S.fh >= S.h) & (S.fa >= S.a)]                    # score data consistent with final score
    k = S[["kH", "kD", "kA"]].to_numpy(float); k = k / k.sum(1, keepdims=True)
    gr, err = [], []
    for (ph, pd_, pa), h, a in zip(k, S.h.to_numpy(int), S.a.to_numpy(int)):
        g, _, e = Pricer.fit_inplay(ph, pd_, pa, h, a)
        gr.append(g); err.append(e)
    gr = np.array(gr); err = np.array(err)
    fh, fa = np.minimum(S.fh.to_numpy(), 10), np.minimum(S.fa.to_numpy(), 10)
    ev = S.event.to_numpy(); minute = S.gmin.to_numpy()
    print("snapshots", len(S), "matches", S.event.nunique(), "median fit error", round(float(np.median(err)), 5))

    rows = []
    for legs in COMBOS:
        mk = mask(legs)
        p = gr[:, mk].sum(1); y = mk[fh, fa].astype(float)
        ind = np.prod([gr[:, LEGS[l]].sum(1) for l in legs], axis=0)
        live = (p > 0.01) & (p < 0.99)
        r = {"combo": " + ".join(legs), "snapshots": int(live.sum()), "matches": int(len(np.unique(ev[live]))),
             "actual": float(y[live].mean()), "model": float(p[live].mean()), "independent": float(ind[live].mean()),
             "actual_vs_model": float(y[live].sum() / p[live].sum()), "actual_vs_model_ci": boot_ratio(y[live], p[live], ev[live])}
        if len(legs) > 1:
            r["actual_vs_independent"] = float(y[live].sum() / ind[live].sum())
            r["actual_vs_independent_ci"] = boot_ratio(y[live], ind[live], ev[live])
        for lab, lo, hi in (("first_half", 0, 46), ("second_half", 46, 91)):
            sel = live & (minute >= lo) & (minute < hi)
            r[f"actual_vs_model_{lab}"] = float(y[sel].sum() / p[sel].sum()) if sel.sum() else None
            r[f"actual_vs_model_{lab}_ci"] = boot_ratio(y[sel], p[sel], ev[sel], 500) if sel.sum() else None
        rows.append(r)

    # how the home-win + over 2.5 correlation changes with the score (model, averaged over snapshots)
    mk = mask(["home", "over2.5"])
    joint = gr[:, mk].sum(1); ind = gr[:, LEGS["home"]].sum(1) * gr[:, LEGS["over2.5"]].sum(1)
    by_state = []
    for (h, a), sub in S.assign(j=joint, i=ind).groupby(["h", "a"]):
        if len(sub) >= 80:
            sub = sub[(sub.i > 0.01) & (sub.i < 0.99)]
            if len(sub):
                by_state.append({"score": f"{h}-{a}", "snapshots": int(len(sub)),
                                 "joint_over_independent": float(sub.j.sum() / sub.i.sum())})

    # the input: is Kalshi's live draw price itself right, by half?
    kd = k[:, 1]; yd = (fh == fa).astype(float)
    draw_check = {}
    for lab, sel in (("first_half", minute < 46), ("second_half", minute >= 46)):
        lvl = sel & (S.h.to_numpy() == S.a.to_numpy())
        draw_check[lab] = {"snapshots": int(sel.sum()), "draw_price": float(kd[sel].mean()), "draw_actual": float(yd[sel].mean()),
                           "level_score_draw_price": float(kd[lvl].mean()), "level_score_draw_actual": float(yd[lvl].mean()),
                           "actual_vs_price": float(yd[sel].sum() / kd[sel].sum()), "ci": boot_ratio(yd[sel], kd[sel], ev[sel], 500)}
    out = {"draw_check": draw_check, "final_draw_rate": float((M.FTHG == M.FTAG).mean()),
           "snapshots": int(len(S)), "matches": int(S.event.nunique()), "fit_error_median": float(np.median(err)),
           "combos": rows, "home_over25_factor_by_score": by_state}
    (RES / "combo_inplay.json").write_text(json.dumps(out, indent=2))
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).drop(columns=["actual_vs_model_ci"]).round(3).to_string())
    print(pd.DataFrame(by_state).round(3).to_string())
    print(json.dumps(draw_check, indent=1), "final draw rate", out["final_draw_rate"])
    for r in rows:
        print(r["combo"], [round(x, 3) for x in r["actual_vs_model_first_half_ci"]], [round(x, 3) for x in r["actual_vs_model_second_half_ci"]])


if __name__ == "__main__":
    main()
