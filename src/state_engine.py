"""State engine deterministik: order book + OHLCV -> satu snapshot kompak.

Kontrak keras:
- Semua field dihitung di CODE, tidak pernah di model.
- Timestamp kausal ketat: snapshot.ts = close_time candle terakhir.
  Tidak ada field yang memakai data sesudah ts (no future leak).
- Snapshot dirancang < 400 token saat diserialisasi (~30 angka).
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any
import numpy as np
from .utils import ema, rsi, atr, realized_vol, log_returns


@dataclass(frozen=True)
class Snapshot:
    symbol: str
    exchange: str
    ts: int                # ms, close time candle terakhir (kausal)
    mid: float
    spread_bps: float
    imbalance: float       # [-1, +1], top-N orderbook
    microprice: float
    depth_bid: float       # notional bid top-N (quote currency)
    depth_ask: float
    last: float
    ema_fast: float
    ema_slow: float
    trend_gap_atr: float   # (ema_fast-ema_slow)/atr
    rsi14: float
    atr: float
    atr_pct: float         # atr/mid*100
    realvol: float         # std log-ret per candle
    ret_1: float
    ret_12: float
    funding: float         # per-interval; 0 jika spot/tidak tersedia
    inventory: float       # posisi notional / equity, [-x, +x]
    drawdown_pct: float    # drawdown equity saat ini
    peak_equity: float
    equity: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_prompt_line(self) -> str:
        """Satu baris kompak untuk model/LLM: ~120 token."""
        d = self.to_dict()
        nums = "mid={mid:.2f} spr={spread_bps:.1f}bp imb={imbalance:+.2f} mp={microprice:.2f} " \
               "emaF={ema_fast:.2f} emaS={ema_slow:.2f} gap={trend_gap_atr:+.2f}atr " \
               "rsi={rsi14:.0f} atrp={atr_pct:.2f}% rv={realvol:.5f} r1={ret_1:+.4f}% r12={ret_12:+.3f}% " \
               "fund={funding:+.5f} inv={inventory:+.2f} dd={drawdown_pct:.2f}%".format(**d)
        return f"{d['symbol']}@{d['exchange']} ts={d['ts']} {nums}"


def build_snapshot(
    *,
    symbol: str,
    exchange: str,
    ohlcv: list[list[float]],   # [[ts, o, h, l, c, v], ...] ascending, terakhir = candle closed
    orderbook: dict,            # {"bids": [[px, qty],...], "asks": [...]}
    funding: float = 0.0,
    equity: float = 0.0,
    peak_equity: float = 0.0,
    position_notional: float = 0.0,
    depth_levels: int = 20,
) -> Snapshot:
    assert len(ohlcv) >= 30, "butuh >=30 candle closed agar indikator stabil"
    arr = np.asarray(ohlcv, dtype=float)
    ts_arr, opens, highs, lows, closes, vols = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4], arr[:, 5]
    ts = int(ts_arr[-1])

    bids = orderbook.get("bids", [])[:depth_levels]
    asks = orderbook.get("asks", [])[:depth_levels]
    best_bid = float(bids[0][0]) if bids else float(closes[-1])
    best_ask = float(asks[0][0]) if asks else float(closes[-1])
    mid = (best_bid + best_ask) / 2.0 if (best_bid > 0 and best_ask > 0) else float(closes[-1])
    spread_bps = ((best_ask - best_bid) / mid * 1e4) if mid > 0 else 0.0

    bid_not = sum(float(px) * float(q) for px, q in bids)
    ask_not = sum(float(px) * float(q) for px, q in asks)
    denom = bid_not + ask_not
    imbalance = (bid_not - ask_not) / denom if denom > 0 else 0.0
    microprice = (
        (best_ask * bid_not + best_bid * ask_not) / denom if denom > 0 else mid
    )

    ef = float(ema(closes, 12)[-1])
    es = float(ema(closes, 48)[-1])
    a = atr(highs, lows, closes, 14)
    gap = (ef - es) / a if a > 0 else 0.0
    r = rsi(closes, 14)
    rets = log_returns(closes[-60:])
    rv = realized_vol(rets)
    r1 = float((closes[-1] / closes[-2] - 1.0) * 100.0) if closes[-2] else 0.0
    look = min(12, len(closes) - 1)
    r12 = float((closes[-1] / closes[-1 - look] - 1.0) * 100.0) if closes[-1 - look] else 0.0

    inv = (position_notional / equity) if equity > 0 else 0.0
    dd = ((peak_equity - equity) / peak_equity * 100.0) if peak_equity > 0 else 0.0

    return Snapshot(
        symbol=symbol, exchange=exchange, ts=ts, mid=mid,
        spread_bps=float(spread_bps), imbalance=float(imbalance),
        microprice=float(microprice), depth_bid=float(bid_not), depth_ask=float(ask_not),
        last=float(closes[-1]), ema_fast=ef, ema_slow=es, trend_gap_atr=float(gap),
        rsi14=float(r), atr=float(a), atr_pct=float(a / mid * 100.0) if mid else 0.0,
        realvol=float(rv), ret_1=float(r1), ret_12=float(r12),
        funding=float(funding or 0.0), inventory=float(inv),
        drawdown_pct=float(max(0.0, dd)), peak_equity=float(peak_equity), equity=float(equity),
    )
