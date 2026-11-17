"""Live Kalshi vs Polymarket scanner for Premier League match markets (paper trading only).

Every POLL seconds it:
  1. finds upcoming EPL matches listed on both venues (home win / draw / away win),
  2. reads both order books,
  3. checks the two "lock-in" trades for each outcome:
       A. buy YES on Kalshi + buy NO on Polymarket
       B. buy YES on Polymarket + buy NO on Kalshi
     One of the pair pays $1 whatever happens, so the trade locks in a profit if the total cost,
     including both venues' taker fees, is under $1. Prices are walked through the book for SIZE
     contracts (VWAP), not just the top level.
  4. logs every check to results/xvenue_scan_log.csv and records a paper trade when the locked-in
     edge beats MIN_EDGE.

It never places orders. Run:  python src/xvenue_scanner.py   (Ctrl+C to stop)
Fees: Kalshi 0.07*P*(1-P) per contract; Polymarket sports 0.05*P*(1-P) per share (taker).
Caveat: the two venues' settlement rules must match for the "lock" to be real (both settle EPL
match results on the 90 minutes plus stoppage time; check before trusting a new market type).
"""
import csv, json, time, datetime as dt
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "results" / "xvenue_scan_log.csv"
K = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA, CLOB = "https://gamma-api.polymarket.com", "https://clob.polymarket.com"
POLL, SIZE, MIN_EDGE = 20, 100, 0.005
fk = lambda p: 0.07 * p * (1 - p)
fp = lambda p: 0.05 * p * (1 - p)
MAP = {"ars": ["ARS"], "ast": ["AVL"], "bou": ["BOU"], "bre": ["BRE"], "bri": ["BRI", "BHA"], "bur": ["BUR"], "che": ["CFC", "CHE"],
       "cov": ["COV"], "cry": ["CRY"], "eve": ["EVE"], "ful": ["FUL"], "hul": ["HUL"], "ips": ["IPS"], "lee": ["LEE"], "liv": ["LFC"],
       "mac": ["MCI"], "mun": ["MUN"], "new": ["NEW"], "not": ["NFO"], "sun": ["SUN"], "tot": ["TOT"], "wes": ["WHU"], "wol": ["WOL"]}
S = requests.Session()


def get(url, **params):
    for a in range(6):
        r = S.get(url, params=params, timeout=20)
        if r.status_code == 429:
            time.sleep(1.5 * (a + 1)); continue
        r.raise_for_status(); return r.json()
    raise RuntimeError("rate limited: " + url)


def pairs():
    """Upcoming EPL matches on both venues: list of dicts with Kalshi tickers and Polymarket token ids."""
    kev = get(K + "/events", series_ticker="KXEPLGAME", status="open", limit=200)["events"]
    ktick = {e["event_ticker"].split("-", 1)[1]: e for e in kev}
    pm = get(GAMMA + "/events", series_id="10188", closed="false", limit=200)
    out = []
    for e in pm:
        parts = e["slug"].split("-")
        if len(parts) != 6 or parts[0] != "epl": continue
        h, a, date = parts[1], parts[2], "-".join(parts[3:])
        d = dt.date.fromisoformat(date)
        for code in ktick:
            kd = dt.datetime.strptime(code[:7], "%y%b%d").date()
            if abs((kd - d).days) <= 1 and code[-6:-3] in MAP.get(h, []) and code[-3:] in MAP.get(a, []):
                home = e["title"].split(" vs")[0].strip(); tok = {}
                for m in e["markets"]:
                    t = json.loads(m["clobTokenIds"])  # [yes, no]
                    g = (m.get("groupItemTitle") or m["question"]).strip()
                    side = "D" if "draw" in g.lower() else ("H" if g == home else "A")
                    tok[side] = t
                ks = {"H": f"KXEPLGAME-{code}-{code[-6:-3]}", "D": f"KXEPLGAME-{code}-TIE", "A": f"KXEPLGAME-{code}-{code[-3:]}"}
                if len(tok) == 3: out.append(dict(match=code, slug=e["slug"], k=ks, pm=tok))
    return out


def vwap(levels, size):
    """Average price to buy `size` from ask levels [(price, qty)] sorted best first; None if too thin."""
    got, cost = 0.0, 0.0
    for p, q in levels:
        take = min(q, size - got); cost += take * p; got += take
        if got >= size: return cost / size
    return None


def kalshi_asks(ticker):
    j = get(f"{K}/markets/{ticker}/orderbook")
    ob = j.get("orderbook_fp") or j.get("orderbook") or {}
    def lv(key):  # bids for one side as [(price in dollars, qty)]
        if ob.get(key + "_dollars"):
            return [(float(p), float(q)) for p, q in ob[key + "_dollars"]]
        return [(float(p) / 100, float(q)) for p, q in (ob.get(key) or [])]   # older format, cents
    yes_bids, no_bids = lv("yes"), lv("no")
    # buying YES = hitting NO bids: price 1 - no_bid; buying NO = 1 - yes_bid
    yes_asks = sorted([(round(1 - p, 4), q) for p, q in no_bids])
    no_asks = sorted([(round(1 - p, 4), q) for p, q in yes_bids])
    return yes_asks, no_asks


def pm_asks(token):
    b = get(CLOB + "/book", token_id=token)
    return sorted([(float(x["price"]), float(x["size"])) for x in b.get("asks", [])])


def scan_once(P, writer, trades):
    now = dt.datetime.utcnow().isoformat(timespec="seconds")
    for p in P:
        for s in "HDA":
            ky, kn = kalshi_asks(p["k"][s])
            py, pn = pm_asks(p["pm"][s][0]), pm_asks(p["pm"][s][1])
            for name, a1, f1, a2, f2 in (("K_yes+PM_no", vwap(ky, SIZE), fk, vwap(pn, SIZE), fp),
                                          ("PM_yes+K_no", vwap(py, SIZE), fp, vwap(kn, SIZE), fk)):
                if a1 is None or a2 is None: continue
                cost = a1 + f1(a1) + a2 + f2(a2); edge = 1 - cost
                writer.writerow([now, p["match"], s, name, round(a1, 4), round(a2, 4), round(cost, 4), round(edge, 4)])
                if edge >= MIN_EDGE:
                    trades.append((now, p["match"], s, name, edge))
                    print(f"{now} PAPER TRADE {p['match']} {s} {name}: cost {cost:.3f} -> locked edge {edge*100:.2f}c per $1")


def main():
    LOG.parent.mkdir(exist_ok=True)
    new = not LOG.exists()
    with open(LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["utc", "match", "outcome", "trade", "price_1", "price_2", "total_cost", "edge"])
        trades, P, refreshed = [], [], 0
        while True:
            if time.time() - refreshed > 600:
                P = pairs(); refreshed = time.time(); print(f"{len(P)} matches on both venues")
            try:
                scan_once(P, w, trades); f.flush()
            except Exception as ex:
                print("scan error:", ex)
            print(f"{dt.datetime.utcnow():%H:%M:%S} scanned {len(P)} matches, {len(trades)} paper trades so far")
            time.sleep(POLL)


if __name__ == "__main__":
    main()
