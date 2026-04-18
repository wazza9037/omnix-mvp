"""
OMNIX Digital Twin — bridge between simulation and reality.

Public surface:

    from omnix.digital_twin import REGISTRY, TwinMode, SyncStatus

    twin = REGISTRY.create(device, workspace, mode=TwinMode.TWIN)
    twin.on_command("takeoff", {"altitude_m": 5})
    snapshot = twin.snapshot()              # for the frontend

    session = twin.start_session(label="takeoff-hover-land")
    # ... commands flow for a bit ...
    finished = twin.stop_session()
    REGISTRY.add_session(finished)

    from omnix.digital_twin.auto_tuner import auto_tune, apply_to_workspace
    result = auto_tune(finished, device.device_type)
    apply_to_workspace(result, workspace)
"""

from .models import (
    TwinMode, SyncStatus, DivergenceMetrics, TwinSnapshot,
    SessionRecord, SessionFrame, TwinThresholds, DEFAULT_THRESHOLDS,
)
from .divergence_detector import compute_divergence, summarize
from .predictor import Predictor, initial_state, extract_for_divergence
from .twin_manager import DigitalTwin, TwinManager, REGISTRY
from .auto_tuner import auto_tune, apply_to_workspace, TuningResult

__all__ = [
    "TwinMode", "SyncStatus", "DivergenceMetrics", "TwinSnapshot",
    "SessionRecord", "SessionFrame", "TwinThresholds", "DEFAULT_THRESHOLDS",
    "compute_divergence", "summarize",
    "Predictor", "initial_state", "extract_for_divergence",
    "DigitalTwin", "TwinManager", "REGISTRY",
    "auto_tune", "apply_to_workspace", "TuningResult",
]
