"""Entrypoint paper live 24/7."""
import asyncio, sys
sys.path.insert(0, ".")
from src.live_loop import run_forever

if __name__ == "__main__":
    cfg = sys.argv[1] if len(sys.argv) > 1 else "config/config.yaml"
    asyncio.run(run_forever(cfg))
