"""Sizing fractional Kelly, capped quarter-Kelly + biaya.

Matematika (didokumentasikan agar pemula paham):
  Diberi probabilitas menang TERKALIBRASI p dan odds b = avg_win/avg_loss:
      f* = (p*(b+1) - 1) / b            (Kelly klasik)
  Kami pakai half-Kelly: f = f* * kelly_fraction (0.5),
  lalu CAP: f_capped = min(f, max_kelly_cap=0.25).
  Skala kualitas: f_final = f_capped * (setup_quality / 3).

  Filter biaya: taksiran edge per trade (dari confidence & ATR) harus >
  taker_fee + slippage + min_edge_bps, kalau tidak size = 0.

  p DI SINI = confidence dari decide(), TAPI dijepit maks 0.90 dan
  direkalibrasi malam hari via review.py (jika Brier buruk -> p dikecilkan).
  b default 1.2 (reward:risk 1.2:1) sampai ada histori fill 20+ trade nyata.

Return: notional USDT yang boleh dibeli (0 = jangan trade).
"""
from __future__ import annotations


def position_notional(
    *,
    equity: float,
    confidence: float,
    setup_quality: int,
    avg_win: float = 1.2,
    avg_loss: float = 1.0,
    cfg: dict,
) -> float:
    s = cfg["sizing"]
    if equity <= 0 or setup_quality < 2:
        return 0.0
    p = float(min(0.90, max(0.51, confidence)))
    b = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    if b <= 0:
        return 0.0
    f_star = (p * (b + 1.0) - 1.0) / b
    if f_star <= 0:
        return 0.0
    f = f_star * float(s.get("kelly_fraction", 0.5))
    f = min(f, float(s.get("max_kelly_cap", 0.25)))
    f *= setup_quality / 3.0
    notion = equity * f
    # cap posisi & exposure
    notion = min(notion, float(s.get("max_position_pct", 0.20)) * equity)
    # filter biaya: butuh edge minimal; aproksimasi edge = (2p-1) * ATRproxy.
    # Tanpa ATR di sini, gunakan asumsi konservatif: butuh p >= 0.80 sudah di-gate;
    # tolak jika fee+slippage+min_edge > edge kasar 40bps * quality.
    cost_bps = float(s.get("taker_fee_bps", 5.0)) + float(s.get("slippage_bps", 3.0))
    edge_bps = 40.0 * (setup_quality / 3.0) * (2 * p - 1) * 2  # ~ hingga 48bps di p=0.9,q=3
    if edge_bps < cost_bps + float(s.get("min_edge_bps", 5.0)):
        return 0.0
    return float(max(0.0, notion))
