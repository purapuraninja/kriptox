"""Unit tests: matematika inti harus benar sebelum uang (walau paper) jalan."""
import numpy as np
from src.utils import kelly_fraction, brier_score, rsi, ema
from src.state_engine import build_snapshot
from src.regime import decide
from src.policy import gate
from src.risk import check_before_order
from src.sizing import position_notional
from src.config_loader import load_config


def ohlcv_trend(n=120, start=60000.0, drift=0.001):
    out, px = [], start
    for i in range(n):
        px *= (1 + drift + np.random.randn() * 0.002)
        o, c = px * 0.999, px
        out.append([i * 60000, o, max(o, c) * 1.001, min(o, c) * 0.999, c, 10.0])
    return out


def test_kelly():
    # p=0.6, b=1 => f*=0.2
    assert abs(kelly_fraction(0.6, 1.0) - 0.2) < 1e-9
    assert kelly_fraction(0.4, 1.0) == 0.0  # no edge => no bet
    assert kelly_fraction(0.9, 0.0) == 0.0


def test_brier():
    assert abs(brier_score(np.array([1.0, 0.0]), np.array([1, 0])) - 0.0) < 1e-9
    assert abs(brier_score(np.array([0.5, 0.5]), np.array([1, 0])) - 0.25) < 1e-9


def test_snapshot_causal():
    ohlcv = ohlcv_trend(60)
    ob = {"bids": [[60000, 1]], "asks": [[60010, 1]]}
    s = build_snapshot(symbol="BTC/USDT", exchange="binance", ohlcv=ohlcv, orderbook=ob,
                       equity=10000, peak_equity=10000, position_notional=0)
    assert s.ts == ohlcv[-1][0]
    assert -1.0 <= s.imbalance <= 1.0
    assert s.mid > 0


def test_gate_blocks_weak():
    cfg = load_config("config/config.yaml")
    ohlcv = ohlcv_trend(150)
    ob = {"bids": [[ohlcv[-1][4], 1]], "asks": [[ohlcv[-1][4] * 1.0001, 1]]}
    s = build_snapshot(symbol="BTC/USDT", exchange="binance", ohlcv=ohlcv, orderbook=ob,
                       equity=10000, peak_equity=10000, position_notional=0)
    d = decide(s, ohlcv, cfg)
    g = gate(d, cfg)
    # gate lemah harus HOLD/ESCALATE, bukan FIRE (kecuali setup sangat kuat)
    assert g.action in ("FIRE", "HOLD", "ESCALATE")
    # risk_state reduce tidak boleh FIRE
    from src.regime import Decision
    d2 = Decision("trending", "long", False, 3, "reduce", 0.85, ("t",))
    assert gate(d2, cfg).action == "HOLD"


def test_risk_halts():
    cfg = load_config("config/config.yaml")
    v = check_before_order(cfg=cfg, equity=8400, peak_equity=10000, day_start_equity=10000,
                           symbol_notional_after=100, total_exposure_after=100)
    assert v.halt_all and not v.allowed  # drawdown 16% >= 15%


def test_sizing_caps():
    cfg = load_config("config/config.yaml")
    n = position_notional(equity=10000, confidence=0.9, setup_quality=3, cfg=cfg)
    assert 0 < n <= 2500.0  # quarter-Kelly cap 25%
    assert position_notional(equity=10000, confidence=0.5, setup_quality=0, cfg=cfg) == 0.0
