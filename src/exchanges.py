"""Exchange adapters via ccxt (spot publik, polling — tanpa WebSocket).

Mendukung: bybit, okx, bitget, gate, binance.
Paper mode hanya memakai endpoint PUBLIK (OHLCV, orderbook, funding),
jadi bisa jalan tanpa API key. Private hanya dipakai jika key tersedia.

Rate-limit: ccxt enableRateLimit=True + poll_seconds dari config.
"""
from __future__ import annotations
import ccxt
from typing import Any

SUPPORTED = ("bybit", "okx", "bitget", "gate", "binance")


def make_exchange(name: str, *, testnet: bool = False) -> Any:
    name = name.lower()
    if name not in SUPPORTED:
        raise ValueError(f"exchange {name} tidak didukung: {SUPPORTED}")
    cls = getattr(ccxt, name)
    ex = cls({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    # testnet hanya bybit/binance yang umum; selain itu abaikan aman
    try:
        if testnet and hasattr(ex, "set_sandbox_mode"):
            ex.set_sandbox_mode(True)
    except Exception:
        pass
    return ex


def fetch_ohlcv(ex: Any, symbol: str, timeframe: str, limit: int = 200) -> list:
    return ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)


def fetch_orderbook(ex: Any, symbol: str, limit: int = 20) -> dict:
    return ex.fetch_order_book(symbol, limit=limit)


def fetch_funding(ex: Any, symbol: str) -> float:
    """Funding rate terakhir (swap). 0.0 jika spot / tidak tersedia. Tidak pernah raise."""
    try:
        if hasattr(ex, "fetch_funding_rate"):
            # butuh pasar swap; coba konversi simbol spot->swap
            swap = symbol.replace("/USDT", "/USDT:USDT")
            try:
                r = ex.fetch_funding_rate(swap)
            except Exception:
                r = ex.fetch_funding_rate(symbol)
            return float(r.get("fundingRate") or 0.0)
    except Exception:
        pass
    return 0.0


def load_markets_safe(ex: Any) -> None:
    try:
        ex.load_markets()
    except Exception:
        pass
