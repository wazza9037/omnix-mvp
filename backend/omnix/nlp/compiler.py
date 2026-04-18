"""
NLP compiler — user text → ExecutionPlan.

Rule-based by default, with an optional LLM pass for creative commands.
The rule-based path handles the common 80% of phrasings: takeoff, land,
hover, move, rotate, drive, grip, release, pick up, patrol, scan.

Overall algorithm:

  1. Strip + normalize the input
  2. Split into clauses on sequence markers: "then", " and then ",
     commas before conjunctions, semicolons, "after that"
  3. For each clause, try intents in order; first match wins
  4. A match produces one or more ParsedSteps
  5. Unmatched clauses are recorded in `unparsed_fragments` so the user
     gets useful feedback about what the system couldn't interpret

Conditionals:
  We do one lightweight thing: "if battery below N% return home" scans
  the input first and prepends a pre-check step that the executor can
  short-circuit on. Anything more structural is left for the Behavior
  Tree feature.

LLM hook:
  `compile_via_llm(text, capability_list, state)` is wired as a fallback
  when the rule-based compiler returns zero steps AND an API key is
  present. The stub raises NotImplementedError so we don't accidentally
  ship a broken/costly path.
"""

from __future__ import annotations

import os
import re
from typing import Any

from .models import ExecutionPlan, PlanStep, IssueSeverity
from .patterns import iter_intents, Intent, ParsedStep


# ── Splitting ────────────────────────────────────────────────────────

# Multi-step markers. Ordered from longest to shortest so the longer
# forms match before their sub-strings.
#
# We split aggressively on ", and ", " and then ", "then", ";", and also
# on a bare " and " when the text AFTER it starts with an action verb
# — so "take off and hover" splits cleanly, but "forward and back" (a
# single "back-and-forth" phrase) would still be one clause because
# "back" isn't listed.
_ACTION_VERBS = (
    "take\\s?off|takeoff|launch|liftoff|lift\\s?off|"
    "land|hover|hold|wait|pause|"
    "fly|move|go|travel|head|drive|roll|motor|"
    "turn|rotate|yaw|spin|"
    "return|rtl|rtb|"
    "patrol|scan|survey|"
    "pick|grab|grip|release|open|close|"
    "home|reset|"
    "stop|halt|abort|emergency|e-?stop|"
    "take\\s+(?:a\\s+)?photo|snap|capture|"
    "sample|measure|ping"
)
_SPLITTERS = re.compile(
    r"\s+(?:and\s+then|after\s+that|then|,\s*then)\s+"
    r"|(?:[;])\s*"
    r"|,\s*(?:and\s+)?"
    r"|\s+and\s+(?=(?:" + _ACTION_VERBS + r")\b)",
    re.I,
)


def split_clauses(text: str) -> list[str]:
    if not text.strip():
        return []
    # Protect commas inside parentheses so "(0.3, 0, 0.2)" isn't chopped
    # into fragments. We swap them out for a sentinel, split, then swap back.
    SENT = "\x00"
    protected = []
    out = []
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1; out.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1); out.append(ch)
        elif ch == "," and depth > 0:
            out.append(SENT)
        else:
            out.append(ch)
    safe = "".join(out)
    parts = _SPLITTERS.split(safe.strip())
    return [p.replace(SENT, ",").strip() for p in parts if p and p.strip()]


# ── Loop / repetition pre-processing ─────────────────────────────────

_LOOP_RE = re.compile(
    r"(?P<body>.+?)\s*(?P<count>\d+)\s*(?:times?|x)\b\s*(?P<rest>.*)$",
    re.I,
)


def preprocess_loops(text: str) -> tuple[str, int]:
    """Detect trailing 'N times' and return (text_without_count, count).

    Leaves `text` untouched (count=1) if no match.
    """
    m = re.search(r"\b(\d+)\s*times?\b", text, re.I)
    if not m:
        return text, 1
    # Only strip the count — leave the action verbs intact
    count = int(m.group(1))
    stripped = re.sub(r"\s*\b\d+\s*times?\b\s*", " ", text, flags=re.I).strip()
    return stripped, max(1, min(20, count))     # cap at 20 to keep plans bounded


# ── Conditional pre-check ────────────────────────────────────────────

_BATTERY_COND = re.compile(
    r"if\s+battery\s*(?:is\s+)?(?:below|under|less\s*than|<=?)\s*"
    r"(\d+(?:\.\d+)?)\s*%?\s*[,]?\s*(?:then\s+)?return\s+home",
    re.I,
)


def extract_battery_precheck(text: str) -> tuple[str, float | None]:
    m = _BATTERY_COND.search(text)
    if not m:
        return text, None
    threshold = float(m.group(1))
    cleaned = _BATTERY_COND.sub("", text).strip()
    cleaned = re.sub(r"^\s*(?:and|then|,)\s*", "", cleaned, flags=re.I).strip()
    return cleaned, threshold


# ── The compiler ─────────────────────────────────────────────────────

def compile_to_plan(
    text: str,
    device_id: str,
    device_type: str,
    capability_names: list[str] | None = None,
) -> ExecutionPlan:
    """Compile natural-language `text` into an ExecutionPlan.

    Args:
        text:             raw user input.
        device_id:        stamped on the plan for later execution.
        device_type:      selects which intent patterns apply.
        capability_names: names the device actually supports. Steps with
                          commands outside this list are still emitted
                          but tagged with an ERROR-severity issue, so
                          the UI can surface "device can't do X" clearly.
    """
    cap_set = set(capability_names or [])
    plan = ExecutionPlan.new(device_id=device_id, text=text)

    # Pre-process conditionals that wrap the whole input
    remaining_text, batt_threshold = extract_battery_precheck(text)
    if batt_threshold is not None:
        plan.add_step(
            "_battery_precheck",
            {"min_pct": batt_threshold, "on_fail": "return_home"},
            description=f"If battery < {batt_threshold:.0f}%, return home and abort",
            duration_s=0.2,
        )

    # Pre-process repetition ("fly a square 3 times")
    remaining_text, repeat = preprocess_loops(remaining_text)

    clauses = split_clauses(remaining_text)
    if not clauses:
        plan.add_issue(IssueSeverity.ERROR, "empty_input",
                       "Nothing to do — try 'take off and hover at 5m'.")
        return plan

    for _iter in range(repeat):
        for clause in clauses:
            matched = _match_clause(clause, device_type)
            if not matched:
                plan.unparsed_fragments.append(clause)
                plan.add_issue(
                    IssueSeverity.WARNING, "unparsed_clause",
                    f"Didn't understand: “{clause}” — try simpler phrasing.",
                )
                continue
            for ps in matched:
                step = plan.add_step(
                    command=ps.command, params=dict(ps.params),
                    description=ps.description,
                    duration_s=ps.duration_s, dwell_s=ps.dwell_s,
                )
                if cap_set and ps.command not in cap_set \
                        and not ps.command.startswith("_"):
                    plan.add_issue(
                        IssueSeverity.ERROR, "unsupported_command",
                        f"Device has no '{ps.command}' capability — "
                        f"available: {sorted(cap_set)[:5]}…",
                        step_index=len(plan.steps) - 1,
                    )

    if not plan.steps:
        plan.add_issue(IssueSeverity.ERROR, "no_steps",
                       "Could not compile any steps from the input.")
    return plan


def _match_clause(clause: str, device_type: str) -> list[ParsedStep]:
    """Try every applicable intent; return the first non-empty match."""
    lowered = clause.lower()
    for intent in iter_intents(device_type):
        # Cheap keyword reject — skip the regex if no trigger word present
        if intent.keywords and not any(k in lowered for k in intent.keywords):
            continue
        m = intent.regex.search(clause)
        if m is None:
            continue
        steps = intent.handler(m, clause)
        if steps:
            return steps
    return []


# ── Optional LLM fallback ────────────────────────────────────────────

def llm_available() -> bool:
    """Whether the optional LLM backend is usable.

    True only when BOTH an API key env var is set AND the 'anthropic' or
    'openai' package can be imported. Defaults to False so the product is
    fully functional without any network calls.
    """
    if os.getenv("OMNIX_NLP_DISABLE_LLM", "").lower() in ("1", "true", "yes"):
        return False
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            import anthropic  # type: ignore   # noqa: F401
            return True
        except ImportError:
            return False
    if os.getenv("OPENAI_API_KEY"):
        try:
            import openai  # type: ignore  # noqa: F401
            return True
        except ImportError:
            return False
    return False


def compile_via_llm(*args, **kwargs):
    """Reserved hook for the LLM-backed compiler path.

    Not wired up yet — the rule-based compiler covers our demo
    scenarios. When we turn this on, it will return an ExecutionPlan
    with the same shape, so no other code in the pipeline needs to
    change.
    """
    raise NotImplementedError(
        "LLM compiler path is a reserved hook; enable once an "
        "API key and the 'anthropic' or 'openai' SDK are present.")


# ── Public convenience ──────────────────────────────────────────────

def compile_plan(text: str, device, use_llm: bool = False) -> ExecutionPlan:
    """High-level compile helper that reads what it needs off an OmnixDevice."""
    caps = []
    if hasattr(device, "get_capabilities"):
        try:
            caps = [c.get("name") for c in device.get_capabilities() if c.get("name")]
        except Exception:
            caps = []
    return compile_to_plan(
        text=text,
        device_id=getattr(device, "id", "unknown"),
        device_type=getattr(device, "device_type", "unknown"),
        capability_names=caps,
    )
