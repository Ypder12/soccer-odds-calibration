"""Kalshi vs Polymarket on the same Premier League matches: price gaps and fee-adjusted arbitrage.

Data (data/xvenue/kalshi_polymarket_minutes.json): for 479 EPL matches listed on both venues
(Aug 2025 to Nov 2026), Kalshi's minute-by-minute best bid/ask and Polymarket's minute price history
(the CLOB prices-history endpoint), from 3 hours before kickoff to 150 minutes after. Only minutes where
a price changed are stored.

Polymarket's history gives one price per minute, not a bid and ask, so its quotes are approximated as
price +/- h (h = 0.25, 0.5 or 1 cent). A "lock-in" (arbitrage) exists when buying YES on one venue and
NO on the other costs less than $1 after both taker fees (Kalshi 0.07*P*(1-P), Polymarket sports
0.05*P*(1-P)). Intervals bootstrap whole matches.
"""
import json
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent; RES = ROOT / 'results'
RNG = np.random.default_rng(4)
X = json.load(open(ROOT / 'data' / 'xvenue' / 'kalshi_polymarket_minutes.json'))
PAIRS, KM, PMH = X['pairs'], X['km'], X['pmh']
M = pd.read_csv(ROOT / 'data' / 'kalshi' / 'matches.csv').set_index('event')
MIN = list(range(-180, 151))
fk = lambda p: 0.07 * p * (1 - p)   # Kalshi taker fee per $1 contract
fp = lambda p: 0.05 * p * (1 - p)   # Polymarket sports taker fee per share


def kseries(s):
    rows = []
    for tok in (s or '').split(','):
        if not tok: continue
        m, b, a = tok.split(':'); rows.append((int(m), float(b) / 1000 if b else np.nan, float(a) / 1000 if a else np.nan))
    d = pd.DataFrame(rows, columns=['m', 'b', 'a']).drop_duplicates('m', keep='last').set_index('m')
    return d.reindex(sorted(set(d.index) | set(MIN))).ffill().reindex(MIN)


def pseries(s):
    rows = []
    for tok in (s or '').split(','):
        if not tok: continue
        m, p = tok.split(':'); rows.append((int(m), float(p) / 1000))
    d = pd.DataFrame(rows, columns=['m', 'p']).drop_duplicates('m', keep='last').set_index('m')
    return d.reindex(sorted(set(d.index) | set(MIN))).ffill().reindex(MIN).p


rows = []
for P in PAIRS:
    e = P['k']
    for s, sfx in (('H', e[-6:-3]), ('D', 'TIE'), ('A', e[-3:])):
        ks, ps = KM.get(f'KXEPLGAME-{e}-{sfx}'), PMH.get(P[s])
        if not ks or ks in ('NA', 'ERR') or not ps or ps in ('NA', 'ERR'): continue
        k = kseries(ks); p = pseries(ps)
        df = pd.DataFrame({'kb': k.b, 'ka': k.a, 'pm': p})
        df['event'] = e; df['side'] = s; df['m'] = df.index; df['pm_vol'] = P['vol']
        df['res'] = M.loc[e, 'FTR'] if e in M.index else np.nan
        rows.append(df)
D = pd.concat(rows, ignore_index=True)
D = D[np.isfinite(D.kb) & np.isfinite(D.ka) & np.isfinite(D.pm) & (D.ka - D.kb <= 0.10) & (D.pm > 0.005) & (D.pm < 0.995) & (D.kb > 0) & (D.ka < 1)]
D['kmid'] = (D.kb + D.ka) / 2
D['gap'] = D.pm - D.kmid
print('rows', len(D), 'matches', D.event.nunique())

# ---------------- statistics ----------------
def boot(df,fn,B=1000):
    ev=df.event.unique(); g=df.groupby('event').indices; out=[]
    for _ in range(B):
        s=RNG.choice(ev,len(ev)); out.append(fn(df.iloc[np.concatenate([g[e] for e in s])]))
    return [float(np.percentile(out,2.5)),float(np.percentile(out,97.5))]
R={'matches':int(D.event.nunique()),'minute_rows':int(len(D))}
D['phase']=np.where(D.m<0,'pre','inplay')
D=D[D.m<=110]
for ph in ('pre','inplay'):
    z=D[D.phase==ph]
    R[ph]=dict(rows=int(len(z)), mean_abs_gap_c=float(z.gap.abs().mean()*100), median_abs_gap_c=float(z.gap.abs().median()*100),
               share_gap_over_2c=float((z.gap.abs()>.02).mean()), share_gap_over_5c=float((z.gap.abs()>.05).mean()),
               mean_gap_pm_minus_kalshi_c=float(z.gap.mean()*100), kalshi_spread_c=float((z.ka-z.kb).mean()*100))
# arbitrage at each minute, Polymarket half-spread assumption h
arb={}
for h in (0.0025,0.005,0.01):
    pb,pa=D.pm-h,D.pm+h
    e1=1-(D.ka+fk(D.ka)+(1-pb)+fp(pb))       # buy Kalshi YES + Polymarket NO
    e2=1-(pa+fp(pa)+(1-D.kb)+fk(D.kb))       # buy Polymarket YES + Kalshi NO
    e=np.maximum(e1,e2); D[f'edge_{h}']=e
    res={}
    for ph in ('pre','inplay'):
        z=D[D.phase==ph]; ez=e[z.index]
        res[ph]=dict(share_minutes_arb=float((ez>0).mean()), share_minutes_arb_1c=float((ez>0.01).mean()),
                     matches_with_any_arb=int(z[ez>0].event.nunique()), mean_edge_when_arb_c=float(ez[ez>0].mean()*100) if (ez>0).any() else 0)
    arb[str(h)]=res
R['arbitrage']=arb
# episodes (h=0.005): consecutive minutes with edge>0 for same event/side
z=D[D['edge_0.005']>0].sort_values(['event','side','m']); ep=[]
for (e,s),g in z.groupby(['event','side']):
    run=1; prev=None
    for m in g.m:
        if prev is not None and m==prev+1: run+=1
        else:
            if prev is not None: ep.append(run)
            run=1
        prev=m
    ep.append(run)
R['arb_episodes']=dict(n=len(ep), median_minutes=float(np.median(ep)) if ep else 0, share_1min=float(np.mean(np.array(ep)==1)) if ep else 0)
# who moves toward whom when they disagree: next-10-minute change of each venue vs current gap
D=D.sort_values(['event','side','m'])
for c in ('kmid','pm'):
    D['f_'+c]=D.groupby(['event','side'])[c].shift(-10)-D[c]
z=D[(D.gap.abs()>0.02)&D.f_kmid.notna()&D.f_pm.notna()&(D.phase=='pre')]
bk=np.polyfit(z.gap,z.f_kmid,1)[0]; bp=np.polyfit(z.gap,z.f_pm,1)[0]
R['gap_closing_pre']=dict(n=int(len(z)), kalshi_moves_share=float(bk/(bk-bp)), polymarket_moves_share=float(-bp/(bk-bp)), beta_kalshi=float(bk), beta_pm=float(bp))
z=D[(D.gap.abs()>0.02)&D.f_kmid.notna()&D.f_pm.notna()&(D.phase=='inplay')]
bk=np.polyfit(z.gap,z.f_kmid,1)[0]; bp=np.polyfit(z.gap,z.f_pm,1)[0]
R['gap_closing_inplay']=dict(n=int(len(z)), kalshi_moves_share=float(bk/(bk-bp)), polymarket_moves_share=float(-bp/(bk-bp)), beta_kalshi=float(bk), beta_pm=float(bp))
# accuracy at kickoff-5 vs result
k=D[(D.m==-5)].copy()
k=k[k.res.notna()]
k['y']=(k.res==k.side).astype(float)
piv=k.pivot_table(index='event',columns='side',values=['kmid','pm','y'])
ok=piv.notna().all(1); piv=piv[ok]
KP=piv['kmid'][['H','D','A']].to_numpy(); KP=KP/KP.sum(1,keepdims=True)
PP=piv['pm'][['H','D','A']].to_numpy(); PP=PP/PP.sum(1,keepdims=True)
Y=piv['y'][['H','D','A']].to_numpy()
ll=lambda P: -np.log(np.clip((P*Y).sum(1),1e-6,1)); d=ll(KP)-ll(PP)
idx=RNG.integers(0,len(d),(4000,len(d)))
R['kickoff_accuracy']=dict(n=int(len(d)), ll_kalshi=float(ll(KP).mean()), ll_polymarket=float(ll(PP).mean()), diff=float(d.mean()), ci=[float(np.percentile(d[idx].mean(1),2.5)),float(np.percentile(d[idx].mean(1),97.5))])
# where the apparent in-play lock-ins happen: share within -1..+3 minutes of a goal (ESPN times, see kalshi_inplay.py)
E=pd.read_csv(RES/'inplay_goal_events.csv'); gw=E.groupby('event').wall.apply(list).to_dict()
z=D[(D.phase=='inplay')&(D['edge_0.005']>0)&D.event.isin(gw)]; allin=D[(D.phase=='inplay')&D.event.isin(gw)]
near=lambda df: np.mean([any(-1<=m-w<=3 for w in gw[e]) for e,m in zip(df.event,df.m)])
R['inplay_arb_near_goals']=dict(share_of_arb_minutes=float(near(z)), share_of_all_inplay_minutes=float(near(allin.iloc[::10])), median_minute=float(z.m.median()))
L=json.load(open(ROOT/'data'/'xvenue'/'live_snapshot_2026-11-17.json'))
e=[max(r[6],r[9]) for r in L['rows']]
R['live_snapshot']=dict(time=L['t'], outcomes=len(e), best_edge_c=float(max(e)*100), mean_edge_c=float(np.mean(e)*100), lockins=int(sum(x>0 for x in e)),
                        same_best_ask=int(sum(r[2]==r[3] for r in L['rows'])))
(RES/'xvenue.json').write_text(json.dumps(R,indent=1)); print(json.dumps(R,indent=1))
D.to_pickle(RES/'xvenue_panel.pkl')
