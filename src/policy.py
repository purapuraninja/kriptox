"""Policy gate: kapan BOLEH tembak. Model tidak pernah bisa override risk.

Aturan (dari config.policy):
  FIRE hanya jika:
    setup_quality >= min_setup_quality (2)
    confidence   >  min_confidence (0.80)
    risk_state   == safe (jika require_risk_safe)
    direction    != neutral
    regime       != crisis
  ESCALATE (tanpa trade, kirim ke review/BRAIN) jika:
    confidence < escalate_confidence (0.60) ATAU regime == crisis
  Selain itu: HOLD.
"""
from __future__ import annotations
from dataclasses import dataclass
from .regime import Decision


@dataclass(frozen=True)
class GateResult:
    action: str   # FIRE | HOLD | ESCALATE
    reason: str


def gate(decision: Decision, cfg: dict) -> GateResult:
    p = cfg["policy"]
    if decision.regime == "crisis":
        return GateResult("ESCALATE", "regime=crisis -> halt new positions, escalate to BRAIN")
    if decision.confidence < float(p["escalate_confidence"]):
        return GateResult("ESCALATE", f"confidence {decision.confidence:.2f} < {p['escalate_confidence']} -> deep re-read, no trade")
    if decision.direction == "neutral":
        return GateResult("HOLD", "direction=neutral")
    if decision.setup_quality < int(p["min_setup_quality"]):
        return GateResult("HOLD", f"quality {decision.setup_quality} < {p['min_setup_quality']}")
    if decision.confidence <= float(p["min_confidence"]):
        return GateResult("HOLD", f"confidence {decision.confidence:.2f} <= {p['min_confidence']}")
    if bool(p["require_risk_safe"]) and decision.risk_state != "safe":
        return GateResult("HOLD", f"risk_state={decision.risk_state} != safe")
    if decision.toxic_flow:
        return GateResult("HOLD", "toxic_flow=true -> no market-taker")
    return GateResult("FIRE", f"{decision.direction} q={decision.setup_quality} conf={decision.confidence:.2f}")
