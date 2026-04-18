"""Workspace store — creation, updates, iterations, telemetry window."""

from __future__ import annotations

import pytest


class TestEnsureAndGet:
    def test_ensure_creates_workspace(self, fresh_workspace_store, fake_drone):
        ws = fresh_workspace_store.ensure(fake_drone)
        assert ws["device_id"] == fake_drone.id
        assert ws["name"] == fake_drone.name
        assert ws["device_type"] == "drone"
        assert ws["iterations"] == []
        assert isinstance(ws["world"], dict)

    def test_ensure_is_idempotent(self, fresh_workspace_store, fake_drone):
        a = fresh_workspace_store.ensure(fake_drone)
        b = fresh_workspace_store.ensure(fake_drone)
        assert a["workspace_id"] == b["workspace_id"]

    def test_ensure_syncs_renamed_device(self, fresh_workspace_store, fake_drone):
        fresh_workspace_store.ensure(fake_drone)
        fake_drone.name = "Renamed Drone"
        ws = fresh_workspace_store.ensure(fake_drone)
        assert ws["name"] == "Renamed Drone"

    def test_get_by_device(self, fresh_workspace_store, fake_drone):
        fresh_workspace_store.ensure(fake_drone)
        assert fresh_workspace_store.get_by_device(fake_drone.id) is not None
        assert fresh_workspace_store.get_by_device("nonexistent") is None

    def test_list_all_newest_first(self, fresh_workspace_store, fake_drone, fake_rover):
        import time
        fresh_workspace_store.ensure(fake_drone)
        time.sleep(0.001)
        fresh_workspace_store.ensure(fake_rover)
        rows = fresh_workspace_store.list_all()
        assert len(rows) == 2
        # Rover was created second → should appear first
        assert rows[0]["device_id"] == fake_rover.id


class TestMetadataUpdates:
    def test_update_meta_saves_notes_and_tags(self, fresh_workspace_store, fake_drone):
        fresh_workspace_store.ensure(fake_drone)
        fresh_workspace_store.update_meta(fake_drone.id,
            notes="Test notes", tags=["indoor", "debug"])
        ws = fresh_workspace_store.get_by_device(fake_drone.id)
        assert ws["notes"] == "Test notes"
        assert ws["tags"] == ["indoor", "debug"]

    def test_update_meta_drops_empty_tags(self, fresh_workspace_store, fake_drone):
        fresh_workspace_store.ensure(fake_drone)
        fresh_workspace_store.update_meta(fake_drone.id,
            tags=["valid", "  ", "", "another"])
        ws = fresh_workspace_store.get_by_device(fake_drone.id)
        assert ws["tags"] == ["valid", "another"]

    def test_update_meta_unknown_device_returns_none(self, fresh_workspace_store):
        result = fresh_workspace_store.update_meta("nope", notes="x")
        assert result is None

    def test_update_world_merges(self, fresh_workspace_store, fake_drone):
        fresh_workspace_store.ensure(fake_drone)
        fresh_workspace_store.update_world(fake_drone.id, {"gravity_m_s2": 3.71})
        ws = fresh_workspace_store.get_by_device(fake_drone.id)
        assert ws["world"]["gravity_m_s2"] == 3.71
        # Other defaults preserved
        assert ws["world"]["surface_friction"] is not None


class TestIterationLifecycle:
    def test_append_iteration_numbers_sequentially(self, fresh_workspace_store, fake_drone):
        fresh_workspace_store.ensure(fake_drone)
        it1 = fresh_workspace_store.append_iteration(fake_drone.id, {
            "metrics": {"overall": 0.5}})
        it2 = fresh_workspace_store.append_iteration(fake_drone.id, {
            "metrics": {"overall": 0.6}})
        assert it1["number"] == 1
        assert it2["number"] == 2

    def test_append_iteration_computes_delta(self, fresh_workspace_store, fake_drone):
        fresh_workspace_store.ensure(fake_drone)
        fresh_workspace_store.append_iteration(fake_drone.id, {
            "metrics": {"overall": 0.5, "stability": 0.9}})
        it2 = fresh_workspace_store.append_iteration(fake_drone.id, {
            "metrics": {"overall": 0.7, "stability": 0.95}})
        assert it2["delta"]["overall"] == pytest.approx(0.2, abs=1e-6)
        assert it2["delta"]["stability"] == pytest.approx(0.05, abs=1e-6)

    def test_remove_iteration(self, fresh_workspace_store, fake_drone):
        fresh_workspace_store.ensure(fake_drone)
        it = fresh_workspace_store.append_iteration(fake_drone.id, {
            "metrics": {"overall": 0.5}})
        assert fresh_workspace_store.remove_iteration(fake_drone.id, it["id"]) is True
        ws = fresh_workspace_store.get_by_device(fake_drone.id)
        assert ws["iterations"] == []

    def test_remove_iteration_returns_false_for_unknown(self, fresh_workspace_store, fake_drone):
        fresh_workspace_store.ensure(fake_drone)
        assert fresh_workspace_store.remove_iteration(fake_drone.id, "nope") is False

    def test_update_iteration_note(self, fresh_workspace_store, fake_drone):
        fresh_workspace_store.ensure(fake_drone)
        it = fresh_workspace_store.append_iteration(fake_drone.id, {
            "metrics": {"overall": 0.5}})
        updated = fresh_workspace_store.update_iteration(fake_drone.id, it["id"], {"note": "a note"})
        assert updated["note"] == "a note"


class TestTelemetryWindow:
    def test_push_and_read_telemetry(self, fresh_workspace_store, fake_drone):
        fresh_workspace_store.ensure(fake_drone)
        fresh_workspace_store.push_telemetry(fake_drone.id, {"battery": 90})
        fresh_workspace_store.push_telemetry(fake_drone.id, {"battery": 89})
        hist = fresh_workspace_store.get_telemetry_history(fake_drone.id)
        assert len(hist) == 2
        assert hist[-1]["data"]["battery"] == 89

    def test_telemetry_window_bounded(self, fresh_workspace_store, fake_drone):
        """Deque capacity 120 — pushing 200 keeps only the most recent 120."""
        fresh_workspace_store.ensure(fake_drone)
        for i in range(200):
            fresh_workspace_store.push_telemetry(fake_drone.id, {"i": i})
        hist = fresh_workspace_store.get_telemetry_history(fake_drone.id)
        assert len(hist) == 120
        # The most recent should be i=199
        assert hist[-1]["data"]["i"] == 199


class TestDrop:
    def test_drop_removes_workspace(self, fresh_workspace_store, fake_drone):
        fresh_workspace_store.ensure(fake_drone)
        fresh_workspace_store.drop(fake_drone.id)
        assert fresh_workspace_store.get_by_device(fake_drone.id) is None


class TestSerialize:
    def test_serialize_excludes_telemetry_by_default(self, fresh_workspace_store, fake_drone):
        ws = fresh_workspace_store.ensure(fake_drone)
        fresh_workspace_store.push_telemetry(fake_drone.id, {"x": 1})
        serialized = fresh_workspace_store.serialize(ws, include_telemetry=False)
        assert "telemetry_window" not in serialized

    def test_serialize_includes_telemetry_when_requested(self, fresh_workspace_store, fake_drone):
        ws = fresh_workspace_store.ensure(fake_drone)
        fresh_workspace_store.push_telemetry(fake_drone.id, {"x": 1})
        serialized = fresh_workspace_store.serialize(ws, include_telemetry=True)
        assert "telemetry_window" in serialized
        assert len(serialized["telemetry_window"]) == 1
