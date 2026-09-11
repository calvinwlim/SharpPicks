"""Shared logistic-regression fitting for the offline model builders.

Pure Python on purpose: the bundled model files are plain JSON and nothing under
``backend/`` may grow a numerical dependency. The builders originally used 4000
epochs of batch gradient descent; this module replaces that with **Newton/IRLS**,
which converges on these problems in well under 10 iterations and lands on the
actual ridge optimum instead of wherever 4000 fixed-step epochs happened to stop.
That makes a full refit seconds rather than minutes, which is what makes the
sweeps in ``mma_experiments.py`` affordable.

Also provides **sign-constrained** fitting (``nonneg``). Under L2 with collinear
inputs a logistic will happily hand a causally-positive feature a negative
weight — the shipped winner model had knockdowns, submission attempts and
control time all pulling the wrong way. Constraining those to >= 0 is solved
exactly here with an active set: fit, pin the violators to zero, refit the rest,
repeat. The objective is convex and the constraints are simple bounds, so this
terminates at the true constrained optimum.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple


def _standardize(X: List[List[float]]) -> Tuple[List[List[float]], List[float], List[float]]:
    """Center/scale columns; returns (Xs, mean, std). Zero-variance cols get std 1."""
    n, dim = len(X), len(X[0])
    mu = [sum(row[j] for row in X) / n for j in range(dim)]
    sd = []
    for j in range(dim):
        var = sum((row[j] - mu[j]) ** 2 for row in X) / n
        s = math.sqrt(var)
        sd.append(s if s > 1e-12 else 1.0)
    Xs = [[(row[j] - mu[j]) / sd[j] for j in range(dim)] for row in X]
    return Xs, mu, sd


def _solve(A: List[List[float]], b: List[float]) -> List[float]:
    """Gaussian elimination with partial pivoting. A is square, modified in place."""
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-14:
            M[col][col] += 1e-9  # singular guard: nudge and continue
            piv = col
        M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        for r in range(n):
            if r == col:
                continue
            f = M[r][col] / pv
            if f:
                for c in range(col, n + 1):
                    M[r][c] -= f * M[col][c]
    return [M[i][n] / M[i][i] for i in range(n)]


def _sigmoid(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def _irls(Xs: List[List[float]], y: Sequence[float], l2: float,
          active: List[int], iters: int = 25, tol: float = 1e-9) -> Tuple[List[float], float]:
    """Ridge-penalised logistic Newton step loop over the ``active`` columns.

    Returns (weights over active columns, intercept). The intercept is fitted but
    never penalised.
    """
    n = len(Xs)
    k = len(active)
    w = [0.0] * k
    b = 0.0
    prev_ll = None
    for _ in range(iters):
        # Build the penalised gradient and Hessian in one pass over the rows.
        dim = k + 1  # + intercept
        H = [[0.0] * dim for _ in range(dim)]
        g = [0.0] * dim
        ll = 0.0
        for i in range(n):
            row = Xs[i]
            z = b + sum(w[j] * row[active[j]] for j in range(k))
            p = _sigmoid(z)
            r = y[i] - p
            wt = max(p * (1.0 - p), 1e-9)
            ll += (y[i] * math.log(p + 1e-12)) + ((1 - y[i]) * math.log(1 - p + 1e-12))
            xs = [row[active[j]] for j in range(k)] + [1.0]
            for a in range(dim):
                xa = xs[a]
                if xa == 0.0:
                    continue
                g[a] += r * xa
                ha = H[a]
                for c in range(a, dim):
                    ha[c] += wt * xa * xs[c]
        for a in range(dim):
            for c in range(a):
                H[a][c] = H[c][a]
        # Ridge on the weights only (not the intercept).
        for a in range(k):
            g[a] -= l2 * w[a]
            H[a][a] += l2
        ll -= 0.5 * l2 * sum(v * v for v in w)
        step = _solve(H, g)
        for j in range(k):
            w[j] += step[j]
        b += step[k]
        if prev_ll is not None and abs(ll - prev_ll) < tol * max(1.0, abs(prev_ll)):
            break
        prev_ll = ll
    return w, b


def fit_logistic(X: List[List[float]], y: Sequence[float], l2: float = 1.0,
                 nonneg: Optional[Sequence[int]] = None) -> Tuple[List[float], float]:
    """Fit ridge logistic regression; return (weights, intercept) in RAW feature space.

    ``nonneg`` is a list of column indices whose weight must not be negative
    (features with a known causal direction). Solved by active set: any violator
    is pinned to exactly zero and the rest refit, until no constraint is violated.
    """
    Xs, mu, sd = _standardize(X)
    dim = len(X[0])
    nonneg_set = set(nonneg or ())
    active = list(range(dim))

    while True:
        w_act, b = _irls(Xs, y, l2, active)
        # A nonneg feature with a negative standardized weight is at its bound
        # (sd > 0, so the sign is the same in raw and standardized space).
        violators = [active[j] for j in range(len(active))
                     if active[j] in nonneg_set and w_act[j] < 0.0]
        if not violators:
            break
        active = [c for c in active if c not in violators]
        if not active:
            return [0.0] * dim, b

    # Expand back to full width, then de-standardize.
    w_std = [0.0] * dim
    for j, col in enumerate(active):
        w_std[col] = w_act[j]
    w_raw = [w_std[j] / sd[j] for j in range(dim)]
    b_raw = b - sum(w_std[j] * mu[j] / sd[j] for j in range(dim))
    return w_raw, b_raw


def predict(w: Sequence[float], b: float, feats: Sequence[float]) -> float:
    return _sigmoid(b + sum(w[i] * feats[i] for i in range(len(w))))


def brier(p: Sequence[float], o: Sequence[float]) -> float:
    return sum((a - c) ** 2 for a, c in zip(p, o)) / len(p)


def log_loss(p: Sequence[float], o: Sequence[float]) -> float:
    return -sum(c * math.log(max(a, 1e-12)) + (1 - c) * math.log(max(1 - a, 1e-12))
                for a, c in zip(p, o)) / len(p)
