"""
OMNIX ROS2 Bridge Connector — Tier 2 (middleware).

Bridges OMNIX's abstract protocol to ROS2. On the ROS2 side we subscribe
to common topic patterns (/odom, /battery_state, /joint_states, etc.) and
publish /cmd_vel + /std_srvs/Trigger-style commands.

Because rclpy requires a ROS2 distro sourced in the environment (Humble,
Iron, Jazzy), we try `import rclpy` and fall back to a simulated ROS2
environment otherwise.  In the simulated environment we fabricate a
plausible set of topics so the rest of OMNIX can be developed against
the bridge without installing ROS2.

Minimal topic contract:
  SUBS:  /cmd_vel  (geometry_msgs/Twist)
         /joint_command (custom, or sensor_msgs/JointState)
  PUBS:  /odom, /battery_state, /joint_states, /tf (best-effort)

The bridge presents one OmnixDevice per discovered namespace — in
practice one per robot — driven from what it sees on the graph.
"""

import math
import random
import threading
import time

from devices.base import DeviceCapability
from connectors.base import (
    ConnectorBase, ConnectorMeta, ConnectorDevice,
    ConfigField, SimulatedBackendMixin,
)

try:
    import rclpy  # type: ignore
    from rclpy.node import Node  # type: ignore
    from geometry_msgs.msg import Twist  # type: ignore
    from sensor_msgs.msg import BatteryState, JointState  # type: ignore
    from nav_msgs.msg import Odometry  # type: ignore
    _HAS_RCLPY = True
except ImportError:
    _HAS_RCLPY = False


# ───────────────────────────────────────────────────────────
#  Simulated ROS2 robot
# ───────────────────────────────────────────────────────────

class _SimRos:
    def __init__(self, robot_kind: str, namespace: str):
        self.kind = robot_kind           # mobile | arm
        self.ns = namespace
        self.boot = time.time()
        self.odom = {"x": 0.0, "y": 0.0, "theta": 0.0}
        self.cmd = {"vx": 0.0, "vy": 0.0, "wz": 0.0}
        self.battery_v = 24.0
        self.battery_pct = 95.0
        self.joints = {"shoulder": 0.0, "elbow": 1.2, "wrist": 0.0} if robot_kind == "arm" else {}
        self.target_joints = dict(self.joints)
        self._last_tick = time.time()

    def cmd_vel(self, vx: float, vy: float, wz: float):
        self.cmd = {"vx": vx, "vy": vy, "wz": wz}
        return True

    def set_joint(self, name: str, pos: float):
        if name in self.target_joints:
            self.target_joints[name] = pos
            return True
        return False

    def tick(self):
        now = time.time()
        dt = max(0.01, now - self._last_tick)
        self._last_tick = now
        if self.kind == "mobile":
            # Integrate odom
            th = self.odom["theta"]
            self.odom["x"] += (self.cmd["vx"] * math.cos(th) - self.cmd["vy"] * math.sin(th)) * dt
            self.odom["y"] += (self.cmd["vx"] * math.sin(th) + self.cmd["vy"] * math.cos(th)) * dt
            self.odom["theta"] = (self.odom["theta"] + self.cmd["wz"] * dt) % (2 * math.pi)
            # Drain battery with use
            activity = math.hypot(self.cmd["vx"], self.cmd["vy"]) + abs(self.cmd["wz"])
            self.battery_pct = max(0.0, self.battery_pct - 0.01 - activity * 0.01)
            self.battery_v = 22.0 + (self.battery_pct / 100.0) * 2.4
        elif self.kind == "arm":
            # Move each joint toward its target
            for j in self.joints:
                diff = self.target_joints[j] - self.joints[j]
                step = min(abs(diff), 1.0 * dt)
                self.joints[j] += step if diff > 0 else -step
            self.battery_pct = max(0.0, self.battery_pct - 0.003)
            self.battery_v = 22.0 + (self.battery_pct / 100.0) * 2.4

    def telemetry(self) -> dict:
        base = {
            "simulated": True,
            "namespace": self.ns,
            "uptime_s": int(time.time() - self.boot),
            "battery_pct": round(self.battery_pct, 1),
            "battery_v": round(self.battery_v, 2),
            "published_topics": self._published_topics(),
        }
        if self.kind == "mobile":
            base["odom"] = {"x": round(self.odom["x"], 3),
                            "y": round(self.odom["y"], 3),
                            "yaw_deg": round(math.degrees(self.odom["theta"]) % 360, 1)}
            base["cmd_vel"] = {"vx": round(self.cmd["vx"], 2),
                               "vy": round(self.cmd["vy"], 2),
                               "wz": round(self.cmd["wz"], 2)}
        elif self.kind == "arm":
            base["joint_states"] = {k: round(v, 3) for k, v in self.joints.items()}
        return base

    def _published_topics(self):
        t = [f"{self.ns}/odom", f"{self.ns}/battery_state"]
        if self.kind == "mobile":
            t.append(f"{self.ns}/cmd_vel")
        if self.kind == "arm":
            t += [f"{self.ns}/joint_states", f"{self.ns}/joint_command"]
        return t


# ───────────────────────────────────────────────────────────
#  ROS2 connector
# ───────────────────────────────────────────────────────────

class Ros2BridgeConnector(SimulatedBackendMixin, ConnectorBase):
    """Tier 2 — ROS2 bridge. Subscribes/publishes to standard topics."""

    meta = ConnectorMeta(
        connector_id="ros2_bridge",
        display_name="ROS2 Bridge",
        tier=2,
        description="Bridges OMNIX commands/telemetry to ROS2 topics (/cmd_vel, /odom, /joint_states, /battery_state).",
        vpe_categories=["ground_robot", "robot_arm", "humanoid", "legged",
                        "service_robot", "warehouse", "industrial", "medical",
                        "home_robot", "space", "extreme"],
        required_packages=["rclpy"],
        supports_simulation=True,
        icon="🧩",
        vendor="Open Robotics (ROS2)",
        docs_url="https://docs.ros.org/",
        config_schema=[
            ConfigField(
                key="name", label="Display name", type="text",
                default="ROS2 Robot", placeholder="TurtleBot4",
            ),
            ConfigField(
                key="namespace", label="Robot namespace", type="text",
                default="/robot1", placeholder="/turtlebot4",
                help="Topic prefix on the ROS2 side (without trailing slash).",
            ),
            ConfigField(
                key="kind", label="Robot kind", type="select",
                default="mobile", options=["mobile", "arm"],
                help="Changes which topics are bridged.",
            ),
            ConfigField(
                key="mode", label="Mode", type="select",
                default="simulate", options=["simulate", "real"],
                help="'simulate' fabricates a ROS2-like environment. 'real' uses rclpy.",
            ),
            ConfigField(
                key="domain_id", label="ROS_DOMAIN_ID", type="number",
                default=0,
                help="ROS2 DDS domain. Set this if your robots use a non-default domain.",
            ),
        ],
        setup_steps=[
            "Install ROS2 (Humble/Iron/Jazzy) on the host running OMNIX, and source the overlay.",
            "Ensure python3-rclpy is in your active ROS2 env (`python -c 'import rclpy'` must succeed).",
            "Make sure your robot is publishing the standard topics under the chosen namespace.",
            "Pick 'real' mode, set namespace + domain id, click Connect.",
            "OMNIX exposes cmd_vel / joint_command; telemetry streams from odom / joint_states / battery_state.",
            "No ROS2? Keep on 'simulate' — it's a full-fidelity stand-in for UI development.",
        ],
    )

    def connect(self) -> bool:
        name = self.config.get("name", "ROS2 Robot")
        ns = self.config.get("namespace", "/robot1").rstrip("/")
        kind = self.config.get("kind", "mobile")
        mode = self.config.get("mode", "simulate")

        device_type = {
            "mobile": "ground_robot", "arm": "robot_arm",
        }.get(kind, "ground_robot")

        self._tele: dict = {"status": "connecting"}
        self._tele_lock = threading.Lock()
        self._stop = threading.Event()

        caps = self._capabilities_for(kind)

        if mode == "simulate":
            self._use_simulation = True
            self._sim = _SimRos(kind, ns)
        else:
            if not _HAS_RCLPY:
                self._mark_connected(False,
                    "rclpy not importable. Source your ROS2 overlay before starting OMNIX, "
                    "or use simulate mode.")
                return False
            try:
                import os
                os.environ.setdefault("ROS_DOMAIN_ID", str(self.config.get("domain_id", 0)))
                # rclpy.init is global; guard against multiple bridges.
                if not rclpy.ok():
                    rclpy.init()
                self._node = _Ros2BridgeNode(ns, kind)
                self._spin_thread = threading.Thread(
                    target=self._spin_loop, daemon=True, name="ros2-spin")
                self._spin_thread.start()
                self._use_simulation = False
            except Exception as e:
                self._mark_connected(False, f"rclpy setup failed: {e}")
                return False

        def handler(c, p): return self._run_command(c, p)
        def tele():
            with self._tele_lock:
                return dict(self._tele)

        dev = ConnectorDevice(
            name=name, device_type=device_type, capabilities=caps,
            command_handler=handler, telemetry_provider=tele,
            source_connector=self,
        )
        self._devices.append(dev)
        self._mark_connected(True)
        return True

    def disconnect(self):
        self._stop.set()
        if not self._use_simulation and hasattr(self, "_node"):
            try:
                self._node.destroy_node()
            except Exception:
                pass
        self._devices.clear()
        self._mark_connected(False)

    def tick(self):
        if self._use_simulation:
            self._sim.tick()
            with self._tele_lock:
                self._tele = self._sim.telemetry()
        elif hasattr(self, "_node"):
            with self._tele_lock:
                self._tele = self._node.latest_telemetry()

    def _spin_loop(self):
        while not self._stop.is_set():
            try:
                rclpy.spin_once(self._node, timeout_sec=0.1)
            except Exception:
                time.sleep(0.1)

    def _capabilities_for(self, kind: str):
        if kind == "mobile":
            return [
                DeviceCapability("cmd_vel", "Publish a Twist on /cmd_vel",
                    {"vx": {"type": "number", "default": 0.2},
                     "vy": {"type": "number", "default": 0.0},
                     "wz": {"type": "number", "default": 0.0}},
                    "movement"),
                DeviceCapability("stop", "Send zero Twist", {}, "safety"),
            ]
        if kind == "arm":
            return [
                DeviceCapability("set_joint", "Set a joint position",
                    {"name": {"type": "text", "default": "shoulder"},
                     "position": {"type": "number", "default": 0.0}},
                    "movement"),
                DeviceCapability("stop", "Hold current pose", {}, "safety"),
            ]
        return []

    def _run_command(self, cmd: str, params: dict) -> dict:
        p = params or {}
        if self._use_simulation:
            if cmd == "cmd_vel":
                self._sim.cmd_vel(float(p.get("vx", 0)),
                                  float(p.get("vy", 0)),
                                  float(p.get("wz", 0)))
                return {"success": True, "message": "/cmd_vel published (sim)"}
            if cmd == "stop":
                if self._sim.kind == "mobile":
                    self._sim.cmd_vel(0, 0, 0)
                return {"success": True, "message": "stopped"}
            if cmd == "set_joint":
                if self._sim.set_joint(p.get("name"), float(p.get("position", 0))):
                    return {"success": True, "message": f"/joint_command set {p.get('name')}"}
                return {"success": False, "message": f"unknown joint {p.get('name')}"}
            return {"success": False, "message": f"unsupported {cmd}"}
        # Real ROS2
        try:
            return self._node.run(cmd, p)
        except Exception as e:
            return {"success": False, "message": f"ROS2 error: {e}"}


# ───────────────────────────────────────────────────────────
#  Real ROS2 bridge node (only imported if rclpy is available)
# ───────────────────────────────────────────────────────────

if _HAS_RCLPY:
    class _Ros2BridgeNode(Node):
        def __init__(self, namespace: str, kind: str):
            super().__init__("omnix_bridge" + namespace.replace("/", "_"))
            self._ns = namespace
            self._kind = kind
            self._tele_lock = threading.Lock()
            self._tele = {"status": "awaiting data"}

            # Publishers
            if kind == "mobile":
                self.pub_cmd_vel = self.create_publisher(Twist, f"{namespace}/cmd_vel", 10)
            # Subscriptions
            self.create_subscription(Odometry, f"{namespace}/odom",
                                     self._on_odom, 10)
            self.create_subscription(BatteryState, f"{namespace}/battery_state",
                                     self._on_battery, 10)
            if kind == "arm":
                self.create_subscription(JointState, f"{namespace}/joint_states",
                                         self._on_joints, 10)
                self.pub_joint_cmd = self.create_publisher(
                    JointState, f"{namespace}/joint_command", 10)

        def _on_odom(self, msg):
            pos = msg.pose.pose.position
            ori = msg.pose.pose.orientation
            # Quaternion → yaw
            siny = 2 * (ori.w * ori.z + ori.x * ori.y)
            cosy = 1 - 2 * (ori.y * ori.y + ori.z * ori.z)
            yaw = math.atan2(siny, cosy)
            with self._tele_lock:
                self._tele["odom"] = {"x": round(pos.x, 3), "y": round(pos.y, 3),
                                      "yaw_deg": round(math.degrees(yaw) % 360, 1)}

        def _on_battery(self, msg):
            with self._tele_lock:
                self._tele["battery_v"] = round(msg.voltage, 2)
                if msg.percentage > 0:
                    self._tele["battery_pct"] = round(msg.percentage * 100, 1)

        def _on_joints(self, msg):
            with self._tele_lock:
                self._tele["joint_states"] = {
                    n: round(p, 3) for n, p in zip(msg.name, msg.position)
                }

        def latest_telemetry(self) -> dict:
            with self._tele_lock:
                out = dict(self._tele)
            out["_ts"] = time.time()
            return out

        def run(self, cmd: str, params: dict) -> dict:
            if cmd == "cmd_vel" and self._kind == "mobile":
                t = Twist()
                t.linear.x = float(params.get("vx", 0))
                t.linear.y = float(params.get("vy", 0))
                t.angular.z = float(params.get("wz", 0))
                self.pub_cmd_vel.publish(t)
                return {"success": True, "message": "/cmd_vel published"}
            if cmd == "stop":
                if self._kind == "mobile":
                    t = Twist()
                    self.pub_cmd_vel.publish(t)
                return {"success": True, "message": "stopped"}
            if cmd == "set_joint" and self._kind == "arm":
                js = JointState()
                js.name = [params.get("name", "")]
                js.position = [float(params.get("position", 0))]
                self.pub_joint_cmd.publish(js)
                return {"success": True, "message": "/joint_command published"}
            return {"success": False, "message": f"unsupported {cmd}"}
else:
    class _Ros2BridgeNode:  # pragma: no cover
        def __init__(self, *a, **kw):
            raise RuntimeError("rclpy not available")
