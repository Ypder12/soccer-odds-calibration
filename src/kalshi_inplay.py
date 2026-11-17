"""How does Kalshi's in-play Premier League market react to goals?

Question (fixed before looking): after a goal, are Kalshi's prices right on average, or do they
over- or under-react? How fast do they move? Are draws priced fairly late in level games?

Data: Kalshi minute-by-minute best bid/ask for each match-result market, from 15 minutes before
kickoff to 150 minutes after (data/kalshi/kalshi_inplay_minutes.json; only minutes where the quote
changed are stored). Goal and red-card times and teams from ESPN's public match data
(data/kalshi/espn_goals.json; every final score checked against football-data). Each goal is placed
on the price path at the biggest move toward the scoring team in a window after the match-clock time.

Test: a fair price is a probability, so across many goals the scoring team's price N minutes after
the goal should equal how often that team went on to win. Intervals bootstrap whole matches.
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy.stats import poisson
from scipy.optimize import least_squares, minimize
ROOT = Path(__file__).resolve().parent.parent
K, RES = ROOT / "data" / "kalshi", ROOT / "results"
RNG = np.random.default_rng(21)

def parse(s):
    rows=[]
    for tok in s.split(','):
        if not tok: continue
        m,b,a=tok.split(':')[:3]
        rows.append((int(m), float(b)/1000 if b else np.nan, float(a)/1000 if a else np.nan))
    return pd.DataFrame(rows,columns=['m','bid','ask']).drop_duplicates('m',keep='last').set_index('m')
def paths(IP, events, minutes=range(-10,141)):
    out={}
    for e in events:
        a,b=e[-6:-3],e[-3:]
        ser={}
        ok=True
        for side,sfx in (('H',a),('D','TIE'),('A',b)):
            s=IP.get(f'KXEPLGAME-{e}-{sfx}')
            if not s or s=='NA': ok=False; break
            d=parse(s)
            d=d.reindex(sorted(set(d.index)|set(minutes))).ffill().reindex(list(minutes))   # only changes are stored
            mid=(d.bid+d.ask)/2
            mid[(d.ask-d.bid)>0.10]=np.nan          # ignore wide quotes
            ser[side]=mid.ffill(limit=5)
        if not ok: continue
        df=pd.DataFrame(ser)
        tot=df[['H','D','A']].sum(1)
        for s in 'HDA': df['p'+s]=df[s]/tot
        out[e]=df
    return out


def main():
    IP = json.load(open(K / 'kalshi_inplay_minutes.json'))
    EV = json.load(open(K / 'espn_goals.json'))
    M = pd.read_csv(K / 'matches.csv')
    P = paths(IP, M.event.tolist(), minutes=range(-10, 151))

    GR = np.arange(11)
    def probs(lh, la, h=0, a=0):
        M_ = np.outer(poisson.pmf(GR, lh), poisson.pmf(GR, la)); fh = h + GR[:, None]; fa = a + GR[None, :]
        return np.array([M_[fh > fa].sum(), M_[fh == fa].sum(), M_[fh < fa].sum()])
    def fit(p):
        return np.exp(least_squares(lambda t: probs(*np.exp(t)) - p, x0=np.log([1.4, 1.1])).x)
    def remaining(t):  # share of goals still to come at match minute t; scoring rate rises ~40% over a match
        F = lambda s: s + 0.2 * s ** 2 / 90
        return max(0.0, (F(90) - F(min(t, 90))) / F(90))

    goals, events, snaps, skipped = [], [], [], {'no_path': 0, 'no_prematch': 0, 'goal_not_found': 0}
    for r in M.itertuples():
        df = P.get(r.event); ev = EV.get(r.event)
        if df is None or ev is None: skipped['no_path'] += 1; continue
        pre = df.loc[-2, ['pH', 'pD', 'pA']].to_numpy(float)
        if not np.isfinite(pre).all(): skipped['no_prematch'] += 1; continue
        off = (ev['espn_ko'] - ev['fd_ko']) / 60  # ESPN kickoff vs scheduled (usually 0)
        x = (df.pH - df.pA)
        y = np.array([r.FTR == 'H', r.FTR == 'D', r.FTR == 'A'], float)
        lh, la = fit(pre)
        det = sorted([d for d in ev['details'] if d[3] or d[4]], key=lambda d: d[0] or 0)
        placed = []; h = a = 0; ok = True; last_wall = -1
        reds = []
        for d in det:
            clock = (d[0] or 0) / 60; home = d[2] == ev['home_id']
            second = clock > 45.5 and not str(d[1]).startswith('45')
            lo = off + clock + (15 if second else 0) - 1; hi = lo + (14 if second else 8)
            lo = max(lo, last_wall + 1)
            if d[4] and not d[3]:
                reds.append((home, clock)); continue
            w = [m for m in range(int(np.floor(lo)), int(np.ceil(hi)) + 1) if m in x.index]
            mv = [(x.get(m + 1, np.nan) - x.get(m - 1, np.nan)) * (1 if home else -1) for m in w]
            if not mv or not np.isfinite(np.nanmax(mv)) or np.nanmax(mv) <= 0.005:
                ok = False; break
            g = w[int(np.nanargmax(mv))]
            # minute the jump is complete: first minute after g where most of the 4-minute move is done
            h += home; a += (not home)
            placed.append(dict(wall=g, clock=clock, home=home, h=h, a=a, pen=d[5], og=d[6], jump=float(np.nanmax(mv))))
            last_wall = g
        if not ok: skipped['goal_not_found'] += 1; continue
        def score_at(m):
            hh = aa = 0
            for p in placed:
                if p['wall'] < m: hh, aa = p['h'], p['a']
            return hh, aa
        red_before = lambda clock: any(c <= clock for _, c in reds)
        # snapshots every 5 wall-minutes from kickoff, skipping minutes right around a goal
        for m in range(0, 116, 5):
            if any(-1 <= m - p['wall'] <= 2 for p in placed): continue
            k = df.loc[m, ['pH', 'pD', 'pA']].to_numpy(float)
            if not np.isfinite(k).all(): continue
            gmin = m if m <= 47 else (45 if m < 63 else min(90, m - 17))
            hh, aa = score_at(m); w = remaining(gmin)
            mod = probs(lh * w, la * w, hh, aa)
            snaps.append(dict(event=r.event, m=m, gmin=gmin, h=hh, a=aa, diff=hh - aa, red=red_before(gmin),
                              kH=k[0], kD=k[1], kA=k[2], mH=mod[0], mD=mod[1], mA=mod[2], yH=y[0], yD=y[1], yA=y[2]))
        for j, p in enumerate(placed):
            side = 0 if p['home'] else 2; nxt = placed[j + 1]['wall'] if j + 1 < len(placed) else 999
            rec = dict(event=r.event, wall=p['wall'], clock=p['clock'], home=p['home'], h=p['h'], a=p['a'], pen=p['pen'],
                       red=red_before(p['clock']), lead_after=(p['h'] - p['a']) * (1 if p['home'] else -1),
                       y_scorer=y[side], y_draw=y[1], y_conc=y[2 - side], next_wall=nxt)
            for lag in (-2, 1, 2, 3, 5, 10, 15, 20):
                mm = p['wall'] + lag
                if mm in df.index and (lag < 0 or mm + 1 < nxt):
                    k = df.loc[mm, ['pH', 'pD', 'pA']].to_numpy(float)
                    if np.isfinite(k).all():
                        rec[f's{lag}'] = k[side]; rec[f'd{lag}'] = k[1]; rec[f'c{lag}'] = k[2 - side]
            gmin = min(90, p['clock']); w = remaining(gmin); mod = probs(lh * w, la * w, p['h'], p['a'])
            rec['m_s'] = mod[side]; rec['m_d'] = mod[1]; rec['m_c'] = mod[2 - side]
            events.append(rec)
    E = pd.DataFrame(events); S = pd.DataFrame(snaps)
    E.to_csv(RES / 'inplay_goal_events.csv', index=False); S.to_csv(RES / 'inplay_snapshots.csv', index=False)
    print('matches used', S.event.nunique(), 'skipped', skipped, 'goals', len(E), 'snapshots', len(S))

    lg=lambda p: np.log(np.clip(p,1e-4,1-1e-4)/(1-np.clip(p,1e-4,1-1e-4)))
    def slope(p,y):
        x=lg(p); f=lambda t: -np.sum(y*(t[0]+t[1]*x)-np.log1p(np.exp(t[0]+t[1]*x)))
        return minimize(f,[0,1]).x
    def boot_by(df,fn,key='event',B=1000):
        ev=df[key].unique(); g={e:i for e,i in df.groupby(key).groups.items()}; out=[]
        for _ in range(B):
            s=RNG.choice(ev,len(ev)); idx=np.concatenate([g[e] for e in s]); out.append(fn(df.loc[idx]))
        out=np.array(out); return [float(np.percentile(out,2.5,axis=0) if out.ndim==1 else 0), float(np.percentile(out,97.5))] if out.ndim==1 else [np.percentile(out,2.5,axis=0).tolist(),np.percentile(out,97.5,axis=0).tolist()]
    R={}
    R['n_matches']=int(S.event.nunique()); R['n_goals']=int(len(E))
    # 1. post-goal prices vs what happened (scoring team wins)
    for lag in ('-2','1','2','5','10'):
        d=E.dropna(subset=['s'+lag]); gap=(d['s'+lag]-d.y_scorer)
        R[f'post_goal_{lag}']=dict(n=int(len(d)), price=float(d['s'+lag].mean()), actual=float(d.y_scorer.mean()), gap_pp=float(gap.mean()*100),
            ci_pp=[x*100 for x in boot_by(d.assign(g=gap),lambda z: z.g.mean())])
    # calibration slope of scorer-win prob 2 min after goal
    d=E.dropna(subset=['s2']).reset_index(drop=True)
    b=slope(d.s2.to_numpy(),d.y_scorer.to_numpy()); R['post_goal_slope']=dict(a=float(b[0]),b=float(b[1]),ci=boot_by(d,lambda z: slope(z.s2.to_numpy(),z.y_scorer.to_numpy())[1],B=500))
    # draw price after goal (scorer leads or equaliser)
    for name,sub in (('equaliser',d[d.lead_after==0]),('goes_ahead_by_1',d[d.lead_after==1])):
        if len(sub)>20:
            R[f'after_{name}']=dict(n=int(len(sub)), draw_price=float(sub.d2.mean()), draw_actual=float(sub.y_draw.mean()), scorer_price=float(sub.s2.mean()), scorer_actual=float(sub.y_scorer.mean()),
                draw_gap_ci_pp=[x*100 for x in boot_by(sub.assign(g=sub.d2-sub.y_draw).reset_index(drop=True),lambda z: z.g.mean())],
                scorer_gap_ci_pp=[x*100 for x in boot_by(sub.assign(g=sub.s2-sub.y_scorer).reset_index(drop=True),lambda z: z.g.mean())])
    # speed: share of the eventual 5-minute move already in the price after 1 minute
    s=E.dropna(subset=['s-2','s1','s5']); mv5=s.s5-s['s-2']; mv1=s.s1-s['s-2']
    m=mv5.abs()>0.05; R['speed_share_of_move_by_1min']=float((mv1[m]/mv5[m]).median())
    # 2. all in-play snapshots: calibration by phase, and draw pricing late in level games
    S=S.reset_index(drop=True)
    Pk=np.stack([S.kH,S.kD,S.kA],1); Pm=np.stack([S.mH,S.mD,S.mA],1); Y=np.stack([S.yH,S.yD,S.yA],1)
    ll=lambda P: -np.log(np.clip((P*Y).sum(1),1e-6,1))
    S['ll_k']=ll(Pk); S['ll_m']=ll(Pm)
    phase=[]
    for lo,hi,lab in ((0,30,"0-30'"),(30,60,"30-60'"),(60,75,"60-75'"),(75,91,"75-90'")):
        z=S[(S.gmin>=lo)&(S.gmin<hi)].reset_index(drop=True)
        p=np.concatenate([z.kH,z.kD,z.kA]); y=np.concatenate([z.yH,z.yD,z.yA]); bb=slope(p,y)
        phase.append(dict(phase=lab,n=int(len(z)),slope=float(bb[1]),ll_kalshi=float(z.ll_k.mean()),ll_model=float(z.ll_m.mean())))
    R['by_phase']=phase
    late=S[(S.gmin>=70)&(S['diff']==0)&(~S.red)].reset_index(drop=True)
    R['late_level_draw']=dict(n=int(len(late)), matches=int(late.event.nunique()), draw_price=float(late.kD.mean()), draw_actual=float(late.yD.mean()),
        gap_ci_pp=[x*100 for x in boot_by(late.assign(g=late.kD-late.yD),lambda z: z.g.mean())], model_draw=float(late.mD.mean()))
    late1=S[(S.gmin>=70)&(S['diff'].abs()==1)&(~S.red)].reset_index(drop=True)
    lead=np.where(late1['diff']>0,late1.kH,late1.kA); ylead=np.where(late1['diff']>0,late1.yH,late1.yA)
    R['late_one_goal_lead']=dict(n=int(len(late1)), matches=int(late1.event.nunique()), leader_price=float(lead.mean()), leader_actual=float(ylead.mean()),
        gap_ci_pp=[x*100 for x in boot_by(late1.assign(g=lead-ylead),lambda z: z.g.mean())], draw_price=float(late1.kD.mean()), draw_actual=float(late1.yD.mean()))
    d=(S.ll_k-S.ll_m); R['snap_ll_kalshi_minus_model']=float(d.mean()); R['snap_ll_ci']=boot_by(S.assign(g=d),lambda z: z.g.mean())
    print(json.dumps(R,indent=1)); (RES / 'kalshi_inplay.json').write_text(json.dumps(R, indent=1))


if __name__ == '__main__':
    main()
