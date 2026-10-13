"""Overnight review: baca fills + decisions, ukur kalibrasi (Brier), tulis laporan.

Karena paper-trade 1 menit tidak punya outcome instan yang bersih, outcome
didefinisikan JUJUR sebagai: markout +k candle ke depan (default 60 menit pada 1m,
atau 12 candle untuk timeframe lain) — apakah arah benar dan menutup biaya.

- Brier score = mean((conf - y)^2), y=1 jika trade profit setelah biaya.
- Jika Brier > brier_warn (0.25) atau winrate tersirat << confidence rata-rata,
  sarankan naikkan min_confidence / turunkan size (tulis ke review report,
  TIDAK otomatis mengubah config — operator yang approve).

Jalan: python scripts/run_review.py [--markout 60]
"""
from __future__ import annotations
import csv
from pathlib import Path
import numpy as np
from .config_loader import load_config
from .utils import brier_score


def load_fills(log_dir: str) -> list[dict]:
    p = Path(log_dir) / "fills.csv"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def summarize(cfg_path: str = "config/config.yaml") -> dict:
    cfg = load_config(cfg_path)
    log_dir = cfg["review"]["log_dir"]
    fills = load_fills(log_dir)
    dpath = Path(log_dir) / "decisions.csv"
    n_dec = 0
    if dpath.exists():
        with open(dpath, encoding="utf-8") as f:
            n_dec = max(0, sum(1 for _ in f) - 1)
    if not fills:
        return {"fills": 0, "decisions": n_dec, "msg": "belum ada fill — review menjamin loop jalan, bukan profit"}
    confs = np.array([float(r.get("conf", 0) or 0) for r in fills if float(r.get("conf", 0) or 0) > 0])
    # outcome proxy tanpa harga markout: pakai note flatten? Untuk paper v1, tandai outcome=unknown
    # dan ukur discriminasi via distribusi confidence + biaya. Brier penuh butuh markout OHLCV (TODO jujur).
    out = {
        "fills": len(fills),
        "decisions": n_dec,
        "avg_conf": float(confs.mean()) if len(confs) else 0.0,
        "n_confident": int((confs > 0.8).sum()) if len(confs) else 0,
        "buys": sum(1 for r in fills if r["side"] == "BUY"),
        "sells": sum(1 for r in fills if r["side"] == "SELL"),
    }
    # Brier placeholder jujur: tidak diklaim tanpa outcome markout
    out["brier"] = None
    out["recommendation"] = (
        "kumpulkan >=20 fill lalu jalankan markout review (lihat TODO di run_review.py). "
        "Jika avg_conf >> winrate markout, naikkan min_confidence +0.02 dan turunkan kelly_fraction."
        if len(fills) < int(cfg["review"].get("min_trades_for_recalib", 20))
        else "cukup sampel: hitung markout PnL per fill dari OHLCV, lalu hitung Brier & kalibrasi per bucket."
    )
    return out


def write_report(cfg_path: str = "config/config.yaml") -> Path:
    import datetime
    cfg = load_config(cfg_path)
    s = summarize(cfg_path)
    p = Path(cfg["review"]["log_dir"]) / f"review-{datetime.datetime.now(datetime.timezone.utc):%Y%m%d}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Kriptox Nightly Review (UTC)", "", f"- fills: {s.get('fills')}", f"- decisions: {s.get('decisions')}"]
    for k in ("avg_conf", "n_confident", "buys", "sells", "brier"):
        if k in s:
            lines.append(f"- {k}: {s[k]}")
    lines += ["", "## Rekomendasi", str(s.get("recommendation", "-")), "",
              "## WHAT COULD I BE WRONG ABOUT?",
              "- Confidence belum terkalibrasi (Brier belum dihitung tanpa markout).",
              "- Backtest tanpa orderbook = optimis. Live spread/slippage bisa membunuh edge kecil.",
              "- Short spot paper = sintetis; live spot tidak bisa short tanpa margin.",
              "- Funding/OI hanya tersedia di derivatif; spot paper mengabaikannya (=0)."]
    p.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nreport: {p}")
    return p


if __name__ == "__main__":
    write_report()
