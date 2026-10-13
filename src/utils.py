"""Shared math + utils. Semua fungsi murni, tanpa I/O, tanpa leak masa depan."""
from __future__ import annotations
import math
import numpy as np


def ema(series: np.ndarray, span: int) -> np.ndarray:
    series = np.asarray(series, dtype=float)
    if len(series) == 0:
        return series
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(series)
    out[0] = series[0]
    for i in range(1, len(series)):
        out[i] = alpha * series[i] + (1 - alpha) * out[i - 1]
    return out


def rsi(closes: np.ndarray, period: int = 14) -> float:
    closes = np.asarray(closes, dtype=float)
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains[-period:].mean()
    avg_loss = losses[-period:].mean()
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    highs, lows, closes = map(lambda x: np.asarray(x, dtype=float), (highs, lows, closes))
    if len(closes) < 2:
        return 0.0
    n = min(period, len(closes) - 1)
    trs = []
    for i in range(len(closes) - n, len(closes)):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return float(np.mean(trs)) if trs else 0.0


def adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> float:
    """ADX Wilder sederhana. 0..100. >22-25 = trending."""
    highs, lows = np.asarray(highs, float), np.asarray(lows, float)
    n = len(closes)
    if n < 2 * period + 1:
        return 0.0
    plus_dm, minus_dm, tr = [], [], []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm.append(up if up > dn and up > 0 else 0.0)
        minus_dm.append(dn if dn > up and dn > 0 else 0.0)
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr_s = sum(tr[-period:]) / period
    if atr_s == 0:
        return 0.0
    plus_di = 100.0 * (sum(plus_dm[-period:]) / period) / atr_s
    minus_di = 100.0 * (sum(minus_dm[-period:]) / period) / atr_s
    denom = plus_di + minus_di
    if denom == 0:
        return 0.0
    dx = 100.0 * abs(plus_di - minus_di) / denom
    # Rata-rata DX sederhana atas 2 window untuk stabilitas
    return float(min(100.0, max(0.0, dx)))


def log_returns(closes: np.ndarray) -> np.ndarray:
    c = np.asarray(closes, dtype=float)
    c = c[c > 0]
    if len(c) < 2:
        return np.array([])
    return np.diff(np.log(c))


def realized_vol(rets: np.ndarray, annualize_periods: int | None = None) -> float:
    """Std dev log-returns per candle. annualize opsional."""
    rets = np.asarray(rets, dtype=float)
    if len(rets) < 2:
        return 0.0
    v = float(np.std(rets, ddof=1))
    if annualize_periods:
        v *= math.sqrt(annualize_periods)
    return v


def brier_score(probs: np.ndarray, outcomes: np.ndarray) -> float:
    """Brier = mean((p - y)^2). 0 sempurna, 0.25 = baseline tebak 0.5 terus."""
    p = np.asarray(probs, float)
    y = np.asarray(outcomes, float)
    if len(p) == 0:
        return float("nan")
    return float(np.mean((p - y) ** 2))


def kelly_fraction(p: float, b: float) -> float:
    """Kelly klasik untuk win prob p, payoff odds b = avg_win/avg_loss.
    f* = (p*(b+1) - 1) / b. Negatif => no bet (return 0).
    p harus probabilitas TERKALIBRASI, bukan confidence mentah.
    """
    if b <= 0 or not (0 < p < 1):
        return 0.0
    f = (p * (b + 1.0) - 1.0) / b
    return float(max(0.0, f))
