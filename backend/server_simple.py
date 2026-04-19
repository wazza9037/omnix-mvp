"""
OMNIX Simple Server — Uses ONLY Python standard library.

Run with: python server_simple.py
Then open: http://localhost:8765
"""

import asyncio
import json
import time
import os
import uuid
import mimetypes
import urllib.request
import urllib.parse
from http.server import HTTPServer, ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading

# ── omnix infrastructure ──
from omnix import configure_logging, get_logger, settings, error_response
from omnix.errors import OmnixError, ValidationError, NotFoundError, ConflictError
from omnix.models import HealthStatus

# ── Production hardening imports ──
from omnix.auth import AuthManager, AuthMiddleware, get_current_user
from omnix.auth.models import User, UserRole, GUEST_USER
from omnix.auth.middleware import is_public_route, set_current_user
from omnix.auth.permissions import Permission, check_permission, require_permission
from omnix.auth.permissions import PermissionError as AuthPermissionError
from omnix.db import MigrationManager, SQLiteRepository, InMemoryRepository
from omnix.security import CORSMiddleware, RateLimiter, SecureHeaders, validate_input, sanitize_string
from omnix.security.validation import validate_request_size, validate_json_body
from omnix.middleware import metrics_collector, request_logger

configure_logging(level=settings.log_level, as_json=settings.log_json)
log = get_logger("omnix.server")

# ── Initialize production modules ──

# Auth
auth_manager = AuthManager(
    secret_key=settings.jwt_secret or None,
    token_expiry_seconds=settings.jwt_expiry,
    refresh_expiry_seconds=settings.jwt_refresh_expiry,
    guest_mode=settings.guest_mode,
)
auth_middleware = AuthMiddleware(auth_manager)

# Security
cors_middleware = CORSMiddleware(
    allowed_origins=settings.cors_origin_list,
)
rate_limiter = RateLimiter(
    auth_rate=settings.rate_limit_auth,
    api_rate=settings.rate_limit_api,
)
secure_headers = SecureHeaders()

# Database
db_repo = None
migration_manager = None

def _init_database():
    """Initialize the database based on configuration."""
    global db_repo, migration_manager
    if settings.db_backend == "sqlite":
        migration_manager = MigrationManager(settings.db_path)
        migration_manager.apply_migrations()
        conn = migration_manager.connect()
        db_repo = SQLiteRepository(conn)
        auth_manager.set_repository(db_repo)
        log.info("database initialized: SQLite (%s)", settings.db_path)
    elif settings.db_backend == "memory":
        db_repo = InMemoryRepository()
        log.info("database initialized: in-memory (data will not persist)")
    else:
        log.warning("unknown db_backend=%s, falling back to in-memory", settings.db_backend)
        db_repo = InMemoryRepository()


# ── Wikipedia lookup helper (free, no API key required) ──
_WIKI_CACHE = {}  # query → result (bounded LRU-like cache)
_WIKI_CACHE_MAX_SIZE = 100  # Limit cache size to prevent memory leak

def _evict_wiki_cache_if_needed():
    """Evict oldest entries if cache grows too large (simple FIFO strategy)."""
    if len(_WIKI_CACHE) > _WIKI_CACHE_MAX_SIZE:
        # Remove first ~20% of entries to amortize eviction cost
        to_remove = list(_WIKI_CACHE.keys())[:_WIKI_CACHE_MAX_SIZE // 5]
        for k in to_remove:
            del _WIKI_CACHE[k]

def _wikipedia_lookup(query: str) -> dict:
    """Look up a term on Wikipedia's REST summary endpoint.
    Returns {found, title, description, extract, thumbnail, url} or {found: False}.
    Cached in-memory for this session (max 100 entries to prevent memory leak).
    """
    key = query.lower().strip()
    if key in _WIKI_CACHE:
        return _WIKI_CACHE[key]

    # 1. Search for best-matching page title
    search_url = (
        "https://en.wikipedia.org/w/api.php?action=opensearch&limit=1&namespace=0"
        "&format=json&search=" + urllib.parse.quote(query)
    )
    try:
        with urllib.request.urlopen(search_url, timeout=4) as resp:
            search_data = json.loads(resp.read().decode("utf-8"))
        titles = search_data[1] if len(search_data) > 1 else []
        if not titles:
            result = {"found": False, "query": query}
            _WIKI_CACHE[key] = result
            _evict_wiki_cache_if_needed()
            return result
        title = titles[0]
    except Exception as e:
        return {"found": False, "error": f"search failed: {e}", "query": query}

    # 2. Fetch summary of that page
    summary_url = (
        "https://en.wikipedia.org/api/rest_v1/page/summary/"
        + urllib.parse.quote(title.replace(" ", "_"))
    )
    try:
        req = urllib.request.Request(summary_url, headers={"User-Agent": "OMNIX-VPE/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            sdata = json.loads(resp.read().decode("utf-8"))
        result = {
            "found": True,
            "query": query,
            "title": sdata.get("title", title),
            "description": sdata.get("description", ""),
            "extract": sdata.get("extract", ""),
            "thumbnail": (sdata.get("thumbnail") or {}).get("source", ""),
            "url": (sdata.get("content_urls") or {}).get("desktop", {}).get("page", ""),
        }
        _WIKI_CACHE[key] = result
        _evict_wiki_cache_if_needed()
        return result
    except Exception as e:
        result = {"found": False, "error": str(e), "query": query}
        _WIKI_CACHE[key] = result
        _evict_wiki_cache_if_needed()
        return result

# Import simulated devices
from devices.drone import SimulatedDrone
from devices.robot_arm import SimulatedRobotArm
from devices.smart_light import SimulatedSmartLight

# Import Visual Physics Engine
from vpe.engine import VisualPhysicsEngine
from vpe.mesh_generator import generate_mesh

# Import Device Store
from device_store import DeviceStore

# Import Movement system
from movements.presets import get_all_presets, get_presets_for_device, get_preset
from movements.executor import MovementExecutor

# Import Connector system
from connectors import ALL_CONNECTORS
from connectors import esp32_wifi as _esp32_module
from connector_manager import ConnectorManager

# Import Workspace + Simulation system
from workspace_store import WorkspaceStore
from simulation import list_scenarios, get_scenario, run_scenario

# Import Template library + Custom Build system
from templates import list_templates, get_template
from custom_build import (
    CustomBuild, CustomRobotDevice, all_part_types, derive_device_name_hint,
)

# Import Natural Language pipeline
from omnix.nlp import (
    compile_to_plan, plan_and_validate, REGISTRY as nlp_registry,
    iteration_from_state, list_capabilities_for_device, ExecutionPlan,
    llm_available,
)

# Import Digital Twin
from omnix.digital_twin import (
    REGISTRY as twin_registry, TwinMode, auto_tune, apply_to_workspace,
)

# Import Behavior Tree engine
from omnix.behavior_tree import (
    BehaviorTree, TreeExecutor, Blackboard, TEMPLATE_LIBRARY,
)
from omnix.behavior_tree.library import list_templates as bt_list_templates, get_template as bt_get_template
from omnix.behavior_tree.tree import BehaviorTree as BT
from omnix.behavior_tree.nodes import node_from_dict

# Behavior Tree executor — one process-wide instance
bt_executor = TreeExecutor()

# Per-workspace tree storage: {device_id: {tree_id: tree_dict}}
_bt_store: dict[str, dict[str, dict]] = {}

# Import Marketplace
from omnix.marketplace import (
    MarketplaceStore, MarketplaceItem, ItemType,
    Publisher, Installer, FeaturedCollections,
)
from omnix.marketplace.featured import seed_marketplace
from omnix.marketplace.publisher import PublishError
from omnix.marketplace.installer import InstallError

# Import Collaboration module
from omnix.collab import CollabWSHandler

# Import Video module
from omnix.video import VideoStreamManager, VideoSource, FrameProcessor

# Import Sensor Dashboard
from omnix.sensors import SensorRegistry, AlertManager, SensorSimulator
from omnix.sensors.alerts import AlertRule
from omnix.sensors.simulator import auto_register_sensors

# Import OTA Firmware Update system
from omnix.ota import OTAManager, OTADeployer, FirmwareBuilder

# Import Swarm Coordination
from omnix.swarm import SwarmCoordinator, FORMATIONS, MISSION_TEMPLATES

# Import AI Enhancement module
from omnix.ai import ModelRegistry, AIInferenceEngine, RobotKnowledgeBase, RobotEnhancer

# Marketplace store — session-scoped, seeded on first access
marketplace_store = MarketplaceStore()
marketplace_installer = Installer(marketplace_store)

# Collaboration handler — session-scoped
collab_handler = CollabWSHandler()

# Video stream manager — session-scoped
video_manager = VideoStreamManager()
_frame_processor = FrameProcessor()

# Sensor Dashboard — registry, alerts, simulator
sensor_registry = SensorRegistry()
alert_manager = AlertManager()
sensor_simulator = SensorSimulator(sensor_registry)

# OTA Firmware Update system — session-scoped
ota_manager = OTAManager()
ota_deployer = OTADeployer(ota_manager)
firmware_builder = FirmwareBuilder()

# Preload existing sketches as available firmware
ota_manager.preload_existing_sketches()

# Swarm Coordinator — session-scoped
swarm_coordinator = SwarmCoordinator()

# AI Enhancement module — session-scoped
ai_model_registry = ModelRegistry()
ai_inference_engine = AIInferenceEngine(ai_model_registry)
ai_knowledge_base = RobotKnowledgeBase()
ai_enhancer = RobotEnhancer(ai_model_registry, ai_inference_engine, ai_knowledge_base)

# WebSocket server (initialized in main() if enabled)
ws_server = None

# Per-device command history for the command-bar up-arrow recall
_nlp_history: dict[str, list[str]] = {}
_NLP_HISTORY_DEVICE_LIMIT = 30  # Max entries per device
_NLP_HISTORY_MAX_DEVICES = 50   # Cleanup if tracking >50 devices (dead devices) to prevent leaks

def _cleanup_nlp_history_if_needed() -> None:
    """Remove history for deleted devices if tracking too many."""
    if len(_nlp_history) > _NLP_HISTORY_MAX_DEVICES:
        # Prune history for devices that no longer exist
        to_delete = [did for did in _nlp_history if did not in devices]
        for did in to_delete:
            del _nlp_history[did]

def _push_history(device_id: str, text: str, limit: int = None) -> None:
    if not text.strip():
        return
    if limit is None:
        limit = _NLP_HISTORY_DEVICE_LIMIT
    h = _nlp_history.setdefault(device_id, [])
    # De-dupe — if the last entry is the same, skip
    if h and h[-1] == text:
        return
    h.append(text)
    if len(h) > limit:
        del h[0:len(h) - limit]
    _cleanup_nlp_history_if_needed()

# Shared ESP32 registries (module-level in esp32_wifi so the connector and
# the HTTP handlers agree on state)
_ESP32_AGENTS, _ESP32_COMMAND_QUEUES, _ESP32_TELEMETRY = _esp32_module._server_hooks()

# Workspace store — one workspace per device (persistent for the session)
workspace_store = WorkspaceStore()

# Server boot timestamp (used by /healthz for uptime)
_server_start_ts = time.time()

# Initialize VPE
vpe_engine = VisualPhysicsEngine()

# Initialize Device Store (session-based)
device_store = DeviceStore()

# Initialize Movement Executor (after devices are registered)
movement_executor = None  # Set in main()

# Initialize Connector Manager (after devices dict exists)
connector_manager: ConnectorManager = None  # Set in main()

# Initialize Plugin System
from omnix.plugins import PluginLoader, PluginRegistry, PluginValidator
plugin_registry: PluginRegistry = None  # Set in main()
plugin_loader: PluginLoader = None       # Set in main()

# ── Pi Agent Registry ──
# Stores connected Pi agents: {agent_id: {device_id, name, device_type, ...}}
pi_agents = {}
# Pending commands for each agent: {agent_id: [cmd, ...]}
pi_command_queues = {}
# Latest telemetry from each agent: {agent_id: {telemetry, timestamp}}
pi_telemetry = {}
# Command results: {command_id: result}
pi_command_results = {}

# Global device registry (simulated devices)
devices = {}


def add_device(device):
    devices[device.id] = device
    # Auto-register sensor channels for the new device
    try:
        auto_register_sensors(sensor_registry, device.id, device.device_type)
    except Exception:
        pass  # Sensor registration is best-effort
    log.info("device registered: %s %s (id=%s)", device.device_type, device.name, device.id,
             extra={"device_type": device.device_type, "device_id": device.id})


class OmnixHandler(SimpleHTTPRequestHandler):
    """HTTP handler for OMNIX API + static file serving."""

    def __init__(self, *args, **kwargs):
        self.frontend_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "frontend"
        )
        super().__init__(*args, directory=self.frontend_dir, **kwargs)

    def log_message(self, format, *args):
        # Send access logs through the omnix logger at DEBUG so they can be
        # surfaced by bumping OMNIX_LOG_LEVEL=DEBUG. Silent by default.
        try:
            log.debug("http %s - %s", self.address_string(), format % args)
        except Exception:
            pass

    def _dispatch(self, fn):
        """Common wrapper: auth, rate limiting, metrics, error handling."""
        start_time = request_logger.before_request(self)
        status = 200
        try:
            path = self.path.split("?")[0]

            # Rate limiting on auth endpoints
            is_auth_endpoint = path.startswith("/api/auth/")
            if is_auth_endpoint and not rate_limiter.check(self, is_auth=True):
                rate_limiter.send_rate_limit_response(self)
                status = 429
                return
            elif not is_auth_endpoint and not rate_limiter.check(self):
                rate_limiter.send_rate_limit_response(self)
                status = 429
                return

            # Request size validation
            if not validate_request_size(self, settings.max_request_size):
                self._json_response(
                    {"error": {"code": "payload_too_large", "message": "Request body too large"}},
                    413,
                )
                status = 413
                return

            # Authentication
            if not is_public_route(path):
                user = auth_middleware.authenticate(self)
                if user is None:
                    self._json_response(
                        {"error": {"code": "unauthorized", "message": "Authentication required"}},
                        401,
                    )
                    status = 401
                    return
            else:
                set_current_user(auth_manager.get_guest_user() or GUEST_USER)

            fn()
        except AuthPermissionError as e:
            status = 403
            self._json_response({"error": {"code": "forbidden", "message": e.message}}, 403)
        except OmnixError as e:
            log.warning("handled error: %s", e.message,
                        extra={"code": e.code, "path": self.path})
            status, body = error_response(e)
            self._json_response(body, status)
        except Exception as e:
            log.exception("unhandled exception in %s", self.path)
            status, body = error_response(e)
            self._json_response(body, status)
        finally:
            request_logger.after_request(self, start_time, status)

    def do_GET(self):
        self._dispatch(self._do_get)

    def do_POST(self):
        self._dispatch(self._do_post)

    def _do_get(self):
        parsed = urlparse(self.path)

        # ── Health probe ──
        if parsed.path == "/healthz" or parsed.path == "/api/health":
            hs = HealthStatus(
                status="healthy",
                version="0.3.0",
                uptime_s=round(time.time() - _server_start_ts, 1),
                device_count=len(devices),
                connector_instances=len(connector_manager.list_instances()) if connector_manager else 0,
                active_workspaces=len(workspace_store._by_device) if workspace_store else 0,
            )
            self._json_response(hs.to_dict())
            return

        # ── Metrics endpoint ──
        if parsed.path == "/api/metrics":
            # Update gauge metrics
            ws_stats = ws_server.get_stats() if ws_server else {"connections": 0}
            metrics_collector.update_gauges(
                device_count=len(devices),
                active_sessions=len(collab_handler.sessions._sessions) if hasattr(collab_handler, 'sessions') else 0,
                ws_connections=ws_stats.get("connections", 0),
            )
            self._json_response(metrics_collector.get_metrics())
            return

        # ── Auth: get current user ──
        if parsed.path == "/api/auth/me":
            user = get_current_user()
            if user and user.id != "guest":
                self._json_response(user.to_dict())
            elif user:
                self._json_response(user.to_dict())
            else:
                self._json_response({"error": "Not authenticated"}, 401)
            return

        # ── Auth: guest token ──
        if parsed.path == "/api/auth/guest":
            guest = auth_manager.get_guest_user()
            if guest:
                token = auth_manager.create_token(guest)
                self._json_response({
                    "user": guest.to_dict(),
                    "access_token": token,
                    "token_type": "bearer",
                    "guest": True,
                })
            else:
                self._json_response({"error": "Guest mode disabled"}, 403)
            return

        # ── Auth: list users (admin only) ──
        if parsed.path == "/api/auth/users":
            user = get_current_user()
            require_permission(user, Permission.ADMIN_USERS)
            self._json_response(auth_manager.list_users())
            return

        # ── Existing Simulated Device Endpoints ──

        if parsed.path == "/api/devices":
            self._json_response({
                did: d.get_info() for did, d in devices.items()
            })

        elif parsed.path == "/api/telemetry":
            # Performance: support ?device_ids=id1,id2,... to fetch only specific devices
            qs = parse_qs(parsed.query)
            requested_ids = None
            if "device_ids" in qs:
                requested_ids = set(qs["device_ids"][0].split(","))

            telemetry = {}
            for did, d in devices.items():
                # Skip if specific device list was requested and this device isn't in it
                if requested_ids is not None and did not in requested_ids:
                    continue
                t = d.get_telemetry()
                telemetry[did] = t
                # Feed the workspace's rolling window if one exists
                ws = workspace_store.get_by_device(did)
                if ws is not None:
                    workspace_store.push_telemetry(did, t)
            self._json_response(telemetry)

        elif parsed.path.startswith("/api/events/"):
            device_id = parsed.path.split("/")[-1]
            if device_id in devices:
                self._json_response(devices[device_id].get_event_log())
            else:
                self._json_response({"error": "Device not found"}, 404)

        # ── Movement Endpoints ──

        elif parsed.path == "/api/movements/presets":
            qs = parse_qs(parsed.query)
            dtype = qs.get("device_type", [None])[0]
            if dtype:
                presets = get_presets_for_device(dtype)
            else:
                all_p = get_all_presets()
                presets = []
                for plist in all_p.values():
                    presets.extend(plist)
            self._json_response([p.to_dict() for p in presets])

        elif parsed.path.startswith("/api/movements/predict/"):
            parts = parsed.path.split("/")
            if len(parts) >= 6:
                dtype = parts[4]
                pname = parts[5]
                qs = parse_qs(parsed.query)
                start = {}
                for axis in ["x", "y", "z"]:
                    if axis in qs:
                        start[axis] = float(qs[axis][0])
                result = movement_executor.predict_path(dtype, pname, start or None)
                self._json_response(result)
            else:
                self._json_response({"error": "Use /api/movements/predict/{device_type}/{preset_name}"}, 400)

        elif parsed.path.startswith("/api/movements/progress/"):
            device_id = parsed.path.split("/")[-1]
            if movement_executor:
                self._json_response(movement_executor.get_progress(device_id))
            else:
                self._json_response({"status": "idle"})

        # ── Device Store Endpoints ──

        elif parsed.path == "/api/device-store/all":
            self._json_response(device_store.get_all())

        elif parsed.path == "/api/device-store/active":
            active = device_store.get_active()
            if active:
                # Return profile without the heavy vpe_result
                resp = {k: v for k, v in active.items() if k != "vpe_result"}
                self._json_response(resp)
            else:
                self._json_response(None)

        elif parsed.path.startswith("/api/device-store/profile/"):
            profile_id = parsed.path.split("/")[-1]
            profile = device_store.get_profile(profile_id)
            if profile:
                resp = {k: v for k, v in profile.items() if k != "vpe_result"}
                self._json_response(resp)
            else:
                self._json_response({"error": "Profile not found"}, 404)

        # ── Pi Agent Endpoints (GET) ──

        elif parsed.path == "/api/pi/agents":
            # List all connected Pi agents
            agents_list = []
            for aid, info in pi_agents.items():
                agent_info = {**info, "agent_id": aid}
                # Attach latest telemetry
                if aid in pi_telemetry:
                    agent_info["telemetry"] = pi_telemetry[aid].get("telemetry", {})
                    agent_info["last_seen"] = pi_telemetry[aid].get("timestamp", 0)
                    agent_info["online"] = (time.time() - agent_info["last_seen"]) < 10
                else:
                    agent_info["telemetry"] = {}
                    agent_info["online"] = False
                agents_list.append(agent_info)
            self._json_response(agents_list)

        elif parsed.path.startswith("/api/pi/commands/"):
            # Pi agent polls for pending commands
            agent_id = parsed.path.split("/")[-1]
            if agent_id in pi_agents:
                commands = pi_command_queues.get(agent_id, [])
                pi_command_queues[agent_id] = []  # Clear after sending
                self._json_response({"commands": commands})
            else:
                self._json_response({"error": "Agent not found"}, 404)

        elif parsed.path.startswith("/api/pi/telemetry/"):
            # Get latest telemetry for an agent (for frontend polling)
            agent_id = parsed.path.split("/")[-1]
            if agent_id in pi_telemetry:
                self._json_response(pi_telemetry[agent_id])
            else:
                self._json_response({"error": "No telemetry"}, 404)

        # ── Connector Endpoints (GET) ──

        elif parsed.path == "/api/connectors/classes":
            self._json_response(connector_manager.list_classes() if connector_manager else [])

        elif parsed.path == "/api/connectors/instances":
            self._json_response(connector_manager.list_instances() if connector_manager else [])

        elif parsed.path == "/api/connectors/registry":
            self._json_response(connector_manager.get_raw_mapping() if connector_manager else {})

        elif parsed.path == "/api/connectors/suggest":
            qs = parse_qs(parsed.query)
            cat = qs.get("category", [""])[0]
            dt = qs.get("device_type", [""])[0]
            suggestions = connector_manager.suggest_for_vpe(cat, dt) if connector_manager else []
            self._json_response(suggestions)

        # ── Plugin Endpoints (GET) ──

        elif parsed.path == "/api/plugins":
            if plugin_registry:
                self._json_response(plugin_registry.list_plugins())
            else:
                self._json_response([])

        # ── ESP32 Agent Endpoints (GET) ──

        elif parsed.path.startswith("/api/esp32/commands/"):
            agent_id = parsed.path.split("/")[-1]
            if agent_id not in _ESP32_AGENTS:
                self._json_response({"error": "Unknown agent", "commands": []}, 404)
            else:
                cmds = _ESP32_COMMAND_QUEUES.get(agent_id, [])
                _ESP32_COMMAND_QUEUES[agent_id] = []
                self._json_response({"commands": cmds})

        elif parsed.path == "/api/esp32/agents":
            out = []
            for aid, info in _ESP32_AGENTS.items():
                entry = {"agent_id": aid, **info}
                if aid in _ESP32_TELEMETRY:
                    entry["telemetry"] = _ESP32_TELEMETRY[aid].get("telemetry", {})
                    entry["last_seen"] = _ESP32_TELEMETRY[aid].get("ts", 0)
                    entry["online"] = (time.time() - entry["last_seen"]) < 10
                else:
                    entry["telemetry"] = {}
                    entry["online"] = False
                out.append(entry)
            self._json_response(out)

        # ── Workspace Endpoints (GET) ──

        elif parsed.path == "/api/workspaces":
            # Ensure every current device has a workspace
            for did, dev in devices.items():
                workspace_store.ensure(dev)
            self._json_response(workspace_store.list_all())

        elif parsed.path.startswith("/api/workspaces/"):
            parts = parsed.path.split("/")
            # /api/workspaces/<device_id>   (and nested paths)
            if len(parts) >= 4:
                device_id = parts[3]
                dev = devices.get(device_id)
                if dev is None:
                    self._json_response({"error": "Device not found"}, 404)
                    return
                ws = workspace_store.ensure(dev)

                # /api/workspaces/<id>
                if len(parts) == 4:
                    self._json_response(workspace_store.serialize(ws, include_telemetry=True))
                    return

                sub = parts[4]
                if sub == "iterations":
                    if len(parts) == 5:
                        # List iterations (without full trajectories for bulk view)
                        summaries = []
                        for it in ws["iterations"]:
                            summaries.append({
                                "id": it.get("id"),
                                "number": it.get("number"),
                                "scenario": it.get("scenario"),
                                "scenario_display_name": it.get("scenario_display_name"),
                                "scenario_icon": it.get("scenario_icon"),
                                "duration_s": it.get("duration_s"),
                                "metrics": it.get("metrics"),
                                "delta": it.get("delta"),
                                "note": it.get("note", ""),
                                "timestamp": it.get("timestamp"),
                            })
                        self._json_response(summaries)
                        return
                    if len(parts) == 6:
                        # /api/workspaces/<id>/iterations/<iter_id>
                        it = workspace_store.get_iteration(device_id, parts[5])
                        if it:
                            self._json_response(it)
                        else:
                            self._json_response({"error": "Iteration not found"}, 404)
                        return
                elif sub == "physics":
                    self._json_response(ws.get("physics") or {})
                    return
                elif sub == "metrics":
                    # Series data for charts
                    out = []
                    for it in ws["iterations"]:
                        out.append({
                            "number": it.get("number"),
                            "scenario": it.get("scenario"),
                            "timestamp": it.get("timestamp"),
                            "metrics": it.get("metrics"),
                            "confidence": (it.get("physics_after") or {}).get("confidence", 0),
                        })
                    self._json_response(out)
                    return
                elif sub == "telemetry-history":
                    self._json_response(workspace_store.get_telemetry_history(device_id))
                    return

            self._json_response({"error": "Bad workspace path"}, 400)

        # ── Simulation Endpoints (GET) ──

        elif parsed.path == "/api/simulation/scenarios":
            qs = parse_qs(parsed.query)
            dt = qs.get("device_type", [None])[0]
            self._json_response(list_scenarios(dt))

        # ── Template gallery + Parts library (GET) ──

        elif parsed.path == "/api/templates":
            self._json_response(list_templates())

        elif parsed.path.startswith("/api/templates/"):
            template_id = parsed.path.split("/")[-1]
            tpl = get_template(template_id)
            if not tpl:
                raise NotFoundError(f"Template not found: {template_id}")
            self._json_response(tpl.to_dict())

        elif parsed.path == "/api/parts":
            self._json_response(all_part_types())

        # ── NLP pipeline (GET) ──

        elif parsed.path.startswith("/api/nlp/execution/"):
            # Live state for a device's currently-running (or most recent) plan
            device_id = parsed.path.split("/")[-1]
            state = nlp_registry.get(device_id)
            if state is None:
                self._json_response(None)
            else:
                self._json_response(state.to_dict())

        elif parsed.path.startswith("/api/nlp/history/"):
            device_id = parsed.path.split("/")[-1]
            hist = _nlp_history.get(device_id, [])
            completed = [s.to_dict() for s in nlp_registry.history(device_id)]
            self._json_response({
                "commands": list(reversed(hist)),   # newest first
                "completed_executions": completed,
            })

        elif parsed.path.startswith("/api/nlp/suggestions/"):
            device_id = parsed.path.split("/")[-1]
            dev = devices.get(device_id)
            if dev is None:
                raise NotFoundError("Device not found", {"device_id": device_id})
            self._json_response({
                "device_type": dev.device_type,
                "intents": list_capabilities_for_device(dev.device_type),
                "llm_enabled": llm_available(),
            })

        # ── Digital Twin (GET) ──

        elif parsed.path.startswith("/api/twin/session/"):
            sess_id = parsed.path.split("/")[-1]
            s = twin_registry.get_session(sess_id)
            if s is None:
                raise NotFoundError("Session not found",
                                    {"session_id": sess_id})
            # For the full frame list use query ?full=1
            include_frames = parse_qs(parsed.query).get("full", ["0"])[0] == "1"
            self._json_response(s.to_dict(include_frames=include_frames))

        elif parsed.path == "/api/twin/sessions":
            self._json_response(twin_registry.list_sessions())

        elif parsed.path.startswith("/api/twin/"):
            device_id = parsed.path.split("/")[-1]
            if device_id in devices:
                twin = twin_registry.get(device_id)
                if twin is None:
                    self._json_response(None)
                else:
                    self._json_response(twin.snapshot().to_dict())
            else:
                raise NotFoundError("Device not found",
                                    {"device_id": device_id})

        # ── Behavior Tree GET routes ─────────────────────
        elif parsed.path == "/api/bt/templates":
            qs = parse_qs(parsed.query)
            dt = qs.get("device_type", [None])[0]
            self._json_response(bt_list_templates(dt))

        elif parsed.path.startswith("/api/bt/template/"):
            name = urllib.parse.unquote(parsed.path.split("/api/bt/template/")[1])
            tpl = bt_get_template(name)
            if tpl is None:
                raise NotFoundError("Template not found", {"name": name})
            self._json_response(tpl)

        elif parsed.path.startswith("/api/bt/trees/"):
            # GET /api/bt/trees/<device_id> — list saved trees
            device_id = parsed.path.split("/api/bt/trees/")[1]
            trees = _bt_store.get(device_id, {})
            summaries = []
            for tid, tdata in trees.items():
                summaries.append({
                    "tree_id": tid,
                    "name": tdata.get("name", "Untitled"),
                    "description": tdata.get("description", ""),
                    "node_count": len(self._count_nodes(tdata.get("root"))),
                    "updated_at": tdata.get("updated_at", 0),
                })
            self._json_response(summaries)

        elif parsed.path.startswith("/api/bt/tree/"):
            # GET /api/bt/tree/<tree_id>?device_id=X — load a specific tree
            tree_id = parsed.path.split("/api/bt/tree/")[1]
            qs = parse_qs(parsed.query)
            device_id = qs.get("device_id", [""])[0]
            trees = _bt_store.get(device_id, {})
            tdata = trees.get(tree_id)
            if tdata is None:
                raise NotFoundError("Tree not found", {"tree_id": tree_id})
            self._json_response(tdata)

        elif parsed.path.startswith("/api/bt/execution/"):
            # GET /api/bt/execution/<device_id> — poll execution status
            device_id = parsed.path.split("/api/bt/execution/")[1]
            record = bt_executor.get(device_id)
            if record:
                self._json_response(record.to_dict())
            else:
                self._json_response(None)

        elif parsed.path.startswith("/api/bt/history/"):
            device_id = parsed.path.split("/api/bt/history/")[1]
            self._json_response(bt_executor.history(device_id))

        # ── Marketplace GET routes ───────────────────────
        elif parsed.path == "/api/marketplace":
            # Ensure seeded
            seed_marketplace(marketplace_store)
            qs = parse_qs(parsed.query)
            result = marketplace_store.browse(
                query=qs.get("q", [""])[0],
                item_type=qs.get("type", [None])[0],
                tags=qs.get("tags", [None])[0].split(",") if qs.get("tags", [None])[0] else None,
                compatibility=qs.get("compat", [None])[0],
                min_rating=float(qs.get("min_rating", ["0"])[0]),
                author=qs.get("author", [None])[0],
                sort=qs.get("sort", ["popular"])[0],
                page=int(qs.get("page", ["1"])[0]),
                per_page=int(qs.get("per_page", ["20"])[0]),
            )
            self._json_response(result)

        elif parsed.path == "/api/marketplace/featured":
            seed_marketplace(marketplace_store)
            collections = FeaturedCollections.get_collections(marketplace_store)
            self._json_response(collections)

        elif parsed.path == "/api/marketplace/installed":
            self._json_response(marketplace_store.get_installed())

        elif parsed.path == "/api/marketplace/my-items":
            qs = parse_qs(parsed.query)
            author = qs.get("author", ["User"])[0]
            items = marketplace_store.get_by_author(author)
            self._json_response([i.summary() for i in items])

        elif parsed.path.startswith("/api/marketplace/"):
            # GET /api/marketplace/<item_id> — item detail
            seed_marketplace(marketplace_store)
            item_id = parsed.path.split("/api/marketplace/")[1]
            item = marketplace_store.get(item_id)
            if not item:
                raise NotFoundError("Item not found", {"item_id": item_id})
            self._json_response(item.to_dict())

        # ── Collaboration GET routes ──────────────────────
        elif parsed.path.startswith("/api/collab/session/"):
            # GET /api/collab/session/<session_id> — session info + peers
            sid = parsed.path.split("/api/collab/session/")[1]
            info = collab_handler.get_session_info(sid)
            if info:
                self._json_response(info)
            else:
                self._json_response({"error": "Session not found"}, 404)

        elif parsed.path.startswith("/api/collab/poll/"):
            # GET /api/collab/poll/<session_id>?peer_id=xxx — poll for events
            parts = parsed.path.split("/api/collab/poll/")[1]
            qs = parse_qs(parsed.query)
            peer_id = qs.get("peer_id", [""])[0]
            if not peer_id:
                self._json_response({"error": "peer_id required"}, 400)
            else:
                events = collab_handler.poll_events(parts, peer_id)
                presence = collab_handler.presence.get_session_presence(parts)
                self._json_response({"events": events, "presence": presence})

        elif parsed.path.startswith("/api/collab/history/"):
            # GET /api/collab/history/<session_id> — edit history
            sid = parsed.path.split("/api/collab/history/")[1]
            qs = parse_qs(parsed.query)
            limit = int(qs.get("limit", ["50"])[0])
            peer_filter = qs.get("peer_id", [None])[0]
            timeline = collab_handler.history.get_timeline(sid, limit=limit,
                                                           peer_id=peer_filter)
            self._json_response(timeline)

        elif parsed.path == "/api/collab/sessions":
            # GET /api/collab/sessions — list all active sessions
            self._json_response(collab_handler.sessions.list_all())

        # ── Mobile PWA routes ─────────────────────────────
        elif parsed.path == "/api/mobile/dashboard":
            # Compact endpoint: devices + active telemetry in one call
            device_list = []
            active_telem = {}
            for did, d in devices.items():
                info = d.get_info()
                t = d.get_telemetry()
                info["battery"] = t.get("battery_pct", t.get("battery", None))
                info["status"] = "simulated" if info.get("simulated") else (
                    "connected" if info.get("connected") else "disconnected"
                )
                device_list.append(info)
                if not active_telem and t:
                    active_telem = {
                        "battery": t.get("battery_pct", t.get("battery")),
                        "altitude": t.get("altitude", t.get("position", {}).get("z", 0)),
                        "speed": t.get("speed", 0),
                        "signal": t.get("signal_strength", "good"),
                        "x": t.get("position", {}).get("x", 0),
                        "y": t.get("position", {}).get("y", 0),
                        "z": t.get("position", {}).get("z", 0),
                        "heading": t.get("heading", t.get("yaw", 0)),
                    }
            self._json_response({
                "devices": device_list,
                "telemetry": active_telem,
                "device_count": len(device_list),
                "timestamp": time.time(),
            })

        elif parsed.path in ("/mobile", "/mobile/", "/m", "/m/"):
            # Serve mobile app shell
            mobile_html = os.path.join(self.frontend_dir, "mobile", "mobile.html")
            if os.path.isfile(mobile_html):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                with open(mobile_html, "rb") as f:
                    content = f.read()
                self.send_header("Content-Length", len(content))
                self.end_headers()
                self.wfile.write(content)
            else:
                self._json_response({"error": "Mobile app not found"}, 404)

        elif parsed.path.startswith("/mobile/"):
            # Serve mobile static assets (manifest, icons, sw.js)
            rel_path = parsed.path[len("/mobile/"):]
            file_path = os.path.join(self.frontend_dir, "mobile", rel_path)
            if os.path.isfile(file_path) and ".." not in rel_path:
                ext = os.path.splitext(file_path)[1].lower()
                content_types = {
                    ".json": "application/json",
                    ".js": "application/javascript",
                    ".png": "image/png",
                    ".svg": "image/svg+xml",
                    ".ico": "image/x-icon",
                    ".webmanifest": "application/manifest+json",
                }
                ctype = content_types.get(ext, "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                # Allow service worker to control /mobile scope
                if rel_path == "sw.js":
                    self.send_header("Service-Worker-Allowed", "/mobile")
                with open(file_path, "rb") as f:
                    content = f.read()
                self.send_header("Content-Length", len(content))
                self.end_headers()
                self.wfile.write(content)
            else:
                self._json_response({"error": "Not found"}, 404)

        # ── Sensor Dashboard Endpoints (GET) ──

        elif parsed.path.startswith("/api/sensors/") and "/alerts" not in parsed.path and "/history" not in parsed.path:
            # GET /api/sensors/<device_id> — all sensors with current values
            parts = parsed.path.split("/")
            if len(parts) >= 4:
                device_id = parts[3]
                # Tick the simulator to get fresh readings
                sensor_simulator.tick(device_id)
                # Check alerts
                for s in sensor_registry.get_device_sensors(device_id):
                    alert_manager.check_sensor(
                        device_id, s["id"], s["name"], s["current_value"])
                sensors = sensor_registry.get_device_sensors(device_id)
                # Update sensor statuses based on active alerts
                active = alert_manager.get_active_alerts(device_id)
                alert_sensor_ids = {a["sensor_id"] for a in active}
                for s in sensors:
                    if s["id"] in alert_sensor_ids:
                        s["status"] = "alert"
                        sensor_registry.update_status(device_id, s["id"], "alert")
                    else:
                        sensor_registry.update_status(device_id, s["id"], "normal")
                self._json_response({
                    "device_id": device_id,
                    "sensors": sensors,
                    "active_alerts": active,
                    "timestamp": time.time(),
                })
            else:
                self._json_response({"error": "Device ID required"}, 400)

        elif parsed.path.endswith("/history"):
            # GET /api/sensors/<device_id>/<sensor_id>/history
            parts = parsed.path.split("/")
            if len(parts) >= 5:
                device_id = parts[3]
                sensor_id = parts[4]
                qs = parse_qs(parsed.query)
                last_n = int(qs.get("last_n", [500])[0])
                history = sensor_registry.get_sensor_history(device_id, sensor_id, last_n)
                ch = sensor_registry.get_sensor(device_id, sensor_id)
                self._json_response({
                    "device_id": device_id,
                    "sensor_id": sensor_id,
                    "sensor_name": ch.name if ch else sensor_id,
                    "unit": ch.unit if ch else "",
                    "history": history,
                    "count": len(history),
                })
            else:
                self._json_response({"error": "Bad path"}, 400)

        elif parsed.path.endswith("/alerts") and parsed.path.startswith("/api/sensors/"):
            # GET /api/sensors/<device_id>/alerts — list alerts with status
            parts = parsed.path.split("/")
            device_id = parts[3]
            qs = parse_qs(parsed.query)
            state_filter = qs.get("state", [None])[0]
            alerts = alert_manager.get_alerts(device_id, state=state_filter)
            rules = alert_manager.get_rules(device_id)
            self._json_response({
                "device_id": device_id,
                "alerts": alerts,
                "rules": rules,
            })

        elif parsed.path.startswith("/api/sensors-export/"):
            # GET /api/sensors-export/<device_id> — CSV export
            parts = parsed.path.split("/")
            device_id = parts[3] if len(parts) >= 4 else ""
            qs = parse_qs(parsed.query)
            sensor_id = qs.get("sensor_id", [None])[0]
            csv_data = sensor_registry.export_csv(device_id, sensor_id)
            body = csv_data.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Disposition",
                             f"attachment; filename=sensors_{device_id[:8]}.csv")
            self.send_header("Content-Length", len(body))
            cors_middleware.apply_headers(self)
            self.end_headers()
            self.wfile.write(body)
            return

        # ── Video endpoints ──

        elif parsed.path == "/api/video/sources":
            sources = video_manager.list_sources()
            self._json_response({"sources": sources})

        elif parsed.path.startswith("/api/video/stream/"):
            # MJPEG stream — multipart/x-mixed-replace
            device_id = parsed.path.split("/api/video/stream/")[1]
            src = video_manager.get_source(device_id)
            if not src:
                # Auto-create simulated source if device exists
                dev = devices.get(device_id)
                if dev:
                    tele_fn = lambda d=dev: d.get_telemetry()
                    video_manager.add_simulated(device_id, dev.device_type, tele_fn)
                    video_manager.start(device_id)
                    src = video_manager.get_source(device_id)
                else:
                    self._json_response({"error": "Device not found"}, 404)
                    return

            if not src._running:
                video_manager.start(device_id)
                time.sleep(0.15)  # Let first frame render

            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            cors_middleware.apply_headers(self)
            self.end_headers()

            try:
                target_dt = 1.0 / max(1, src.config.target_fps)
                while True:
                    frame = src.get_frame()
                    if frame:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(frame)}\r\n".encode())
                        self.wfile.write(b"\r\n")
                        self.wfile.write(frame)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                    time.sleep(target_dt)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass  # Client disconnected

        elif parsed.path.startswith("/api/video/snapshot/"):
            device_id = parsed.path.split("/api/video/snapshot/")[1]
            src = video_manager.get_source(device_id)
            if not src:
                dev = devices.get(device_id)
                if dev:
                    tele_fn = lambda d=dev: d.get_telemetry()
                    video_manager.add_simulated(device_id, dev.device_type, tele_fn)
                    video_manager.start(device_id)
                    time.sleep(0.2)
                    src = video_manager.get_source(device_id)
                else:
                    self._json_response({"error": "Device not found"}, 404)
                    return

            frame = src.get_frame() if src else None
            if frame:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", len(frame))
                self.send_header("Cache-Control", "no-cache")
                cors_middleware.apply_headers(self)
                self.end_headers()
                self.wfile.write(frame)
            else:
                self._json_response({"error": "No frame available"}, 503)

        # ── OTA Firmware Endpoints (GET) ──

        elif parsed.path == "/api/ota/firmware":
            # List all firmware
            firmware_list = ota_manager.list_firmware()
            self._json_response({"firmware": firmware_list})

        elif parsed.path.startswith("/api/ota/firmware/check"):
            # ESP32 update check: /api/ota/firmware/check?platform=esp32&current_version=1.0.0
            qs = parse_qs(parsed.query)
            platform = qs.get("platform", [""])[0]
            current_version = qs.get("current_version", [""])[0]
            if not platform:
                self._json_response({"update_available": False, "error": "platform required"})
                return
            all_fw = ota_manager.list_firmware()
            # Find newest firmware for this platform that's newer than current
            for fw in all_fw:
                if fw.get("platform") == platform and fw.get("type") != "source":
                    if fw.get("version", "") != current_version:
                        self._json_response({
                            "update_available": True,
                            "firmware_id": fw["id"],
                            "version": fw["version"],
                            "download_url": f"/api/ota/firmware/{fw['id']}/download",
                            "checksum": fw.get("checksum", ""),
                            "file_size": fw.get("file_size", 0),
                        })
                        return
            self._json_response({"update_available": False})

        elif parsed.path.startswith("/api/ota/firmware/") and parsed.path.endswith("/download"):
            # Download firmware binary: /api/ota/firmware/<id>/download
            parts = parsed.path.split("/")
            fw_id = parts[4] if len(parts) >= 6 else ""
            binary = ota_manager.get_firmware_binary(fw_id)
            if binary:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", len(binary))
                self.send_header("Content-Disposition", f'attachment; filename="{fw_id}.bin"')
                cors_middleware.apply_headers(self)
                secure_headers.apply(self)
                self.end_headers()
                self.wfile.write(binary)
            else:
                meta = ota_manager.get_firmware(fw_id)
                if meta and meta.get("type") == "source":
                    self._json_response({"error": "Source firmware cannot be downloaded as binary. Compile first."}, 400)
                else:
                    self._json_response({"error": "Firmware not found"}, 404)

        elif parsed.path.startswith("/api/ota/deploy/") and parsed.path.endswith("/status"):
            # Get deployment status: /api/ota/deploy/<device_id>/status
            parts = parsed.path.split("/")
            device_id = parts[4] if len(parts) >= 6 else ""
            status = ota_deployer.get_status(device_id)
            if status:
                self._json_response(status)
            else:
                self._json_response({"status": "none", "device_id": device_id})

        elif parsed.path == "/api/ota/builder/status":
            # Check if arduino-cli is available
            self._json_response({
                "available": firmware_builder.is_available(),
                "boards": firmware_builder.list_boards() if firmware_builder.is_available() else [],
            })

        # ── Swarm Coordination GET routes ──────────────────
        elif parsed.path == "/api/swarm/groups":
            self._json_response({"ok": True, "groups": swarm_coordinator.list_groups()})

        elif parsed.path.startswith("/api/swarm/groups/") and parsed.path.endswith("/status"):
            gid = parsed.path.split("/api/swarm/groups/")[1].rsplit("/status")[0]
            self._json_response(swarm_coordinator.group_status(gid, devices))

        elif parsed.path == "/api/swarm/formations":
            self._json_response({
                "ok": True,
                "formations": {k: f.to_dict() for k, f in FORMATIONS.items()},
            })

        elif parsed.path == "/api/swarm/missions":
            self._json_response({"ok": True, "templates": MISSION_TEMPLATES})

        elif parsed.path.startswith("/api/swarm/mission/"):
            mid = parsed.path.split("/api/swarm/mission/")[1]
            m = swarm_coordinator.get_mission(mid)
            if m:
                self._json_response({"ok": True, "mission": m})
            else:
                self._json_response({"ok": False, "error": "mission not found"}, status=404)

        # ── AI Enhancement GET routes ────────────────────────
        elif parsed.path == "/api/ai/models":
            models = ai_model_registry.list_models()
            self._json_response({
                "models": [m.to_dict() for m in models],
                "total": len(models),
            })
            return

        elif parsed.path.startswith("/api/ai/knowledge/"):
            device_id = parsed.path.split("/api/ai/knowledge/")[1]
            if device_id not in devices:
                raise NotFoundError(f"Device {device_id} not found")
            knowledge = ai_knowledge_base.get_knowledge(device_id)
            self._json_response(knowledge.to_dict() if knowledge else {
                "device_id": device_id,
                "analyses": [],
                "learned_params": {},
                "performance_history": [],
                "capabilities_inferred": [],
                "description_ai": "",
                "mesh_suggestions": [],
            })
            return

        else:
            # Auto-redirect mobile user-agents to mobile PWA from root
            if parsed.path == "/" and self._is_mobile_ua():
                self.send_response(302)
                self.send_header("Location", "/mobile")
                self.end_headers()
                return
            # Serve static files
            super().do_GET()

    def _do_post(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        # Cap body size to protect against accidental huge uploads
        if content_length > settings.max_request_size:
            raise ValidationError("Request body too large",
                                  {"content_length": content_length,
                                   "max": settings.max_request_size})
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON body: {e}") from e

        # ── Auth endpoints ──

        if parsed.path == "/api/auth/register":
            from omnix.auth.auth import AuthError
            try:
                result = auth_manager.register(
                    username=sanitize_string(data.get("username", ""), 32, strip_html=False),
                    password=data.get("password", ""),
                    email=sanitize_string(data.get("email", ""), 128, strip_html=False),
                    display_name=sanitize_string(data.get("display_name", ""), 64),
                )
                self._json_response(result, 201)
            except AuthError as e:
                self._json_response(
                    {"error": {"code": "auth_error", "message": e.message}},
                    e.status,
                )
            return

        elif parsed.path == "/api/auth/login":
            from omnix.auth.auth import AuthError
            try:
                result = auth_manager.login(
                    username=data.get("username", ""),
                    password=data.get("password", ""),
                )
                self._json_response(result)
            except AuthError as e:
                self._json_response(
                    {"error": {"code": "auth_error", "message": e.message}},
                    e.status,
                )
            return

        elif parsed.path == "/api/auth/refresh":
            refresh_token = data.get("refresh_token", "")
            result = auth_manager.refresh_access_token(refresh_token)
            if result:
                self._json_response(result)
            else:
                self._json_response(
                    {"error": {"code": "invalid_token", "message": "Invalid or expired refresh token"}},
                    401,
                )
            return

        # ── Simulated Device Commands ──

        elif parsed.path == "/api/command":
            device_id = data.get("device_id")
            command = data.get("command")
            params = data.get("params", {})
            if device_id not in devices:
                self._json_response({"error": f"Device not found: {device_id}"}, 404)
                return
            result = devices[device_id].execute_command(command, params)
            self._json_response(result)

        elif parsed.path == "/api/add_device":
            dtype = data.get("device_type", "smart_light")
            name = data.get("name", f"New {dtype}")
            device_map = {
                "drone": SimulatedDrone,
                "robot_arm": SimulatedRobotArm,
                "smart_light": SimulatedSmartLight,
            }
            if dtype in device_map:
                device = device_map[dtype](name=name)
                add_device(device)
                self._json_response(device.get_info())
            else:
                self._json_response({"error": f"Unknown type: {dtype}"}, 400)

        elif parsed.path == "/api/remove_device":
            device_id = data.get("device_id")
            if device_id in devices:
                del devices[device_id]
                workspace_store.drop(device_id)
                self._json_response({"success": True})
            else:
                self._json_response({"error": "Not found"}, 404)

        elif parsed.path == "/api/rename_device":
            device_id = data.get("device_id")
            new_name = (data.get("name") or "").strip()
            if not new_name:
                self._json_response({"error": "Name cannot be empty"}, 400)
                return
            if device_id in devices:
                devices[device_id].name = new_name
                self._json_response({"success": True, "name": new_name})
            else:
                self._json_response({"error": "Not found"}, 404)

        elif parsed.path == "/api/device-store/rename":
            profile_id = data.get("profile_id")
            if device_store.rename(
                profile_id,
                new_name=data.get("name"),
                new_description=data.get("description"),
                new_category=data.get("category"),
            ):
                self._json_response({"success": True})
            else:
                self._json_response({"error": "Profile not found"}, 404)

        elif parsed.path == "/api/vpe/lookup":
            # Enrich a classification using Wikipedia's free summary API
            query = (data.get("query") or "").strip()
            if not query:
                self._json_response({"error": "No query"}, 400)
                return
            try:
                result = _wikipedia_lookup(query)
                self._json_response(result)
            except Exception as e:
                self._json_response({"error": str(e), "found": False}, 200)

        # ── Movement Endpoints ──

        elif parsed.path == "/api/movements/execute":
            device_id = data.get("device_id")
            preset_name = data.get("preset_name")
            if not device_id or not preset_name:
                self._json_response({"error": "Provide device_id and preset_name"}, 400)
                return
            if movement_executor:
                result = movement_executor.execute_preset(device_id, preset_name)
                self._json_response(result)
            else:
                self._json_response({"error": "Movement executor not initialized"}, 500)

        elif parsed.path == "/api/movements/stop":
            device_id = data.get("device_id")
            if movement_executor:
                result = movement_executor.stop_execution(device_id)
                self._json_response(result)
            else:
                self._json_response({"error": "Movement executor not initialized"}, 500)

        # ── VPE Analyze + Auto-Store ──

        elif parsed.path == "/api/vpe/analyze":
            image_b64 = data.get("image")
            if not image_b64:
                self._json_response({"error": "No image provided"}, 400)
                return
            try:
                result = vpe_engine.analyze_base64(image_b64)

                # Generate 3D mesh from analysis
                mesh_params = generate_mesh(
                    result["classification"],
                    result["image_analysis"],
                    result["physics"],
                )
                result["mesh_params"] = mesh_params

                # Auto-store in device store
                # Extract small thumbnail (first 200 chars of base64 for identification)
                thumb = image_b64[:200] if len(image_b64) > 200 else image_b64
                profile = device_store.store(result, mesh_params, image_b64)
                result["profile_id"] = profile["id"]
                result["is_active_device"] = profile["id"] == device_store.active_id

                self._json_response(result)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._json_response({"error": f"Analysis failed: {str(e)}"}, 500)

        # ── VPE Simulated Scan ──

        elif parsed.path == "/api/vpe/simulate":
            device_type_hint = data.get("device_type")
            try:
                result = vpe_engine.simulate_scan(device_type_hint)
                mesh_params = generate_mesh(
                    result["classification"],
                    result["image_analysis"],
                    result["physics"],
                )
                result["mesh_params"] = mesh_params
                profile = device_store.store(result, mesh_params)
                result["profile_id"] = profile["id"]
                result["is_active_device"] = profile["id"] == device_store.active_id
                self._json_response(result)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._json_response({"error": f"Simulated scan failed: {str(e)}"}, 500)

        # ── VPE Multi-Image (add image to existing profile) ──

        elif parsed.path == "/api/vpe/add-image":
            image_b64 = data.get("image")
            profile_id = data.get("profile_id")
            if not image_b64 or not profile_id:
                self._json_response({"error": "Provide image and profile_id"}, 400)
                return
            try:
                result = vpe_engine.analyze_base64(image_b64)
                mesh_params = generate_mesh(
                    result["classification"],
                    result["image_analysis"],
                    result["physics"],
                )
                updated = device_store.update_with_image(profile_id, result, mesh_params)
                if updated:
                    result["profile_id"] = profile_id
                    result["image_count"] = updated["image_count"]
                    result["mesh_params"] = mesh_params
                    self._json_response(result)
                else:
                    self._json_response({"error": "Profile not found"}, 404)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._json_response({"error": f"Analysis failed: {str(e)}"}, 500)

        # ── Device Store Management ──

        elif parsed.path == "/api/device-store/set-active":
            profile_id = data.get("profile_id")
            if device_store.set_active(profile_id):
                self._json_response({"success": True, "active_id": profile_id})
            else:
                self._json_response({"error": "Profile not found"}, 404)

        elif parsed.path == "/api/device-store/remove":
            profile_id = data.get("profile_id")
            if device_store.remove(profile_id):
                self._json_response({"success": True})
            else:
                self._json_response({"error": "Not found"}, 404)

        # ── Pi Agent Endpoints (POST) ──

        elif parsed.path == "/api/pi/register":
            # Pi agent registers itself
            agent_id = str(uuid.uuid4())[:8]
            device_id = f"pi-{agent_id}"
            pi_agents[agent_id] = {
                "device_id": device_id,
                "name": data.get("name", "Pi Device"),
                "device_type": data.get("device_type", "ground_robot"),
                "capabilities": data.get("capabilities", []),
                "hardware": data.get("hardware", {}),
                "description": data.get("description", ""),
                "registered_at": time.time(),
                "is_pi": True,
            }
            pi_command_queues[agent_id] = []
            log.info("Pi agent registered: %s agent=%s device=%s",
                     data.get('name'), agent_id, device_id,
                     extra={"agent_id": agent_id, "device_id": device_id})
            self._json_response({
                "agent_id": agent_id,
                "device_id": device_id,
                "message": "Registered successfully",
            })

        elif parsed.path.startswith("/api/pi/telemetry/"):
            # Pi agent sends telemetry
            agent_id = parsed.path.split("/")[-1]
            if agent_id in pi_agents:
                pi_telemetry[agent_id] = {
                    "device_id": data.get("device_id"),
                    "telemetry": data.get("telemetry", {}),
                    "timestamp": data.get("timestamp", time.time()),
                }
                self._json_response({"success": True})
            else:
                self._json_response({"error": "Agent not found"}, 404)

        elif parsed.path == "/api/pi/send-command":
            # Frontend sends command to a Pi agent
            agent_id = data.get("agent_id")
            command = data.get("command")
            params = data.get("params", {})
            if agent_id not in pi_agents:
                self._json_response({"error": "Agent not found"}, 404)
                return
            cmd_id = str(uuid.uuid4())[:8]
            pi_command_queues.setdefault(agent_id, []).append({
                "id": cmd_id,
                "command": command,
                "params": params,
                "timestamp": time.time(),
            })
            self._json_response({"success": True, "command_id": cmd_id})

        elif parsed.path.startswith("/api/pi/command-result/"):
            # Pi agent reports command result
            agent_id = parsed.path.split("/")[-1]
            cmd_id = data.get("command_id")
            result = data.get("result", {})
            if cmd_id:
                pi_command_results[cmd_id] = {
                    "agent_id": agent_id,
                    "result": result,
                    "timestamp": time.time(),
                }
            self._json_response({"success": True})

        elif parsed.path.startswith("/api/pi/deregister/"):
            # Pi agent disconnects
            agent_id = parsed.path.split("/")[-1]
            if agent_id in pi_agents:
                name = pi_agents[agent_id]["name"]
                del pi_agents[agent_id]
                pi_command_queues.pop(agent_id, None)
                pi_telemetry.pop(agent_id, None)
                log.info("Pi agent deregistered: %s (agent=%s)", name, agent_id,
                         extra={"agent_id": agent_id})
                self._json_response({"success": True})
            else:
                self._json_response({"error": "Agent not found"}, 404)

        # ── Connector Endpoints (POST) ──

        elif parsed.path == "/api/connectors/start":
            connector_id = data.get("connector_id")
            config = data.get("config", {})
            if not connector_id:
                self._json_response({"error": "connector_id required"}, 400)
                return
            result = connector_manager.start_instance(connector_id, config)
            if not result.get("ok"):
                self._json_response(result, 400)
            else:
                log.info("connector started: %s instance=%s devices=%d",
                         connector_id, result['status']['instance_id'],
                         result['status']['device_count'],
                         extra={"connector_id": connector_id,
                                "instance_id": result['status']['instance_id']})
                self._json_response(result)

        elif parsed.path == "/api/connectors/stop":
            instance_id = data.get("instance_id")
            if not instance_id:
                self._json_response({"error": "instance_id required"}, 400)
                return
            result = connector_manager.stop_instance(instance_id)
            if result.get("ok"):
                log.info("connector stopped: %s", instance_id,
                         extra={"instance_id": instance_id})
            status_code = 200 if result.get("ok") else 404
            self._json_response(result, status_code)

        elif parsed.path == "/api/connectors/reload-registry":
            if connector_manager:
                connector_manager.reload_registry()
                self._json_response({"success": True})
            else:
                self._json_response({"error": "Manager not ready"}, 500)

        # ── Plugin Endpoints (POST) ──

        elif parsed.path == "/api/plugins/reload":
            if plugin_registry and plugin_loader:
                results = plugin_registry.reload_all(plugin_loader)
                self._json_response({"success": True, "results": results})
            else:
                self._json_response({"error": "Plugin system not ready"}, 500)

        elif parsed.path.startswith("/api/plugins/enable/"):
            name = parsed.path.split("/")[-1]
            if plugin_registry:
                ok = plugin_registry.enable_plugin(name)
                self._json_response({"success": ok, "plugin": name})
            else:
                self._json_response({"error": "Plugin system not ready"}, 500)

        elif parsed.path.startswith("/api/plugins/disable/"):
            name = parsed.path.split("/")[-1]
            if plugin_registry:
                ok = plugin_registry.disable_plugin(name)
                self._json_response({"success": ok, "plugin": name})
            else:
                self._json_response({"error": "Plugin system not ready"}, 500)

        # ── ESP32 Agent Endpoints (POST) ──

        elif parsed.path == "/api/esp32/register":
            agent_id = uuid.uuid4().hex[:8]
            device_id = f"esp32-{agent_id}"
            _ESP32_AGENTS[agent_id] = {
                "device_id": device_id,
                "name": data.get("name", "ESP32"),
                "board_type": data.get("board_type", "lights"),
                "mac": data.get("mac", ""),
                "capabilities": data.get("capabilities", []),
                "ip": data.get("ip", ""),
                "registered_at": time.time(),
                "simulated": False,
            }
            _ESP32_COMMAND_QUEUES[agent_id] = []
            log.info("ESP32 registered: %s agent=%s mac=%s",
                     data.get('name'), agent_id, data.get('mac', '?'),
                     extra={"agent_id": agent_id, "mac": data.get("mac")})
            self._json_response({
                "agent_id": agent_id,
                "device_id": device_id,
                "message": "Registered",
            })

        elif parsed.path.startswith("/api/esp32/telemetry/"):
            agent_id = parsed.path.split("/")[-1]
            if agent_id in _ESP32_AGENTS:
                _ESP32_TELEMETRY[agent_id] = {
                    "telemetry": data.get("telemetry", {}),
                    "ts": time.time(),
                }
                self._json_response({"success": True})
            else:
                self._json_response({"error": "Unknown agent"}, 404)

        elif parsed.path.startswith("/api/esp32/deregister/"):
            agent_id = parsed.path.split("/")[-1]
            if agent_id in _ESP32_AGENTS:
                name = _ESP32_AGENTS[agent_id].get("name", agent_id)
                _ESP32_AGENTS.pop(agent_id, None)
                _ESP32_COMMAND_QUEUES.pop(agent_id, None)
                _ESP32_TELEMETRY.pop(agent_id, None)
                log.info("ESP32 deregistered: %s (agent=%s)", name, agent_id,
                         extra={"agent_id": agent_id})
                self._json_response({"success": True})
            else:
                self._json_response({"error": "Unknown agent"}, 404)

        # ── OTA Firmware Endpoints (POST) ──

        elif parsed.path == "/api/ota/firmware/upload":
            # Upload firmware binary — accepts JSON with base64-encoded binary
            # {name, version, platform, binary_b64, description?, compatible_devices?}
            import base64
            name = data.get("name", "").strip()
            version = data.get("version", "").strip()
            platform = data.get("platform", "").strip()
            binary_b64 = data.get("binary_b64", "")
            description = data.get("description", "")
            compatible_devices = data.get("compatible_devices", [])

            if not name or not version or not platform:
                self._json_response(
                    {"error": "name, version, and platform are required"}, 400)
                return
            if not binary_b64:
                self._json_response(
                    {"error": "binary_b64 (base64-encoded firmware binary) is required"}, 400)
                return

            try:
                binary_data = base64.b64decode(binary_b64)
            except Exception:
                self._json_response({"error": "Invalid base64 data"}, 400)
                return

            try:
                result = ota_manager.upload_firmware(
                    name=name, version=version, platform=platform,
                    binary_data=binary_data, description=description,
                    compatible_devices=compatible_devices,
                )
                self._json_response({"ok": True, "firmware": result}, 201)
            except ValueError as e:
                self._json_response({"error": str(e)}, 400)

        elif parsed.path.startswith("/api/ota/deploy/") and parsed.path.endswith("/progress"):
            # ESP32 reports deployment progress: /api/ota/deploy/<device_id>/progress
            parts = parsed.path.split("/")
            device_id = parts[4] if len(parts) >= 6 else ""
            status = data.get("status", "")
            progress = data.get("progress_pct", 0)
            error = data.get("error", "")
            if device_id:
                ota_deployer._update_state(device_id, status=status, progress=progress, error=error or None)
                self._json_response({"ok": True})
            else:
                self._json_response({"error": "device_id required"}, 400)

        elif parsed.path.startswith("/api/ota/deploy/"):
            # Start deployment: POST /api/ota/deploy/<device_id>
            parts = parsed.path.split("/")
            device_id = parts[4] if len(parts) >= 5 else ""
            firmware_id = data.get("firmware_id", "")
            if not device_id or not firmware_id:
                self._json_response(
                    {"error": "device_id (in URL) and firmware_id (in body) required"}, 400)
                return

            # Get device info for platform detection
            dev = devices.get(device_id)
            device_info = {}
            if dev:
                tele = dev.get_telemetry()
                device_info = {
                    "platform": tele.get("platform", dev.device_type),
                    "current_version": tele.get("fw_version", "unknown"),
                }

            try:
                result = ota_deployer.deploy(device_id, firmware_id, device_info)
                # For ESP32 devices, queue the OTA command
                for aid, info in _ESP32_AGENTS.items():
                    if info.get("device_id") == device_id or aid == device_id:
                        fw = ota_manager.get_firmware(firmware_id)
                        _ESP32_COMMAND_QUEUES.setdefault(aid, []).append({
                            "id": uuid.uuid4().hex[:8],
                            "command": "ota_update",
                            "params": {
                                "firmware_id": firmware_id,
                                "download_url": f"/api/ota/firmware/{firmware_id}/download",
                                "version": fw.get("version", "") if fw else "",
                                "checksum": fw.get("checksum", "") if fw else "",
                            },
                            "ts": time.time(),
                        })
                        break

                self._json_response({"ok": True, "deployment": result})
            except ValueError as e:
                self._json_response({"error": str(e)}, 400)

        elif parsed.path.startswith("/api/ota/rollback/"):
            # Rollback: POST /api/ota/rollback/<device_id>
            parts = parsed.path.split("/")
            device_id = parts[4] if len(parts) >= 5 else ""
            if not device_id:
                self._json_response({"error": "device_id required"}, 400)
                return
            try:
                result = ota_deployer.rollback(device_id)
                self._json_response({"ok": True, "deployment": result})
            except ValueError as e:
                self._json_response({"error": str(e)}, 400)

        elif parsed.path.startswith("/api/ota/firmware/") and not parsed.path.endswith("/download"):
            # DELETE firmware: handled as POST /api/ota/firmware/<id>/delete
            parts = parsed.path.split("/")
            fw_id = parts[4] if len(parts) >= 5 else ""
            if parsed.path.endswith("/delete"):
                fw_id = parts[4] if len(parts) >= 6 else ""
                if ota_manager.delete_firmware(fw_id):
                    self._json_response({"ok": True})
                else:
                    self._json_response({"error": "Firmware not found"}, 404)
            elif parsed.path.endswith("/compile"):
                # Compile source firmware: POST /api/ota/firmware/<id>/compile
                fw_id = parts[4] if len(parts) >= 6 else ""
                fw = ota_manager.get_firmware(fw_id)
                if not fw:
                    self._json_response({"error": "Firmware not found"}, 404)
                    return
                if not firmware_builder.is_available():
                    self._json_response({"error": "arduino-cli not installed"}, 503)
                    return
                sketch_path = fw.get("sketch_path", "")
                board_fqbn = data.get("board_fqbn", "esp32:esp32:esp32")
                if sketch_path:
                    result = firmware_builder.compile(sketch_path, board_fqbn)
                    self._json_response(result)
                else:
                    self._json_response({"error": "No sketch path for this firmware"}, 400)
            else:
                self._json_response({"error": "Unknown OTA firmware action"}, 400)

        # ── Workspace Endpoints (POST) ──

        elif parsed.path.startswith("/api/workspaces/"):
            parts = parsed.path.split("/")
            if len(parts) < 5:
                self._json_response({"error": "Bad workspace path"}, 400)
                return
            device_id = parts[3]
            dev = devices.get(device_id)
            if dev is None:
                self._json_response({"error": "Device not found"}, 404)
                return
            ws = workspace_store.ensure(dev)
            sub = parts[4]

            if sub == "meta":
                # Update notes / tags / color / name / connector_info
                workspace_store.update_meta(
                    device_id,
                    name=data.get("name"),
                    notes=data.get("notes"),
                    tags=data.get("tags"),
                    color=data.get("color"),
                    connector_info=data.get("connector_info"),
                )
                # If name was changed, also update the device
                if data.get("name"):
                    dev.name = data["name"].strip() or dev.name
                self._json_response({"success": True})
                return

            if sub == "world":
                workspace_store.update_world(device_id, data.get("world", {}))
                self._json_response({"success": True, "world": ws["world"]})
                return

            if sub == "iterations":
                # Create a new iteration — runs the scenario
                scenario = data.get("scenario")
                param_override = data.get("params") or {}
                note = data.get("note", "")
                if not scenario:
                    self._json_response({"error": "scenario required"}, 400)
                    return
                try:
                    iteration = run_scenario(
                        ws, scenario, param_override=param_override,
                        note=note, workspace_store=workspace_store,
                    )
                    self._json_response(iteration)
                except ValueError as e:
                    self._json_response({"error": str(e)}, 400)
                except Exception as e:
                    import traceback; traceback.print_exc()
                    self._json_response({"error": f"simulation failed: {e}"}, 500)
                return

            if sub == "reset-physics":
                workspace_store.set_physics(device_id, None)
                self._json_response({"success": True})
                return

            if sub == "iteration-note":
                iter_id = data.get("iteration_id")
                note = data.get("note", "")
                updated = workspace_store.update_iteration(device_id, iter_id, {"note": note})
                if updated:
                    self._json_response({"success": True})
                else:
                    self._json_response({"error": "Iteration not found"}, 404)
                return

            if sub == "custom-build":
                if not isinstance(dev, CustomRobotDevice):
                    raise ValidationError(
                        "Device is not a custom-build device — only custom "
                        "robots support in-place build edits.",
                        {"device_id": device_id, "device_type": dev.device_type})
                build_dict = data.get("build") or data
                try:
                    build = CustomBuild.from_dict(build_dict)
                except Exception as e:
                    raise ValidationError(f"Invalid build payload: {e}") from e
                dev.update_build(build)
                # Sync the workspace's device_type in case it flipped
                if ws.get("device_type") != dev.device_type:
                    ws["device_type"] = dev.device_type
                workspace_store.set_custom_build(device_id, build.to_dict())
                self._json_response({
                    "ok": True,
                    "device": dev.get_info(),
                    "build": build.to_dict(),
                })
                return

            self._json_response({"error": f"Unknown workspace action '{sub}'"}, 400)
            return

        elif parsed.path.startswith("/api/workspace-iteration-delete/"):
            # DELETE semantics via POST since some corporate proxies strip DELETE
            parts = parsed.path.split("/")
            if len(parts) >= 5:
                device_id = parts[3]
                iter_id = parts[4]
                if workspace_store.remove_iteration(device_id, iter_id):
                    self._json_response({"success": True})
                else:
                    self._json_response({"error": "Not found"}, 404)
                return
            self._json_response({"error": "Bad path"}, 400)

        # ── Template + Custom Build Endpoints (POST) ──

        elif parsed.path == "/api/templates/instantiate":
            """Create a new CustomRobotDevice from a template and auto-open
            a workspace for it."""
            template_id = data.get("template_id")
            custom_name = (data.get("name") or "").strip()
            tpl = get_template(template_id) if template_id else None
            if not tpl:
                raise ValidationError(
                    f"Unknown template '{template_id}'",
                    {"template_id": template_id})
            build = tpl.instantiate()
            name = custom_name or tpl.display_name
            dev = CustomRobotDevice(name=name, build=build)
            add_device(dev)
            # Re-register sensors with template-specific set
            sensor_registry.unregister_device(dev.id)
            auto_register_sensors(sensor_registry, dev.id, dev.device_type, template_id=template_id)
            ws = workspace_store.ensure(dev)
            workspace_store.set_custom_build(
                dev.id, build.to_dict(), template_id=template_id)
            log.info("template instantiated: %s → %s (id=%s)",
                     template_id, name, dev.id,
                     extra={"template_id": template_id, "device_id": dev.id})
            self._json_response({
                "ok": True,
                "device": dev.get_info(),
                "workspace_id": ws["workspace_id"],
                "template_id": template_id,
            })

        # ── NLP pipeline (POST) ──

        elif parsed.path == "/api/nlp/compile":
            device_id = data.get("device_id")
            text = (data.get("text") or "").strip()
            if not device_id:
                raise ValidationError("device_id required")
            if not text:
                raise ValidationError("text required")
            dev = devices.get(device_id)
            if dev is None:
                raise NotFoundError("Device not found", {"device_id": device_id})
            caps = [c.get("name") for c in dev.get_capabilities() if c.get("name")]
            plan = compile_to_plan(text, device_id, dev.device_type, caps)
            try:
                tele = dev.get_telemetry() or {}
            except Exception:
                tele = {}
            plan_and_validate(plan, dev.device_type, telemetry=tele,
                              capability_names=caps)
            _push_history(device_id, text)
            self._json_response(plan.to_dict())

        elif parsed.path == "/api/nlp/execute":
            plan_dict = data.get("plan")
            if not plan_dict:
                raise ValidationError("plan required")
            try:
                plan = ExecutionPlan.from_dict(plan_dict)
            except Exception as e:
                raise ValidationError(f"Invalid plan: {e}") from e
            dev = devices.get(plan.device_id)
            if dev is None:
                raise NotFoundError("Device not found",
                                    {"device_id": plan.device_id})
            # Bridge completed runs into the workspace iteration log so NLP
            # plans show up alongside scenario runs in the lab notebook.
            def _on_iter(state):
                ws = workspace_store.get_by_device(state.device_id)
                if ws:
                    try:
                        workspace_store.append_iteration(
                            state.device_id, iteration_from_state(state))
                    except Exception:
                        log.exception("failed to append NLP iteration")
            try:
                state = nlp_registry.start(plan, dev, on_iteration=_on_iter)
            except RuntimeError as e:
                raise ConflictError(str(e)) from e
            log.info("nlp execution started: device=%s plan=%s steps=%d",
                     plan.device_id, plan.plan_id, len(plan.steps),
                     extra={"device_id": plan.device_id,
                            "plan_id": plan.plan_id})
            self._json_response(state.to_dict())

        elif parsed.path == "/api/nlp/stop":
            device_id = data.get("device_id")
            if not device_id:
                raise ValidationError("device_id required")
            ok = nlp_registry.stop(device_id, reason="user e-stop")
            self._json_response({"ok": bool(ok)})

        # ── Digital Twin (POST) ──

        elif parsed.path == "/api/twin/create":
            device_id = data.get("device_id")
            mode_str = data.get("mode", "twin")
            if not device_id:
                raise ValidationError("device_id required")
            dev = devices.get(device_id)
            if dev is None:
                raise NotFoundError("Device not found",
                                    {"device_id": device_id})
            try:
                mode = TwinMode(mode_str)
            except ValueError:
                raise ValidationError(
                    f"unknown twin mode '{mode_str}'. "
                    f"valid: {[m.value for m in TwinMode]}")
            ws = workspace_store.get_by_device(device_id)
            twin = twin_registry.create(dev, workspace=ws, mode=mode)
            log.info("twin created: device=%s mode=%s", device_id, mode.value,
                     extra={"device_id": device_id, "twin_mode": mode.value})
            self._json_response({"ok": True, "twin": twin.snapshot().to_dict()})

        elif parsed.path == "/api/twin/destroy":
            device_id = data.get("device_id")
            if not device_id:
                raise ValidationError("device_id required")
            ok = twin_registry.destroy(device_id)
            self._json_response({"ok": ok})

        elif parsed.path == "/api/twin/mode":
            device_id = data.get("device_id")
            mode_str = data.get("mode", "twin")
            twin = twin_registry.get(device_id) if device_id else None
            if twin is None:
                raise NotFoundError("Twin not found — create one first",
                                    {"device_id": device_id})
            try:
                mode = TwinMode(mode_str)
            except ValueError:
                raise ValidationError(
                    f"unknown twin mode '{mode_str}'")
            twin.set_mode(mode)
            self._json_response({"ok": True, "twin": twin.snapshot().to_dict()})

        elif parsed.path == "/api/twin/record":
            device_id = data.get("device_id")
            start = bool(data.get("start", True))
            label = data.get("label", "")
            twin = twin_registry.get(device_id) if device_id else None
            if twin is None:
                raise NotFoundError("Twin not found",
                                    {"device_id": device_id})
            if start:
                sess = twin.start_session(label=label)
                self._json_response({
                    "ok": True, "recording": True,
                    "session_id": sess.session_id,
                })
            else:
                finished = twin.stop_session()
                if finished:
                    twin_registry.add_session(finished)
                    self._json_response({
                        "ok": True, "recording": False,
                        "session": finished.summary(),
                    })
                else:
                    self._json_response({"ok": True, "recording": False,
                                         "session": None})

        elif parsed.path == "/api/twin/calibrate":
            device_id = data.get("device_id")
            twin = twin_registry.get(device_id) if device_id else None
            if twin is None:
                raise NotFoundError("Twin not found",
                                    {"device_id": device_id})
            dev = devices.get(device_id)
            if dev is None:
                raise NotFoundError("Device not found",
                                    {"device_id": device_id})

            # Start a session, then dispatch the calibration sequence
            # through the NLP executor so it shows up in the iteration log.
            info = twin.run_calibration()
            twin.start_session(label="calibration")

            plan = ExecutionPlan.new(device_id=device_id,
                                     text=f"calibrate {dev.device_type}")
            for cmd, params in info["sequence"]:
                step = plan.add_step(
                    command=cmd, params=params,
                    description=f"cal: {cmd}",
                    duration_s=1.2,
                )
            # Basic planner pass so waypoints are populated
            caps = [c.get("name") for c in dev.get_capabilities() if c.get("name")]
            plan_and_validate(plan, dev.device_type,
                              telemetry=dev.get_telemetry() or {},
                              capability_names=caps)

            def _after_cal(state):
                # Stop recording + add session for later tuning
                sess = twin.stop_session()
                if sess is not None:
                    twin_registry.add_session(sess)

            try:
                state = nlp_registry.start(plan, dev, on_iteration=_after_cal)
            except RuntimeError as e:
                raise ConflictError(str(e)) from e
            self._json_response({
                "ok": True, "execution": state.to_dict(),
                "sequence": info["sequence"],
            })

        elif parsed.path == "/api/twin/auto-tune":
            device_id = data.get("device_id")
            session_id = data.get("session_id")
            if not device_id:
                raise ValidationError("device_id required")
            dev = devices.get(device_id)
            if dev is None:
                raise NotFoundError("Device not found",
                                    {"device_id": device_id})
            session = None
            if session_id:
                session = twin_registry.get_session(session_id)
            else:
                # Pick the most recent completed session for this device
                for s in twin_registry.list_sessions():
                    if s["device_id"] == device_id and s.get("ended_at"):
                        session = twin_registry.get_session(s["session_id"])
                        break
            if session is None:
                raise NotFoundError(
                    "No session to tune from — record one first.")

            result = auto_tune(session, dev.device_type)
            ws = workspace_store.get_by_device(device_id)
            if ws is not None:
                apply_to_workspace(result, ws)
                # Also update the live twin's physics so the UI
                # sees the tuned params immediately.
                twin = twin_registry.get(device_id)
                if twin and twin.predictor.physics:
                    twin.predictor.physics.params.update(result.params_after)
                # Log as an iteration so Tuning shows up in the lab notebook
                try:
                    workspace_store.append_iteration(device_id, {
                        "scenario": "twin_auto_tune",
                        "scenario_display_name": f"🔗 Auto-tune from {session.label or 'session'}",
                        "scenario_icon": "🎯",
                        "duration_s": 0.1,
                        "params": {
                            "session_id": session.session_id,
                            "iterations": result.iterations,
                        },
                        "metrics": {
                            "overall": max(0.0, min(1.0,
                                1.0 - result.score_after / max(1e-9, result.score_before))),
                            "score_before": result.score_before,
                            "score_after": result.score_after,
                            "confidence_after": result.confidence_after,
                        },
                        "trajectory": [], "reference": [], "note": "",
                        "physics_after": {
                            "params": result.params_after,
                            "confidence": result.confidence_after,
                            "samples": int(ws.get("physics", {}).get("samples", 0)),
                            "last_updated": time.time(),
                            "fit_error": 0.0,
                        },
                        "timestamp": time.time(),
                    })
                except Exception:
                    log.exception("failed to record tune iteration")
            log.info("twin auto-tune: device=%s improved %.1f%%",
                     device_id,
                     (1 - result.score_after / max(1e-9, result.score_before)) * 100,
                     extra={"device_id": device_id})
            self._json_response({"ok": True, "result": result.to_dict()})

        elif parsed.path == "/api/custom-build/create":
            """Create a new empty CustomRobotDevice for scratch-builders."""
            name = (data.get("name") or "").strip() or "My Robot"
            build = CustomBuild()
            dev = CustomRobotDevice(name=name, build=build)
            add_device(dev)
            ws = workspace_store.ensure(dev)
            workspace_store.set_custom_build(dev.id, build.to_dict())
            log.info("custom build created: %s (id=%s)", name, dev.id,
                     extra={"device_id": dev.id})
            self._json_response({
                "ok": True,
                "device": dev.get_info(),
                "workspace_id": ws["workspace_id"],
            })

        # ── Behavior Tree POST routes ────────────────────
        elif parsed.path == "/api/bt/save":
            """Save (create or update) a behavior tree for a device."""
            device_id = data.get("device_id", "")
            tree_data = data.get("tree", {})
            tree_id = tree_data.get("tree_id", f"bt-{uuid.uuid4().hex[:10]}")
            tree_data["tree_id"] = tree_id
            tree_data["device_id"] = device_id
            tree_data["updated_at"] = time.time()
            if "created_at" not in tree_data:
                tree_data["created_at"] = time.time()
            _bt_store.setdefault(device_id, {})[tree_id] = tree_data
            log.info("bt saved: %s for device=%s", tree_data.get("name", ""), device_id)
            self._json_response({"ok": True, "tree_id": tree_id})

        elif parsed.path == "/api/bt/delete":
            """Delete a saved tree."""
            device_id = data.get("device_id", "")
            tree_id = data.get("tree_id", "")
            trees = _bt_store.get(device_id, {})
            if tree_id in trees:
                del trees[tree_id]
                self._json_response({"ok": True})
            else:
                raise NotFoundError("Tree not found", {"tree_id": tree_id})

        elif parsed.path == "/api/bt/execute":
            """Start executing a behavior tree."""
            device_id = data.get("device_id", "")
            tree_data = data.get("tree", {})
            try:
                tick_rate = float(data.get("tick_rate_hz", 5.0))
                if tick_rate <= 0 or tick_rate > 100:
                    raise ValueError("tick_rate_hz must be between 0.1 and 100")
            except (ValueError, TypeError) as e:
                raise ValidationError(f"Invalid tick_rate_hz: {e}") from e

            device = devices.get(device_id)
            if not device:
                raise NotFoundError("Device not found", {"device_id": device_id})

            tree = BT.from_dict(tree_data)
            tree.device_id = device_id

            record = bt_executor.start(
                tree, device,
                tick_rate_hz=tick_rate,
                workspace_store=workspace_store,
                twin_registry=twin_registry,
            )
            log.info("bt execution started: %s on %s", tree.name, device_id)
            self._json_response({"ok": True, "execution": record.to_dict()})

        elif parsed.path == "/api/bt/stop":
            """Stop a running behavior tree."""
            device_id = data.get("device_id", "")
            ok = bt_executor.stop(device_id)
            self._json_response({"ok": ok})

        elif parsed.path == "/api/bt/pause":
            device_id = data.get("device_id", "")
            ok = bt_executor.pause(device_id)
            self._json_response({"ok": ok})

        elif parsed.path == "/api/bt/resume":
            device_id = data.get("device_id", "")
            ok = bt_executor.resume(device_id)
            self._json_response({"ok": ok})

        elif parsed.path == "/api/bt/from-template":
            """Create a tree from a named template."""
            tpl_name = data.get("template", "")
            device_id = data.get("device_id", "")
            tpl = bt_get_template(tpl_name)
            if tpl is None:
                raise NotFoundError("Template not found", {"name": tpl_name})
            tree_data = {
                "tree_id": f"bt-{uuid.uuid4().hex[:10]}",
                "name": tpl["name"],
                "description": tpl["description"],
                "device_id": device_id,
                "root": tpl["root"],
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            _bt_store.setdefault(device_id, {})[tree_data["tree_id"]] = tree_data
            self._json_response({"ok": True, "tree": tree_data})

        elif parsed.path == "/api/bt/nlp-to-tree":
            """Convert natural language mission description to a behavior tree."""
            text = data.get("text", "")
            device_id = data.get("device_id", "")
            device = devices.get(device_id)
            if not device:
                raise NotFoundError("Device not found", {"device_id": device_id})
            tree_data = self._nlp_to_bt(text, device)
            self._json_response({"ok": True, "tree": tree_data})

        # ── Marketplace POST routes ──────────────────────
        elif parsed.path == "/api/marketplace/publish":
            """Publish content from a workspace to the marketplace."""
            seed_marketplace(marketplace_store)
            pub_type = data.get("type", "robot_build")
            title = data.get("title", "")
            description = data.get("description", "")
            author = data.get("author", "User")
            tags = data.get("tags", [])
            version = data.get("version", "1.0.0")

            try:
                if pub_type == "robot_build":
                    device_id = data.get("device_id", "")
                    ws = workspace_store.get_by_device(device_id)
                    if not ws:
                        raise NotFoundError("Workspace not found")
                    item = Publisher.publish_robot_build(
                        ws, title=title, description=description,
                        author=author, tags=tags, version=version)
                elif pub_type == "mission_template":
                    tree_data = data.get("tree", {})
                    item = Publisher.publish_mission(
                        tree_data, title=title, description=description,
                        author=author, tags=tags, version=version)
                elif pub_type == "physics_profile":
                    device_id = data.get("device_id", "")
                    ws = workspace_store.get_by_device(device_id)
                    if not ws:
                        raise NotFoundError("Workspace not found")
                    item = Publisher.publish_physics_profile(
                        ws, title=title, description=description,
                        author=author, tags=tags)
                else:
                    raise ValidationError(f"Unknown publish type: {pub_type}")

                marketplace_store.add(item)
                log.info("marketplace publish: %s by %s", title, author)
                self._json_response({"ok": True, "item": item.summary()})
            except PublishError as e:
                self._json_response({"ok": False, "error": str(e)}, 400)

        elif parsed.path.startswith("/api/marketplace/install/"):
            """Install a marketplace item."""
            item_id = parsed.path.split("/api/marketplace/install/")[1]
            device_id = data.get("device_id", "")
            try:
                result = marketplace_installer.install(
                    item_id,
                    devices_registry=devices,
                    workspace_store=workspace_store,
                    bt_store=_bt_store,
                    device_id=device_id,
                )
                self._json_response({"ok": True, "result": result})
            except InstallError as e:
                self._json_response({"ok": False, "error": str(e)}, 400)

        elif parsed.path.startswith("/api/marketplace/review/"):
            """Add a review to a marketplace item."""
            item_id = parsed.path.split("/api/marketplace/review/")[1]
            try:
                rating = int(data.get("rating", 5))
                if rating < 1 or rating > 5:
                    raise ValueError("rating must be between 1 and 5")
            except (ValueError, TypeError) as e:
                raise ValidationError(f"Invalid rating: {e}") from e
            comment = data.get("comment", "")
            author = data.get("author", "User")
            review = marketplace_store.add_review(item_id, rating, comment, author)
            if review:
                self._json_response({"ok": True, "review": review.to_dict()})
            else:
                raise NotFoundError("Item not found", {"item_id": item_id})

        elif parsed.path == "/api/marketplace/uninstall":
            item_id = data.get("item_id", "")
            result = marketplace_installer.uninstall(item_id)
            self._json_response({"ok": True, "result": result})

        # ── Collaboration POST routes ─────────────────────
        elif parsed.path == "/api/collab/create":
            owner_id = data.get("owner_id", f"user-{uuid.uuid4().hex[:6]}")
            owner_name = data.get("owner_name", "You")
            device_id = data.get("device_id")
            result = collab_handler.create_session(owner_id, owner_name, device_id)
            self._json_response(result)

        elif parsed.path == "/api/collab/join":
            code = data.get("code", "").strip().upper()
            peer_id = data.get("peer_id", f"user-{uuid.uuid4().hex[:6]}")
            peer_name = data.get("peer_name", "Guest")
            if not code:
                self._json_response({"error": "Share code required"}, 400)
            else:
                result = collab_handler.join_session(code, peer_id, peer_name)
                if result:
                    self._json_response(result)
                else:
                    self._json_response({"error": "Invalid share code"}, 404)

        elif parsed.path == "/api/collab/leave":
            session_id = data.get("session_id", "")
            peer_id = data.get("peer_id", "")
            ok = collab_handler.leave_session(session_id, peer_id)
            self._json_response({"ok": ok})

        elif parsed.path == "/api/collab/send":
            # Send a message/action to the session (change, cursor, chat, etc.)
            session_id = data.get("session_id", "")
            peer_id = data.get("peer_id", "")
            message = data.get("message", {})
            if not session_id or not peer_id:
                self._json_response({"error": "session_id and peer_id required"}, 400)
            else:
                resp = collab_handler.handle_message(session_id, peer_id, message)
                self._json_response(resp or {"ok": True})

        # ── Mobile command endpoint ────────────────────────
        elif parsed.path == "/api/mobile/command":
            device_id = data.get("device_id")
            command = data.get("command", "")
            params = data.get("params", {})
            if not device_id or device_id not in devices:
                self._json_response({"error": "Unknown device"}, 404)
            else:
                device = devices[device_id]
                # Map common mobile commands to device actions
                cmd_map = {
                    "takeoff": "takeoff",
                    "land": "land",
                    "return_home": "return_home",
                    "emergency_stop": "emergency_stop",
                    "hover": "hover",
                    "joystick": "joystick",
                    "dpad": "dpad",
                }
                mapped = cmd_map.get(command, command)
                try:
                    if hasattr(device, "execute_command"):
                        result = device.execute_command(mapped, params)
                    else:
                        result = {"status": "accepted", "command": mapped}
                    self._json_response({
                        "ok": True,
                        "command": mapped,
                        "device_id": device_id,
                        "result": result if isinstance(result, dict) else {"status": "ok"},
                        "timestamp": time.time(),
                    })
                except Exception as e:
                    self._json_response({"error": str(e)}, 500)

        # ── Sensor Dashboard POST routes ─────────────────────

        elif parsed.path.startswith("/api/sensors/") and parsed.path.endswith("/alerts"):
            # POST /api/sensors/<device_id>/alerts — create/update alert rules
            parts = parsed.path.split("/")
            device_id = parts[3]
            rule_data = dict(data)
            rule_data["device_id"] = device_id
            if "id" not in rule_data:
                rule_data["id"] = f"rule-{uuid.uuid4().hex[:8]}"
            rule = AlertRule.from_dict(rule_data)
            alert_manager.add_rule(rule)
            log.info("sensor alert rule created: %s on %s/%s",
                     rule.alert_type, device_id, rule.sensor_id)
            self._json_response({"ok": True, "rule": rule.to_dict()})

        elif parsed.path.startswith("/api/sensors/acknowledge/"):
            # POST /api/sensors/acknowledge/<alert_id>
            alert_id = parsed.path.split("/")[-1]
            ok = alert_manager.acknowledge(alert_id)
            if ok:
                self._json_response({"ok": True, "alert_id": alert_id})
            else:
                self._json_response({"error": "Alert not found or already acknowledged"}, 404)

        elif parsed.path.startswith("/api/sensors/delete-rule/"):
            # POST /api/sensors/delete-rule/<device_id>/<rule_id>
            parts = parsed.path.split("/")
            if len(parts) >= 5:
                device_id = parts[4]
                rule_id = parts[5] if len(parts) >= 6 else ""
                ok = alert_manager.remove_rule(device_id, rule_id)
                self._json_response({"ok": ok})
            else:
                self._json_response({"error": "Bad path"}, 400)

        # ── Video POST routes ──────────────────────────────

        elif parsed.path.startswith("/api/video/record/"):
            device_id = parsed.path.split("/api/video/record/")[1]
            action = data.get("action", "start")
            if action == "start":
                ok = video_manager.start_recording(device_id)
                self._json_response({"ok": ok, "action": "recording_started"})
            elif action == "stop":
                frames = video_manager.stop_recording(device_id)
                # Save frames to a directory
                if frames:
                    rec_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           "..", "recordings", device_id[:8])
                    os.makedirs(rec_dir, exist_ok=True)
                    ts = int(time.time())
                    saved = []
                    for i, f in enumerate(frames):
                        fname = f"rec_{ts}_{i:04d}.jpg"
                        fpath = os.path.join(rec_dir, fname)
                        with open(fpath, "wb") as fp:
                            fp.write(f)
                        saved.append(fname)
                    self._json_response({
                        "ok": True, "action": "recording_stopped",
                        "frame_count": len(frames),
                        "directory": rec_dir,
                        "files": saved[:5],  # First 5 as preview
                    })
                else:
                    self._json_response({"ok": False, "error": "No frames recorded"})
            else:
                self._json_response({"error": f"Unknown action: {action}"}, 400)

        elif parsed.path.startswith("/api/video/configure/"):
            device_id = parsed.path.split("/api/video/configure/")[1]
            ok = video_manager.configure(device_id, **data)
            if ok:
                src = video_manager.get_source(device_id)
                self._json_response({"ok": True, "config": src.info() if src else {}})
            else:
                self._json_response({"error": "Video source not found"}, 404)

        # ── Swarm Coordination POST routes ────────────────

        elif parsed.path == "/api/swarm/groups":
            # POST /api/swarm/groups — create a new group
            name = data.get("name", "Untitled Group")
            desc = data.get("description", "")
            group = swarm_coordinator.create_group(name, desc)
            # Auto-add devices if provided
            for d in data.get("device_ids", []):
                swarm_coordinator.add_device_to_group(group.id, d)
            self._json_response({"ok": True, "group": group.to_dict()})

        elif parsed.path.startswith("/api/swarm/groups/") and parsed.path.endswith("/devices"):
            gid = parsed.path.split("/api/swarm/groups/")[1].rsplit("/devices")[0]
            action = data.get("action", "add")
            device_id = data.get("device_id", "")
            role = data.get("role", "unassigned")
            if action == "remove":
                self._json_response(swarm_coordinator.remove_device_from_group(gid, device_id))
            else:
                self._json_response(swarm_coordinator.add_device_to_group(gid, device_id, role))

        elif parsed.path.startswith("/api/swarm/groups/") and parsed.path.endswith("/formation"):
            gid = parsed.path.split("/api/swarm/groups/")[1].rsplit("/formation")[0]
            ft = data.get("formation_type", "line")
            params = data.get("params", {})
            apply_to_devices = data.get("apply", False)
            result = swarm_coordinator.set_formation(
                gid, ft, params, devices if apply_to_devices else None,
            )
            self._json_response(result)

        elif parsed.path.startswith("/api/swarm/groups/") and parsed.path.endswith("/command"):
            gid = parsed.path.split("/api/swarm/groups/")[1].rsplit("/command")[0]
            text = data.get("text", "")
            if text:
                # NLP-aware group command
                parsed_cmd = swarm_coordinator.parse_group_command(text, devices)
                group = swarm_coordinator.get_group(gid)
                if not group:
                    self._json_response({"ok": False, "error": "group not found"}, 404)
                elif parsed_cmd.get("type") == "formation":
                    result = swarm_coordinator.set_formation(
                        gid, parsed_cmd["formation_type"],
                        parsed_cmd.get("params", {}), devices,
                    )
                    result["nlp"] = parsed_cmd
                    self._json_response(result)
                elif parsed_cmd.get("type") == "sync_takeoff":
                    self._json_response(swarm_coordinator.synchronized_takeoff(gid, 5.0, devices))
                elif parsed_cmd.get("type") == "sync_land":
                    self._json_response(swarm_coordinator.synchronized_land(gid, devices))
                elif parsed_cmd.get("type") == "emergency_stop":
                    self._json_response(swarm_coordinator.emergency_stop(gid, devices))
                elif parsed_cmd.get("type") == "mission":
                    result = swarm_coordinator.start_mission(
                        gid, parsed_cmd["mission_type"], data.get("params", {}), devices,
                    )
                    result["nlp"] = parsed_cmd
                    self._json_response(result)
                else:
                    # Broadcast as raw command
                    cmd = data.get("command", "hover")
                    params = data.get("params", {})
                    self._json_response(swarm_coordinator.broadcast_command(gid, cmd, params, devices))
            else:
                cmd = data.get("command", "")
                params = data.get("params", {})
                self._json_response(swarm_coordinator.broadcast_command(gid, cmd, params, devices))

        elif parsed.path.startswith("/api/swarm/groups/") and parsed.path.endswith("/mission"):
            gid = parsed.path.split("/api/swarm/groups/")[1].rsplit("/mission")[0]
            mt = data.get("mission_type", "area_search")
            params = data.get("params", {})
            self._json_response(swarm_coordinator.start_mission(gid, mt, params, devices))

        elif parsed.path.startswith("/api/swarm/groups/") and parsed.path.endswith("/sync"):
            gid = parsed.path.split("/api/swarm/groups/")[1].rsplit("/sync")[0]
            action = data.get("action", "barrier")
            group = swarm_coordinator.get_group(gid)
            if not group:
                self._json_response({"ok": False, "error": "group not found"}, 404)
            elif action == "barrier":
                label = data.get("label", "checkpoint")
                b = swarm_coordinator.sync.create_barrier(gid, label, group.device_ids())
                self._json_response({"ok": True, "barrier": b.to_dict()})
            elif action == "countdown":
                try:
                    secs = int(data.get("seconds", 3))
                    if secs <= 0 or secs > 300:
                        raise ValueError("seconds must be between 1 and 300")
                except (ValueError, TypeError) as e:
                    raise ValidationError(f"Invalid seconds: {e}") from e
                label = data.get("label", "Launch")
                c = swarm_coordinator.sync.create_countdown(gid, secs, label)
                result = swarm_coordinator.sync.start_countdown(c.id)
                self._json_response(result)
            elif action == "emergency_stop":
                self._json_response(swarm_coordinator.emergency_stop(gid, devices))
            elif action == "arrive":
                barrier_id = data.get("barrier_id", "")
                device_id = data.get("device_id", "")
                self._json_response(swarm_coordinator.sync.arrive_barrier(barrier_id, device_id))
            else:
                self._json_response({"ok": False, "error": f"unknown sync action: {action}"}, 400)

        elif parsed.path.startswith("/api/swarm/groups/") and parsed.path.endswith("/role"):
            gid = parsed.path.split("/api/swarm/groups/")[1].rsplit("/role")[0]
            device_id = data.get("device_id", "")
            role = data.get("role", "unassigned")
            self._json_response(swarm_coordinator.set_device_role(gid, device_id, role))

        elif parsed.path == "/api/swarm/groups/delete":
            gid = data.get("group_id", "")
            ok = swarm_coordinator.delete_group(gid)
            self._json_response({"ok": ok})

        elif parsed.path == "/api/swarm/formation-preview":
            ft = data.get("formation_type", "line")
            try:
                count = int(data.get("count", 4))
                if count <= 0 or count > 100:
                    raise ValueError("count must be between 1 and 100")
            except (ValueError, TypeError) as e:
                raise ValidationError(f"Invalid count: {e}") from e
            params = data.get("params", {})
            self._json_response(swarm_coordinator.get_formation_preview(ft, count, params))

        elif parsed.path.startswith("/api/swarm/mission/") and parsed.path.endswith("/stop"):
            mid = parsed.path.split("/api/swarm/mission/")[1].rsplit("/stop")[0]
            self._json_response(swarm_coordinator.stop_mission(mid))

        # ── AI Enhancement POST routes ───────────────────────
        elif parsed.path.startswith("/api/ai/analyze/"):
            device_id = parsed.path.split("/api/ai/analyze/")[1]
            if device_id not in devices:
                raise NotFoundError(f"Device {device_id} not found")
            image_b64 = data.get("image", None)
            result = ai_enhancer.full_analysis(device_id, image_b64=image_b64)
            self._json_response(result)
            return

        elif parsed.path.startswith("/api/ai/enhance-3d/"):
            device_id = parsed.path.split("/api/ai/enhance-3d/")[1]
            if device_id not in devices:
                raise NotFoundError(f"Device {device_id} not found")
            image_b64 = data.get("image", "")
            if not image_b64:
                raise ValidationError("image field is required for 3D enhancement")
            result = ai_enhancer.enhance_3d_model(device_id, image_b64)
            self._json_response(result)
            return

        elif parsed.path.startswith("/api/ai/estimate-physics/"):
            device_id = parsed.path.split("/api/ai/estimate-physics/")[1]
            if device_id not in devices:
                raise NotFoundError(f"Device {device_id} not found")
            image_b64 = data.get("image", None)
            result = ai_enhancer.estimate_physics(device_id, image_b64=image_b64)
            self._json_response(result)
            return

        elif parsed.path == "/api/ai/configure":
            provider = data.get("provider", "")
            api_key = data.get("api_key", "")
            if not provider or not api_key:
                raise ValidationError("provider and api_key are required")
            ai_model_registry.configure_api_key(provider, api_key)
            self._json_response({"ok": True, "provider": provider})
            return

        else:
            self._json_response({"error": "Not found"}, 404)

    # ── Mobile helpers ──────────────────────────────────

    def _is_mobile_ua(self):
        """Detect mobile user-agents for auto-redirect."""
        ua = (self.headers.get("User-Agent") or "").lower()
        mobile_keywords = ("iphone", "android", "mobile", "ipod", "opera mini",
                           "iemobile", "blackberry", "webos")
        return any(kw in ua for kw in mobile_keywords)

    # ── BT helper methods ────────────────────────────────

    def _count_nodes(self, root_dict) -> list:
        """Count nodes in a tree dict recursively."""
        if not root_dict:
            return []
        nodes = [root_dict]
        for c in root_dict.get("children", []):
            nodes.extend(self._count_nodes(c))
        return nodes

    def _nlp_to_bt(self, text: str, device) -> dict:
        """Convert an NL mission description into a behavior tree definition.

        Uses the existing NLP compiler to extract steps, then wraps them
        in a Sequence tree with appropriate BT nodes.
        """
        from omnix.nlp import compile_to_plan, list_capabilities_for_device
        caps = list_capabilities_for_device(device)
        plan = compile_to_plan(text, device.id, device.device_type, caps)

        # Build BT nodes from plan steps
        children = []
        x_offset = 50
        for i, step in enumerate(plan.steps):
            node = {
                "type": "ExecuteCommand",
                "node_id": f"nlp-s{i+1:03d}",
                "name": step.description or step.command,
                "category": "action",
                "properties": {
                    "command": step.command,
                    "params": dict(step.params),
                    "duration_s": step.expected_duration_s,
                },
                "children": [],
                "x": x_offset + i * 160,
                "y": 180,
            }
            children.append(node)

        root = {
            "type": "Sequence",
            "node_id": "nlp-root",
            "name": f"Mission: {text[:40]}",
            "category": "composite",
            "properties": {},
            "children": children,
            "x": 400, "y": 50,
        }

        return {
            "tree_id": f"bt-{uuid.uuid4().hex[:10]}",
            "name": f"Mission: {text[:50]}",
            "description": f"Auto-generated from: {text}",
            "device_id": device.id,
            "root": root,
            "created_at": time.time(),
            "updated_at": time.time(),
        }

    def _json_response(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        # Apply CORS and security headers
        cors_middleware.apply_headers(self)
        secure_headers.apply(self)
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self):
        self._dispatch(self._do_delete)

    def _do_delete(self):
        parsed = urlparse(self.path)

        # DELETE /api/ota/firmware/<id> — remove a firmware version
        if parsed.path.startswith("/api/ota/firmware/"):
            parts = parsed.path.split("/")
            fw_id = parts[4] if len(parts) >= 5 else ""
            if not fw_id:
                self._json_response({"error": "firmware_id required"}, 400)
                return
            if ota_manager.delete_firmware(fw_id):
                self._json_response({"ok": True})
            else:
                self._json_response({"error": "Firmware not found"}, 404)
        else:
            self._json_response({"error": "Not found"}, 404)

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        cors_middleware.handle_preflight(self)


def main():
    global movement_executor, connector_manager, ws_server, plugin_registry, plugin_loader

    # ── Initialize database ──
    _init_database()

    # ── Initialize auth ──
    auth_manager.create_default_admin()
    log.info("auth initialized (guest_mode=%s)", settings.guest_mode)

    # ── Register devices ──
    add_device(SimulatedDrone("SkyHawk Drone"))
    add_device(SimulatedRobotArm("Workshop Arm R1"))
    add_device(SimulatedSmartLight("Living Room Light"))
    add_device(SimulatedSmartLight("Desk Lamp"))

    # Initialize video sources for all simulated devices
    for did, dev in devices.items():
        tele_fn = (lambda d=dev: d.get_telemetry())
        video_manager.add_simulated(did, dev.device_type, tele_fn)
        video_manager.start(did)
    log.info("video feeds initialized for %d devices", len(devices))

    # Register sensor channels for all devices
    for did, dev in devices.items():
        auto_register_sensors(sensor_registry, did, dev.device_type)
        # Seed initial readings
        for _ in range(30):
            sensor_simulator.tick(did)
    log.info("sensor dashboard initialized: %d devices with sensors",
             len(sensor_registry.get_all_device_ids()))

    # Initialize movement executor with device registry
    movement_executor = MovementExecutor(devices)

    # Initialize connector manager and register all shipped connectors
    connector_manager = ConnectorManager(devices)
    for cls in ALL_CONNECTORS:
        try:
            connector_manager.register(cls)
        except Exception as e:
            log.exception("failed to register connector %s", cls.__name__,
                          extra={"connector_class": cls.__name__})

    # ── Load plugins ──
    plugins_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins")
    plugin_loader = PluginLoader(plugins_dir)
    plugin_registry = PluginRegistry()

    # Wire plugin registry into connector manager
    plugin_registry.set_connector_hooks(
        register_fn=lambda cls: connector_manager.register(cls),
        unregister_fn=lambda cid: connector_manager._classes.pop(cid, None),
    )
    plugin_registry.set_sensor_hooks(
        register_fn=lambda spec: sensor_registry.register(
            spec["device_id"], spec["sensor_id"], spec["name"],
            spec.get("sensor_type", "custom"),
            spec.get("range_min", 0), spec.get("range_max", 100),
            spec.get("unit", ""),
        ),
        unregister_fn=lambda did, sid: sensor_registry.unregister(did, sid)
        if hasattr(sensor_registry, "unregister") else None,
    )

    # Discover and load plugins
    discovered = plugin_loader.discover()
    loaded_count = 0
    for plugin in discovered:
        try:
            if plugin_registry.load_plugin(plugin):
                loaded_count += 1
        except Exception as e:
            log.exception("failed to load plugin %s",
                          plugin.meta.name if plugin.meta else "unknown")
    log.info("plugins loaded: %d/%d from %s", loaded_count, len(discovered), plugins_dir)

    # ── Start WebSocket server ──
    ws_started = False
    if settings.ws_enabled:
        try:
            from omnix.ws import WebSocketServer, WSCollabHandler
            ws_server = WebSocketServer(host=settings.host, port=settings.ws_port)
            ws_started = ws_server.start()
            if ws_started:
                # Wrap the collab handler with WebSocket support
                global collab_handler
                ws_collab = WSCollabHandler(collab_handler, ws_server)
                log.info("WebSocket server started on port %d", settings.ws_port)
        except Exception as e:
            log.warning("WebSocket server failed to start: %s (falling back to polling)", e)
            ws_server = None

    port = settings.port
    # ThreadingHTTPServer lets long-running requests (simulation runs,
    # connector starts) proceed without blocking the telemetry poll loop.
    server = ThreadingHTTPServer((settings.host, port), OmnixHandler)

    print()
    print("=" * 55)
    print("    OMNIX Universal Robotics Control Server v0.3.0")
    print("    Production-Ready Edition")
    print("=" * 55)
    print()
    print(f"  Dashboard:       http://localhost:{port}")
    print(f"  Mobile PWA:      http://localhost:{port}/mobile")
    print(f"  Pi Manager:      http://localhost:{port}/pi.html")
    print(f"  Physics Engine:  http://localhost:{port}/vpe.html")
    print(f"  Motion 3D:       http://localhost:{port}/motion3d.html")
    print(f"  API Metrics:     http://localhost:{port}/api/metrics")
    print()
    print(f"  Auth:            {'Enabled (guest mode)' if settings.guest_mode else 'Enabled (login required)'}")
    print(f"  Database:        {settings.db_backend}" + (f" ({settings.db_path})" if settings.db_backend == "sqlite" else ""))
    print(f"  WebSocket:       {'ws://localhost:' + str(settings.ws_port) if ws_started else 'Disabled (polling fallback)'}")
    print(f"  AI Enhancement:  {'Available' if ai_model_registry else 'Disabled'}")
    print(f"  Environment:     {settings.env}")
    print()
    print("  Simulated devices:")
    for did, d in devices.items():
        print(f"    [{d.device_type}] {d.name} (id: {did})")
    print()
    print("  Registered connectors:")
    for cls in ALL_CONNECTORS:
        meta = cls.meta
        print(f"    [T{meta.tier}] {meta.display_name:32s} ({meta.connector_id})")
    print()
    print("  Loaded plugins:")
    if plugin_registry and plugin_registry.get_plugin_names():
        for pname in plugin_registry.get_plugin_names():
            p = plugin_registry.get_plugin(pname)
            if p and p.meta:
                print(f"    [{p.meta.icon}] {p.meta.name:32s} v{p.meta.version}")
    else:
        print("    (none)")
    print()
    print("  Pi agents can connect via:")
    print(f"    python pi_agent.py --server http://<this-ip>:{port}")
    print()
    print("  Default admin: admin / omnix-admin (change in production!)")
    print()
    print("  Server running! Press Ctrl+C to stop.")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("server shutting down on keyboard interrupt")
        if ws_server:
            ws_server.stop()
        if migration_manager:
            migration_manager.close()
        server.server_close()


if __name__ == "__main__":
    main()
