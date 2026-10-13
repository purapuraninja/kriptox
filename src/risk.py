"""Risk layer deterministik — TIDAK BISA di-override model/policy.

Cek SEBELUM setiap order (check_before_order):
  1. kill switch file ada -> HALT
  2. drawdown dari peak >= max_drawdown_pct -> HALT (tutup semua, berhenti total)
  3. daily loss hari UTC >= max_daily_loss_pct -> STOP hari ini
  4. notional posisi symbol > max_position_pct*equity -> REJECT
  5. total exposure > max_total_exposure_pct*equity -> REJECT
  6. cooldown setelah stop -> REJECT sementara

Semua angka dari config.risk. Fungsi murni kecuali baca file kill-switch + waktu.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class RiskVerdict:
    allowed: bool
    halt_all: bool
    reason: str


def _day_utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_before_order(
    *,
    cfg: dict,
    equity: float,
    peak_equity: float,
    day_start_equity: float,
    day: str | None = None,
    symbol_notional_after: float,
    total_exposure_after: float,
    last_stop_ts: float = 0.0,
    now_ts: float | None = None,
) -> RiskVerdict:
    import time
    r = cfg["risk"]
    now_ts = now_ts if now_ts is not None else time.time()
    day = day or _day_utc_now()

    # 1. kill switch manual
    ks = Path(str(r.get("kill_switch_file", "state/kill_switch.armed")))
    if ks.exists():
        return RiskVerdict(False, True, f"KILL SWITCH armed ({ks}) -> HALT all")

    # 2. max drawdown
    dd = ((peak_equity - equity) / peak_equity * 100.0) if peak_equity > 0 else 0.0
    if dd >= float(r["max_drawdown_pct"]):
        return RiskVerdict(False, True, f"max_drawdown {dd:.2f}% >= {r['max_drawdown_pct']}% -> HALT, flatten")

    # 3. max daily loss
    dl = ((day_start_equity - equity) / day_start_equity * 100.0) if day_start_equity > 0 else 0.0
    if dl >= float(r["max_daily_loss_pct"]):
        return RiskVerdict(False, False, f"max_daily_loss {dl:.2f}% >= {r['max_daily_loss_pct']}% -> STOP today {day}")

    # 4/5. exposure caps
    if symbol_notional_after > float(r["max_position_pct"]) * equity:
        return RiskVerdict(False, False, f"symbol notional {symbol_notional_after:.2f} > {r['max_position_pct']}*equity")
    if total_exposure_after > float(r["max_total_exposure_pct"]) * equity:
        return RiskVerdict(False, False, f"total exposure {total_exposure_after:.2f} > {r['max_total_exposure_pct']}*equity")

    # 6. cooldown
    cd = float(r.get("cooldown_after_stop_seconds", 3600))
    if last_stop_ts > 0 and (now_ts - last_stop_ts) < cd and dl > 0:
        return RiskVerdict(False, False, f"cooldown {(now_ts - last_stop_ts):.0f}s < {cd:.0f}s")

    if equity <= 0:
        return RiskVerdict(False, True, "equity<=0 -> HALT")
    return RiskVerdict(True, False, "ok")
