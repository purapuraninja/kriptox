"""Cek konektivitas 5 exchange (publik, tanpa key)."""
import sys
sys.path.insert(0, ".")
from src.exchanges import make_exchange, fetch_ohlcv

for name in ("bybit", "okx", "bitget", "gate", "binance"):
    try:
        ex = make_exchange(name)
        data = fetch_ohlcv(ex, "BTC/USDT", timeframe="1h", limit=5)
        print(f"OK   {name}: {len(data)} candles, last={data[-1][4]}")
    except Exception as e:
        print(f"FAIL {name}: {type(e).__name__}: {str(e)[:120]}")
