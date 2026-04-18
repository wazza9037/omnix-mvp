#!/usr/bin/env python3
"""
Minimal stdlib test runner — lets the pytest-style test suite run in
environments where pytest isn't installed (the sandbox, stripped-down CI
images, first-time contributors).

When real pytest is available, prefer `make test` / `pytest` directly —
this runner is a compatibility shim, not a replacement.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import inspect
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
TESTS = BACKEND / "tests"
sys.path.insert(0, str(BACKEND))


# ── Minimal pytest shim ────────────────────────────────────────────
# Only the handful of pytest features our test suite actually uses.

class _ApproxValue:
    def __init__(self, expected, abs_tol=1e-6, rel_tol=None):
        self.expected = expected
        self.abs_tol = abs_tol
        self.rel_tol = rel_tol

    def __eq__(self, other):
        if self.rel_tol is not None:
            return abs(other - self.expected) <= self.rel_tol * abs(self.expected)
        return abs(other - self.expected) <= self.abs_tol

    def __repr__(self):
        return f"approx({self.expected}, abs={self.abs_tol})"


@contextlib.contextmanager
def _raises(exc_cls, match: str | None = None):
    try:
        yield None
    except exc_cls as e:
        if match is not None:
            import re
            if not re.search(match, str(e)):
                raise AssertionError(
                    f"expected exception matching {match!r}, got {e!r}") from e
        return
    except BaseException as e:
        raise AssertionError(
            f"expected {exc_cls.__name__}, got {type(e).__name__}: {e}") from e
    raise AssertionError(f"expected {exc_cls.__name__} but no exception was raised")


def _fixture(fn=None, **kwargs):
    """Minimal @pytest.fixture decorator — just marks the function."""
    def wrap(f):
        f.__is_fixture__ = True
        return f
    if fn is None:
        return wrap
    return wrap(fn)


if "pytest" not in sys.modules:
    shim = sys.modules["pytest"] = type(sys)("pytest")
    shim.approx = lambda v, abs=1e-6, rel=None: _ApproxValue(v, abs_tol=abs, rel_tol=rel)
    shim.raises = _raises
    shim.fixture = _fixture


# ── Minimal runner ────────────────────────────────────────────────

def _load_module(path: Path):
    rel = path.relative_to(BACKEND).with_suffix("").as_posix().replace("/", ".")
    spec = importlib.util.spec_from_file_location(rel, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[rel] = mod
    spec.loader.exec_module(mod)
    return mod


def _collect_fixtures(conftest_path: Path) -> dict:
    mod = _load_module(conftest_path)
    fixtures = {}
    for name, fn in inspect.getmembers(mod, inspect.isfunction):
        if getattr(fn, "__is_fixture__", False):
            fixtures[name] = fn
    return fixtures


def _invoke_fixture(name, fn, fixtures: dict, cache: dict, teardowns: list):
    """Invoke a fixture fn, recursively resolving its own dependencies.

    Results are cached in `cache` keyed by fixture name so multiple args in
    the same test that reference the same fixture get the same instance —
    matching pytest's function-scoped fixture semantics.
    """
    if name in cache:
        return cache[name]
    sig = inspect.signature(fn)
    sub_args = []
    for p_name, p in sig.parameters.items():
        if p_name in fixtures:
            sub_args.append(_invoke_fixture(p_name, fixtures[p_name], fixtures, cache, teardowns))
        elif p.default is not inspect.Parameter.empty:
            sub_args.append(p.default)
        else:
            raise RuntimeError(f"Fixture {fn.__name__} needs unknown fixture '{p_name}'")
    result = fn(*sub_args)
    if inspect.isgenerator(result):
        gen = result
        value = next(gen)
        def _finish(g=gen):
            try: next(g)
            except StopIteration: pass
        teardowns.append(_finish)
        cache[name] = value
        return value
    cache[name] = result
    return result


def _resolve_args(fn, fixtures: dict):
    """Look at the function's signature and call each needed fixture.

    Returns (args, teardowns). Each teardown is a zero-arg callable that
    finishes a generator-style fixture after the test runs.
    """
    sig = inspect.signature(fn)
    args = []
    teardowns: list = []
    cache: dict = {}
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        if name in fixtures:
            args.append(_invoke_fixture(name, fixtures[name], fixtures, cache, teardowns))
        elif param.default is not inspect.Parameter.empty:
            args.append(param.default)
        else:
            raise RuntimeError(f"Unknown fixture '{name}' for {fn.__qualname__}")
    return args, teardowns


def main() -> int:
    # Minimize noise — turn off colour logging during tests
    os.environ.setdefault("OMNIX_LOG_LEVEL", "WARNING")

    # Load conftest fixtures
    fixtures = {}
    conftest = TESTS / "conftest.py"
    if conftest.exists():
        fixtures = _collect_fixtures(conftest)

    test_files = sorted(TESTS.glob("test_*.py"))
    if not test_files:
        print("no test_*.py files found")
        return 1

    passed = failed = 0
    failures: list[tuple[str, str]] = []

    for test_file in test_files:
        mod = _load_module(test_file)
        # Merge conftest fixtures with module-local fixtures
        local_fixtures = dict(fixtures)
        for name, fn in inspect.getmembers(mod, inspect.isfunction):
            if getattr(fn, "__is_fixture__", False):
                local_fixtures[name] = fn

        # Module-level test_* functions
        for name, fn in inspect.getmembers(mod, inspect.isfunction):
            if not name.startswith("test_"):
                continue
            _run_test(fn.__qualname__, fn, None, local_fixtures, failures)

        # Class-based tests
        for cls_name, cls in inspect.getmembers(mod, inspect.isclass):
            if not cls_name.startswith("Test") or cls.__module__ != mod.__name__:
                continue
            instance = cls()
            for name, method in inspect.getmembers(instance, inspect.ismethod):
                if not name.startswith("test_"):
                    continue
                _run_test(f"{cls_name}.{name}", method, instance, local_fixtures, failures)

    # Count from failure list
    for f in failures:
        pass
    passed = _total_passed
    failed = len(failures)
    total = passed + failed

    print()
    if failed:
        print(f"FAILED: {failed} / {total}")
        print()
        for name, tb in failures[:30]:
            print(f"— {name} —")
            print(tb)
        return 1
    print(f"OK: all {passed} tests passed")
    return 0


_total_passed = 0


def _run_test(label, fn, self_obj, fixtures, failures):
    global _total_passed
    teardowns: list = []
    try:
        args, teardowns = _resolve_args(fn, fixtures)
        if self_obj is None or inspect.ismethod(fn):
            fn(*args)
        else:
            fn(self_obj, *args)
        print(f"  ✓ {label}")
        _total_passed += 1
    except Exception:
        tb = traceback.format_exc()
        print(f"  ✗ {label}")
        failures.append((label, tb))
    finally:
        for t in teardowns:
            try: t()
            except Exception: pass


if __name__ == "__main__":
    sys.exit(main())
