"""
Input validation and sanitization utilities.

Provides validators for common input patterns and a sanitizer
that strips potentially dangerous content.
"""

from __future__ import annotations

import html
import re
from typing import Any


# Patterns for common input types
_PATTERNS = {
    "username": re.compile(r"^[a-zA-Z0-9_]{3,32}$"),
    "email": re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"),
    "device_id": re.compile(r"^[a-zA-Z0-9_-]{1,64}$"),
    "session_id": re.compile(r"^[a-zA-Z0-9_-]{1,64}$"),
    "tree_id": re.compile(r"^[a-zA-Z0-9_-]{1,64}$"),
    "item_id": re.compile(r"^[a-zA-Z0-9_-]{1,64}$"),
    "slug": re.compile(r"^[a-zA-Z0-9_-]{1,128}$"),
}

# Maximum lengths for string fields
_MAX_LENGTHS = {
    "name": 128,
    "description": 2048,
    "comment": 1024,
    "chat_message": 500,
    "command": 512,
    "tags": 20,  # max number of tags
    "tag": 64,   # max length per tag
}


def sanitize_string(value: str, max_length: int = 1024, strip_html: bool = True) -> str:
    """Sanitize a string input: trim, limit length, optionally strip HTML."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if strip_html:
        value = html.escape(value)
    if len(value) > max_length:
        value = value[:max_length]
    return value


def validate_input(value: Any, pattern_name: str) -> bool:
    """Validate an input value against a named pattern."""
    if not isinstance(value, str):
        return False
    pat = _PATTERNS.get(pattern_name)
    if pat is None:
        return True  # No pattern = no restriction
    return bool(pat.match(value))


def validate_json_body(body: dict, required_fields: list[str] | None = None,
                       max_depth: int = 10) -> list[str]:
    """
    Validate a JSON request body.
    Returns a list of error messages (empty = valid).
    """
    errors: list[str] = []

    if not isinstance(body, dict):
        return ["Request body must be a JSON object"]

    if required_fields:
        for field in required_fields:
            if field not in body:
                errors.append(f"Missing required field: {field}")

    # Check nesting depth to prevent abuse
    if _check_depth(body) > max_depth:
        errors.append(f"JSON nesting too deep (max {max_depth} levels)")

    return errors


def _check_depth(obj: Any, current: int = 0) -> int:
    """Recursively check the nesting depth of a JSON-like structure."""
    if current > 50:  # Hard safety limit
        return current
    if isinstance(obj, dict):
        if not obj:
            return current
        return max(_check_depth(v, current + 1) for v in obj.values())
    if isinstance(obj, list):
        if not obj:
            return current
        return max(_check_depth(v, current + 1) for v in obj)
    return current


def validate_request_size(handler: Any, max_bytes: int = 20 * 1024 * 1024) -> bool:
    """Check that the request body doesn't exceed the size limit."""
    content_length = handler.headers.get("Content-Length", "0")
    try:
        size = int(content_length)
    except (ValueError, TypeError):
        size = 0
    return size <= max_bytes
