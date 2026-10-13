"""Dry-run OFFLINE: full loop tanpa internet (data sintetis).

Membuktikan rantai snapshot -> decide -> gate -> sizing -> risk -> fill
jalan benar di mesin ini, walau exchange diblokir jaringan.
Bukan bukti profit — hanya bukti engineering.

Jalan: python scripts/run_dry.py --steps 300
"""
import sys
sys.path.insert(0, ".")
import numpy as np
from src.config_loader import load_config
from src.state_engine import build_snapshot
from src.regime import decide
from src.policy import gate
from src.risk import check_before_order
from src.sizing import position_notional
from src.paper_broker import PaperBroker


def gen_ohlcv(n=400, start=67000.0, seed=7):
    rng = np.random.default_rng(seed)
    out, px = [], start
    ts = 1_700_000_000_000
    # campuran regime: trend + chop + spike (menguji semua cabang)
    for i in range(n):
        drift = 0.0008 if i < n // 3 else (-0.0006 if i < 2 * n // 3 else 0.0002)
        shock = rng.normal(0, 0.004)
        if i == 2 * n // 3:
            shock += 0.03  # spike: harus memicu high_vol/crisis handling
        px *= (1 + drift + shock)
        o, c = px / (1 + drift + shock), px
        h, l = max(o, c) * 1.001, min(o, c) * 0.999
        out.append([ts + i * 60000, o, h, l, c, 10.0])
    return out


def main(steps=300, cfg_path="config/config.yaml"):
    cfg = load_config(cfg_path)
    ohlcv = gen_ohlcv(max(400, steps + 100))
    broker = PaperBroker(equity_start=float(cfg["starting_equity_usdt"]),
                         fee_bps=float(cfg["sizing"]["taker_fee_bps"]),
                         slip_bps=float(cfg["sizing"]["slippage_bps"]),
                         log_dir=cfg["review"]["log_dir"])
    marks, fires, holds, esc = {}, 0, 0, 0
    key = ("dry", "BTC/USDT")
    for i in range(60, 60 + steps):
        window = ohlcv[:i + 1]
        close = window[-1][4]
        ob = {"bids": [[close, 1.5]], "asks": [[close * 1.0002, 1.2]]}
        marks[key] = close
        equity = broker.equity(marks)
        broker.update_peak_day(equity, "dry-day")
        pos_not = broker.positions.get(key, 0.0) * close
        snap = build_snapshot(symbol=key[1], exchange=key[0], ohlcv=window, orderbook=ob,
                              funding=0.0001 if i % 50 == 0 else 0.0,
                              equity=equity, peak_equity=broker.peak, position_notional=pos_not)
        dec = decide(snap, window, cfg)
        g = gate(dec, cfg)
        if g.action == "FIRE":
            notion = position_notional(equity=equity, confidence=dec.confidence,
                                       setup_quality=dec.setup_quality, cfg=cfg)
            if notion > 0:
                v = check_before_order(cfg=cfg, equity=equity, peak_equity=broker.peak,
                                       day_start_equity=broker.day_start,
                                       symbol_notional_after=abs(pos_not) + notion,
                                       total_exposure_after=abs(pos_not) + notion)
                if v.allowed:
                    if dec.direction == "long":
                        broker.market_buy(key, snap.mid, notion, snap.ts, dec.confidence, "dry")
                    else:
                        broker.market_sell(key, snap.mid, notion, snap.ts, dec.confidence, "dry")
                    fires += 1
                else:
                    holds += 1
            else:
                holds += 1
        elif g.action == "ESCALATE":
            esc += 1
        else:
            holds += 1
    eq = broker.equity(marks)
    print(f"DRY-RUN OK: steps={steps} FIRE={fires} HOLD={holds} ESCALATE={esc} "
          f"fills={broker.trades} equity={eq:.2f} peak={broker.peak:.2f}")
    print("Rantai penuh terverifikasi offline. Untuk live: python scripts/run_paper.py (butuh internet).")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--config", default="config/config.yaml")
    a = ap.parse_args()
    main(a.steps, a.config)
