"""Turning bookmaker odds into probabilities.

Raw implied probabilities 1/odds sum to more than 1; the excess is the
bookmaker's margin (overround). Two standard ways to remove it:

multiplicative : scale every implied probability down by the same factor.
                 Assumes the margin is spread proportionally to probability.

shin           : Shin (1991/1993). Models the book as protecting itself against
                 a share z of insiders. The margin then falls disproportionately
                 on longshots, which is exactly the favourite-longshot pattern.
                 Solve for z so the probabilities sum to 1.
"""
import numpy as np
from scipy.optimize import brentq


def overround(odds: np.ndarray) -> np.ndarray:
    return (1.0 / odds).sum(axis=1) - 1.0


def multiplicative(odds: np.ndarray) -> np.ndarray:
    q = 1.0 / odds
    return q / q.sum(axis=1, keepdims=True)


def _shin_probs(q: np.ndarray, z: float) -> np.ndarray:
    s = q.sum()
    return (np.sqrt(z**2 + 4 * (1 - z) * q**2 / s) - z) / (2 * (1 - z))


def shin(odds: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Returns (probabilities, z) for each row."""
    q = 1.0 / odds
    probs = np.empty_like(q)
    zs = np.empty(len(q))
    for i, row in enumerate(q):
        if row.sum() <= 1.0:  # no margin to remove (rare data errors)
            probs[i], zs[i] = row / row.sum(), 0.0
            continue
        f = lambda z: _shin_probs(row, z).sum() - 1.0
        z = brentq(f, 0.0, 0.5)
        zs[i] = z
        probs[i] = _shin_probs(row, z)
    return probs, zs
