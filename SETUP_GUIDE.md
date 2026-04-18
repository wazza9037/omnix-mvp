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

If you have a Raspberry Pi on the same network:

1. Copy `backend/devices/pi_agent.py` to your Pi
2. On the Pi, run:

```bash
python3 pi_agent.py --server http://YOUR_COMPUTER_IP:8765
```

Replace `YOUR_COMPUTER_IP` with your computer's local IP address (like `192.168.1.42`). You can find it with `hostname -I` on Linux/Mac or `ipconfig` on Windows.

3. Your Pi should appear in the OMNIX dashboard automatically!

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
Make sure both devices are on the same WiFi network. Check that your computer's firewall allows connections on port 8765.

**Arduino not showing up**
Make sure you have the right serial port selected and the Arduino IDE isn't holding the port open.

---

## What's Next?

- Try the **NLP Command Bar** — type natural language commands like "fly a square at 3m altitude"
- Build a custom robot in the **Robot Builder**
- Set up a **Digital Twin** to compare simulated vs real behavior
- Check out the **Marketplace** for community templates and behaviors

Questions? Open an issue on GitHub!
