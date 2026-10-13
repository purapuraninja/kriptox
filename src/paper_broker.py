"""Paper broker: simulasi fill dengan fee + slippage, tanpa uang sungguhan.

- Posisi per (exchange, symbol): qty (positif=long spot, negatif=short CFD-spot-sintetis).
  Untuk paper spot murni, short disimulasikan sebagai posisi sintetis dengan PnL
  = -qty * d price (tanpa borrow fee — labeled ESTIMATE).
- Equity = cash + sum(qty*price). Mark-to-market tiap snapshot.
- Fill: market-taker di mid +/- slippage_bps, dikurangi taker_fee_bps.
- Semua fill dicatat ke CSV untuk review malam (Brier + PnL attribution).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import csv
import time


@dataclass
class PaperBroker:
    equity_start: float
    fee_bps: float = 5.0
    slip_bps: float = 3.0
    log_dir: str = "state/logs"
    cash: float = field(init=False)
    positions: dict = field(default_factory=dict)  # (ex,sym) -> qty
    peak: float = field(init=False)
    day: str = ""
    day_start: float = field(init=False)
    trades: int = 0

    def __post_init__(self):
        self.cash = float(self.equity_start)
        self.peak = float(self.equity_start)
        self.day_start = float(self.equity_start)
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)

    def price(self, positions_value: dict) -> float:
        return self.cash + sum(positions_value.values())

    def equity(self, marks: dict) -> float:
        v = self.cash
        for k, qty in self.positions.items():
            v += qty * marks.get(k, 0.0)
        return v

    def update_peak_day(self, equity: float, day: str):
        self.peak = max(self.peak, equity)
        if self.day != day:
            self.day = day
            self.day_start = equity

    def market_buy(self, key: tuple, price: float, notional: float, ts: int, conf: float, note: str = "") -> dict:
        px = price * (1 + self.slip_bps / 1e4)
        fee = notional * self.fee_bps / 1e4
        qty = notional / px if px > 0 else 0.0
        self.cash -= (notional + fee)
        self.positions[key] = self.positions.get(key, 0.0) + qty
        return self._log(key, "BUY", px, qty, fee, ts, conf, note)

    def market_sell(self, key: tuple, price: float, notional: float, ts: int, conf: float, note: str = "") -> dict:
        px = price * (1 - self.slip_bps / 1e4)
        fee = notional * self.fee_bps / 1e4
        qty = notional / px if px > 0 else 0.0
        self.cash += (notional - fee)
        self.positions[key] = self.positions.get(key, 0.0) - qty
        return self._log(key, "SELL", px, -qty, fee, ts, conf, note)

    def flatten(self, key: tuple, price: float, ts: int) -> dict | None:
        q = self.positions.get(key, 0.0)
        if abs(q) < 1e-12:
            return None
        if q > 0:
            return self.market_sell(key, price, abs(q) * price, ts, 0.0, "flatten")
        # short sintetis: buy to cover dari cash
        px = price * (1 + self.slip_bps / 1e4)
        notion = abs(q) * px
        fee = notion * self.fee_bps / 1e4
        self.cash -= (notion + fee)
        self.positions[key] = 0.0
        return self._log(key, "COVER", px, abs(q), fee, ts, 0.0, "flatten")

    def _log(self, key, side, px, qty, fee, ts, conf, note):
        self.trades += 1
        row = {"ts": ts, "exchange": key[0], "symbol": key[1], "side": side,
               "price": px, "qty": qty, "fee": fee, "conf": conf, "note": note,
               "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts / 1000))}
        p = Path(self.log_dir) / "fills.csv"
        new = not p.exists()
        with open(p, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(row.keys()))
            if new:
                w.writeheader()
            w.writerow(row)
        return row
