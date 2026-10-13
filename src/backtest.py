"""Backtest offline sederhana di atas OHLCV (tanpa orderbook real).

Asumsi jujur (ditulis agar tidak menipu diri):
- Fill di close candle berikutnya + slippage & fee dari config.
- Orderbook imbalance=0, funding=0 (konservatif: tanpa edge flow/funding).
- Cocok untuk validasi logika regime/policy/risk, BUKAN janji profit.

Jalan: python scripts/run_backtest.py --exchange binance --symbol BTC/USDT --timeframe 1h --limit 1000
Butuh internet sekali untuk unduh OHLCV (via ccxt).
"""
from __future__ import annotations
import argparse
from .config_loader import load_config
from .exchanges import make_exchange, fetch_ohlcv
from .state_engine import build_snapshot
from .regime import decide
from .policy import gate
from .risk import check_before_order
from .sizing import position_notional


def run_backtest(ex_name: str, symbol: str, timeframe: str, limit: int, cfg_path: str):
    cfg = load_config(cfg_path)
    ex = make_exchange(ex_name)
    ohlcv = fetch_ohlcv(ex, symbol, timeframe, limit)
    print(f"candles: {len(ohlcv)} {ex_name} {symbol} {timeframe}")
    equity = float(cfg["starting_equity_usdt"])
    peak = equity
    day_start = equity
    pos_qty = 0.0
    pos_entry = 0.0
    trades, wins, pnl_sum = 0, 0, 0.0
    fee_bps = float(cfg["sizing"]["taker_fee_bps"])
    slip_bps = float(cfg["sizing"]["slippage_bps"])

    fake_ob = {"bids": [[1, 1]], "asks": [[1, 1]]}
    for i in range(60, len(ohlcv) - 1):
        window = ohlcv[:i + 1]
        close = window[-1][4]
        # orderbook sintetis netral
        fake_ob = {"bids": [[close, 1]], "asks": [[close * 1.0001, 1]]}
        pos_not = pos_qty * close
        snap = build_snapshot(symbol=symbol, exchange=ex_name, ohlcv=window, orderbook=fake_ob,
                              funding=0.0, equity=equity, peak_equity=peak,
                              position_notional=pos_not)
        dec = decide(snap, window, cfg)
        g = gate(dec, cfg)
        nxt = ohlcv[i + 1][4]
        # update equity mark-to-market
        equity += pos_qty * (nxt - close)
        peak = max(peak, equity)
        if g.action == "FIRE" and abs(pos_qty) < 1e-12:
            notion = position_notional(equity=equity, confidence=dec.confidence,
                                       setup_quality=dec.setup_quality, cfg=cfg)
            tot_after = abs(pos_not) + notion
            v = check_before_order(cfg=cfg, equity=equity, peak_equity=peak,
                                   day_start_equity=day_start,
                                   symbol_notional_after=tot_after,
                                   total_exposure_after=tot_after)
            if v.allowed and notion > 0:
                px = nxt * (1 + slip_bps / 1e4 if dec.direction == "long" else 1 - slip_bps / 1e4)
                fee = notion * fee_bps / 1e4
                equity -= fee
                qty = notion / px
                pos_qty = qty if dec.direction == "long" else -qty
                pos_entry = px
        elif abs(pos_qty) > 1e-12:
            # exit sederhana: TP/SL 1.5R berbasis ATR atau sinyal berbalik
            entry = pos_entry
            pnl_pct = (nxt - entry) / entry * (1 if pos_qty > 0 else -1)
            atr_pct = snap.atr_pct / 100.0 if snap.atr_pct else 0.01
            if pnl_pct >= 1.5 * atr_pct or pnl_pct <= -1.0 * atr_pct or (dec.direction == "long" and pos_qty < 0) or (dec.direction == "short" and pos_qty > 0):
                equity -= abs(pos_qty) * nxt * fee_bps / 1e4
                pnl_sum += pnl_pct * abs(pos_qty) * entry
                trades += 1
                wins += 1 if pnl_pct > 0 else 0
                pos_qty = 0.0
    # tutup sisa
    if abs(pos_qty) > 1e-12:
        last = ohlcv[-1][4]
        equity -= abs(pos_qty) * last * fee_bps / 1e4
        trades += 1
    dd = (peak - equity) / peak * 100 if peak else 0
    print(f"Hasil (ESTIMASI, bukan janji): equity={equity:.2f} peak={peak:.2f} maxDD~{dd:.2f}% trades={trades} winrate={wins/max(1,trades):.2f}")
    print("Catatan: backtest tanpa orderbook/funding real -> anggap UPPER BOUND optimis dari eksekusi.")
    return equity


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--config", default="config/config.yaml")
    a = ap.parse_args()
    run_backtest(a.exchange, a.symbol, a.timeframe, a.limit, a.config)
