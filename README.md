<p align="center">
  <img src="https://via.placeholder.com/120x120/0D1B2A/00B4D8?text=⬡" alt="OMNIX Logo" width="120" />
</p>

<h1 align="center">OMNIX</h1>
<p align="center"><strong>One App. Any Robot. Zero Limits.</strong></p>
<p align="center">The universal platform for building, commanding, and iterating on any robot — from hobby drones to industrial arms.</p>

<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/build-passing-brightgreen?style=flat-square" alt="Build Status" /></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.10+-blue?style=flat-square&logo=python&logoColor=white" alt="Python" /></a>
  <a href="#"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License" /></a>
  <a href="#"><img src="https://img.shields.io/badge/docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker" /></a>
  <a href="#"><img src="https://img.shields.io/badge/lines-40k+-blueviolet?style=flat-square" alt="Lines of Code" /></a>
  <a href="#"><img src="https://img.shields.io/badge/tests-246+-success?style=flat-square" alt="Tests" /></a>
</p>

---

## What is OMNIX?

OMNIX is a local-first, open-source robotics control platform. It gives every robot — real or simulated — a complete workspace with live 3D visualization, adaptive physics that improves with every iteration, and a lab notebook of every test run.

The core server runs on **the Python standard library alone** with zero dependencies. Connectors, vision, and simulation features are opt-in.

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/omnix-platform/omnix.git && cd omnix

# 2. Run (zero dependencies needed)
cd backend && python3 server_simple.py

# 3. Open
open http://localhost:8765
```

That's it. Four simulated robots are ready to go. Click **Connect a Device** to add a Tello drone, Arduino rover, ROS2 bridge, or any other connector — all work in simulation mode out of the box.

**With Docker:**

```bash
docker-compose up -d
open http://localhost:8765
```

**Full development setup:**

```bash
make dev        # install runtime + pytest + ruff
make run        # start the server
make test       # run the 246+ test suite
```

---

## Features

### NLP Command Bar
Type natural language commands like *"fly a square at 3m altitude"* and OMNIX parses them into executable plans. No coding required.

### Digital Twin
Run simulated and real robots side-by-side. Spot divergence before it matters with real-time comparison and a divergence meter.

### Visual Mission Planner
Drag-and-drop behavior trees with 20+ node types. Build complex autonomous missions — from simple sequences to full-stack autonomy.

### Custom Robot Builder
Assemble any robot from modular parts. Define physics parameters, adjust components, and export configurations to real hardware.

### Marketplace
Discover and share templates, behaviors, and connectors. 32+ community-contributed items and growing.

### Real-time Collaboration
Multiple engineers, one robot. Live cursors, shared state, and collaborative editing powered by WebSocket channels.

### Visual Physics Engine (VPE)
Upload a photo of any device. The VPE runs an 8-pass image analysis, classifies against 100 device fingerprints, generates a parametric 3D mesh, and suggests the best connector.

### 6 Connectors Out of the Box
Pi, Arduino Serial, ESP32 WiFi, DJI Tello (real UDP SDK), PX4/ArduPilot via MAVLink, and ROS2 Bridge — each with a complete simulated fallback.

---

## Architecture

```
                          ┌──────────────────────┐
                          │      Frontend         │
                          │  HTML5 + Three.js     │
                          │  index.html (Studio)  │
                          │  landing.html         │
                          │  demo.html            │
                          │  stats.html           │
                          │  vpe.html / pi.html   │
                          └──────────┬────────────┘
                                     │ HTTP + WebSocket
                          ┌──────────▼────────────┐
                          │     API Server         │
                          │  server_simple.py      │
                          │  45+ endpoints         │
                          │  8 WS channels         │
                          └──────────┬────────────┘
                 ┌───────────────────┼──────────────────┐
                 │                   │                   │
        ┌────────▼──────┐  ┌────────▼──────┐  ┌────────▼──────┐
        │  Connectors   │  │  Simulation   │  │  NLP + BT     │
        │  6 adapters   │  │  Adaptive     │  │  Command Bar  │
        │  MAVLink      │  │  Physics      │  │  Behavior     │
        │  ROS2, Tello  │  │  Scenarios    │  │  Trees (20+   │
        │  Serial, WiFi │  │  Runner       │  │  node types)  │
        └───────┬───────┘  └───────────────┘  └───────────────┘
                │
        ┌───────▼───────┐
        │   Devices      │
        │  Drones, Arms  │
        │  Rovers, Lights│
        │  Custom builds │
        └────────────────┘
```

**By the numbers:** 114 Python files · 40,000+ lines of code · 45+ REST endpoints · 8 WebSocket channels · 32 test files · 246+ tests passing

---

## Pages

| Page | URL | Description |
|------|-----|-------------|
| **Studio** | `/` | Main dashboard — multi-robot tabs, 3D viewer, telemetry, control |
| **Landing** | `/landing.html` | Investor-facing landing page with 3D hero animation |
| **Demo** | `/demo.html` | Interactive 7-step guided tour of all features |
| **Stats** | `/stats.html` | Platform metrics dashboard with animated counters |
| **VPE** | `/vpe.html` | Visual Physics Engine — scan a device from a photo |
| **Pi Fleet** | `/pi.html` | Raspberry Pi fleet manager |

---

## Configuration

All configuration is environment-driven. See `backend/omnix/config.py` for the full list.

| Variable | Default | Purpose |
|----------|---------|---------|
| `OMNIX_HOST` | 0.0.0.0 | HTTP bind address |
| `OMNIX_PORT` | 8765 | HTTP port |
| `OMNIX_LOG_LEVEL` | INFO | Log level |
| `OMNIX_LOG_JSON` | 0 | Structured JSON log lines |
| `OMNIX_SIM_TICK_S` | 0.05 | Simulation integration step |
| `OMNIX_CONNECTOR_TICK_S` | 0.5 | Connector tick interval |

---

## API Reference

All endpoints return JSON. Errors use a structured envelope with codes: `validation_error`, `not_found`, `conflict`, `upstream_error`, `internal_error`.

**Core endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/healthz` | Liveness + counts + uptime |
| GET | `/api/devices` | List all registered devices |
| GET | `/api/telemetry` | Telemetry snapshot |
| POST | `/api/command` | Send command to a device |
| POST | `/api/add_device` | Register a new device |
| GET | `/api/connectors/classes` | Available connector types |
| POST | `/api/connectors/start` | Start a connector instance |
| GET | `/api/workspaces` | List all workspaces |
| POST | `/api/workspaces/<id>/iterations` | Run a simulation |
| POST | `/api/vpe/analyze` | Analyze a device image |
| GET | `/api/simulation/scenarios` | Available scenarios |

Full API documentation covers 45+ endpoints across devices, connectors, workspaces, simulation, VPE, movements, and agent protocols. See the source for complete details.

---

## Writing a New Connector

```python
from connectors.base import ConnectorBase, ConnectorMeta, ConfigField
from devices.base import DeviceCapability

class MyConnector(ConnectorBase):
    meta = ConnectorMeta(
        connector_id="my_connector",
        display_name="My Vendor XYZ",
        tier=2,
        description="Controls the XYZ robot over TCP.",
        vpe_categories=["drone", "ground_robot"],
        supports_simulation=True,
        config_schema=[
            ConfigField(key="host", label="Host", type="text", default="192.168.1.10"),
            ConfigField(key="mode", label="Mode", type="select",
                        default="simulate", options=["simulate", "real"]),
        ],
    )

    def connect(self) -> bool: ...
    def tick(self) -> None: ...
```

Register in `backend/connectors/__init__.py` and add to `registry.json`.

---

## Testing

```bash
make test              # full suite (246+ tests)
make test-quick        # skip slow tests
make cov               # with coverage report
```

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Run `make check` (lint + test) before committing
4. Submit a Pull Request

Keep the server boot-dependency-free. Optional features may add deps, but the core must run on `python3 server_simple.py` alone.

---

## License

MIT — see `LICENSE`.

---

<p align="center">
  <strong>Built for roboticists, by roboticists.</strong><br/>
  <a href="http://localhost:8765">Dashboard</a> · <a href="http://localhost:8765/landing.html">Landing Page</a> · <a href="http://localhost:8765/demo.html">Interactive Demo</a> · <a href="http://localhost:8765/stats.html">Platform Stats</a>
</p>
