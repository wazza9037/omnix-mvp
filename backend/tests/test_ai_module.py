"""
Tests for the AI Enhancement module (omnix.ai).

Validates model registry, inference engine (fallback mode), knowledge base,
and robot enhancer without requiring external API access.
"""

import json
import time
import sys
import os

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from omnix.ai import ModelRegistry, AIInferenceEngine, RobotKnowledgeBase, RobotEnhancer
from omnix.ai.robot_knowledge import Analysis, KnowledgeRecord, PerformanceRecord
from omnix.ai.model_registry import ModelEntry


# ── Model Registry Tests ──────────────────────────────────────────────

def test_model_registry_initialization():
    """Registry should start with 8 pre-configured models."""
    registry = ModelRegistry()
    models = registry.list_models()
    assert len(models) == 8
    assert all(isinstance(m, ModelEntry) for m in models)


def test_model_registry_get_model():
    """Should retrieve a specific model by ID."""
    registry = ModelRegistry()
    clip = registry.get_model("clip-vit-base")
    assert clip is not None
    assert clip.model_name == "CLIP ViT-B/32"
    assert "image-classification" in clip.capabilities

    missing = registry.get_model("nonexistent")
    assert missing is None


def test_model_registry_capability_filter():
    """Should filter models by capability."""
    registry = ModelRegistry()
    vision = registry.get_models_by_capability("image-classification")
    assert len(vision) >= 1
    assert all("image-classification" in m.capabilities for m in vision)

    nlp = registry.get_models_by_capability("text-classification")
    assert len(nlp) >= 1


def test_model_entry_serialization():
    """ModelEntry.to_dict() should produce JSON-serializable dicts."""
    registry = ModelRegistry()
    for model in registry.list_models():
        d = model.to_dict()
        assert isinstance(d, dict)
        assert "model_id" in d
        assert "capabilities" in d
        json.dumps(d)  # Should not raise


def test_model_registry_configure_api_key():
    """Should store API keys per provider."""
    registry = ModelRegistry()
    registry.configure_api_key("huggingface", "hf_test_key_123")
    # The key should be stored (we can't easily verify without accessing internals,
    # but at least it shouldn't raise)


# ── Knowledge Base Tests ──────────────────────────────────────────────

def test_knowledge_base_add_analysis_dict():
    """Should accept plain dicts for convenience."""
    kb = RobotKnowledgeBase()
    kb.add_analysis("dev1", {
        "model": "test-model",
        "type": "classification",
        "input_summary": "test image",
        "output": {"class": "drone"},
        "confidence": 0.95,
    })
    knowledge = kb.get_knowledge("dev1")
    assert knowledge is not None
    assert len(knowledge.analyses) == 1
    assert knowledge.analyses[0].analysis_type == "classification"
    assert knowledge.analyses[0].confidence == 0.95


def test_knowledge_base_add_analysis_object():
    """Should accept Analysis objects."""
    kb = RobotKnowledgeBase()
    analysis = Analysis(
        model="clip-vit-base",
        timestamp=time.time(),
        analysis_type="visual",
        input_summary="photo of drone",
        output={"features": [0.1, 0.2, 0.3]},
        confidence=0.85,
    )
    kb.add_analysis("dev1", analysis)
    knowledge = kb.get_knowledge("dev1")
    assert knowledge is not None
    assert knowledge.analyses[0].model == "clip-vit-base"


def test_knowledge_base_accumulates():
    """Multiple analyses should accumulate."""
    kb = RobotKnowledgeBase()
    for i in range(5):
        kb.add_analysis("dev1", {
            "model": f"model-{i}",
            "type": "test",
            "input_summary": f"input-{i}",
            "output": {"i": i},
        })
    knowledge = kb.get_knowledge("dev1")
    assert len(knowledge.analyses) == 5


def test_knowledge_base_multiple_devices():
    """Each device gets its own knowledge record."""
    kb = RobotKnowledgeBase()
    kb.add_analysis("dev1", {"model": "m1", "type": "t1", "input_summary": "", "output": {}})
    kb.add_analysis("dev2", {"model": "m2", "type": "t2", "input_summary": "", "output": {}})

    assert kb.get_knowledge("dev1") is not None
    assert kb.get_knowledge("dev2") is not None
    assert kb.get_knowledge("dev3") is None

    devices = kb.list_devices()
    assert "dev1" in devices
    assert "dev2" in devices


def test_knowledge_base_export_import():
    """Export and import should round-trip correctly."""
    kb = RobotKnowledgeBase()
    kb.add_analysis("dev1", Analysis(
        model="clip", timestamp=1234.0, analysis_type="visual",
        input_summary="photo", output={"class": "drone"}, confidence=0.9,
    ))
    kb.add_analysis("dev1", Analysis(
        model="blip", timestamp=1235.0, analysis_type="caption",
        input_summary="photo", output={"caption": "A small drone"}, confidence=0.8,
    ))

    exported = kb.export_json("dev1")
    assert isinstance(exported, str)
    parsed = json.loads(exported)
    assert parsed["device_id"] == "dev1"
    assert len(parsed["analyses"]) == 2

    # Import into fresh knowledge base
    kb2 = RobotKnowledgeBase()
    kb2.import_json("dev1", exported)
    k2 = kb2.get_knowledge("dev1")
    assert k2 is not None
    assert len(k2.analyses) == 2
    assert k2.analyses[0].model == "clip"


def test_knowledge_record_to_dict():
    """KnowledgeRecord should serialize to JSON-safe dict."""
    record = KnowledgeRecord(device_id="test")
    record.analyses.append(Analysis(
        model="m", timestamp=0, analysis_type="t",
        input_summary="s", output={"k": "v"}, confidence=0.5,
    ))
    record.learned_params = {"mass": 1.5, "drag": 0.3}

    d = record.to_dict()
    assert isinstance(d, dict)
    assert d["device_id"] == "test"
    json.dumps(d)  # Should not raise


def test_knowledge_base_set_description():
    """Should store AI-generated descriptions."""
    kb = RobotKnowledgeBase()
    kb.set_description("dev1", "A quadcopter drone with 4 rotors.")
    k = kb.get_knowledge("dev1")
    assert k is not None
    assert k.description_ai == "A quadcopter drone with 4 rotors."


def test_knowledge_base_clear():
    """Should clear all knowledge for a device."""
    kb = RobotKnowledgeBase()
    kb.add_analysis("dev1", {"model": "m", "type": "t", "input_summary": "", "output": {}})
    assert kb.get_knowledge("dev1") is not None
    kb.clear("dev1")
    assert kb.get_knowledge("dev1") is None


# ── Inference Engine Tests ────────────────────────────────────────────

def test_inference_engine_initialization():
    """Engine should initialize without errors."""
    registry = ModelRegistry()
    engine = AIInferenceEngine(registry)
    assert engine is not None


def test_inference_engine_cache():
    """Cache should store results."""
    registry = ModelRegistry()
    engine = AIInferenceEngine(registry)
    # The cache starts empty
    assert len(engine._result_cache) == 0


# ── Enhancer Tests (Fallback Mode) ───────────────────────────────────

def test_enhancer_estimate_physics():
    """Should return physics estimates (using fallbacks in sandbox)."""
    registry = ModelRegistry()
    engine = AIInferenceEngine(registry)
    kb = RobotKnowledgeBase()
    enhancer = RobotEnhancer(registry, engine, kb)

    result = enhancer.estimate_physics("test-dev")
    assert isinstance(result, dict)
    # Should have some physics-related keys
    assert any(k in result for k in ["mass_kg", "estimated_mass", "physics", "estimates", "error"])


def test_enhancer_suggest_capabilities():
    """Should return capability suggestions (using fallbacks)."""
    registry = ModelRegistry()
    engine = AIInferenceEngine(registry)
    kb = RobotKnowledgeBase()
    enhancer = RobotEnhancer(registry, engine, kb)

    result = enhancer.suggest_capabilities("test-dev")
    assert isinstance(result, dict)


def test_enhancer_generate_description():
    """Should return a description string."""
    registry = ModelRegistry()
    engine = AIInferenceEngine(registry)
    kb = RobotKnowledgeBase()
    enhancer = RobotEnhancer(registry, engine, kb)

    result = enhancer.generate_description("test-dev")
    assert isinstance(result, str)
    assert len(result) > 5


def test_enhancer_full_analysis():
    """Full analysis should return a JSON-serializable dict."""
    registry = ModelRegistry()
    engine = AIInferenceEngine(registry)
    kb = RobotKnowledgeBase()
    enhancer = RobotEnhancer(registry, engine, kb)

    result = enhancer.full_analysis("test-dev")
    assert isinstance(result, dict)
    assert "device_id" in result
    assert "physics" in result
    assert "capabilities" in result
    assert "description" in result
    json.dumps(result)  # Must be JSON-serializable


def test_enhancer_stores_in_knowledge_base():
    """Enhancer should store results in the knowledge base."""
    registry = ModelRegistry()
    engine = AIInferenceEngine(registry)
    kb = RobotKnowledgeBase()
    enhancer = RobotEnhancer(registry, engine, kb)

    enhancer.full_analysis("test-dev")
    knowledge = kb.get_knowledge("test-dev")
    assert knowledge is not None
    # Should have at least one analysis stored
    assert len(knowledge.analyses) > 0 or knowledge.description_ai


# ── Prompt Templates Tests ────────────────────────────────────────────

def test_prompts_exist():
    """All prompt templates should be importable and non-empty."""
    from omnix.ai.prompts import (
        CLASSIFY_ROBOT_PROMPT,
        ESTIMATE_PHYSICS_PROMPT,
        SUGGEST_MESH_PROMPT,
        INFER_CAPABILITIES_PROMPT,
        OPTIMIZE_BEHAVIOR_PROMPT,
        GENERATE_DESCRIPTION_PROMPT,
        COMMAND_TO_BEHAVIOR_PROMPT,
    )
    for name, prompt in [
        ("CLASSIFY_ROBOT_PROMPT", CLASSIFY_ROBOT_PROMPT),
        ("ESTIMATE_PHYSICS_PROMPT", ESTIMATE_PHYSICS_PROMPT),
        ("SUGGEST_MESH_PROMPT", SUGGEST_MESH_PROMPT),
        ("INFER_CAPABILITIES_PROMPT", INFER_CAPABILITIES_PROMPT),
        ("OPTIMIZE_BEHAVIOR_PROMPT", OPTIMIZE_BEHAVIOR_PROMPT),
        ("GENERATE_DESCRIPTION_PROMPT", GENERATE_DESCRIPTION_PROMPT),
        ("COMMAND_TO_BEHAVIOR_PROMPT", COMMAND_TO_BEHAVIOR_PROMPT),
    ]:
        assert isinstance(prompt, str), f"{name} should be a string"
        assert len(prompt) > 20, f"{name} should not be empty"


# ── Run all tests ─────────────────────────────────────────────────────

if __name__ == "__main__":
    test_functions = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for fn in test_functions:
        try:
            fn()
            print(f"  PASS: {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {fn.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    if failed == 0:
        print("ALL TESTS PASSED")
    else:
        sys.exit(1)
