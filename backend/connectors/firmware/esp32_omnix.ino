/*
 * OMNIX ESP32 Firmware — Tier 1 connector
 *
 * Target boards: ESP32 (Wroom / S2 / S3 / C3), ESP8266 (with the matching
 * ESP8266WiFi / ESP8266HTTPClient libraries).
 *
 * The firmware registers itself with an OMNIX server over HTTP, then
 * polls for commands and posts telemetry. The Python side of the
 * connector lives at backend/connectors/esp32_wifi.py.
 *
 * Dependencies (Arduino IDE → Library Manager):
 *   - ArduinoJson (v6.x)
 *   - WiFi (built-in for ESP32)
 *   - HTTPClient (built-in for ESP32)
 *
 * Wire protocol (all HTTP, JSON bodies):
 *   POST /api/esp32/register
 *     { "name":"Porch Light", "board_type":"lights",
 *       "mac":"AA:BB:...", "capabilities":["toggle","set_color"...] }
 *     → { "agent_id":"...", "device_id":"..." }
 *
 *   GET  /api/esp32/commands/<agent_id>
 *     → { "commands":[{"id":"...","command":"toggle","params":{"state":"on"}}] }
 *
 *   POST /api/esp32/telemetry/<agent_id>
 *     { "telemetry":{...} }
 *
 *   POST /api/esp32/deregister/<agent_id>
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ═══ USER CONFIG ════════════════════════════════════════════════
const char* WIFI_SSID   = "YOUR_WIFI_SSID";
const char* WIFI_PASS   = "YOUR_WIFI_PASSWORD";
const char* OMNIX_URL   = "http://192.168.1.42:8765";    // your OMNIX server
const char* BOARD_TYPE  = "lights";                      // lights | rover | sensor
const char* DISPLAY_NAME = "Porch Light";
// ════════════════════════════════════════════════════════════════

// Pins (edit to match your wiring)
const int PIN_R = 25;
const int PIN_G = 26;
const int PIN_B = 27;
const int PIN_MOTOR_L_PWM = 16;
const int PIN_MOTOR_L_DIR = 17;
const int PIN_MOTOR_R_PWM = 18;
const int PIN_MOTOR_R_DIR = 19;
const int PIN_DHT = 4;     // optional sensor

// PWM channels (ESP32 LEDC)
#define CH_R 0
#define CH_G 1
#define CH_B 2

// State
String agentId = "";
unsigned long lastTelemetry = 0;
unsigned long lastPoll = 0;
const unsigned long TELEMETRY_PERIOD_MS = 800;
const unsigned long POLL_PERIOD_MS = 400;

struct LightsState { bool on = false; int brightness = 0; uint8_t r = 0, g = 0, b = 0; };
struct RoverState { int motor_l = 0, motor_r = 0, sonar_cm = 200; };
struct SensorState { float temp_c = 22.0; int humidity = 45; bool motion = false; };

LightsState lights;
RoverState  rover;
SensorState sensor;

// ─── Setup ──────────────────────────────────────────────
void setupLights() {
  ledcSetup(CH_R, 5000, 8); ledcAttachPin(PIN_R, CH_R);
  ledcSetup(CH_G, 5000, 8); ledcAttachPin(PIN_G, CH_G);
  ledcSetup(CH_B, 5000, 8); ledcAttachPin(PIN_B, CH_B);
}
void setupRover() {
  pinMode(PIN_MOTOR_L_PWM, OUTPUT); pinMode(PIN_MOTOR_L_DIR, OUTPUT);
  pinMode(PIN_MOTOR_R_PWM, OUTPUT); pinMode(PIN_MOTOR_R_DIR, OUTPUT);
}
void setupSensor() { /* Add DHT / PIR init here if wired */ }

// ─── Wi-Fi ──────────────────────────────────────────────
void connectWifi() {
  Serial.printf("WiFi → joining %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.printf("\nIP: %s   MAC: %s\n",
                WiFi.localIP().toString().c_str(),
                WiFi.macAddress().c_str());
}

// ─── OMNIX handshake ────────────────────────────────────
bool registerWithOmnix() {
  HTTPClient http;
  http.begin(String(OMNIX_URL) + "/api/esp32/register");
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<512> d;
  d["name"] = DISPLAY_NAME;
  d["board_type"] = BOARD_TYPE;
  d["mac"] = WiFi.macAddress();
  JsonArray caps = d.createNestedArray("capabilities");
  if (!strcmp(BOARD_TYPE, "lights")) {
    caps.add("toggle"); caps.add("set_color"); caps.add("set_brightness");
  } else if (!strcmp(BOARD_TYPE, "rover")) {
    caps.add("drive"); caps.add("emergency_stop");
  } else if (!strcmp(BOARD_TYPE, "sensor")) {
    caps.add("sample");
  }
  String body; serializeJson(d, body);

  int code = http.POST(body);
  if (code != 200) {
    Serial.printf("register failed: HTTP %d\n", code);
    http.end();
    return false;
  }
  String resp = http.getString();
  StaticJsonDocument<256> rd;
  deserializeJson(rd, resp);
  agentId = String((const char*)(rd["agent_id"] | ""));
  Serial.printf("Registered as %s\n", agentId.c_str());
  http.end();
  return agentId.length() > 0;
}

// ─── Commands from OMNIX ────────────────────────────────
void applyCommand(const char* command, JsonObject params) {
  if (!strcmp(BOARD_TYPE, "lights")) {
    if (!strcmp(command, "set_color")) {
      const char* hex = params["color"] | "FFFFFF";
      long v = strtol(hex, NULL, 16);
      lights.r = (v >> 16) & 0xFF;
      lights.g = (v >> 8)  & 0xFF;
      lights.b = v & 0xFF;
      writeLights();
    } else if (!strcmp(command, "toggle")) {
      lights.on = !strcmp(params["state"] | "on", "on");
      lights.brightness = lights.on ? 100 : 0;
      writeLights();
    } else if (!strcmp(command, "set_brightness")) {
      lights.brightness = (int)(params["brightness"] | 50);
      writeLights();
    }
  } else if (!strcmp(BOARD_TYPE, "rover")) {
    if (!strcmp(command, "drive")) {
      int speed = (int)(params["speed"] | 128);
      const char* dir = params["dir"] | "stop";
      if      (!strcmp(dir, "forward"))  { rover.motor_l = rover.motor_r = speed; }
      else if (!strcmp(dir, "backward")) { rover.motor_l = rover.motor_r = -speed; }
      else if (!strcmp(dir, "left"))     { rover.motor_l = -speed; rover.motor_r = speed; }
      else if (!strcmp(dir, "right"))    { rover.motor_l = speed;  rover.motor_r = -speed; }
      else                               { rover.motor_l = rover.motor_r = 0; }
      writeMotors();
    } else if (!strcmp(command, "emergency_stop")) {
      rover.motor_l = rover.motor_r = 0;
      writeMotors();
    }
  } else if (!strcmp(BOARD_TYPE, "sensor")) {
    if (!strcmp(command, "sample")) {
      // Would read actual sensors here
      sensor.temp_c = 20.0 + (random(0, 100) / 10.0);
      sensor.humidity = random(30, 70);
      sensor.motion = random(0, 100) < 15;
    }
  }
}

void pollCommands() {
  if (agentId.isEmpty()) return;
  HTTPClient http;
  http.begin(String(OMNIX_URL) + "/api/esp32/commands/" + agentId);
  int code = http.GET();
  if (code != 200) { http.end(); return; }
  String body = http.getString();
  http.end();

  StaticJsonDocument<768> d;
  DeserializationError err = deserializeJson(d, body);
  if (err) return;
  JsonArray arr = d["commands"].as<JsonArray>();
  for (JsonObject cmd : arr) {
    const char* c = cmd["command"] | "";
    JsonObject p = cmd["params"].isNull() ? d.createNestedObject("_e")
                                          : cmd["params"].as<JsonObject>();
    applyCommand(c, p);
  }
}

// ─── Outputs ────────────────────────────────────────────
void writeLights() {
  float scale = lights.on ? (lights.brightness / 100.0f) : 0;
  ledcWrite(CH_R, (uint8_t)(lights.r * scale));
  ledcWrite(CH_G, (uint8_t)(lights.g * scale));
  ledcWrite(CH_B, (uint8_t)(lights.b * scale));
}

void writeMotors() {
  int l = rover.motor_l, r = rover.motor_r;
  digitalWrite(PIN_MOTOR_L_DIR, l >= 0 ? HIGH : LOW);
  digitalWrite(PIN_MOTOR_R_DIR, r >= 0 ? HIGH : LOW);
  analogWrite(PIN_MOTOR_L_PWM, min(abs(l), 255));
  analogWrite(PIN_MOTOR_R_PWM, min(abs(r), 255));
}

// ─── Telemetry ──────────────────────────────────────────
void sendTelemetry() {
  if (agentId.isEmpty()) return;
  HTTPClient http;
  http.begin(String(OMNIX_URL) + "/api/esp32/telemetry/" + agentId);
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<512> d;
  JsonObject t = d.createNestedObject("telemetry");
  t["rssi_dbm"]     = WiFi.RSSI();
  t["heap_free_kb"] = ESP.getFreeHeap() / 1024;
  t["uptime_s"]     = (int)(millis() / 1000);
  t["ip"]           = WiFi.localIP().toString();

  if (!strcmp(BOARD_TYPE, "lights")) {
    t["on"] = lights.on; t["brightness"] = lights.brightness;
    t["r"] = lights.r; t["g"] = lights.g; t["b"] = lights.b;
  } else if (!strcmp(BOARD_TYPE, "rover")) {
    t["motor_l"] = rover.motor_l; t["motor_r"] = rover.motor_r;
    t["sonar_cm"] = rover.sonar_cm;
  } else if (!strcmp(BOARD_TYPE, "sensor")) {
    t["temp_sensor_c"] = sensor.temp_c;
    t["humidity"] = sensor.humidity;
    t["motion"] = sensor.motion;
  }

  String body; serializeJson(d, body);
  http.POST(body);
  http.end();
}

// ─── Lifecycle ──────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("OMNIX ESP32 firmware v1");

  if (!strcmp(BOARD_TYPE, "lights"))      setupLights();
  else if (!strcmp(BOARD_TYPE, "rover"))  setupRover();
  else if (!strcmp(BOARD_TYPE, "sensor")) setupSensor();

  connectWifi();

  // Retry registration until server is reachable
  while (!registerWithOmnix()) {
    Serial.println("register retry in 3s");
    delay(3000);
  }
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWifi();
  }
  unsigned long now = millis();
  if (now - lastPoll > POLL_PERIOD_MS) {
    pollCommands();
    lastPoll = now;
  }
  if (now - lastTelemetry > TELEMETRY_PERIOD_MS) {
    sendTelemetry();
    lastTelemetry = now;
  }
  delay(20);
}
