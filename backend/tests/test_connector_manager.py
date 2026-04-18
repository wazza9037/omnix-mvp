"""Connector manager — class registration, lifecycle, VPE suggestions."""

from __future__ import annotations

import pytest


@pytest.fixture
def manager(fresh_device_registry):
    from connector_manager import ConnectorManager
    from connectors import ALL_CONNECTORS
    mgr = ConnectorManager(fresh_device_registry)
    for cls in ALL_CONNECTORS:
        mgr.register(cls)
    yield mgr
    mgr.shutdown()


class TestRegistration:
    def test_all_shipped_connectors_register(self, manager):
        ids = {c["connector_id"] for c in manager.list_classes()}
        assert {"pi_agent", "arduino_serial", "esp32_wifi",
                "tello", "mavlink", "ros2_bridge"} <= ids

    def test_every_class_has_full_meta(self, manager):
        for cls_meta in manager.list_classes():
            assert cls_meta["display_name"]
            assert cls_meta["tier"] in (1, 2, 3)
            assert cls_meta["description"]
            assert isinstance(cls_meta["vpe_categories"], list)
            assert isinstance(cls_meta["config_schema"], list)


class TestSuggestions:
    def test_drone_gets_tello_first(self, manager):
        sugs = manager.suggest_for_vpe("drone")
        assert sugs[0]["connector_id"] == "tello"

    def test_robot_arm_gets_ros2_first(self, manager):
        sugs = manager.suggest_for_vpe("robot_arm")
        assert sugs[0]["connector_id"] == "ros2_bridge"

    def test_unknown_category_falls_back_to_defaults(self, manager):
        sugs = manager.suggest_for_vpe("totally_unknown")
        assert sugs        # non-empty
        # Defaults include pi_agent / esp32_wifi / arduino_serial
        ids = {s["connector_id"] for s in sugs}
        assert ids & {"pi_agent", "esp32_wifi", "arduino_serial"}


class TestLifecycleTello:
    def test_start_and_stop_tello_simulation(self, manager):
        """Start a Tello-simulated connector, verify device registers, stop it."""
        # Access the manager's device registry directly rather than depending
        # on the fresh_device_registry fixture — this avoids any fixture-cache
        # ordering subtleties.
        device_registry = manager._device_registry
        result = manager.start_instance("tello", {
            "name": "TestTello", "mode": "simulate"
        })
        assert result["ok"] is True
        inst_id = result["status"]["instance_id"]
        assert result["status"]["connected"] is True
        assert len(result["devices"]) == 1
        # Device appeared in the registry
        assert len(device_registry) == 1

        # Run tick a few times
        inst = manager.get_instance(inst_id)
        for _ in range(3):
            inst.tick()

        # Stop it
        stop = manager.stop_instance(inst_id)
        assert stop["ok"] is True
        assert len(device_registry) == 0

    def test_stop_unknown_instance_returns_error(self, manager):
        result = manager.stop_instance("nope")
        assert result["ok"] is False

    def test_tello_sim_takeoff_and_state(self, manager):
        import time
        result = manager.start_instance("tello", {"name": "T2", "mode": "simulate"})
        dev_id = result["devices"][0]["id"]
        inst = manager.get_instance(result["status"]["instance_id"])
        # Find the ConnectorDevice
        devs = inst.get_devices()
        assert len(devs) == 1
        dev = devs[0]
        # takeoff (also triggers a state frame emission on the sim)
        r = dev.execute_command("takeoff", {})
        assert r["success"] is True
        # advance sim and let the 200ms telemetry cache expire
        for _ in range(5):
            inst.tick()
        time.sleep(0.25)
        tele = dev.get_telemetry()
        assert tele.get("flying") is True


class TestLifecycleMavlink:
    def test_mavlink_sim_flies_to_target(self, manager):
        import time
        result = manager.start_instance("mavlink", {
            "name": "Pixhawk", "mode": "simulate", "frame_type": "quad"
        })
        assert result["ok"] is True
        inst = manager.get_instance(result["status"]["instance_id"])
        dev = inst.get_devices()[0]
        dev.execute_command("arm", {"arm": True})
        dev.execute_command("takeoff", {"altitude_m": 20})
        # Run enough ticks for the sim to fly up, then wait out the telemetry cache
        for _ in range(40):
            inst.tick()
        time.sleep(0.25)
        tele = dev.get_telemetry()
        assert tele["armed"] is True
        assert tele["mode"] in ("GUIDED", "STABILIZE")
        assert tele["altitude_rel_m"] > 5.0   # started climbing


class TestLifecycleRover:
    def test_pi_agent_rover_drive(self, manager):
        import time
        result = manager.start_instance("pi_agent", {
            "profile": "rover", "name": "Rover1", "mode": "simulate"
        })
        inst = manager.get_instance(result["status"]["instance_id"])
        dev = inst.get_devices()[0]
        r = dev.execute_command("drive", {
            "direction": "forward", "speed": 50, "duration_ms": 1000
        })
        assert r["success"] is True
        # The command response itself carries position data, so assert against
        # that (telemetry has a 200ms cache populated by start_instance).
        assert r["data"]["x"] > 0 or r["data"]["y"] > 0
        # Also verify telemetry catches up after the cache expires.
        time.sleep(0.25)
        tele = dev.get_telemetry()
        assert tele["position"]["x"] != 0 or tele["position"]["y"] != 0


class TestConnectorMeta:
    def test_bad_class_raises(self, fresh_device_registry):
        from connector_manager import ConnectorManager
        class BadConnector:
            meta = None
        mgr = ConnectorManager(fresh_device_registry)
        with pytest.raises(ValueError, match="ConnectorMeta"):
            mgr.register(BadConnector)
