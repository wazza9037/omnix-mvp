"""
Prompt templates for AI tasks.

Templates designed to maximize useful output from free-tier models by being
explicit, structured, and providing clear examples of expected output format.

All prompts use {placeholder} format for dynamic content injection.
"""

from __future__ import annotations


# ── Robot Classification & Description ──

CLASSIFY_ROBOT_PROMPT = """Analyze this robot image and provide structured information about it.

Your analysis should identify:
1. Robot Type (e.g., drone, arm, wheeled robot, humanoid, etc.)
2. Main Components (motors, joints, wheels, arms, sensors, etc.)
3. Apparent Use Cases (what can it do?)
4. Build Quality Assessment (professional, DIY, commercial, etc.)
5. Key Capabilities (based on visible parts)

Image Properties:
- Size (estimate from visual context): {size_estimate}
- Material (guess from appearance): {material_guess}

Provide structured output with clear sections."""


GENERATE_DESCRIPTION_PROMPT = """Generate a detailed technical description of this robot.

Context:
- Device ID: {device_id}
- Known capabilities: {capabilities}
- Learned parameters: {params_summary}
- Previous observations: {observation_summary}

Write a 2-3 paragraph description that:
1. Summarizes the robot's purpose and main components
2. Describes its movement capabilities and sensor setup
3. Lists key technical specifications we've learned
4. Notes any special features or capabilities

Make it technical but accessible. Include specific parameters where known."""


# ── Physics Estimation ──

ESTIMATE_PHYSICS_PROMPT = """Estimate the physical properties of this robot from its appearance.

Analyze the robot visually and estimate:
1. Mass (kg) - consider size and visible material density
2. Dimensions (height, width, depth in cm)
3. Center of Gravity (rough position: front/center/back)
4. Drag Coefficient (0.0-1.0, based on shape)
5. Max Thrust/Force (estimate from motor size if visible)
6. Friction Coefficient (0.0-1.0, based on materials)
7. Joint Limits (degrees of freedom and angle limits if visible)
8. Wheel/Contact Type (wheels, legs, propellers, etc.)

Robot Info:
- Device Type: {device_type}
- Visual Size: {visual_size}
- Apparent Weight: {apparent_weight}

Output format:
mass_kg: [number]
height_cm: [number]
width_cm: [number]
depth_cm: [number]
center_of_gravity: [front|center|back]
drag_coefficient: [0.0-1.0]
max_thrust_kg: [number]
friction_coefficient: [0.0-1.0]
primary_motion: [type]

Be conservative with estimates. Errors should tend toward safer (lighter, less power) predictions."""


# ── 3D Model Enhancement ──

SUGGEST_MESH_PROMPT = """Suggest improvements to this robot's 3D model based on the image.

Current Model Info:
- Mesh Quality: {mesh_quality}
- Part Count: {part_count}
- Realism Score: {realism_score}

Analyze the robot image and suggest:
1. Proportion Fixes (any parts that look disproportionate?)
2. Missing Components (parts you see but model doesn't include?)
3. Material/Texture Improvements (unrealistic materials?)
4. Joint Placement (do mechanical joints look accurate?)
5. Detail Enhancements (add details from this image?)
6. Simplification Areas (what could be simplified?)

Output format:
Suggestion: [brief suggestion]
Confidence: [0.0-1.0]
Priority: [high|medium|low]
PartAffected: [component name]

Prioritize high-impact improvements for accuracy and realism."""


# ── Capability Inference ──

INFER_CAPABILITIES_PROMPT = """What capabilities can this robot perform based on its design?

Robot Details:
- Device Type: {device_type}
- Visible Components: {components}
- Inferred Mass: {mass}
- Movement Type: {movement_type}

Analyze the robot's design and infer:
1. Movement Capabilities (fly, drive, walk, swim, etc.)
2. Manipulation Capabilities (grab, lift, rotate, etc.)
3. Sensing Capabilities (cameras, lidar, sonar, etc.)
4. Environmental Adaptation (terrain types, conditions)
5. Automation/Intelligence (autonomous, remote, AI-ready, etc.)
6. Payload Capacity (can it carry things?)
7. Speed Class (slow, medium, fast)

Output format:
Capability: [name]
Confidence: 0.0-1.0
EvidenceFromImage: [what you see that supports this]

Only list capabilities with confidence > 0.4. Focus on realistic assessments."""


# ── Behavior Optimization ──

OPTIMIZE_BEHAVIOR_PROMPT = """Analyze simulation performance and suggest parameter optimizations.

Recent Performance:
{performance_data}

Metrics Summary:
- Average Score: {avg_score}
- Best Score: {best_score}
- Trend: {trend}
- Failure Modes: {failure_modes}

Known Physics Parameters:
{physics_params}

Suggest optimizations for:
1. Control Parameters (gains, damping, etc.)
2. Movement Strategy (speed, acceleration profiles)
3. Sensing Thresholds (when to react)
4. Energy Efficiency (reduce power consumption)
5. Safety Margins (improve stability)

Output format:
Parameter: [parameter name]
Current: [current value]
Suggested: [new value]
Rationale: [why this helps]
ExpectedImprovement: [expected % gain]

Be specific and measurable. Focus on parameters we've actually tested."""


# ── Command Understanding ──

COMMAND_TO_BEHAVIOR_PROMPT = """Convert a natural language command into a behavior sequence.

Robot Context:
- Type: {device_type}
- Capabilities: {capabilities}
- Current State: {current_state}
- Environment: {environment}

User Command: {command_text}

Generate:
1. Interpretation (what does the user want?)
2. Safety Check (is this safe/possible?)
3. Behavior Sequence (ordered steps)
4. Expected Duration (estimated time)
5. Sensor Requirements (what must the robot sense?)
6. Success Criteria (how to know if it worked?)

Output JSON:
{{
    "interpretation": "...",
    "safety_ok": true/false,
    "safety_notes": "...",
    "steps": [
        {{"action": "...", "duration_s": 1.0, "params": {{}}}},
        ...
    ],
    "success_criteria": "...",
    "estimated_duration_s": 5.0
}}

Be explicit and precise. Default to safe actions."""


# ── Image Analysis (generic) ──

IMAGE_ANALYSIS_PROMPT = """Analyze this image for robot detection and analysis.

Provide:
1. Robot Presence (yes/no, confidence 0-1)
2. Number of Robots (count)
3. Robot Types (each one)
4. Quality Assessment (how clear is the image for analysis?)
5. Key Features (what's most important to analyze?)
6. Recommendations (any data issues we should know about?)

Output as structured data."""


# ── Feature Extraction ──

EXTRACT_FEATURES_PROMPT = """Extract semantic features from this robot image.

Feature Categories to Extract:
1. Shape Features (bounding box, aspect ratio, symmetry)
2. Component Features (what parts are visible?)
3. Color/Material Features (dominant colors, materials)
4. Motion Indicators (signs of movement capability)
5. Structural Features (open/closed, articulated/rigid)
6. Functional Features (what this design suggests about function)

Output format:
FeatureCategory: [name]
Feature: [specific feature]
Value: [measurement or description]
Confidence: [0.0-1.0]

Be descriptive and quantitative where possible."""


def format_prompt(template: str, **kwargs) -> str:
    """
    Format a prompt template with keyword arguments.

    Args:
        template: Prompt template with {placeholders}
        **kwargs: Values to substitute

    Returns:
        Formatted prompt string
    """
    try:
        return template.format(**kwargs)
    except KeyError as e:
        # If a placeholder is missing, just leave it as-is
        return template
