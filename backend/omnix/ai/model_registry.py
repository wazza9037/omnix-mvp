"""
Registry of available AI models and their capabilities.

Maintains metadata about free-tier models available via Hugging Face Inference API,
including capabilities, API endpoints, rate limits, and availability checks.
Models can be checked for availability, and API keys can be configured per provider.
"""

from __future__ import annotations

import time
import threading
import urllib.request
import urllib.error
import json
from dataclasses import dataclass, field, asdict
from typing import Any

from omnix.logging_setup import get_logger
from omnix.errors import ValidationError, UpstreamError


logger = get_logger(__name__)


@dataclass
class ModelCapability:
    """Describes what a model can do."""
    name: str
    description: str


@dataclass
class ModelEntry:
    """Registry entry for a single model."""
    model_id: str
    model_name: str
    provider: str
    api_url: str
    capabilities: list[str]
    free_tier_limits: dict[str, Any]
    fallback_behavior: str
    description: str = ""
    requires_auth: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return asdict(self)


@dataclass
class ProviderConfig:
    """Configuration for a model provider."""
    provider_name: str
    api_key: str | None = None
    base_url: str = ""
    rate_limit_calls_per_day: int = 1000


class ModelRegistry:
    """
    Registry of available AI models with metadata and availability checks.

    Supports free-tier Hugging Face Inference API models without authentication.
    Tracks model capabilities, rate limits, and fallback behaviors.
    """

    def __init__(self):
        """Initialize the registry with default free-tier models."""
        self._models: dict[str, ModelEntry] = {}
        self._providers: dict[str, ProviderConfig] = {}
        self._availability_cache: dict[str, tuple[bool, float]] = {}  # (available, timestamp)
        self._cache_ttl_s = 300  # 5 minutes
        self._lock = threading.Lock()

        self._init_default_models()

    def _init_default_models(self) -> None:
        """Register default free-tier Hugging Face Inference API models."""
        # Vision / Classification models
        self._models["clip-vit-base"] = ModelEntry(
            model_id="clip-vit-base",
            model_name="CLIP ViT-B/32",
            provider="huggingface",
            api_url="https://api-inference.huggingface.co/models/openai/clip-vit-base-patch32",
            capabilities=["image-classification", "feature-extraction", "similarity"],
            free_tier_limits={"calls_per_day": 1000, "batch_size": 1},
            fallback_behavior="return_cached_or_default",
            description="OpenAI CLIP for image understanding and similarity matching",
            requires_auth=False,
        )

        self._models["blip2"] = ModelEntry(
            model_id="blip2",
            model_name="BLIP-2",
            provider="huggingface",
            api_url="https://api-inference.huggingface.co/models/Salesforce/blip2-opt-2.7b",
            capabilities=["image-captioning", "visual-qa", "object-understanding"],
            free_tier_limits={"calls_per_day": 500, "batch_size": 1},
            fallback_behavior="return_cached_or_default",
            description="Salesforce BLIP-2 for image captioning and VQA",
            requires_auth=False,
        )

        self._models["dinov2"] = ModelEntry(
            model_id="dinov2",
            model_name="DINOv2",
            provider="huggingface",
            api_url="https://api-inference.huggingface.co/models/facebook/dinov2-base",
            capabilities=["visual-feature-extraction", "image-understanding"],
            free_tier_limits={"calls_per_day": 1000, "batch_size": 1},
            fallback_behavior="return_cached_or_default",
            description="Meta DINOv2 for robust visual feature extraction",
            requires_auth=False,
        )

        # 3D Generation stubs (APIs may be rate-limited)
        self._models["tripro-sr"] = ModelEntry(
            model_id="tripro-sr",
            model_name="TripoSR",
            provider="external-api",
            api_url="https://api.tripo.ai/v1/predict",
            capabilities=["image-to-3d", "mesh-generation"],
            free_tier_limits={"calls_per_day": 10, "batch_size": 1},
            fallback_behavior="skip_unavailable",
            description="Image-to-3D model stub (external service)",
            requires_auth=True,
        )

        self._models["instant-mesh"] = ModelEntry(
            model_id="instant-mesh",
            model_name="InstantMesh",
            provider="external-api",
            api_url="https://api.instamesh.ai/v1/generate",
            capabilities=["image-to-3d", "mesh-generation", "texture-generation"],
            free_tier_limits={"calls_per_day": 5, "batch_size": 1},
            fallback_behavior="skip_unavailable",
            description="Fast image-to-3D mesh generation",
            requires_auth=True,
        )

        self._models["point-e"] = ModelEntry(
            model_id="point-e",
            model_name="Point-E",
            provider="huggingface",
            api_url="https://api-inference.huggingface.co/models/openai/point-e",
            capabilities=["text-to-3d", "point-cloud-generation"],
            free_tier_limits={"calls_per_day": 100, "batch_size": 1},
            fallback_behavior="return_cached_or_default",
            description="OpenAI Point-E for text-to-3D point cloud generation",
            requires_auth=False,
        )

        # NLP models
        self._models["zero-shot-classification"] = ModelEntry(
            model_id="zero-shot-classification",
            model_name="Zero-Shot Classifier",
            provider="huggingface",
            api_url="https://api-inference.huggingface.co/models/facebook/bart-large-mnli",
            capabilities=["text-classification", "intent-detection", "command-understanding"],
            free_tier_limits={"calls_per_day": 2000, "batch_size": 1},
            fallback_behavior="return_cached_or_default",
            description="Zero-shot text classification for understanding robot commands",
            requires_auth=False,
        )

        self._models["summarization"] = ModelEntry(
            model_id="summarization",
            model_name="Text Summarization",
            provider="huggingface",
            api_url="https://api-inference.huggingface.co/models/facebook/bart-large-cnn",
            capabilities=["summarization", "text-compression"],
            free_tier_limits={"calls_per_day": 500, "batch_size": 1},
            fallback_behavior="return_cached_or_default",
            description="Summarize robot descriptions and capabilities",
            requires_auth=False,
        )

        # Initialize provider configs
        self._providers["huggingface"] = ProviderConfig(
            provider_name="huggingface",
            api_key=None,  # Free tier requires no key
            base_url="https://api-inference.huggingface.co",
            rate_limit_calls_per_day=10000,
        )
        self._providers["external-api"] = ProviderConfig(
            provider_name="external-api",
            api_key=None,
        )

    def list_models(self) -> list[ModelEntry]:
        """Return all registered models."""
        with self._lock:
            return list(self._models.values())

    def get_model(self, model_id: str) -> ModelEntry | None:
        """Get a single model by ID, or None if not found."""
        with self._lock:
            return self._models.get(model_id)

    def get_models_by_capability(self, capability: str) -> list[ModelEntry]:
        """Get all models that support a given capability."""
        with self._lock:
            return [m for m in self._models.values() if capability in m.capabilities]

    def check_availability(self, model_id: str) -> bool:
        """
        Check if a model endpoint is available via a simple ping.

        Returns cached result if within TTL. Silently falls back to assuming
        the model is unavailable if the check fails.
        """
        with self._lock:
            # Check cache first
            cached = self._availability_cache.get(model_id)
            if cached:
                available, ts = cached
                if time.time() - ts < self._cache_ttl_s:
                    return available

            model = self._models.get(model_id)
            if not model:
                return False

        # Check availability (outside lock to avoid blocking on HTTP)
        available = self._ping_endpoint(model.api_url, model.provider)

        # Update cache
        with self._lock:
            self._availability_cache[model_id] = (available, time.time())

        return available

    def _ping_endpoint(self, api_url: str, provider: str) -> bool:
        """Attempt to ping an API endpoint to verify it's available."""
        try:
            # Hugging Face endpoints respond to a simple GET with a 502/503 if model is loading
            # or return 200 with a simple response. We just check connectivity.
            req = urllib.request.Request(
                api_url,
                method="HEAD",
                headers={"User-Agent": "OMNIX-AI/1.0"}
            )
            with urllib.request.urlopen(req, timeout=2) as _:
                pass
            logger.debug(f"API endpoint available: {api_url}")
            return True
        except (urllib.error.URLError, urllib.error.HTTPError, Exception) as e:
            logger.debug(f"API endpoint unavailable: {api_url} ({type(e).__name__})")
            return False

    def configure_api_key(self, provider: str, api_key: str) -> None:
        """
        Set API key for a provider. Used for models that require authentication.

        Args:
            provider: Provider name (e.g., "huggingface", "external-api")
            api_key: API key for the provider

        Raises:
            ValidationError: If provider is not registered
        """
        with self._lock:
            if provider not in self._providers:
                raise ValidationError(f"Unknown provider: {provider}")
            self._providers[provider].api_key = api_key
            logger.info(f"Configured API key for provider: {provider}")

    def get_provider_config(self, provider: str) -> ProviderConfig | None:
        """Get configuration for a provider."""
        with self._lock:
            return self._providers.get(provider)

    def clear_availability_cache(self) -> None:
        """Clear the availability check cache."""
        with self._lock:
            self._availability_cache.clear()
