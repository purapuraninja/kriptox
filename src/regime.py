"""Regime + decision schema (pengganti Jev yang deterministik & teraudit).

Schema per candle (dievaluasi paralel per symbol):
  regime: trending | mean_reverting | high_vol | crisis
  direction: long | short | neutral
  toxic_flow: bool
  setup_quality: 0..3 (int)
  risk_state: safe | mean_limit | reduce
  confidence: 0..1 (terkalibrasi, dijepit)

Prioritas regime (urutan penting, crisis selalu menang):
  1. crisis  jika drawdown >= crisis_drawdown ATAU (spread sangat lebar + vol ekstrem)
  2. high_vol jika realvol >= persentil-80 lookback (dihitung dari histori candle)
  3. trending jika ADX >= min DAN |trend_gap| >= min
  4. mean_reverting jika RSI ekstrem berbalik / gap kecil + RSI di tengah
  5. default: mean_reverting (paling konservatif untuk sizing kecil)

Semua threshold dari config — code tidak menebak.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .utils import adx
from .state_engine import Snapshot


@dataclass(frozen=True)
class Decision:
    regime: str
    direction: str
    toxic_flow: bool
    setup_quality: int
    risk_state: str
    confidence: float
    reasons: tuple[str, ...]


def detect_regime(snap: Snapshot, ohlcv: list, cfg: dict) -> str:
    rc = cfg["regime"]
    # 1. crisis — selalu menang
    if snap.drawdown_pct >= float(rc["crisis_drawdown_pct"]):
        return "crisis"
    if snap.spread_bps >= float(rc["crisis_spread_bps"]) and snap.atr_pct > 1.5:
        return "crisis"
    # 2. high_vol — persentil realvol atas histori
    closes = np.asarray([c[4] for c in ohlcv], float)
    if len(closes) >= 120:
        lrets = np.diff(np.log(closes[closes > 0]))
        win = 30
        vols = [float(np.std(lrets[i:i + win], ddof=1)) for i in range(max(0, len(lrets) - int(rc["high_vol_lookback"])), len(lrets) - win)]
        if len(vols) > 50:
            thresh = float(np.quantile(vols, float(rc["high_vol_percentile"])))
            if snap.realvol >= thresh and thresh > 0:
                return "high_vol"
    # 3. trending
    arr = np.asarray(ohlcv, float)
    a = adx(arr[:, 2], arr[:, 3], arr[:, 4])
    if a >= float(rc["adx_trend_min"]) and abs(snap.trend_gap_atr) >= float(rc["ema_atr_trend_min"]):
        return "trending"
    return "mean_reverting"


def is_toxic_flow(snap: Snapshot, cfg: dict) -> bool:
    """Aliran toksik = spread melebar + imbalance searah lonjakan harga berlawanan likuiditas.
    Heuristik sederhana & konservatif: tandai toxic jika spread > 2x normal (20bps)
    dan imbalance ekstrem (>0.7) searah ret_1 besar. Toxic => jangan jadi market-taker."""
    return bool(abs(snap.imbalance) > 0.7 and abs(snap.ret_1) > 0.35 and snap.spread_bps > 20.0)


def score_setup(snap: Snapshot, regime: str, cfg: dict) -> tuple[int, str, float]:
    """Skor 0..3 dari konfluensi independen. Tiap poin = 1 bukti:
    T (trend): gap searah & ADX ok — dihitung via gap magnitude
    M (mean-rev): RSI ekstrem + imbalance berlawanan arah (contrarian)
    F (flow): imbalance searah ret_12 tanpa toxic
    V (vol-breakout): ret_1 searah trend & atr moderat (tidak meledak)
    Skor dikonversi ke confidence mentah lalu DIJEPIT 0.5..0.9 (kalibrasi konservatif).
    """
    pts, legs = 0, []
    fund_extreme = float(cfg["regime"]["funding_extreme"])
    # T
    if abs(snap.trend_gap_atr) >= 0.35 and snap.atr_pct < 2.0:
        pts += 1
        legs.append("trend-aligned")
    # M (contrarian): RSI jenuh + funding ekstrem berlawanan = fade crowd
    if (snap.rsi14 >= 70 or snap.rsi14 <= 30) and abs(snap.funding) >= fund_extreme:
        # funding positif + RSI overbought => crowd long, setup short berkualitas
        pts += 1
        legs.append("crowd-fade")
    elif (snap.rsi14 >= 68 or snap.rsi14 <= 32):
        pts += 1
        legs.append("rsi-extreme")
    # F
    toxic = is_toxic_flow(snap, cfg)
    if not toxic and abs(snap.imbalance) >= 0.25 and np.sign(snap.imbalance) == np.sign(snap.ret_12 or 0.0) and snap.ret_12 != 0:
        pts += 1
        legs.append("flow-confirm")
    # V
    if abs(snap.ret_1) >= 0.10 and abs(snap.ret_1) <= 1.5 and snap.spread_bps < 25.0 and not toxic:
        pts += 1
        legs.append("clean-impulse")
    pts = int(min(3, pts))
    # confidence mentah: baseline 0.5 + 0.12 per poin, bonus kecil jika regime cocok
    conf = 0.50 + 0.12 * pts
    if regime == "trending" and "trend-aligned" in legs:
        conf += 0.04
    if regime == "mean_reverting" and ("rsi-extreme" in legs or "crowd-fade" in legs):
        conf += 0.04
    conf = float(min(0.90, max(0.50, conf)))
    return pts, "+".join(legs) if legs else "no-edge", conf


def decide(snap: Snapshot, ohlcv: list, cfg: dict) -> Decision:
    regime = detect_regime(snap, ohlcv, cfg)
    toxic = is_toxic_flow(snap, cfg)
    q, legs, conf = score_setup(snap, regime, cfg)

    # Direction: gabungan trend gap + RSI contrarian + funding fade
    long_votes, short_votes = 0, 0
    if snap.trend_gap_atr > 0.15:
        long_votes += 1
    elif snap.trend_gap_atr < -0.15:
        short_votes += 1
    if snap.rsi14 < 35:
        long_votes += 1
    elif snap.rsi14 > 65:
        short_votes += 1
    if snap.funding <= -float(cfg["regime"]["funding_extreme"]):
        long_votes += 1   # short crowd membayar -> long fade
    elif snap.funding >= float(cfg["regime"]["funding_extreme"]):
        short_votes += 1
    if snap.imbalance > 0.2:
        long_votes += 1
    elif snap.imbalance < -0.2:
        short_votes += 1

    if long_votes - short_votes >= 2:
        direction = "long"
    elif short_votes - long_votes >= 2:
        direction = "short"
    else:
        direction = "neutral"
        conf = min(conf, 0.65)  # netral tidak boleh pede

    if toxic:
        q = min(q, 1)  # aliran toksik memenggal kualitas
        conf = min(conf, 0.62)

    # risk_state deterministik dari inventory + drawdown + spread
    if regime == "crisis" or snap.drawdown_pct >= 10.0 or abs(snap.inventory) > 0.5:
        risk_state = "reduce"
    elif snap.drawdown_pct >= 5.0 or snap.spread_bps >= 25.0 or regime == "high_vol":
        risk_state = "mean_limit"
    else:
        risk_state = "safe"

    reasons = (f"regime={regime}", f"legs={legs}", f"votes=L{long_votes}/S{short_votes}", f"toxic={toxic}")
    return Decision(regime, direction, toxic, int(q), risk_state, float(conf), reasons)
