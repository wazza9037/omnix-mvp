"""
Rule-based intent patterns per device family.

The compiler tries each pattern in order until one matches. A successful
match produces one or more concrete commands, each with parameters
extracted from the input string.

Design goals:

  * Cover the common 80% of phrasings a user will actually type.
  * Stay understandable — every pattern is a plain regex + a tiny callback.
  * Allow the same intent ("take off to 5m") to be spelled multiple ways
    ("takeoff", "launch to 5 meters", "fly up to 5m altitude").
  * Return a list of steps — "patrol a square" expands into a whole
    movement sequence inside one intent.

Each Intent is tagged with:
  - `applies_to`: set of device_types it can fire for (or None for any)
  - `keywords`: quick-reject words a clause must contain to even try the
    regex — avoids O(patterns) regex compilation on every clause

The compiler gets a helper `iter_intents(device_type)` that yields only
the intents applicable to the active device.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable


# ── Parameter extractors ─────────────────────────────────────────────

# Numbers with units
_DIST_PATTERNS = [
    (r"(-?\d+(?:\.\d+)?)\s*(?:m\b|meters?|metres?)", 1.0),
    (r"(-?\d+(?:\.\d+)?)\s*(?:cm|centimet(?:er|re)s?)", 0.01),
    (r"(-?\d+(?:\.\d+)?)\s*(?:ft|feet|foot)", 0.3048),
]

_TIME_PATTERNS = [
    (r"(\d+(?:\.\d+)?)\s*(?:ms|millisec(?:ond)?s?)", 0.001),
    (r"(\d+(?:\.\d+)?)\s*(?:s(?:ec(?:ond)?s?)?)\b", 1.0),
    (r"(\d+(?:\.\d+)?)\s*(?:min(?:ute)?s?)\b", 60.0),
]

_ANGLE_PATTERNS = [
    (r"(-?\d+(?:\.\d+)?)\s*(?:°|deg(?:rees?)?)", 1.0),
    (r"(-?\d+(?:\.\d+)?)\s*(?:rad(?:ians?)?)", 180.0 / math.pi),
]


def extract_distance(text: str, default: float = 1.0) -> float:
    for patt, factor in _DIST_PATTERNS:
        m = re.search(patt, text, re.I)
        if m:
            return float(m.group(1)) * factor
    # Bare number inside "by N"/"N meters"/etc — last-resort bare float
    m = re.search(r"\b(-?\d+(?:\.\d+)?)\b", text)
    if m:
        return float(m.group(1))
    return default


def extract_duration(text: str, default: float = 2.0) -> float:
    for patt, factor in _TIME_PATTERNS:
        m = re.search(patt, text, re.I)
        if m:
            return float(m.group(1)) * factor
    return default


def extract_angle(text: str, default: float = 90.0) -> float:
    for patt, factor in _ANGLE_PATTERNS:
        m = re.search(patt, text, re.I)
        if m:
            return float(m.group(1)) * factor
    # Bare integer — assume degrees
    m = re.search(r"\b(-?\d+(?:\.\d+)?)\b", text)
    if m:
        return float(m.group(1))
    return default


def extract_coords(text: str) -> list[float] | None:
    """Match (x, y) or (x, y, z) — with parentheses, commas, or just spaces."""
    # Try parenthesized first: (x, y, z)
    m = re.search(
        r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)"
        r"(?:\s*,\s*(-?\d+(?:\.\d+)?))?\s*\)", text)
    if m:
        xs = m.group(1, 2, 3)
        out = [float(x) for x in xs if x is not None]
        while len(out) < 3:
            out.append(0.0)
        return out
    # Try space-separated after "position" or "at": position 0.3 0 0.2
    m2 = re.search(
        r"(?:position|at|to|coords?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)"
        r"(?:\s+(-?\d+(?:\.\d+)?))?", text, re.I)
    if m2:
        xs = m2.group(1, 2, 3)
        out = [float(x) for x in xs if x is not None]
        while len(out) < 3:
            out.append(0.0)
        return out
    return None


def extract_count(text: str, default: int = 1) -> int:
    """Match '3 times', 'twice', 'three times', '5x'."""
    m = re.search(r"(\d+)\s*(?:times?|x)\b", text, re.I)
    if m:
        return int(m.group(1))
    # Bare "twice" / "thrice" — no "times" required
    bare = {"twice": 2, "thrice": 3}
    for w, n in bare.items():
        if re.search(rf"\b{w}\b", text, re.I):
            return n
    # Word followed by "times": "three times"
    word_n = {"once": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
              "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    for w, n in word_n.items():
        if re.search(rf"\b{w}\s+times?\b", text, re.I):
            return n
    return default


# ── Intent definition ────────────────────────────────────────────────

@dataclass
class ParsedStep:
    """One step returned from an intent handler."""
    command: str
    params: dict
    description: str = ""
    duration_s: float = 1.0
    dwell_s: float = 0.0


@dataclass
class Intent:
    name: str
    regex: re.Pattern
    handler: Callable[[re.Match, str], list[ParsedStep]]
    applies_to: set[str] | None = None     # device types (None = any)
    keywords: list[str] = field(default_factory=list)
    help: str = ""


# ── Drone intents ────────────────────────────────────────────────────

def _takeoff(m, text):
    alt = extract_distance(text, default=5.0)
    return [ParsedStep("takeoff", {"altitude_m": alt},
                       description=f"Take off to {alt:.1f} m",
                       duration_s=max(1.5, alt * 0.4))]


def _land(m, text):
    return [ParsedStep("land", {},
                       description="Land at current location",
                       duration_s=2.5)]


def _hover(m, text):
    d = extract_duration(text, default=3.0)
    return [ParsedStep("hover", {"duration_s": d},
                       description=f"Hover for {d:.1f} s",
                       duration_s=0.3, dwell_s=d)]


_DIRECTIONS_3D = {
    "forward": "forward", "fwd": "forward", "ahead": "forward",
    "back": "backward", "backward": "backward", "backwards": "backward",
    "left": "left",
    "right": "right",
    "up": "up", "upward": "up", "upwards": "up",
    "down": "down", "downward": "down", "downwards": "down",
    "north": "forward", "south": "backward",
    "east": "right", "west": "left",
}


def _move_dir(m, text):
    dir_word = m.group(1).lower()
    direction = _DIRECTIONS_3D.get(dir_word, "forward")
    dist = extract_distance(text, default=2.0)
    return [ParsedStep("move",
                       {"direction": direction, "distance_m": dist},
                       description=f"Move {direction} {dist:.1f} m",
                       duration_s=max(1.0, dist * 0.6))]


def _rotate_dir(m, text):
    # "turn left" / "rotate 90 degrees" / "spin right 45 degrees"
    lower = text.lower()
    signed = 1
    if re.search(r"\b(left|ccw|counter\s*-?\s*clockwise|anti\s*-?\s*clockwise)\b", lower):
        signed = 1           # positive yaw = left in our convention
    elif re.search(r"\b(right|cw|clockwise)\b", lower):
        signed = -1
    deg = extract_angle(text, default=90.0)
    deg = signed * abs(deg)
    return [ParsedStep("rotate", {"degrees": deg},
                       description=f"Rotate {deg:+.0f}°",
                       duration_s=max(1.0, abs(deg) / 90.0 * 2.0))]


def _return_home(m, text):
    return [ParsedStep("return_home", {},
                       description="Return to launch",
                       duration_s=4.0)]


def _take_photo(m, text):
    return [ParsedStep("take_photo", {},
                       description="Capture a photo",
                       duration_s=0.4)]


def _goto_coords(m, text):
    coords = extract_coords(text)
    if not coords:
        return []
    x, y, z = coords
    return [ParsedStep("goto",
                       {"x": x, "y": y, "altitude_m": z if z != 0 else 5.0},
                       description=f"Fly to ({x:.1f}, {y:.1f}, {z:.1f})",
                       duration_s=max(2.0, math.hypot(x, y) * 0.5))]


def _patrol_square(m, text):
    side = extract_distance(text, default=4.0)
    alt = 5.0
    # allow "at 3 meters altitude"
    m_alt = re.search(r"at\s+(\d+(?:\.\d+)?)\s*(?:m|meters?|metres?)"
                       r"(?:\s+(?:altitude|high))?", text, re.I)
    if m_alt:
        alt = float(m_alt.group(1))
    count = extract_count(text, default=1)

    per_lap = [
        ParsedStep("takeoff", {"altitude_m": alt},
                   description=f"Take off to {alt:.1f} m",
                   duration_s=max(1.5, alt * 0.4)),
    ]
    for _ in range(count):
        for d in ("forward", "right", "backward", "left"):
            per_lap.append(ParsedStep(
                "move", {"direction": d, "distance_m": side},
                description=f"Move {d} {side:.1f} m",
                duration_s=max(1.0, side * 0.5)))
    per_lap.append(ParsedStep("hover", {"duration_s": 1.0},
                              description="Hold at start",
                              duration_s=0.3, dwell_s=1.0))
    return per_lap


def _scan_area(m, text):
    return [
        ParsedStep("take_photo", {}, description="Scan photo 1", duration_s=0.3),
        ParsedStep("rotate", {"degrees": 90},
                   description="Yaw 90°", duration_s=1.0),
        ParsedStep("take_photo", {}, description="Scan photo 2", duration_s=0.3),
        ParsedStep("rotate", {"degrees": 90},
                   description="Yaw 90°", duration_s=1.0),
        ParsedStep("take_photo", {}, description="Scan photo 3", duration_s=0.3),
        ParsedStep("rotate", {"degrees": 90},
                   description="Yaw 90°", duration_s=1.0),
        ParsedStep("take_photo", {}, description="Scan photo 4", duration_s=0.3),
    ]


# ── Rover intents ────────────────────────────────────────────────────

def _drive(m, text):
    dir_word = (m.group(1) if m.lastindex else "forward").lower()
    direction = _DIRECTIONS_3D.get(dir_word, "forward")
    if direction in ("up", "down"):
        direction = "forward"     # rovers can't fly
    dist = extract_distance(text, default=1.0)
    speed = 50.0
    m_sp = re.search(r"at\s+(\d+(?:\.\d+)?)\s*(?:%|percent|pct)?(?!\s*(?:m|cm))", text, re.I)
    if m_sp:
        speed = min(100.0, float(m_sp.group(1)))
    duration_s = max(1.0, dist / (speed * 0.01) * 2.0)
    return [ParsedStep("drive",
                       {"direction": direction, "speed": speed,
                        "duration_ms": int(duration_s * 1000)},
                       description=f"Drive {direction} {dist:.1f} m @ {speed:.0f}%",
                       duration_s=duration_s)]


def _stop(m, text):
    return [ParsedStep("emergency_stop", {},
                       description="Stop all motors",
                       duration_s=0.2)]


def _rover_turn(m, text):
    """Rovers don't have a `rotate` command — they turn via differential
    drive (drive left or drive right). This intent maps "turn right 90°"
    on a ground robot to a short drive in that direction.
    """
    lower = text.lower()
    if re.search(r"\bleft\b", lower) or "ccw" in lower or "counter" in lower:
        direction = "left"
    else:
        direction = "right"
    angle = extract_angle(text, default=90.0)
    # In the sim, differential-drive turns at ~30°/s at default speed
    duration_s = max(0.3, abs(angle) / 30.0)
    return [ParsedStep(
        "drive",
        {"direction": direction, "speed": 50,
         "duration_ms": int(duration_s * 1000)},
        description=f"Turn {direction} {abs(angle):.0f}°",
        duration_s=duration_s,
    )]


# ── Arm intents ──────────────────────────────────────────────────────

def _home_arm(m, text):
    return [ParsedStep("go_home", {},
                       description="Return to home pose",
                       duration_s=2.0)]


def _grip(m, text):
    force = 50.0
    m_f = re.search(r"(?:force|pressure)\s*(?:of)?\s*(\d+)", text, re.I)
    if m_f:
        force = float(m_f.group(1))
    return [ParsedStep("grip", {"force": force},
                       description=f"Close gripper (force {force:.0f})",
                       duration_s=0.8)]


def _release(m, text):
    return [ParsedStep("release", {},
                       description="Open gripper",
                       duration_s=0.6)]


def _move_joint(m, text):
    m_j = re.search(r"joint\s*(\d+|j\d+)", text, re.I)
    joint_idx = 0
    if m_j:
        token = m_j.group(1).lstrip("jJ")
        try: joint_idx = int(token)
        except ValueError: joint_idx = 0
    angle = extract_angle(text, default=0.0)
    return [ParsedStep("move_joint",
                       {"joint_index": joint_idx, "angle_deg": angle},
                       description=f"Joint {joint_idx} → {angle:+.0f}°",
                       duration_s=1.0)]


def _move_to_position(m, text):
    coords = extract_coords(text)
    if not coords:
        return []
    return [
        ParsedStep("move_joint", {"joint_index": 0,
                                  "angle_deg": math.degrees(math.atan2(coords[1], coords[0]))},
                   description=f"Orient base toward ({coords[0]:.2f}, {coords[1]:.2f}, {coords[2]:.2f})",
                   duration_s=1.0),
        ParsedStep("move_joint", {"joint_index": 1,
                                  "angle_deg": math.degrees(math.atan2(coords[2], math.sqrt(coords[0]**2 + coords[1]**2)))},
                   description=f"Adjust shoulder to reach height {coords[2]:.2f}",
                   duration_s=1.0),
    ]


def _pick_at(m, text):
    coords = extract_coords(text)
    if not coords:
        coords = [0.3, 0.0, 0.1]  # Default pick position in front of arm
    return [
        ParsedStep("release", {},
                   description="Open gripper for approach",
                   duration_s=0.5),
        ParsedStep("move_joint", {"joint_index": 0,
                                  "angle_deg": math.degrees(math.atan2(coords[1], coords[0]))},
                   description=f"Orient base toward pick target",
                   duration_s=1.0),
        ParsedStep("grip", {"force": 60},
                   description="Grip object",
                   duration_s=0.8),
        ParsedStep("go_home", {},
                   description="Lift to home pose",
                   duration_s=1.5),
    ]


# ── Universal intents ───────────────────────────────────────────────

def _emergency(m, text):
    return [ParsedStep("emergency_stop", {},
                       description="EMERGENCY STOP",
                       duration_s=0.1)]


def _scan_sensor(m, text):
    return [ParsedStep("scan", {},
                       description="Sample sensor",
                       duration_s=0.3)]


def _ping(m, text):
    return [ParsedStep("ping", {},
                       description="Heartbeat ping",
                       duration_s=0.1)]


# ── Intent table ─────────────────────────────────────────────────────

DRONE_TYPES = {"drone"}
ROVER_TYPES = {"ground_robot"}
ARM_TYPES = {"robot_arm"}
LEGGED_TYPES = {"legged", "humanoid"}
MARINE_TYPES = {"marine"}

# Order matters — more specific patterns must come BEFORE more general ones.
INTENTS: list[Intent] = [
    # ── Drone (and fixed-wing) ──────────────────────────────
    Intent(
        name="patrol_square",
        regex=re.compile(r"\b(?:patrol|fly|trace)\b.*\b(?:square|rectangle|perimeter|loop)\b", re.I),
        handler=_patrol_square,
        applies_to=DRONE_TYPES,
        keywords=["patrol", "square", "perimeter", "loop"],
        help="patrol a square [of side N m] [at altitude H m] [3 times]",
    ),
    Intent(
        name="scan_area",
        regex=re.compile(r"\b(?:scan|survey)\b.*\b(?:area|surroundings|around)\b", re.I),
        handler=_scan_area,
        applies_to=DRONE_TYPES,
        keywords=["scan", "survey", "area"],
        help="scan the area",
    ),
    Intent(
        name="takeoff",
        regex=re.compile(r"\b(take\s*off|takeoff|launch|lift\s*off|liftoff)\b", re.I),
        handler=_takeoff,
        applies_to=DRONE_TYPES,
        keywords=["take", "takeoff", "launch", "lift"],
        help="take off [to N meters]",
    ),
    Intent(
        name="land",
        regex=re.compile(r"\b(land|touch\s*down|set\s*down)\b", re.I),
        handler=_land,
        applies_to=DRONE_TYPES | MARINE_TYPES,
        keywords=["land", "touch", "set"],
        help="land",
    ),
    Intent(
        name="hover",
        regex=re.compile(r"\b(hover|hold\s*position|wait|pause)\b", re.I),
        handler=_hover,
        applies_to=DRONE_TYPES | MARINE_TYPES,
        keywords=["hover", "hold", "wait", "pause"],
        help="hover [for N seconds]",
    ),
    Intent(
        name="return_home",
        regex=re.compile(r"\b(return|come)\s*(?:home|to\s*(?:home|launch|base))\b|\brtl\b|\brtb\b", re.I),
        handler=_return_home,
        applies_to=DRONE_TYPES | ROVER_TYPES | MARINE_TYPES,
        keywords=["return", "home", "launch", "base", "rtl", "rtb"],
        help="return home",
    ),
    Intent(
        name="goto_coords",
        regex=re.compile(
            r"\b(?:go|fly|move)\s*to\b|\bat\s*\("
            r"|\((-?\d+).*\)", re.I),
        handler=_goto_coords,
        applies_to=DRONE_TYPES | MARINE_TYPES,
        keywords=["go", "fly", "move", "to"],
        help="fly to (x, y, z)",
    ),
    Intent(
        name="move_dir",
        regex=re.compile(
            r"\b(?:fly|move|go|travel|head)\b.*?"
            r"\b(forward|back(?:ward)?s?|left|right|up|down|north|south|east|west|ahead|fwd)\b",
            re.I),
        handler=_move_dir,
        applies_to=DRONE_TYPES | MARINE_TYPES,
        keywords=["fly", "move", "go", "travel", "head"],
        help="fly forward/back/left/right/up/down [N meters]",
    ),
    # Rover turns first — more specific (applies_to=ROVER only)
    Intent(
        name="rover_turn",
        regex=re.compile(r"\b(turn|rotate|spin|face)\b", re.I),
        handler=_rover_turn,
        applies_to=ROVER_TYPES,
        keywords=["turn", "rotate", "spin", "face"],
        help="turn left/right [N degrees]",
    ),
    Intent(
        name="rotate",
        regex=re.compile(r"\b(turn|rotate|yaw|spin|face)\b", re.I),
        handler=_rotate_dir,
        applies_to=DRONE_TYPES | LEGGED_TYPES,
        keywords=["turn", "rotate", "yaw", "spin", "face"],
        help="turn left/right [N degrees]",
    ),
    Intent(
        name="take_photo",
        regex=re.compile(
            r"\b(take\s*(?:a\s*)?pho(?:to|tograph)|snap(?:\s*a\s*pic)?|capture\s+(?:image|photo))\b",
            re.I),
        handler=_take_photo,
        applies_to=DRONE_TYPES | ROVER_TYPES | LEGGED_TYPES,
        keywords=["photo", "photograph", "snap", "capture"],
        help="take a photo",
    ),

    # ── Rover / ground robot ────────────────────────────────
    Intent(
        name="drive",
        regex=re.compile(
            r"\b(?:drive|roll|motor)\b.*?"
            r"\b(forward|back(?:ward)?s?|left|right|ahead|fwd|up|down)\b",
            re.I),
        handler=_drive,
        applies_to=ROVER_TYPES | LEGGED_TYPES,
        keywords=["drive", "roll", "motor"],
        help="drive forward/back [N m]",
    ),
    Intent(
        name="stop",
        regex=re.compile(r"^\s*stop\b|\bhalt\b|\bfreeze\b", re.I),
        handler=_stop,
        applies_to=None,
        keywords=["stop", "halt", "freeze"],
        help="stop",
    ),

    # ── Arm ─────────────────────────────────────────────────
    Intent(
        name="pick_at",
        regex=re.compile(r"\bpick\s*up\b|\bgrab\s+(?:the\s+)?object\b", re.I),
        handler=_pick_at,
        applies_to=ARM_TYPES,
        keywords=["pick", "grab"],
        help="pick up at (x, y, z)",
    ),
    Intent(
        name="home_arm",
        regex=re.compile(r"\b(?:go\s*home|home\s*pose|return\s*(?:to\s*)?home|reset\s*pose)\b", re.I),
        handler=_home_arm,
        applies_to=ARM_TYPES,
        keywords=["home", "reset"],
        help="go home",
    ),
    Intent(
        name="grip",
        regex=re.compile(r"\b(grip|close\s*(?:the\s*)?gripper|grab)\b(?!\s+object)", re.I),
        handler=_grip,
        applies_to=ARM_TYPES,
        keywords=["grip", "close", "grab"],
        help="grip [with force N]",
    ),
    Intent(
        name="release",
        regex=re.compile(r"\b(release|open\s*(?:the\s*)?gripper|let\s*go|drop)\b", re.I),
        handler=_release,
        applies_to=ARM_TYPES,
        keywords=["release", "open", "let", "drop"],
        help="release / open gripper",
    ),
    Intent(
        name="move_to_position",
        regex=re.compile(r"\b(?:move|go)\s+to\s+(?:position|point|coords?|location)\b", re.I),
        handler=_move_to_position,
        applies_to=ARM_TYPES,
        keywords=["move", "position", "coords"],
        help="move to position x y z",
    ),
    Intent(
        name="move_joint",
        regex=re.compile(r"\b(?:move|set|rotate)\s*(?:the\s*)?joint\b", re.I),
        handler=_move_joint,
        applies_to=ARM_TYPES,
        keywords=["joint", "move"],
        help="move joint N to A degrees",
    ),

    # ── Universal ──────────────────────────────────────────
    Intent(
        name="emergency",
        regex=re.compile(r"\b(emergency|e-?stop|abort|kill\s*switch|panic)\b", re.I),
        handler=_emergency,
        applies_to=None,
        keywords=["emergency", "estop", "e-stop", "abort", "kill", "panic"],
        help="emergency stop",
    ),
    Intent(
        name="scan_sensor",
        regex=re.compile(r"\b(scan|sample|measure)\b(?!\s+(?:the\s+)?area)", re.I),
        handler=_scan_sensor,
        applies_to=None,
        keywords=["scan", "sample", "measure"],
        help="scan (sample sensor)",
    ),
    Intent(
        name="ping",
        regex=re.compile(r"^\s*(?:ping|heartbeat|are\s*you\s*(?:there|alive))\s*$", re.I),
        handler=_ping,
        applies_to=None,
        keywords=["ping", "heartbeat", "alive"],
        help="ping",
    ),
]


def iter_intents(device_type: str):
    """Yield intents applicable to the given device_type."""
    for intent in INTENTS:
        if intent.applies_to is None or device_type in intent.applies_to:
            yield intent


def list_capabilities_for_device(device_type: str) -> list[dict]:
    """Return a frontend-friendly list of example phrases for a device type.

    Powers the command-bar autocomplete.
    """
    out = []
    for intent in iter_intents(device_type):
        out.append({
            "name": intent.name,
            "help": intent.help,
            "keywords": list(intent.keywords)[:4],
        })
    return out
