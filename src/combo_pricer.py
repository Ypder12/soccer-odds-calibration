"""Soccer combo (same-game parlay) pricer.

Turns the market's single-match prices into a full scoreline distribution, then prices any
combination of legs on that match from it, so linked legs (a favourite winning and the match going
over 2.5, say) are priced together instead of multiplied as if independent.

Models (each turns fair, margin-free 1X2 + over/under 2.5 prices into a grid of final scores)
  "poisson"  each team's goals Poisson(lh), Poisson(la); 2 parameters fitted by least squares to
             the 4 prices. Cannot match the market's draw price exactly (it prices draws ~1.5
             points too low on average).
  "dc"       Dixon-Coles: Poisson plus one parameter rho that moves probability between the low
             scores (0-0, 1-1 vs 1-0, 0-1). With 3 parameters per match the grid reproduces home,
             draw, away and over 2.5 exactly.
  "tilt"     Poisson plus one parameter kappa that reweights scores where both teams scored by
             e^kappa. Also reproduces all four prices exactly. Captures game-state effects: a team
             that goes behind attacks, so one side scoring makes the other side's goal more likely.
No parameter is learned from results: every grid comes only from that match's own prices.
Tested on 6,060 matches (src/combo_study.py): all three price combos about equally well, and plain
Poisson is marginally the best, so it is the default. Matching the market's draw price exactly does
not help, because the market's own draw price runs slightly high.

In-play: given the current score (h0, a0) and live 1X2 prices, the rates for the goals still to
come are refitted (Poisson) and added to the current score.

Usage
  >>> P = Pricer()            # "poisson"; or Pricer("dc") / Pricer("tilt")
  >>> g = P.grid(p_home=.55, p_draw=.25, p_away=.20, p_over=.52)
  >>> P.price(g, ["home", "over2.5"]), P.independent(g, ["home", "over2.5"])
"""
from __future__ import annotations
import numpy as np
from scipy.optimize import least_squares
from scipy.stats import poisson

N = 11                      # goals 0..10 per team
G = np.arange(N)
H, A = np.meshgrid(G, G, indexing="ij")   # H[i, j] = i home goals, A[i, j] = j away goals
BOTH = (H > 0) & (A > 0)


def score_grid(lh: float, la: float, rho: float = 0.0, kappa: float = 0.0, h0: int = 0, a0: int = 0) -> np.ndarray:
    """Probability of each final score (rows = home goals, cols = away goals).

    lh, la: rates for the goals still to come; (h0, a0): score so far. rho (Dixon-Coles) and
    kappa (both-teams-score tilt) apply pre-match only.
    """
    M = np.outer(poisson.pmf(G, lh), poisson.pmf(G, la))
    if h0 == 0 and a0 == 0:
        if rho:
            M[0, 0] *= 1 - lh * la * rho
            M[0, 1] *= 1 + lh * rho
            M[1, 0] *= 1 + la * rho
            M[1, 1] *= 1 - rho
            M = np.clip(M, 0, None)
        if kappa:
            M = M * np.where(BOTH, np.exp(kappa), 1.0)
    M /= M.sum()
    if h0 or a0:                       # shift the remaining-goal grid by the current score
        S = np.zeros((N, N))
        S[h0:, a0:] = M[: N - h0, : N - a0]
        M = S / S.sum()
    return M


def _legs():
    T = H + A
    L = {"home": H > A, "draw": H == A, "away": H < A,
         "btts": BOTH, "no_btts": ~BOTH,
         "home_scores": H > 0, "away_scores": A > 0,
         "home_clean_sheet": A == 0, "away_clean_sheet": H == 0,
         "home_or_draw": H >= A, "away_or_draw": H <= A}
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        L[f"over{line}"] = T > line
        L[f"under{line}"] = T < line
    return L


LEGS = _legs()   # each leg is a boolean mask over final scores


def mask(legs) -> np.ndarray:
    m = np.ones((N, N), bool)
    for leg in legs:
        m &= LEGS[leg]
    return m


class Pricer:
    def __init__(self, model: str = "poisson"):
        assert model in ("poisson", "dc", "tilt")
        self.model = model

    def fit(self, p_home, p_draw, p_away, p_over):
        """Pre-match fit. Returns (grid, params, max abs pricing error vs the four inputs)."""
        target = np.array([p_home, p_draw, p_away, p_over])
        legs = [LEGS["home"], LEGS["draw"], LEGS["away"], LEGS["over2.5"]]

        def grid_of(t):
            lh, la = np.exp(t[:2])
            if self.model == "poisson":
                return score_grid(lh, la)
            if self.model == "dc":
                return score_grid(lh, la, rho=t[2])
            return score_grid(lh, la, kappa=t[2])

        def resid(t):
            g = grid_of(t)
            return np.array([g[m].sum() for m in legs]) - target

        if self.model == "poisson":
            x0, lo, hi = [np.log(1.4), np.log(1.1)], [-9, -9], [2.1, 2.1]
        elif self.model == "dc":
            x0, lo, hi = [np.log(1.4), np.log(1.1), -0.05], [-9, -9, -0.5], [2.1, 2.1, 0.5]
        else:
            x0, lo, hi = [np.log(1.4), np.log(1.1), 0.2], [-9, -9, -1.5], [2.1, 2.1, 1.5]
        r = least_squares(resid, x0=x0, bounds=(lo, hi))
        return grid_of(r.x), r.x, float(np.abs(r.fun).max())

    def grid(self, p_home, p_draw, p_away, p_over):
        return self.fit(p_home, p_draw, p_away, p_over)[0]

    @staticmethod
    def fit_inplay(p_home, p_draw, p_away, h0, a0):
        """In-play: Poisson rates for the rest of the match that reproduce live 1X2 at score h0-a0."""
        target = np.array([p_home, p_draw, p_away])
        legs = [LEGS["home"], LEGS["draw"], LEGS["away"]]

        def resid(t):
            g = score_grid(*np.exp(t), h0=h0, a0=a0)
            return np.array([g[m].sum() for m in legs]) - target

        r = least_squares(resid, x0=np.log([0.6, 0.5]), bounds=(np.log(1e-4), np.log(6)))
        return score_grid(*np.exp(r.x), h0=h0, a0=a0), np.exp(r.x), float(np.abs(r.fun).max())

    @staticmethod
    def price(grid, legs) -> float:
        """Fair probability that every leg wins (a same-game parlay)."""
        return float(grid[mask(legs)].sum())

    @staticmethod
    def independent(grid, legs) -> float:
        """What multiplying the legs' own fair prices would give (the naive parlay price)."""
        return float(np.prod([grid[LEGS[leg]].sum() for leg in legs]))

    def correlation_factor(self, grid, legs) -> float:
        """Joint price / independent price. > 1: legs win together more often than independence implies."""
        return self.price(grid, legs) / self.independent(grid, legs)
