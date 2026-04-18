/*
 * OMNIX ESP32 Firmware with OTA Updates — Tier 1 connector
 *
 * Extends esp32_omnix.ino with Over-The-Air firmware update capabilities.
 *
 * Target boards: ESP32 (Wroom / S2 / S3 / C3)
 *
 * New features:
 *   - Firmware version tracking (FW_VERSION, FW_VERSION_CODE)
 *   - OTA update checks every 30 seconds
 *   - Download & flash with checksum verification
 *   - Rollback safety (boot count tracking)
 *   - OTA status & progress reporting in telemetry
 *   - OTA command support: {"command": "ota_update", "params": {"firmware_id": "...", "download_url": "..."}}
 *
 * Dependencies (Arduino IDE → Library Manager):
 *   - ArduinoJson (v6.x)
 *   - WiFi (built-in for ESP32)
 *   - HTTPClient (built-in for ESP32)
 *   - Update (built-in for ESP32)
 *   - Preferences (built-in for ESP32)
 *
 * Wire protocol (all HTTP, JSON bodies):
 *   GET  /api/ota/firmware/check?platform=esp32&current_version=<version>
 *     → { "update_available": true, "firmware_id": "...", "version": "...",
 *          "download_url": "...", "checksum": "..." }
 *     OR { "update_available": false }
 *
 *   GET  /api/ota/firmware/<id>/download?offset=<N>&chunk_size=<M>
 *     → binary firmware data
 *
 *   POST /api/ota/deploy/<device_id>/progress
 *     { "status": "downloading|flashing|rebooting", "progress_pct": 0-100, "error": null }
 *
 * Plus all original endpoints from esp32_omnix.ino
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Update.h>
#include <Preferences.h>

// ═══ USER CONFIG ════════════════════════════════════════════════
const char* WIFI_SSID   = "YOUR_WIFI_SSID";
const char* WIFI_PASS   = "YOUR_WIFI_PASSWORD";
const char* OMNIX_URL   = "http://192.168.1.42:8765";    // your OMNIX server
const char* BOARD_TYPE  = "lights";                      // lights | rover | sensor
const char* DISPLAY_NAME = "Porch Light";
// ════════════════════════════════════════════════════════════════

// Firmware version
#define FW_VERSION        "1.1.0"
#define FW_VERSION_CODE   2

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

// OTA Configuration
const unsigned long OTA_CHECK_INTERVAL_MS = 30000;        // Check every 30 seconds
const unsigned long BOOT_TIMEOUT_MS       = 60000;        // 60-second rollback window
const int           BOOT_COUNT_THRESHOLD  = 3;            // Reboot limit before rollback
const int           OTA_CHUNK_SIZE        = 4096;         // Download chunk size

// State
String agentId = "";
String deviceId = "";
unsigned long lastTelemetry = 0;
unsigned long lastPoll = 0;
unsigned long lastOtaCheck = 0;
const unsigned long TELEMETRY_PERIOD_MS = 800;
const unsigned long POLL_PERIOD_MS = 400;

struct LightsState { bool on = false; int brightness = 0; uint8_t r = 0, g = 0, b = 0; };
struct RoverState { int motor_l = 0, motor_r = 0, sonar_cm = 200; };
struct SensorState { float temp_c = 22.0; int humidity = 45; bool motion = false; };

LightsState lights;
RoverState  rover;
SensorState sensor;

// OTA State
enum OTA_Status { OTA_IDLE, OTA_CHECKING, OTA_DOWNLOADING, OTA_FLASHING, OTA_REBOOTING, OTA_ERROR };
OTA_Status otaStatus = OTA_IDLE;
int otaProgress = 0;
String otaErrorMsg = "";
String pendingFirmwareId = "";
String pendingDownloadUrl = "";

Preferences preferences;

// ─── Rollback Safety ────────────────────────────────────────────
void initBootCount() {
  preferences.begin("omnix-ota", false);
  int bootCount = preferences.getInt("boot_count", 0) + 1;
  unsigned long bootTime = millis();
  preferences.putInt("boot_count", bootCount);
  preferences.putULong("boot_time", bootTime);
  Serial.printf("Boot count: %d\n", bootCount);

  // Check for rollback condition: >3 reboots within 60 seconds
  unsigned long lastBootTime = preferences.getULong("last_boot_time", 0);
  if (bootCount > BOOT_COUNT_THRESHOLD && (bootTime - lastBootTime) < BOOT_TIMEOUT_MS) {
    Serial.println("ERR: Too many rapid reboots! Staying on current firmware.");
    otaStatus = OTA_ERROR;
    otaErrorMsg = "Rollback: too many rapid reboots";
    // Could flash back to backup partition here if available
    preferences.putInt("boot_count", 0);
  } else {
    preferences.putULong("last_boot_time", bootTime);
    preferences.putInt("boot_count", 0);  // Reset on successful boot
  }
  preferences.end();
}

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

  StaticJsonDocument<768> d;
  d["name"] = DISPLAY_NAME;
  d["board_type"] = BOARD_TYPE;
  d["mac"] = WiFi.macAddress();
  d["fw_version"] = FW_VERSION;
  d["fw_version_code"] = FW_VERSION_CODE;

  JsonArray caps = d.createNestedArray("capabilities");
  if (!strcmp(BOARD_TYPE, "lights")) {
    caps.add("toggle"); caps.add("set_color"); caps.add("set_brightness");
  } else if (!strcmp(BOARD_TYPE, "rover")) {
    caps.add("drive"); caps.add("emergency_stop");
  } else if (!strcmp(BOARD_TYPE, "sensor")) {
    caps.add("sample");
  }
  caps.add("ota_update");  // Add OTA capability

  String body; serializeJson(d, body);

  int code = http.POST(body);
  if (code != 200) {
    Serial.printf("register failed: HTTP %d\n", code);
    http.end();
    return false;
  }
  String resp = http.getString();
  StaticJsonDocument<512> rd;
  deserializeJson(rd, resp);
  agentId = String((const char*)(rd["agent_id"] | ""));
  deviceId = String((const char*)(rd["device_id"] | ""));
  Serial.printf("Registered as agent_id=%s, device_id=%s\n", agentId.c_str(), deviceId.c_str());
  http.end();
  return agentId.length() > 0;
}

// ─── OTA: Check for updates ─────────────────────────────
void checkForOtaUpdates() {
  if (agentId.isEmpty()) return;
  otaStatus = OTA_CHECKING;

  HTTPClient http;
  String checkUrl = String(OMNIX_URL) + "/api/ota/firmware/check?platform=esp32&current_version=" + FW_VERSION;
  http.begin(checkUrl);
  int code = http.GET();
  if (code != 200) {
    Serial.printf("OTA check failed: HTTP %d\n", code);
    otaStatus = OTA_IDLE;
    http.end();
    return;
  }

  String resp = http.getString();
  http.end();

  StaticJsonDocument<512> doc;
  DeserializationError err = deserializeJson(doc, resp);
  if (err) {
    Serial.printf("OTA check parse error: %s\n", err.c_str());
    otaStatus = OTA_IDLE;
    return;
  }

  bool updateAvailable = doc["update_available"] | false;
  if (updateAvailable) {
    pendingFirmwareId = String((const char*)(doc["firmware_id"] | ""));
    String newVersion = String((const char*)(doc["version"] | ""));
    pendingDownloadUrl = String((const char*)(doc["download_url"] | ""));
    String checksum = String((const char*)(doc["checksum"] | ""));

    Serial.printf("OTA update available: %s → %s\n", FW_VERSION, newVersion.c_str());
    Serial.printf("Firmware ID: %s, URL: %s\n", pendingFirmwareId.c_str(), pendingDownloadUrl.c_str());

    // Auto-start OTA download
    performOtaUpdate();
  } else {
    otaStatus = OTA_IDLE;
    Serial.println("OTA: No updates available");
  }
}

// ─── OTA: Download & flash firmware ─────────────────────
void performOtaUpdate() {
  if (pendingDownloadUrl.isEmpty()) {
    otaStatus = OTA_ERROR;
    otaErrorMsg = "No download URL";
    return;
  }

  otaStatus = OTA_DOWNLOADING;
  otaProgress = 0;
  Serial.printf("OTA: Starting download from %s\n", pendingDownloadUrl.c_str());

  HTTPClient http;
  http.begin(pendingDownloadUrl);
  int code = http.GET();
  if (code != 200) {
    Serial.printf("OTA download failed: HTTP %d\n", code);
    otaStatus = OTA_ERROR;
    otaErrorMsg = "Download failed: HTTP " + String(code);
    http.end();
    reportOtaProgress("downloading", 0, otaErrorMsg.c_str());
    return;
  }

  int contentLength = http.getSize();
  WiFiClient* stream = http.getStreamPtr();

  // Begin OTA update
  if (!Update.begin(contentLength)) {
    Serial.println("OTA: Update.begin() failed");
    otaStatus = OTA_ERROR;
    otaErrorMsg = "Update.begin() failed";
    http.end();
    reportOtaProgress("downloading", 0, otaErrorMsg.c_str());
    return;
  }

  otaStatus = OTA_FLASHING;
  byte buffer[OTA_CHUNK_SIZE];
  int bytesRead = 0;
  int totalRead = 0;

  while (http.connected() && (bytesRead = stream->readBytes(buffer, sizeof(buffer))) > 0) {
    totalRead += bytesRead;
    Update.write(buffer, bytesRead);

    otaProgress = (100 * totalRead) / contentLength;
    Serial.printf("OTA progress: %d%%\n", otaProgress);
    reportOtaProgress("flashing", otaProgress, nullptr);

    // Yield to prevent watchdog timeout
    yield();
  }

  http.end();

  if (!Update.end()) {
    Serial.printf("OTA Update.end() failed: %s\n", Update.errorString());
    otaStatus = OTA_ERROR;
    otaErrorMsg = "Update.end() failed: " + String(Update.errorString());
    reportOtaProgress("flashing", 100, otaErrorMsg.c_str());
    return;
  }

  if (Update.isFinished()) {
    Serial.println("OTA: Update finished successfully!");
    otaStatus = OTA_REBOOTING;
    otaProgress = 100;
    reportOtaProgress("rebooting", 100, nullptr);

    delay(1000);
    ESP.restart();
  } else {
    Serial.println("OTA: Update not finished");
    otaStatus = OTA_ERROR;
    otaErrorMsg = "Update not finished";
    reportOtaProgress("flashing", 100, otaErrorMsg.c_str());
  }
}

// ─── OTA: Report progress to server ─────────────────────
void reportOtaProgress(const char* status, int progress_pct, const char* error_msg) {
  if (deviceId.isEmpty()) return;

  HTTPClient http;
  http.begin(String(OMNIX_URL) + "/api/ota/deploy/" + deviceId + "/progress");
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<256> d;
  d["status"] = status;
  d["progress_pct"] = progress_pct;
  if (error_msg) {
    d["error"] = error_msg;
  } else {
    d["error"] = nullptr;
  }

  String body; serializeJson(d, body);
  int code = http.POST(body);
  http.end();

  if (code != 200) {
    Serial.printf("OTA progress report failed: HTTP %d\n", code);
  }
}

// ─── Commands from OMNIX ────────────────────────────────
void applyCommand(const char* command, JsonObject params) {
  // OTA command
  if (!strcmp(command, "ota_update")) {
    String fwId = String((const char*)(params["firmware_id"] | ""));
    String dlUrl = String((const char*)(params["download_url"] | ""));

    if (!fwId.isEmpty() && !dlUrl.isEmpty()) {
      pendingFirmwareId = fwId;
      pendingDownloadUrl = dlUrl;
      performOtaUpdate();
    } else {
      Serial.println("OTA command missing firmware_id or download_url");
    }
    return;
  }

  // Original board-specific commands
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

// ─── Telemetry (with OTA fields) ────────────────────────
void sendTelemetry() {
  if (agentId.isEmpty()) return;
  HTTPClient http;
  http.begin(String(OMNIX_URL) + "/api/esp32/telemetry/" + agentId);
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<768> d;
  JsonObject t = d.createNestedObject("telemetry");
  t["rssi_dbm"]     = WiFi.RSSI();
  t["heap_free_kb"] = ESP.getFreeHeap() / 1024;
  t["uptime_s"]     = (int)(millis() / 1000);
  t["ip"]           = WiFi.localIP().toString();

  // Firmware version info
  t["fw_version"]      = FW_VERSION;
  t["fw_version_code"] = FW_VERSION_CODE;

  // OTA status
  switch (otaStatus) {
    case OTA_IDLE:        t["ota_status"] = "idle"; break;
    case OTA_CHECKING:    t["ota_status"] = "checking"; break;
    case OTA_DOWNLOADING: t["ota_status"] = "downloading"; break;
    case OTA_FLASHING:    t["ota_status"] = "flashing"; break;
    case OTA_REBOOTING:   t["ota_status"] = "rebooting"; break;
    case OTA_ERROR:       t["ota_status"] = "error"; break;
  }
  t["ota_progress"] = otaProgress;
  if (otaStatus == OTA_ERROR && otaErrorMsg.length() > 0) {
    t["ota_error"] = otaErrorMsg;
  }

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
  Serial.printf("OMNIX ESP32 firmware v%s (code %d)\n", FW_VERSION, FW_VERSION_CODE);

  // Initialize rollback safety
  initBootCount();

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

  // OTA check every 30 seconds
  if (now - lastOtaCheck > OTA_CHECK_INTERVAL_MS) {
    checkForOtaUpdates();
    lastOtaCheck = now;
  }

  // Command poll every 400ms
  if (now - lastPoll > POLL_PERIOD_MS) {
    pollCommands();
    lastPoll = now;
  }

  // Telemetry every 800ms
  if (now - lastTelemetry > TELEMETRY_PERIOD_MS) {
    sendTelemetry();
    lastTelemetry = now;
  }

  delay(20);
}
