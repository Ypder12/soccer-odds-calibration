"""Load football-data.co.uk CSVs into one tidy match table.

One row per match. Columns kept:
  league, season, date, home, away, result (H/D/A)
  pin_open_*  : Pinnacle pre-match odds (PSH/PSD/PSA)          -- all seasons except 2026/27
  pin_close_* : Pinnacle closing odds (PSCH/PSCD/PSCA)         -- all seasons except 2026/27
  b365_open_* : Bet365 pre-match odds (B365H/D/A)              -- all seasons
  best_open_* : best price across books, pre-match (MaxH / BbMxH)
  best_close_*: best closing price across books (MaxCH)        -- 2019/20 onwards
"""
from pathlib import Path
import pandas as pd
import numpy as np

DATA = Path(__file__).resolve().parent.parent / "data"
LEAGUE_NAMES = {"E0": "Premier League", "E1": "Championship"}

COLMAP = {
    "pin_open": ("PSH", "PSD", "PSA"),
    "pin_close": ("PSCH", "PSCD", "PSCA"),
    "b365_open": ("B365H", "B365D", "B365A"),
    "best_close": ("MaxCH", "MaxCD", "MaxCA"),
}
BEST_OPEN_ALTS = [("MaxH", "MaxD", "MaxA"), ("BbMxH", "BbMxD", "BbMxA")]


def _read(path: Path) -> pd.DataFrame:
    # some seasons have trailing empty columns / odd encodings
    df = pd.read_csv(path, encoding="latin-1", on_bad_lines="skip")
    df = df.dropna(how="all")
    lg, season = path.stem.split("_")
    out = pd.DataFrame({
        "league": lg,
        "season": f"20{season[:2]}/{season[2:]}",
        "date": pd.to_datetime(df["Date"], format="mixed", dayfirst=True, errors="coerce"),
        "home": df["HomeTeam"],
        "away": df["AwayTeam"],
        "result": df["FTR"],
    })
    for name, cols in COLMAP.items():
        for side, c in zip("HDA", cols):
            out[f"{name}_{side}"] = pd.to_numeric(df[c], errors="coerce") if c in df else np.nan
    for cols in BEST_OPEN_ALTS:
        if cols[0] in df:
            for side, c in zip("HDA", cols):
                out[f"best_open_{side}"] = pd.to_numeric(df[c], errors="coerce")
            break
    else:
        for side in "HDA":
            out[f"best_open_{side}"] = np.nan
    return out


def load_all() -> pd.DataFrame:
    frames = [_read(p) for p in sorted(DATA.glob("E*_*.csv"))]
    df = pd.concat(frames, ignore_index=True)
    df = df[df["result"].isin(["H", "D", "A"])].copy()
    df["match_id"] = np.arange(len(df))
    return df


def odds(df: pd.DataFrame, book: str) -> np.ndarray:
    """(n, 3) array of decimal odds in H, D, A order."""
    return df[[f"{book}_H", f"{book}_D", f"{book}_A"]].to_numpy(float)


def outcome_matrix(df: pd.DataFrame) -> np.ndarray:
    """(n, 3) one-hot of the actual result, H, D, A order."""
    return np.stack([(df["result"] == s).to_numpy() for s in "HDA"], axis=1).astype(float)


if __name__ == "__main__":
    df = load_all()
    print(df.groupby(["league", "season"]).agg(
        matches=("result", "size"),
        first=("date", "min"),
        pin_close=("pin_close_H", lambda s: s.notna().mean()),
        b365=("b365_open_H", lambda s: s.notna().mean()),
        best_close=("best_close_H", lambda s: s.notna().mean()),
    ).to_string())
