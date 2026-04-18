"""
OMNIX Plugin Validator — checks plugin structure before loading.

Validates:
  - Required files exist (omnix_plugin.py)
  - Plugin class inherits from OmnixPlugin
  - PluginMeta is properly set with required fields
  - No dangerous imports (os.system, subprocess, eval, exec, etc.)
  - Version string is valid
"""

import os
import re
import ast
from typing import List, Tuple

from .base import OmnixPlugin, PluginMeta


# Imports/calls that plugins should NOT use. We check the raw AST
# rather than trying to sandbox at runtime — this catches obvious
# mistakes and malicious intent without a full sandbox.
DANGEROUS_PATTERNS = {
    # Functions that execute arbitrary code
    "eval", "exec", "compile", "__import__",
    # System-level calls
    "os.system", "os.popen", "os.exec", "os.spawn",
    "subprocess.call", "subprocess.run", "subprocess.Popen",
    "subprocess.check_output", "subprocess.check_call",
    # Network (plugins should use OMNIX's HTTP helpers)
    "socket.socket",
    # File system abuse
    "shutil.rmtree",
}

# Module-level imports that are suspicious
DANGEROUS_IMPORTS = {
    "ctypes", "multiprocessing", "signal",
}

# Semver-ish pattern: major.minor.patch with optional pre-release
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(-[\w.]+)?$")


class ValidationError:
    """A single validation problem."""

    def __init__(self, level: str, message: str, line: int = None):
        self.level = level       # "error" or "warning"
        self.message = message
        self.line = line

    def __repr__(self):
        loc = f" (line {self.line})" if self.line else ""
        return f"[{self.level.upper()}]{loc} {self.message}"

    def to_dict(self):
        return {"level": self.level, "message": self.message, "line": self.line}


class PluginValidator:
    """Validates a plugin directory before it's loaded."""

    def validate(self, plugin_dir: str) -> Tuple[bool, List[ValidationError]]:
        """Validate a plugin directory.

        Returns (is_valid, errors) where is_valid is True if there are
        no errors (warnings are okay).
        """
        errors: List[ValidationError] = []

        # 1. Check directory exists
        if not os.path.isdir(plugin_dir):
            errors.append(ValidationError("error", f"Plugin directory not found: {plugin_dir}"))
            return False, errors

        # 2. Check omnix_plugin.py exists
        plugin_file = os.path.join(plugin_dir, "omnix_plugin.py")
        if not os.path.isfile(plugin_file):
            errors.append(ValidationError("error", "Missing omnix_plugin.py"))
            return False, errors

        # 3. Parse and validate the source
        try:
            with open(plugin_file, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception as e:
            errors.append(ValidationError("error", f"Cannot read omnix_plugin.py: {e}"))
            return False, errors

        # 4. Check for syntax errors
        try:
            tree = ast.parse(source, filename="omnix_plugin.py")
        except SyntaxError as e:
            errors.append(ValidationError("error", f"Syntax error: {e}", line=e.lineno))
            return False, errors

        # 5. Check for dangerous patterns
        self._check_dangerous(tree, source, errors)

        # 6. Check for OmnixPlugin subclass
        plugin_classes = self._find_plugin_classes(tree)
        if not plugin_classes:
            errors.append(ValidationError(
                "error",
                "No OmnixPlugin subclass found. Your plugin must define a class "
                "that inherits from OmnixPlugin."
            ))

        # 7. Check for PluginMeta assignment
        has_meta = False
        for cls_node in plugin_classes:
            for item in cls_node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id == "meta":
                            has_meta = True
                elif isinstance(item, ast.AnnAssign):
                    if isinstance(item.target, ast.Name) and item.target.id == "meta":
                        has_meta = True

        if plugin_classes and not has_meta:
            errors.append(ValidationError(
                "error",
                "Plugin class must define a 'meta' attribute with a PluginMeta instance."
            ))

        # 8. Check for on_load method
        has_on_load = False
        for cls_node in plugin_classes:
            for item in cls_node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name == "on_load":
                        has_on_load = True

        if plugin_classes and not has_on_load:
            errors.append(ValidationError(
                "warning",
                "Plugin class should implement on_load() to register connectors/sensors."
            ))

        # 9. Optional: check for README
        if not os.path.isfile(os.path.join(plugin_dir, "README.md")):
            errors.append(ValidationError(
                "warning",
                "No README.md found. Consider adding documentation for your plugin."
            ))

        has_errors = any(e.level == "error" for e in errors)
        return not has_errors, errors

    def validate_meta(self, meta: PluginMeta) -> List[ValidationError]:
        """Validate a PluginMeta instance at runtime (after import)."""
        errors = []

        if not meta:
            errors.append(ValidationError("error", "Plugin.meta is None"))
            return errors

        if not meta.name:
            errors.append(ValidationError("error", "meta.name is required"))

        if not meta.version:
            errors.append(ValidationError("error", "meta.version is required"))
        elif not _VERSION_RE.match(meta.version):
            errors.append(ValidationError(
                "warning",
                f"meta.version '{meta.version}' is not valid semver (expected X.Y.Z)"
            ))

        if not meta.description:
            errors.append(ValidationError("warning", "meta.description is empty"))

        if not meta.author or meta.author == "Unknown":
            errors.append(ValidationError("warning", "meta.author should be set"))

        return errors

    # ── Internal helpers ──────────────────────────────────

    def _find_plugin_classes(self, tree: ast.Module) -> List[ast.ClassDef]:
        """Find all class definitions that inherit from OmnixPlugin."""
        result = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for base in node.bases:
                base_name = ""
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr
                if base_name == "OmnixPlugin":
                    result.append(node)
        return result

    def _check_dangerous(self, tree: ast.Module, source: str,
                         errors: List[ValidationError]) -> None:
        """Walk the AST looking for dangerous calls and imports."""

        for node in ast.walk(tree):
            # Check function calls
            if isinstance(node, ast.Call):
                call_name = self._get_call_name(node)
                if call_name in DANGEROUS_PATTERNS:
                    errors.append(ValidationError(
                        "error",
                        f"Dangerous call '{call_name}' is not allowed in plugins.",
                        line=getattr(node, "lineno", None),
                    ))

            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in DANGEROUS_IMPORTS:
                        errors.append(ValidationError(
                            "warning",
                            f"Suspicious import '{alias.name}' — ensure this is necessary.",
                            line=node.lineno,
                        ))

            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod in DANGEROUS_IMPORTS:
                    errors.append(ValidationError(
                        "warning",
                        f"Suspicious import from '{mod}' — ensure this is necessary.",
                        line=node.lineno,
                    ))

    def _get_call_name(self, node: ast.Call) -> str:
        """Extract the dotted name from a Call node (e.g. 'os.system')."""
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            parts = []
            current = func
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return ".".join(reversed(parts))
        return ""
