/*
 * OMNIX Arduino Firmware — Tier 1 connector
 *
 * Target boards: Arduino Uno / Nano / Mega / Leonardo / RP2040 Pico / Teensy.
 * Wire protocol: newline-terminated JSON frames at 115200 baud.
 *
 * You will probably need to install ArduinoJson (v6.x) via Library Manager.
 *
 * Edit BOARD_TYPE, the pin map for your variant, and flash.
 * The Python side is at backend/connectors/arduino_serial.py.
 *
 * Wire format:
 *   IN   host → mcu:  {"c":"drive","p":{"speed":120,"dir":"forward"}}\n
 *   OUT  mcu  → host: {"t":{"speed":120,"dist":0,"batt":87,...}}\n
 *   OUT  mcu  → host: {"ok":true,"m":"drive forward 120"}\n
 *   OUT  mcu  → host: {"err":"unknown command xyz"}\n
 */

#include <ArduinoJson.h>

// ─── Board variant: rover | arm | lights ────────────────
// Must match the `board_type` you pick in the OMNIX connector config.
#define BOARD_TYPE "rover"

// ─── Pin map (edit for your hardware) ───────────────────

#if defined(__AVR__) || defined(ESP32)
  // Rover: L298N-style H-bridge
  const int PIN_MOTOR_L_PWM = 5;
  const int PIN_MOTOR_L_DIR = 4;
  const int PIN_MOTOR_R_PWM = 6;
  const int PIN_MOTOR_R_DIR = 7;

  // Arm: 5 hobby servos
  const int PIN_J0 = 3;   // base
  const int PIN_J1 = 9;   // shoulder
  const int PIN_J2 = 10;  // elbow
  const int PIN_J3 = 11;  // wrist
  const int PIN_GRIPPER = 12;

  // Lights: RGB LED or WS2812 data
  const int PIN_R = 9;
  const int PIN_G = 10;
  const int PIN_B = 11;

  // Battery voltage divider
  const int PIN_VBAT = A0;
#endif

// ─── Global state ───────────────────────────────────────
unsigned long lastTelemetry = 0;
const unsigned long TELEMETRY_PERIOD_MS = 200;

struct RoverState { int speed = 0; char dir[10] = "stop"; long dist_cm = 0; int heading = 0; };
struct ArmState   { int j0 = 0, j1 = 45, j2 = -30, j3 = 0, gripper = 50; };
struct LightsState { bool on = false; int brightness = 0; char color[8] = "000000"; };

RoverState  rover;
ArmState    arm;
LightsState lights;

#include <Servo.h>
Servo servos[5];

// ─── Helpers ─────────────────────────────────────────────
void sendOk(const char* msg) {
  StaticJsonDocument<160> d;
  d["ok"] = true;
  d["m"] = msg;
  serializeJson(d, Serial);
  Serial.println();
}

void sendErr(const char* msg) {
  StaticJsonDocument<160> d;
  d["err"] = msg;
  serializeJson(d, Serial);
  Serial.println();
}

void sendTelemetry() {
  StaticJsonDocument<256> d;
  JsonObject t = d.createNestedObject("t");

  // Common — battery read (rough)
  int raw = analogRead(PIN_VBAT);
  float vbat = raw * (5.0 / 1023.0) * 3.0;   // assuming 1/3 divider
  t["batt"] = (int)constrain(vbat * 10, 0, 120);

  if (strcmp(BOARD_TYPE, "rover") == 0) {
    t["speed"]   = rover.speed;
    t["dir"]     = rover.dir;
    t["dist_cm"] = rover.dist_cm;
    t["heading"] = rover.heading;
  } else if (strcmp(BOARD_TYPE, "arm") == 0) {
    t["j0"] = arm.j0; t["j1"] = arm.j1; t["j2"] = arm.j2;
    t["j3"] = arm.j3; t["gripper"] = arm.gripper;
  } else if (strcmp(BOARD_TYPE, "lights") == 0) {
    t["on"]         = lights.on;
    t["brightness"] = lights.brightness;
    t["color"]      = lights.color;
  }

  serializeJson(d, Serial);
  Serial.println();
}

// ─── Command handlers ───────────────────────────────────
void doDrive(const char* dir, int speed) {
  strncpy(rover.dir, dir, sizeof(rover.dir) - 1);
  rover.dir[sizeof(rover.dir) - 1] = 0;
  rover.speed = speed;

  int lPWM = 0, rPWM = 0, lDir = LOW, rDir = LOW;
  if (!strcmp(dir, "forward")) { lPWM = rPWM = speed; lDir = rDir = HIGH; }
  else if (!strcmp(dir, "backward")) { lPWM = rPWM = speed; lDir = rDir = LOW; }
  else if (!strcmp(dir, "left"))  { lPWM = speed; rPWM = speed; lDir = LOW;  rDir = HIGH; }
  else if (!strcmp(dir, "right")) { lPWM = speed; rPWM = speed; lDir = HIGH; rDir = LOW; }
  else { lPWM = rPWM = 0; }

  digitalWrite(PIN_MOTOR_L_DIR, lDir);
  digitalWrite(PIN_MOTOR_R_DIR, rDir);
  analogWrite(PIN_MOTOR_L_PWM, lPWM);
  analogWrite(PIN_MOTOR_R_PWM, rPWM);
  sendOk("drive updated");
}

void doEmergencyStop() {
  if (strcmp(BOARD_TYPE, "rover") == 0) {
    analogWrite(PIN_MOTOR_L_PWM, 0);
    analogWrite(PIN_MOTOR_R_PWM, 0);
    rover.speed = 0;
    strcpy(rover.dir, "stop");
  }
  sendOk("stopped");
}

void doMoveJoint(const char* joint, int angle) {
  int idx = -1;
  if      (!strcmp(joint, "j0"))      { arm.j0 = angle; idx = 0; }
  else if (!strcmp(joint, "j1"))      { arm.j1 = angle; idx = 1; }
  else if (!strcmp(joint, "j2"))      { arm.j2 = angle; idx = 2; }
  else if (!strcmp(joint, "j3"))      { arm.j3 = angle; idx = 3; }
  else if (!strcmp(joint, "gripper")){ arm.gripper = angle; idx = 4; }
  if (idx < 0) { sendErr("bad joint"); return; }
  servos[idx].write(constrain(angle + 90, 0, 180));
  sendOk("joint set");
}

void doSetColor(const char* hex) {
  strncpy(lights.color, hex, sizeof(lights.color) - 1);
  lights.color[sizeof(lights.color) - 1] = 0;
  long v = strtol(hex, NULL, 16);
  int r = (v >> 16) & 0xFF, g = (v >> 8) & 0xFF, b = v & 0xFF;
  analogWrite(PIN_R, r);
  analogWrite(PIN_G, g);
  analogWrite(PIN_B, b);
  sendOk("color set");
}

void doToggle(const char* state) {
  lights.on = (strcmp(state, "on") == 0);
  if (!lights.on) { analogWrite(PIN_R, 0); analogWrite(PIN_G, 0); analogWrite(PIN_B, 0); }
  else            { doSetColor(lights.color); }
  sendOk(lights.on ? "on" : "off");
}

void doSetBrightness(int b) {
  lights.brightness = constrain(b, 0, 100);
  sendOk("brightness set");
}

// ─── Command dispatch ───────────────────────────────────
void handleCommand(const char* cmd, JsonObject params) {
  if      (!strcmp(cmd, "ping"))            sendOk("pong");
  else if (!strcmp(cmd, "emergency_stop"))  doEmergencyStop();
  // Rover
  else if (!strcmp(cmd, "drive") && !strcmp(BOARD_TYPE, "rover"))
    doDrive(params["dir"] | "stop", (int)(params["speed"] | 0));
  // Arm
  else if (!strcmp(cmd, "move_joint") && !strcmp(BOARD_TYPE, "arm"))
    doMoveJoint(params["joint"] | "j0", (int)(params["angle"] | 0));
  // Lights
  else if (!strcmp(cmd, "set_color")      && !strcmp(BOARD_TYPE, "lights"))
    doSetColor(params["color"] | "FFFFFF");
  else if (!strcmp(cmd, "toggle")         && !strcmp(BOARD_TYPE, "lights"))
    doToggle(params["state"] | "on");
  else if (!strcmp(cmd, "set_brightness") && !strcmp(BOARD_TYPE, "lights"))
    doSetBrightness((int)(params["brightness"] | 50));
  else
    sendErr("unknown command");
}

// ─── Arduino lifecycle ──────────────────────────────────
void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 2000) {}

  if (strcmp(BOARD_TYPE, "rover") == 0) {
    pinMode(PIN_MOTOR_L_PWM, OUTPUT); pinMode(PIN_MOTOR_L_DIR, OUTPUT);
    pinMode(PIN_MOTOR_R_PWM, OUTPUT); pinMode(PIN_MOTOR_R_DIR, OUTPUT);
  } else if (strcmp(BOARD_TYPE, "arm") == 0) {
    servos[0].attach(PIN_J0);
    servos[1].attach(PIN_J1);
    servos[2].attach(PIN_J2);
    servos[3].attach(PIN_J3);
    servos[4].attach(PIN_GRIPPER);
  } else if (strcmp(BOARD_TYPE, "lights") == 0) {
    pinMode(PIN_R, OUTPUT); pinMode(PIN_G, OUTPUT); pinMode(PIN_B, OUTPUT);
  }

  // Hello line
  Serial.println("{\"hello\":\"omnix-arduino\",\"version\":1,\"board\":\"" BOARD_TYPE "\"}");
}

void loop() {
  // Parse any incoming lines
  static String buf = "";
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (buf.length() > 0) {
        StaticJsonDocument<256> d;
        DeserializationError err = deserializeJson(d, buf);
        if (err) {
          sendErr("bad json");
        } else {
          const char* cmd = d["c"] | "";
          JsonObject p = d["p"].isNull() ? d.createNestedObject("_empty")
                                         : d["p"].as<JsonObject>();
          handleCommand(cmd, p);
        }
        buf = "";
      }
    } else if (c != '\r' && buf.length() < 220) {
      buf += c;
    }
  }

  // Periodic telemetry
  if (millis() - lastTelemetry > TELEMETRY_PERIOD_MS) {
    sendTelemetry();
    lastTelemetry = millis();
  }
}
