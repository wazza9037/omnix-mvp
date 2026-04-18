"""Structured error hierarchy + JSON response helpers."""

from __future__ import annotations

from omnix.errors import (
    OmnixError, ValidationError, NotFoundError, ConflictError,
    UpstreamError, error_response,
)


class TestErrorHierarchy:
    def test_validation_error_status_and_code(self):
        e = ValidationError("bad input", {"field": "name"})
        assert e.status == 400
        assert e.code == "validation_error"
        assert e.details == {"field": "name"}

    def test_not_found_error(self):
        e = NotFoundError("device not found")
        assert e.status == 404
        assert e.code == "not_found"

    def test_conflict_error(self):
        e = ConflictError("already exists")
        assert e.status == 409
        assert e.code == "conflict"

    def test_upstream_error(self):
        e = UpstreamError("vendor SDK timeout")
        assert e.status == 502
        assert e.code == "upstream_error"

    def test_to_dict_includes_details(self):
        e = ValidationError("bad", {"f": "x"})
        d = e.to_dict()
        assert d["code"] == "validation_error"
        assert d["message"] == "bad"
        assert d["details"]["f"] == "x"

    def test_to_dict_omits_empty_details(self):
        e = NotFoundError("missing")
        d = e.to_dict()
        assert "details" not in d


class TestErrorResponse:
    def test_known_omnix_error_preserves_status(self):
        status, body = error_response(ValidationError("bad"))
        assert status == 400
        assert body["error"]["code"] == "validation_error"

    def test_unknown_exception_is_squashed_to_500(self):
        status, body = error_response(RuntimeError("leaked internals"))
        assert status == 500
        assert body["error"]["code"] == "internal_error"
        # Must not leak the original message
        assert "leaked internals" not in body["error"]["message"]
        # But we record the type for debugging
        assert body["error"]["details"]["exception_type"] == "RuntimeError"
