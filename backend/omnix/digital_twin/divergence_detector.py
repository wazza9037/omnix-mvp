"""
Divergence calculator.

Given sim and real state dicts (produced by the twin's state extractor),
compute per-channel error and roll up to a sync_score. Pure functions,
fully unit-testable.
"""

from __future__ import annotations

import math
from typing import Any

from .models import DivergenceMetrics, SyncStatus, TwinThresholds, DEFAULT_THRESHOLDS


def _pos_error(sim: dict, real: dict) -> float:
    sp = sim.get("pos") or [0.0, 0.0, 0.0]
    rp = real.get("pos") or [0.0, 0.0, 0.0]
    return math.sqrt(sum((sp[i] - rp[i]) ** 2 for i in range(3)))


def _vel_error(sim: dict, real: dict) -> float:
    sv = sim.get("vel") or [0.0, 0.0, 0.0]
    rv = real.get("vel") or [0.0, 0.0, 0.0]
    return math.sqrt(sum((sv[i] - rv[i]) ** 2 for i in range(3)))


def _orient_error_deg(sim: dict, real: dict) -> float:
    sy = float(sim.get("yaw_deg", 0.0))
    ry = float(real.get("yaw_deg", 0.0))
    # Wrap to [-180, 180]
    d = (sy - ry + 540) % 360 - 180
    return abs(d)


def _battery_error_pct(sim: dict, real: dict) -> float:
    sb = sim.get("battery_pct")
    rb = real.get("battery_pct")
    if sb is None or rb is None:
        return 0.0
    return abs(float(sb) - float(rb))


def _joint_error_deg(sim: dict, real: dict) -> float:
    sj = sim.get("joints") or {}
    rj = real.get("joints") or {}
    if not sj or not rj:
        return 0.0
    tot = 0.0
    n = 0
    for k, v in sj.items():
        if k in rj:
            tot += (float(v) - float(rj[k])) ** 2
            n += 1
    return math.sqrt(tot / n) if n else 0.0


def _status_from_errors(m: DivergenceMetrics, t: TwinThresholds) -> SyncStatus:
    # If any channel breaches the red cap → DIVERGED
    if (m.position_error_m >= t.red_position_m or
            m.orientation_error_deg >= t.red_orientation_deg or
            m.velocity_error_m_s >= t.red_velocity_m_s or
            m.battery_error_pct >= t.red_battery_pct):
        return SyncStatus.DIVERGED
    if (m.position_error_m >= t.yellow_position_m or
            m.orientation_error_deg >= t.yellow_orientation_deg or
            m.velocity_error_m_s >= t.yellow_velocity_m_s or
            m.battery_error_pct >= t.yellow_battery_pct):
        return SyncStatus.DRIFTING
    return SyncStatus.IN_SYNC


def _score_from_errors(m: DivergenceMetrics, t: TwinThresholds) -> float:
    """Roll up per-channel errors into a single 0..100 score.

    Each channel contributes a sub-score capped at 100 that hits 0 when the
    channel's red threshold is reached. We take the min across channels as
    the overall score — the weakest link dominates.
    """
    def channel(value: float, red: float) -> float:
        return max(0.0, min(100.0, 100.0 * (1.0 - value / max(red, 1e-6))))

    scores = [
        channel(m.position_error_m, t.red_position_m),
        channel(m.orientation_error_deg, t.red_orientation_deg),
        channel(m.velocity_error_m_s, t.red_velocity_m_s),
        channel(m.battery_error_pct, t.red_battery_pct),
    ]
    if m.joint_error_deg > 0:
        scores.append(channel(m.joint_error_deg, t.red_orientation_deg))
    return min(scores)


def compute_divergence(sim: dict, real: dict,
                       thresholds: TwinThresholds = DEFAULT_THRESHOLDS,
                       ) -> DivergenceMetrics:
    """Per-sample divergence between sim and real state dicts."""
    m = DivergenceMetrics(
        position_error_m=_pos_error(sim, real),
        orientation_error_deg=_orient_error_deg(sim, real),
        velocity_error_m_s=_vel_error(sim, real),
        battery_error_pct=_battery_error_pct(sim, real),
        joint_error_deg=_joint_error_deg(sim, real),
    )
    m.sync_score = _score_from_errors(m, thresholds)
    m.status = _status_from_errors(m, thresholds)
    return m


# ── Summary statistics (used by auto-tuner + session reports) ────

def summarize(divergences: list[DivergenceMetrics]) -> dict:
    """Aggregate a series of divergence samples."""
    if not divergences:
        return {"count": 0, "mean_sync_score": None}
    n = len(divergences)
    mean_sync = sum(d.sync_score for d in divergences) / n
    max_pos = max(d.position_error_m for d in divergences)
    max_orient = max(d.orientation_error_deg for d in divergences)
    pct_in_sync = sum(1 for d in divergences if d.status == SyncStatus.IN_SYNC) / n * 100
    return {
        "count": n,
        "mean_sync_score": round(mean_sync, 2),
        "max_position_error_m": round(max_pos, 3),
        "max_orientation_error_deg": round(max_orient, 2),
        "pct_in_sync": round(pct_in_sync, 1),
    }
