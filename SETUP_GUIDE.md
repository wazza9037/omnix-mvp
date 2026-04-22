# How to Run OMNIX Locally with Your Arduino or Raspberry Pi

Hey! This guide will get OMNIX running on your computer in about 5 minutes. No special tools needed — just Python.

---

## What You'll Get

OMNIX gives you a browser-based dashboard to control robots. Out of the box it comes with 4 simulated devices you can play with immediately. When you're ready, you can connect real hardware like an Arduino, Raspberry Pi, ESP32, or even a DJI Tello drone.

---

## Step 1: Clone the Repo

Open a terminal and run:

```bash
git clone https://github.com/omnix-platform/omnix.git
cd omnix
```

---

## Step 2: Install the Only Dependency

OMNIX's core server runs on pure Python (no frameworks!), but you'll want websockets for real-time features:

```bash
pip install websockets
```

That's it. One package.

(If you're on a Pi or Linux and `pip` complains, try `pip3 install websockets` or `pip install websockets --break-system-packages`)

---

## Step 3: Start the Server

```bash
cd backend
python3 server_simple.py
```

You should see something like:

```
=======================================================
    OMNIX Universal Robotics Control Server v0.3.0
=======================================================

  Dashboard:       http://localhost:8765
  Mobile PWA:      http://localhost:8765/mobile
```

---

## Step 4: Open the Dashboard

Open your browser and go to:

**http://localhost:8765**

You'll see the main dashboard with 4 simulated devices (a drone, a robot arm, and two lights). Click around — you can send commands, run simulations, and explore the 3D viewer.

Other pages to check out:

- **http://localhost:8765/landing.html** — Project landing page
- **http://localhost:8765/demo.html** — Guided interactive demo
- **http://localhost:8765/stats.html** — Platform stats
- **http://localhost:8765/vpe.html** — Visual Physics Engine (upload a photo of a device!)

---

## Step 5: Connect a Raspberry Pi (Optional)

### 5a. Find your computer's IP address

The Pi needs to reach the OMNIX server over the network. Find your IP:

- **Linux/Mac:** `hostname -I` (first address, e.g. `192.168.1.42`)
- **Windows:** `ipconfig` → look for "IPv4 Address" under your active adapter
- **Quick check:** `python3 -c "import socket; print(socket.gethostbyname(socket.gethostname()))"`

### 5b. Copy the required files to your Pi

The Pi needs three files from the `backend/devices/` folder. Copy the whole folder or just these:

```bash
# From your computer (adjust paths):
scp -r backend/devices/ pi@YOUR_PI_IP:~/omnix-agent/
```

Or on the Pi: `git clone` the full repo, then `cd omnix/backend`.

### 5c. Install Pi dependencies (optional, for real GPIO)

```bash
# On the Pi:
pip3 install RPi.GPIO          # for real GPIO control
pip3 install picamera2          # for Pi Camera Module
pip3 install adafruit-circuitpython-dht  # for DHT temp sensors
```

If you skip these, the agent runs in **simulated mode** (useful for testing the connection first).

### 5d. Test the connection

Before running the full agent, verify the server is reachable:

```bash
# On the Pi, test connectivity:
curl http://YOUR_COMPUTER_IP:8765/api/pi/ping
```

You should see: `{"status": "ok", "server": "omnix", ...}`

If you get "Connection refused": check that the server is running, both devices are on the same WiFi, and your firewall allows port 8765.

### 5e. Run the Pi agent

```bash
# On the Pi:
cd omnix-agent   # or wherever you put the files
python3 devices/pi_agent.py --server http://YOUR_COMPUTER_IP:8765 --profile rover
```

Available profiles: `rover` (2-motor drive), `arm` (robotic arm), `sentinel` (pan/tilt camera).

You should see:
```
  Pinging http://YOUR_COMPUTER_IP:8765...
  Server OK! Version: 0.3.0, agents connected: 0
  Registering...
  Registered! Agent ID: a1b2c3d4, Device ID: pi-a1b2c3d4
  Agent running! Sending telemetry every 1.0s
```

### 5f. Verify in the dashboard

Open **http://localhost:8765** and your Pi device should appear in the device list with a green "online" indicator. You can now send commands from the dashboard and they'll be executed on the Pi.

### 5g. Test without a Pi (simulation)

You can validate the entire pipeline without any hardware:

```bash
# On the same machine as the server:
cd backend
python3 test_pi_connection.py
```

This runs 12 automated tests covering registration, telemetry, commands, and cleanup.

### Pi troubleshooting

**"Ping FAILED: Connection refused"** — The server isn't reachable from the Pi. Check: (1) Is `server_simple.py` running? (2) Are both devices on the same network? (3) Is port 8765 open in your firewall? On Linux: `sudo ufw allow 8765`. On Windows: add an inbound rule for port 8765 in Windows Firewall.

**"Registration FAILED: 401 Unauthorized"** — Your server version is outdated. The Pi agent endpoints must be in the public route list. Pull the latest code and restart the server.

**Agent connects but nothing appears in dashboard** — Refresh the dashboard page. The Pi device should appear in the device list within a few seconds of registration.

**Telemetry shows "simulated"** — This is normal if you haven't installed `RPi.GPIO`. The connection is working — install the GPIO libraries for real sensor data.

---

## Step 6: Connect an Arduino (Optional)

1. Flash the firmware from `backend/connectors/firmware/arduino_omnix.ino` to your Arduino using the Arduino IDE
2. Connect the Arduino to your computer via USB
3. In the OMNIX dashboard, click **Connect a Device** and select **Arduino Serial**
4. Choose your serial port (usually `/dev/ttyUSB0` on Linux, `/dev/cu.usbmodem*` on Mac, or `COM3` on Windows)

---

## Step 7: Connect an ESP32 (Optional)

1. Flash `backend/connectors/firmware/esp32_omnix.ino` to your ESP32
2. The ESP32 connects over WiFi — make sure it's on the same network
3. In the dashboard, click **Connect a Device** and select **ESP32 WiFi**

---

## Troubleshooting

**"Port 8765 already in use"**
Another program is using that port. Either close it, or run OMNIX on a different port:
```bash
OMNIX_PORT=9000 python3 server_simple.py
```

**"ModuleNotFoundError: No module named 'omnix'"**
Make sure you're running from inside the `backend/` directory:
```bash
cd backend && python3 server_simple.py
```

**Pi agent can't connect**
See the detailed Pi troubleshooting section in Step 5 above. Quick checklist: (1) both on same network, (2) firewall allows port 8765, (3) test with `curl http://YOUR_IP:8765/api/pi/ping` from the Pi, (4) run `python3 test_pi_connection.py` on the server machine to validate the pipeline.

**Arduino not showing up**
Make sure you have the right serial port selected and the Arduino IDE isn't holding the port open.

---

## What's Next?

- Try the **NLP Command Bar** — type natural language commands like "fly a square at 3m altitude"
- Build a custom robot in the **Robot Builder**
- Set up a **Digital Twin** to compare simulated vs real behavior
- Check out the **Marketplace** for community templates and behaviors

Questions? Open an issue on GitHub!
