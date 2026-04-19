"""
Per-device AI knowledge storage.

Accumulates analysis results, learned physics parameters, performance history,
inferred capabilities, and AI-generated descriptions for each robot device.

Versioned and timestamped to track how knowledge evolves over multiple analyses.
"""

from __future__ import annotations

import time
import json
import threading
from dataclasses import dataclass, asdict, field
from typing import Any

from omnix.logging_setup import get_logger
from omnix.errors import NotFoundError, ValidationError


logger = get_logger(__name__)


@dataclass
class Analysis:
    """Single analysis result from an AI model."""
    model: str
    timestamp: float
    analysis_type: str  # "physics", "visual", "capability", "description", etc.
    input_summary: str
    output: dict[str, Any]
    confidence: float = 0.5


@dataclass
class PerformanceRecord:
    """Historical performance data from simulation iterations."""
    iteration_id: str
    timestamp: float
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class MeshSuggestion:
    """Suggestion for 3D model improvement."""
    suggestion: str
    confidence: float
    model: str
    timestamp: float


@dataclass
class KnowledgeRecord:
    """Complete AI knowledge for a single device."""
    device_id: str
    analyses: list[Analysis] = field(default_factory=list)
    learned_params: dict[str, float] = field(default_factory=dict)
    performance_history: list[PerformanceRecord] = field(default_factory=list)
    capabilities_inferred: list[str] = field(default_factory=list)
    description_ai: str = ""
    mesh_suggestions: list[MeshSuggestion] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "device_id": self.device_id,
            "analyses": [asdict(a) for a in self.analyses],
            "learned_params": self.learned_params,
            "performance_history": [asdict(p) for p in self.performance_history],
            "capabilities_inferred": self.capabilities_inferred,
            "description_ai": self.description_ai,
            "mesh_suggestions": [asdict(m) for m in self.mesh_suggestions],
            "last_updated": self.last_updated,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> KnowledgeRecord:
        """Reconstruct from dict."""
        analyses = [
            Analysis(
                model=a["model"],
                timestamp=a["timestamp"],
                analysis_type=a["analysis_type"],
                input_summary=a["input_summary"],
                output=a["output"],
                confidence=a.get("confidence", 0.5),
            )
            for a in data.get("analyses", [])
        ]
        perf = [
            PerformanceRecord(
                iteration_id=p["iteration_id"],
                timestamp=p["timestamp"],
                metrics=p.get("metrics", {}),
            )
            for p in data.get("performance_history", [])
        ]
        suggestions = [
            MeshSuggestion(
                suggestion=m["suggestion"],
                confidence=m["confidence"],
                model=m["model"],
                timestamp=m["timestamp"],
            )
            for m in data.get("mesh_suggestions", [])
        ]

        return KnowledgeRecord(
            device_id=data["device_id"],
            analyses=analyses,
            learned_params=data.get("learned_params", {}),
            performance_history=perf,
            capabilities_inferred=data.get("capabilities_inferred", []),
            description_ai=data.get("description_ai", ""),
            mesh_suggestions=suggestions,
            last_updated=data.get("last_updated", time.time()),
        )


class RobotKnowledgeBase:
    """
    Stores and manages AI-derived knowledge for each robot device.

    Provides thread-safe access to accumulated analyses, learned parameters,
    performance history, and AI-generated content. Supports import/export for
    persistence.
    """

    def __init__(self):
        """Initialize the knowledge base (in-memory store)."""
        self._knowledge: dict[str, KnowledgeRecord] = {}
        self._lock = threading.Lock()

    def add_analysis(self, device_id: str, analysis: Analysis | dict) -> None:
        """
        Add a single analysis result to a device's record.

        Args:
            device_id: Device identifier
            analysis: Analysis result to add (Analysis object or dict)
        """
        # Accept plain dicts for convenience (e.g. from API endpoints)
        if isinstance(analysis, dict):
            analysis = Analysis(
                model=analysis.get("model", "unknown"),
                timestamp=analysis.get("timestamp", time.time()),
                analysis_type=analysis.get("type", analysis.get("analysis_type", "unknown")),
                input_summary=analysis.get("input_summary", ""),
                output=analysis.get("output", {}),
                confidence=analysis.get("confidence", 0.5),
            )

        with self._lock:
            if device_id not in self._knowledge:
                self._knowledge[device_id] = KnowledgeRecord(device_id=device_id)

            record = self._knowledge[device_id]
            record.analyses.append(analysis)
            record.last_updated = time.time()

            logger.debug(f"Added {analysis.analysis_type} analysis for {device_id}")

    def get_knowledge(self, device_id: str) -> KnowledgeRecord | None:
        """
        Retrieve all knowledge for a device.

        Args:
            device_id: Device identifier

        Returns:
            KnowledgeRecord if exists, None otherwise
        """
        with self._lock:
            return self._knowledge.get(device_id)

    def export_json(self, device_id: str) -> str:
        """
        Export device knowledge as JSON string.

        Args:
            device_id: Device identifier

        Returns:
            JSON string representation

        Raises:
            NotFoundError: If device not found
        """
        with self._lock:
            record = self._knowledge.get(device_id)
            if not record:
                raise NotFoundError(f"No knowledge for device: {device_id}")

            return json.dumps(record.to_dict(), indent=2)

    def import_json(self, device_id: str, data: str | dict) -> None:
        """
        Import device knowledge from JSON.

        Args:
            device_id: Device identifier
            data: JSON string or dict to import

        Raises:
            ValidationError: If JSON is malformed
        """
        try:
            if isinstance(data, str):
                parsed = json.loads(data)
            else:
                parsed = data

            record = KnowledgeRecord.from_dict(parsed)
            with self._lock:
                self._knowledge[device_id] = record
                logger.info(f"Imported knowledge for {device_id}")
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise ValidationError(f"Invalid knowledge JSON: {e}")

    def get_latest_analysis(
        self,
        device_id: str,
        analysis_type: str,
    ) -> Analysis | None:
        """
        Get the most recent analysis of a given type for a device.

        Args:
            device_id: Device identifier
            analysis_type: Type of analysis to find

        Returns:
            Latest Analysis matching the type, or None if not found
        """
        with self._lock:
            record = self._knowledge.get(device_id)
            if not record:
                return None

            matching = [a for a in record.analyses if a.analysis_type == analysis_type]
            if not matching:
                return None

            return max(matching, key=lambda a: a.timestamp)

    def update_learned_params(self, device_id: str, params: dict[str, float]) -> None:
        """
        Update or merge learned physics parameters.

        Args:
            device_id: Device identifier
            params: Dict of parameter names to values
        """
        with self._lock:
            if device_id not in self._knowledge:
                self._knowledge[device_id] = KnowledgeRecord(device_id=device_id)

            record = self._knowledge[device_id]
            record.learned_params.update(params)
            record.last_updated = time.time()

            logger.debug(f"Updated learned params for {device_id}: {list(params.keys())}")

    def add_performance_record(
        self,
        device_id: str,
        iteration_id: str,
        metrics: dict[str, float],
    ) -> None:
        """
        Log performance data from a simulation iteration.

        Args:
            device_id: Device identifier
            iteration_id: Unique iteration identifier
            metrics: Performance metrics dict
        """
        with self._lock:
            if device_id not in self._knowledge:
                self._knowledge[device_id] = KnowledgeRecord(device_id=device_id)

            record = self._knowledge[device_id]
            record.performance_history.append(
                PerformanceRecord(
                    iteration_id=iteration_id,
                    timestamp=time.time(),
                    metrics=metrics,
                )
            )
            record.last_updated = time.time()

    def set_capabilities(self, device_id: str, capabilities: list[str]) -> None:
        """
        Set the inferred capabilities for a device.

        Args:
            device_id: Device identifier
            capabilities: List of capability strings
        """
        with self._lock:
            if device_id not in self._knowledge:
                self._knowledge[device_id] = KnowledgeRecord(device_id=device_id)

            record = self._knowledge[device_id]
            record.capabilities_inferred = capabilities
            record.last_updated = time.time()

    def set_description(self, device_id: str, description: str) -> None:
        """
        Set the AI-generated description for a device.

        Args:
            device_id: Device identifier
            description: Description text
        """
        with self._lock:
            if device_id not in self._knowledge:
                self._knowledge[device_id] = KnowledgeRecord(device_id=device_id)

            record = self._knowledge[device_id]
            record.description_ai = description
            record.last_updated = time.time()

    def add_mesh_suggestion(
        self,
        device_id: str,
        suggestion: str,
        confidence: float,
        model: str,
    ) -> None:
        """
        Add a suggestion for 3D mesh improvement.

        Args:
            device_id: Device identifier
            suggestion: Suggestion text
            confidence: Confidence score (0-1)
            model: Model name that generated the suggestion
        """
        with self._lock:
            if device_id not in self._knowledge:
                self._knowledge[device_id] = KnowledgeRecord(device_id=device_id)

            record = self._knowledge[device_id]
            record.mesh_suggestions.append(
                MeshSuggestion(
                    suggestion=suggestion,
                    confidence=confidence,
                    model=model,
                    timestamp=time.time(),
                )
            )
            record.last_updated = time.time()

    def clear(self, device_id: str) -> None:
        """
        Clear all knowledge for a device.

        Args:
            device_id: Device identifier
        """
        with self._lock:
            if device_id in self._knowledge:
                del self._knowledge[device_id]
                logger.info(f"Cleared knowledge for {device_id}")

    def list_devices(self) -> list[str]:
        """
        List all device IDs that have knowledge records.

        Returns:
            List of device IDs
        """
        with self._lock:
            return list(self._knowledge.keys())

    def clear_all(self) -> None:
        """Clear all knowledge records (for testing)."""
        with self._lock:
            self._knowledge.clear()

    def get_stats(self) -> dict[str, Any]:
        """Return knowledge base statistics."""
        with self._lock:
            total_analyses = sum(len(r.analyses) for r in self._knowledge.values())
            total_devices = len(self._knowledge)
            return {
                "devices_with_knowledge": total_devices,
                "total_analyses": total_analyses,
            }
