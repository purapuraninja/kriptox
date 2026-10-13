"""Entrypoint backtest."""
import sys
sys.path.insert(0, ".")
from src.backtest import run_backtest
import argparse

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--config", default="config/config.yaml")
    a = ap.parse_args()
    run_backtest(a.exchange, a.symbol, a.timeframe, a.limit, a.config)
