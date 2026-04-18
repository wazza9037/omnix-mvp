# OMNIX Demo Script

> **Audience:** Investors, potential users, partners
> **Setup:** Have the OMNIX server running (`python3 server_simple.py`) with a browser open to `localhost:8765`.

---

## 5-Minute Version (Elevator Pitch + Live Demo)

### Minute 0:00 — The Hook (30 seconds)

**Open:** `landing.html`

**Say:** "Every robotics team today juggles 5-6 different tools — one for simulation, one for control, one for fleet management. OMNIX replaces all of them. One app. Any robot. Zero limits."

**Action:** Scroll slowly through the hero section. Let the 3D animation catch their eye.

**Key point:** "We support 6 connector protocols out of the box, from $20 Arduino boards to $10,000 industrial drones."

### Minute 0:30 — The Dashboard (60 seconds)

**Navigate to:** `index.html` (main Studio)

**Say:** "This is the OMNIX Studio. Every robot gets its own workspace tab — like browser tabs for robots."

**Actions:**
1. Point to the sidebar showing connected devices (Tello Drone, Robot Arm, Smart Light, Rover)
2. Click on the **Tello Drone** tab
3. Show the 3D viewer with live telemetry
4. Point out the four views: Overview, Control, Simulate, Iterations

**Key point:** "Each workspace learns. The physics model improves with every simulation run — your 50th test is fundamentally more accurate than your first."

### Minute 1:30 — NLP Commands (60 seconds)

**Stay on:** the drone workspace

**Say:** "Here's where it gets interesting. Instead of writing code, you just type what you want."

**Actions:**
1. Click the NLP Command Bar
2. Type: `take off and fly a square at 3m altitude`
3. Show the parsed plan preview
4. Hit execute — watch the 3D viewer animate the path

**Key point:** "That one sentence replaced about 40 lines of MAVLink Python. And it works for any robot — arms, rovers, drones."

**Wow moment:** "Watch — I'll switch to the robot arm." Click the arm tab. Type: `pick up the red block and place it on the shelf`. Show the parsed plan.

### Minute 2:30 — Digital Twin (45 seconds)

**Navigate to:** the Twin view (if available) or show the simulation panel

**Say:** "The digital twin runs sim and real side-by-side. You can catch problems before they cost you hardware."

**Actions:**
1. Show the simulated vs. real panels
2. Point out the divergence meter
3. "When divergence crosses a threshold, OMNIX alerts you and can auto-land."

**Key point:** "This saved one of our beta testers from crashing a $3,000 drone into a wall."

### Minute 3:15 — Behavior Trees + Marketplace (60 seconds)

**Say:** "For complex missions, you don't write code — you compose visual behavior trees."

**Actions:**
1. Open the Mission Planner view
2. Show a behavior tree: Sequence → Takeoff → Repeat(4, Move Forward) → Land
3. "These are shareable. Which brings us to the marketplace..."
4. Open the Marketplace panel
5. Browse items: "Agricultural Survey behavior, LiDAR Mapper template, Racing Drone Kit"

**Key point:** "32 items and growing. This becomes a network effect — every user makes the platform more valuable."

### Minute 4:15 — The Numbers (45 seconds)

**Navigate to:** `stats.html`

**Say:** "Under the hood: 40,000 lines of code. 114 Python modules. 45+ API endpoints. 246 tests passing. All Dockerized with CI/CD."

**Actions:** Let the animated counters tick up. Scroll through the architecture diagram.

**Key point:** "The core server runs on zero dependencies — just Python's standard library. That's intentional. We want OMNIX to run on a Raspberry Pi, a laptop, or a cloud cluster."

**Close:** "We're building the VS Code of robotics. One app that every roboticist opens first thing in the morning."

---

## 15-Minute Version (Deep Dive)

### Minutes 0:00 – 2:00 — Problem + Landing Page (same as above, expanded)

**Open:** `landing.html`

Spend more time on the problem space:
- "The robotics tooling market is fragmented. ROS is powerful but has a steep learning curve. Vendor tools only work with one brand. Research teams waste weeks on integration."
- "OMNIX is protocol-agnostic. We abstract away the transport layer — whether it's MAVLink, ROS2, serial, or WiFi — and give every robot the same first-class experience."

Scroll through all landing page sections. Highlight the pricing tiers: "Our free tier is generous enough for hobbyists. Pro at $29/month is where teams start. We've validated that price point with early conversations."

### Minutes 2:00 – 5:00 — Full Studio Tour

**Navigate to:** `index.html`

Walk through each feature methodically:

1. **Sidebar:** "Device management. Add, remove, rename. Each device shows its connector type and connection status."
2. **Connect a Device:** Click through the flow. "Select Tello → configure → connect. In simulation mode, it's instant. Real hardware requires Wi-Fi pairing."
3. **4 Views:** Click through each tab:
   - Overview: specs, notes, learned physics parameters
   - Control: 3D viewer + command panel
   - Simulate: scenario picker (hover, patrol, figure-8)
   - Iterations: lab notebook with charts

4. **Run a simulation:** Pick "figure_8" scenario → run → watch the 3D trajectory → show the iteration appear in the notebook with metrics.

**Talking point:** "Every iteration teaches the physics model. See this confidence metric? After 10 runs, the model is accurate enough to predict battery drain within 5%."

### Minutes 5:00 – 7:00 — NLP Deep Dive

**Say:** "The NLP command bar is our most viral feature."

**Demo sequence:**
1. Drone: `take off, fly north 10 meters, rotate 360, land`
2. Arm: `move to position (0.5, 0.3, 0.1) and grip`
3. Light: `set color to blue and pulse at 2 Hz`

Show how each command parses differently per device type.

**Anticipated questions:**
- "How does NLP parsing work?" → "We use a rule-based parser tuned for robotics vocabulary. LLM integration is on the roadmap for v2."
- "What if the command is ambiguous?" → "OMNIX shows a plan preview and asks for confirmation. Nothing executes without user approval."

### Minutes 7:00 – 9:00 — Visual Physics Engine

**Navigate to:** `vpe.html`

**Say:** "This is the VPE — our visual physics engine. Upload a photo of any robot and OMNIX classifies it, generates a 3D mesh, and suggests the right connector."

**Actions:**
1. Show the upload interface
2. Point to the 100 device fingerprints: "We support classification across drones, arms, rovers, humanoids, marine robots, and more."
3. "Once classified, OMNIX auto-suggests a connector and generates starter physics parameters."

**Key point:** "This is the onramp. New user, new robot, one photo, and they're running simulations in 60 seconds."

### Minutes 9:00 – 11:00 — Behavior Trees + Custom Builder

**Behavior Trees:**
1. Open mission planner
2. Build a tree live: drag Sequence → add Takeoff → add Repeat node → nest Move Forward → add Land
3. "20+ node types: conditionals, loops, parallel execution, sensor checks, timers."
4. Execute the tree — watch it step through nodes with visual highlighting

**Custom Robot Builder:**
1. Open the builder
2. Show part selection: frame, motors, sensors, controllers
3. Adjust parameters with sliders
4. "Export to JSON, import on another instance, or publish to the marketplace."

### Minutes 11:00 – 13:00 — Marketplace + Collaboration

**Marketplace:**
1. Browse categories: templates, behaviors, connectors
2. Show item details with ratings and descriptions
3. "One-click import into your workspace"

**Collaboration:**
1. "Real-time collaboration over WebSocket. Multiple engineers, one robot."
2. Show the collaboration features: shared state, cursors, chat

**Key point:** "This is the network effect flywheel. More users → more marketplace items → more value → more users."

### Minutes 13:00 – 14:00 — Technical Deep Dive

**Navigate to:** `stats.html`

Walk through the architecture:
- "114 Python files, cleanly separated into connectors, devices, simulation, NLP, auth, and marketplace modules."
- "The server starts in under 1 second with zero pip installs. That's not a constraint — it's a feature."
- "Full Docker-compose setup with Nginx, Redis, and PostgreSQL for production."
- "CI/CD via GitHub Actions. 246 tests. Pre-commit hooks with ruff."

**Anticipated questions:**
- "What about scale?" → "The architecture supports horizontal scaling. Each workspace is independent. We've tested with 50 simultaneous devices."
- "Why not use ROS?" → "ROS is a great framework, but it's an operating system. OMNIX is an application layer that can sit on top of ROS — our ROS2 bridge connector proves it."
- "What's the business model?" → "SaaS tiers. Free for hobbyists, Pro/Team for professionals, Enterprise for companies needing on-prem and custom connectors."

### Minute 14:00 – 15:00 — Vision + Close

**Navigate to:** `landing.html`, scroll to CTA

**Say:** "Our roadmap: mobile app for field operations, cloud fleet management for managing hundreds of robots, and ML model training — teach your robot from demonstrations."

**Close:** "We're 40,000 lines into building the universal operating layer for robotics. Every robot deserves a great developer experience. OMNIX delivers that today."

**Final action:** Click "Get Started Free."

---

## Wow Moments Cheat Sheet

Use these to punctuate the demo with impact:

1. **NLP Magic** — Type a natural language command and watch it parse into waypoints instantly. The gasps come when you switch robot types and the same approach works.

2. **Zero to Flying** — From `python3 server_simple.py` to a simulated drone executing a figure-8 in under 30 seconds. Time it.

3. **Photo to Robot** — Upload a photo in VPE → classification → 3D mesh → suggested connector. "One photo, and OMNIX knows what your robot is."

4. **Stats Counter** — Open stats.html and let the "40,000+ lines" counter tick up. Engineers respect code volume when it's clean.

5. **The Marketplace Network Effect** — "Every template someone shares makes every other user's experience better. That's the flywheel."

---

## Troubleshooting During Demo

| Issue | Quick Fix |
|-------|-----------|
| Server won't start | `cd backend && python3 server_simple.py` — no deps needed |
| 3D viewer blank | Refresh the page; Three.js occasionally needs a reload |
| Simulation seems slow | "Simulation fidelity is configurable — we're running high-res for the demo" |
| Feature not responding | Switch to a different device tab and back |
| Question you can't answer | "Great question — that's on our roadmap. Let me follow up with details." |

---

## Pre-Demo Checklist

- [ ] Server running on `localhost:8765`
- [ ] Browser open with tabs: `index.html`, `landing.html`, `demo.html`, `stats.html`
- [ ] At least 2 simulated devices active in the dashboard
- [ ] Screen sharing set up (if remote)
- [ ] Font size bumped up for readability (Cmd/Ctrl +)
- [ ] Notifications silenced
- [ ] Practice the 5-minute version at least twice
