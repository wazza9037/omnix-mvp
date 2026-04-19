"""
OMNIX AI Enhancement Module.

Orchestrates AI-powered robot analysis and improvement using free-tier models
(Hugging Face Inference API, no authentication required). Enhances the VPE with
ML-based physics estimation, visual feature extraction, and capability inference.

Public pipeline:

    from omnix.ai import RobotEnhancer, ModelRegistry, AIInferenceEngine, RobotKnowledgeBase

    registry = ModelRegistry()
    engine = AIInferenceEngine(registry)
    knowledge = RobotKnowledgeBase()
    enhancer = RobotEnhancer(registry, engine, knowledge)

    analysis = enhancer.full_analysis(device_id, image_b64)
    improvements = enhancer.enhance_3d_model(device_id, image_b64)
    physics = enhancer.estimate_physics(device_id, image_b64)
"""

from .model_registry import ModelRegistry
from .inference import AIInferenceEngine
from .robot_knowledge import RobotKnowledgeBase
from .enhancer import RobotEnhancer

__all__ = [
    "ModelRegistry",
    "AIInferenceEngine",
    "RobotKnowledgeBase",
    "RobotEnhancer",
]
