"""Live loop 24/7 paper trading.

Alur per iterasi (per exchange x symbol):
  1. fetch OHLCV + orderbook + funding (publik)
  2. build_snapshot (kausal, <400 token)
  3. decide -> Decision (regime/direction/quality/confidence)
  4. gate -> FIRE/HOLD/ESCALATE
  5. jika FIRE: sizing Kelly + check_before_order (risk) -> paper fill
  6. mark-to-market equity, update peak/day, tulis status + decision log
  7. jika HALT (drawdown/kill-switch): flatten semua, berhenti total.

Jalan:  python scripts/run_paper.py  (berhenti dengan Ctrl+C)
"""
from __future__ import annotations
import asyncio
import csv
import time
from datetime import datetime, timezone
from pathlib import Path

from .config_loader import load_config, ensure_state_dirs
from .exchanges import make_exchange, fetch_ohlcv, fetch_orderbook, fetch_funding, load_markets_safe
from .state_engine import build_snapshot
from .regime import decide
from .policy import gate
from .risk import check_before_order
from .sizing import position_notional
from .paper_broker import PaperBroker


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def poll_once(ex, ex_name: str, symbol: str, cfg: dict, broker: PaperBroker, marks: dict, stats: dict):
    tf = cfg.get("timeframe", "1m")
    depth = int(cfg.get("orderbook_depth", 20))
    try:
        ohlcv = await asyncio.to_thread(fetch_ohlcv, ex, symbol, tf, 200)
        ob = await asyncio.to_thread(fetch_orderbook, ex, symbol, depth)
        funding = await asyncio.to_thread(fetch_funding, ex, symbol)
    except Exception as e:
        stats["errors"] += 1
        log_decision(cfg, {"ts": int(time.time() * 1000), "exchange": ex_name, "symbol": symbol,
                            "action": "ERROR", "note": str(e)[:200]})
        return

    if not ohlcv or len(ohlcv) < 30:
        return
    key = (ex_name, symbol)
    marks[key] = float(ohlcv[-1][4])
    equity = broker.equity(marks)
    broker.update_peak_day(equity, _utc_day())
    pos_not = broker.positions.get(key, 0.0) * marks[key]

    snap = build_snapshot(symbol=symbol, exchange=ex_name, ohlcv=ohlcv, orderbook=ob,
                          funding=funding, equity=equity, peak_equity=broker.peak,
                          position_notional=pos_not, depth_levels=depth)
    dec = decide(snap, ohlcv, cfg)
    g = gate(dec, cfg)

    # Sizing hanya jika FIRE
    fill_note = ""
    if g.action == "FIRE":
        notion = position_notional(equity=equity, confidence=dec.confidence,
                                   setup_quality=dec.setup_quality, cfg=cfg)
        # arah: long=buy, short=sell (paper)
        if notion > 0:
            tot_after = sum(abs(q) * marks.get(k, 0.0) for k, q in broker.positions.items()) + notion
            verdict = check_before_order(cfg=cfg, equity=equity, peak_equity=broker.peak,
                                         day_start_equity=broker.day_start,
                                         symbol_notional_after=abs(pos_not) + notion,
                                         total_exposure_after=tot_after)
            if verdict.allowed:
                if dec.direction == "long":
                    fill = broker.market_buy(key, snap.mid, notion, snap.ts, dec.confidence, "|".join(dec.reasons))
                else:
                    fill = broker.market_sell(key, snap.mid, notion, snap.ts, dec.confidence, "|".join(dec.reasons))
                stats["trades"] += 1
                fill_note = f"filled {fill['side']} {fill['qty']:.6f}@{fill['price']:.2f}"
            elif verdict.halt_all:
                await halt_and_flatten(cfg, broker, marks, verdict.reason)
                stats["halted"] = True
                return
            else:
                g = type(g)(action="HOLD", reason=f"RISK-REJECT: {verdict.reason}")
        else:
            g = type(g)(action="HOLD", reason="sizing=0 (edge<biaya atau Kelly<=0)")

    # Crisis: jangan buka posisi baru; catat escalate
    if dec.regime == "crisis":
        stats["crisis"] += 1

    stats["snapshots"] += 1
    log_decision(cfg, {"ts": snap.ts, "exchange": ex_name, "symbol": symbol,
                       "action": g.action, "note": f"{g.reason} | {snap.to_prompt_line()} | {fill_note}"})
    # status ringkas ke console
    eq2 = broker.equity(marks)
    print(f"[{_utc_day()} {datetime.now(timezone.utc).strftime('%H:%M:%S')}] {ex_name}:{symbol} "
          f"{dec.regime}/{dec.direction} q={dec.setup_quality} conf={dec.confidence:.2f} -> {g.action} | eq={eq2:.2f} | {fill_note or g.reason[:90]}",
          flush=True)


async def halt_and_flatten(cfg, broker: PaperBroker, marks: dict, reason: str):
    print(f"HALT: {reason} — flatten semua posisi paper.", flush=True)
    for key, qty in list(broker.positions.items()):
        if abs(qty) > 1e-12:
            broker.flatten(key, marks.get(key, 0.0), int(time.time() * 1000))
    p = Path(cfg["risk"]["kill_switch_file"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"halted at {time.asctime()} : {reason}\n", encoding="utf-8")


def log_decision(cfg: dict, row: dict):
    d = Path(cfg["review"]["log_dir"])
    d.mkdir(parents=True, exist_ok=True)
    p = d / "decisions.csv"
    new = not p.exists()
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


async def run_forever(cfg_path: str = "config/config.yaml"):
    cfg = load_config(cfg_path)
    ensure_state_dirs(cfg)
    assert cfg.get("mode", "paper") == "paper", "mode harus paper untuk loop ini (live dikunci)"
    ex_names = cfg["exchanges"]
    symbols = cfg["symbols"]
    poll = int(cfg.get("poll_seconds", 15))
    broker = PaperBroker(equity_start=float(cfg.get("starting_equity_usdt", 10000.0)),
                         fee_bps=float(cfg["sizing"]["taker_fee_bps"]),
                         slip_bps=float(cfg["sizing"]["slippage_bps"]),
                         log_dir=cfg["review"]["log_dir"])
    exes = {}
    for n in ex_names:
        try:
            ex = make_exchange(n, testnet=bool(cfg.get("data", {}).get("use_testnet", False)))
            await asyncio.to_thread(load_markets_safe, ex)
            exes[n] = ex
            print(f"connected: {n}", flush=True)
        except Exception as e:
            print(f"SKIP {n}: {e}", flush=True)

    if not exes:
        raise SystemExit("Tidak ada exchange yang bisa dipakai. Cek internet / nama exchange.")
    marks: dict = {}
    stats = {"snapshots": 0, "trades": 0, "errors": 0, "crisis": 0, "halted": False}
    print(f"KRIPTOX paper live mulai: {list(exes)} x {symbols} | poll={poll}s | equity={broker.equity_start}", flush=True)
    try:
        while True:
            for ex_name, ex in exes.items():
                for sym in symbols:
                    await poll_once(ex, ex_name, sym, cfg, broker, marks, stats)
                    if stats.get("halted"):
                        print("Loop berhenti (HALT). Hapus kill-switch file setelah review untuk restart.", flush=True)
                        return
                    await asyncio.sleep(1)  # jeda antar symbol, hemat rate-limit
            print(f"-- heartbeat snapshots={stats['snapshots']} trades={stats['trades']} errors={stats['errors']} eq={broker.equity(marks):.2f} --", flush=True)
            await asyncio.sleep(poll)
    except KeyboardInterrupt:
        print(f"\nBerhenti. snapshots={stats} equity={broker.equity(marks):.2f}", flush=True)
