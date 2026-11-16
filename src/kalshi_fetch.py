"""Download Kalshi Premier League prices (match result and over/under 2.5) around kickoff.

Writes data/kalshi/kalshi_1x2.json and data/kalshi/kalshi_ou25.json, which
src/kalshi_vs_books.py reads. The data used in the write-up was collected with the
same logic on 16 Nov 2026 (run from a browser session); this script is the
plain-Python version of that download.

Kalshi's public API needs no key. Markets settled before the "historical cutoff"
are served from /historical/..., newer ones from /series/....
Over/under tickers changed meaning over time (suffix -3 was "over 3.5" in 2025/26
and "over 2.5" in 2026/27), so the over-2.5 market is found by its floor_strike.
"""
import json, re, time, sys
from pathlib import Path
import datetime as dt
from zoneinfo import ZoneInfo
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "kalshi"
B = "https://api.elections.kalshi.com/trade-api/v2"
S = requests.Session()

NAME = {"Manchester United": "Man United", "Man Utd": "Man United", "Manchester City": "Man City",
        "Nottingham Forest": "Nott'm Forest", "Nottingham": "Nott'm Forest", "Wolverhampton": "Wolves",
        "Leeds United": "Leeds", "Hull City": "Hull", "Ipswich Town": "Ipswich"}


def get(url, params=None):
    for a in range(8):
        r = S.get(url, params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(1.5 * (a + 1)); continue
        time.sleep(0.12)
        return r
    return None


def events():
    out, cur = [], None
    while True:
        p = {"series_ticker": "KXEPLGAME", "status": "settled", "limit": 200}
        if cur: p["cursor"] = cur
        d = get(B + "/events", p).json()
        out += [(e["event_ticker"], e["title"]) for e in d["events"]]
        cur = d.get("cursor")
        if not cur: return out


def kickoffs(evs):
    F = []
    for f in ["E0_2425.csv", "E0_2526.csv", "E0_2627.csv"]:
        F.append(pd.read_csv(ROOT / "data" / f, encoding="latin-1"))
    F = pd.concat(F, ignore_index=True)
    F["date"] = pd.to_datetime(F.Date, dayfirst=True).dt.date
    jobs, rows = [], []
    for tk, title in evs:
        h, a = [NAME.get(s.strip(), s.strip()) for s in title.split(":")[0].split(" vs ")]
        m = re.search(r"-(\d\d)([A-Z]{3})(\d\d)", tk)
        d = dt.datetime.strptime("".join(m.groups()), "%y%b%d").date()
        c = F[(F.HomeTeam == h) & (F.AwayTeam == a) & ((pd.to_datetime(F.date) - pd.Timestamp(d)).abs().dt.days <= 1)]
        if len(c) != 1: continue
        r = c.iloc[0]
        ko = dt.datetime.combine(r.date, dt.datetime.strptime(r.Time, "%H:%M").time()).replace(tzinfo=ZoneInfo("Europe/London"))
        jobs.append((tk.split("-", 1)[1], int(ko.timestamp())))
        cols = ["Date", "Time", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR", "PSCH", "PSCD", "PSCA", "AvgCH", "AvgCD", "AvgCA",
                "PSC>2.5", "PSC<2.5", "AvgC>2.5", "AvgC<2.5"]
        rows.append({"event": tk.split("-", 1)[1], **{c: r.get(c) for c in cols}})
    pd.DataFrame(rows).rename(columns={"PSC>2.5": "PSCO", "PSC<2.5": "PSCU", "AvgC>2.5": "AvgCO", "AvgC<2.5": "AvgCU"}).to_csv(OUT / "matches.csv", index=False)
    return jobs


def candles(series, ticker, ko):
    q = {"start_ts": ko - 26 * 3600, "end_ts": ko, "period_interval": 60}
    r = get(f"{B}/historical/markets/{ticker}/candlesticks", q)
    if r is None or r.status_code != 200:
        r = get(f"{B}/series/{series}/markets/{ticker}/candlesticks", q)
    if r is None or r.status_code != 200: return None
    cs = []
    for c in r.json().get("candlesticks", []):
        g = lambda o, k: (o or {}).get(k + "_dollars", (o or {}).get(k))
        bid, ask = g(c.get("yes_bid"), "close"), g(c.get("yes_ask"), "close")
        if bid is None or ask is None: continue
        bid, ask = float(bid), float(ask)
        if ask - bid <= 0.05 and c["end_period_ts"] <= ko:
            cs.append([c["end_period_ts"], bid, ask])
    at = lambda h: next((c for c in reversed(cs) if c[0] <= ko - h * 3600), None)
    return [at(0), at(1), at(3), at(24)]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = kickoffs(events())
    print(len(jobs), "matches")
    x12, ou = {}, {}
    for n, (e, ko) in enumerate(jobs):
        for s in (e[-6:-3], e[-3:], "TIE"):
            t = f"KXEPLGAME-{e}-{s}"
            x12[t] = candles("KXEPLGAME", t, ko)
        for sfx in ("2", "3"):
            t = f"KXEPLTOTAL-{e}-{sfx}"
            r = get(f"{B}/historical/markets/{t}")
            if r is None or r.status_code != 200: r = get(f"{B}/markets/{t}")
            if r is not None and r.status_code == 200 and float(r.json()["market"].get("floor_strike") or 0) == 2.5:
                ou[e] = [t, r.json()["market"].get("result"), candles("KXEPLTOTAL", t, ko)]
                break
        if n % 25 == 0: print(n, file=sys.stderr)
    json.dump({"kickoffs": dict(jobs), "markets": x12}, open(OUT / "kalshi_1x2.json", "w"))
    json.dump(ou, open(OUT / "kalshi_ou25.json", "w"))


if __name__ == "__main__":
    main()
