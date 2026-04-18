#!/usr/bin/env python3
"""
OMNIX CLI — command-line tool for managing the OMNIX platform.

Usage:
    python omnix_cli.py plugin list              — show installed plugins
    python omnix_cli.py plugin create <name>     — scaffold a new plugin
    python omnix_cli.py plugin install <path>    — install a plugin
    python omnix_cli.py plugin remove <name>     — uninstall a plugin
    python omnix_cli.py plugin validate <name>   — check a plugin for errors
"""

import os
import sys
import json
import shutil
import argparse


# ── Paths ─────────────────────────────────────────────────

CLI_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGINS_DIR = os.path.join(CLI_DIR, "plugins")
TEMPLATE_DIR = os.path.join(PLUGINS_DIR, "_template")
BACKEND_DIR = os.path.join(CLI_DIR, "backend")

# Add backend to path so we can import OMNIX modules
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


# ── Helpers ───────────────────────────────────────────────

def print_header(text):
    print(f"\n  {text}")
    print(f"  {'─' * len(text)}")


def print_ok(text):
    print(f"  ✓ {text}")


def print_err(text):
    print(f"  ✗ {text}")


def print_warn(text):
    print(f"  ⚠ {text}")


def get_plugin_dirs():
    """List all plugin directories (excluding templates and hidden)."""
    if not os.path.isdir(PLUGINS_DIR):
        return []
    return [
        d for d in sorted(os.listdir(PLUGINS_DIR))
        if not d.startswith("_") and not d.startswith(".")
        and os.path.isdir(os.path.join(PLUGINS_DIR, d))
    ]


# ── Commands ──────────────────────────────────────────────

def cmd_plugin_list(args):
    """List installed plugins with metadata."""
    dirs = get_plugin_dirs()

    if not dirs:
        print("\n  No plugins installed.")
        print(f"  Plugin directory: {PLUGINS_DIR}")
        print(f"\n  Create one with: python omnix_cli.py plugin create my_plugin\n")
        return

    print_header(f"Installed Plugins ({len(dirs)})")
    print()

    for dirname in dirs:
        plugin_dir = os.path.join(PLUGINS_DIR, dirname)
        plugin_file = os.path.join(plugin_dir, "omnix_plugin.py")
        has_readme = os.path.isfile(os.path.join(plugin_dir, "README.md"))

        # Try to extract metadata without importing
        meta = _extract_meta_quick(plugin_file)

        name = meta.get("name", dirname)
        version = meta.get("version", "?")
        author = meta.get("author", "?")
        description = meta.get("description", "")
        icon = meta.get("icon", "🔌")

        status = "✓" if os.path.isfile(plugin_file) else "✗ missing omnix_plugin.py"

        print(f"  {icon} {name} v{version}")
        if description:
            print(f"    {description[:80]}")
        print(f"    Author: {author}  |  Status: {status}  |  README: {'yes' if has_readme else 'no'}")
        print(f"    Path: {plugin_dir}")
        print()


def cmd_plugin_create(args):
    """Scaffold a new plugin from the template."""
    name = args.name

    # Validate name
    if not name.replace("_", "").replace("-", "").isalnum():
        print_err(f"Invalid plugin name '{name}'. Use only letters, numbers, underscores, and hyphens.")
        sys.exit(1)

    # Normalize to underscore
    safe_name = name.replace("-", "_")
    dest = os.path.join(PLUGINS_DIR, safe_name)

    if os.path.exists(dest):
        print_err(f"Plugin directory already exists: {dest}")
        sys.exit(1)

    # Copy template
    if not os.path.isdir(TEMPLATE_DIR):
        print_err(f"Template not found at {TEMPLATE_DIR}")
        sys.exit(1)

    shutil.copytree(TEMPLATE_DIR, dest)

    # Update the plugin file with the new name
    plugin_file = os.path.join(dest, "omnix_plugin.py")
    if os.path.isfile(plugin_file):
        with open(plugin_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Replace template-specific names
        content = content.replace('name="led_controller"', f'name="{safe_name}"')
        content = content.replace(
            'description="Control LEDs via GPIO pins. Supports brightness, "\n'
            '                    "color, and individual pin addressing."',
            f'description="TODO: Describe your {safe_name} plugin"'
        )
        content = content.replace('author="OMNIX Team"', f'author="Your Name"')

        with open(plugin_file, "w", encoding="utf-8") as f:
            f.write(content)

    print_header("Plugin Created")
    print_ok(f"Plugin scaffolded at: {dest}")
    print()
    print("  Next steps:")
    print(f"    1. Edit {plugin_file}")
    print(f"    2. Update the PluginMeta with your plugin's info")
    print(f"    3. Implement your connector/sensors in on_load()")
    print(f"    4. Validate: python omnix_cli.py plugin validate {safe_name}")
    print(f"    5. Start the server — your plugin loads automatically")
    print()


def cmd_plugin_install(args):
    """Install a plugin from a directory path."""
    source = os.path.abspath(args.path)

    if not os.path.isdir(source):
        # Check if it's a zip file
        if source.endswith(".zip") and os.path.isfile(source):
            _install_from_zip(source)
            return
        print_err(f"Source not found: {source}")
        sys.exit(1)

    # Check for omnix_plugin.py
    plugin_file = os.path.join(source, "omnix_plugin.py")
    if not os.path.isfile(plugin_file):
        print_err(f"No omnix_plugin.py found in {source}")
        sys.exit(1)

    dirname = os.path.basename(source)
    dest = os.path.join(PLUGINS_DIR, dirname)

    if os.path.exists(dest):
        print_warn(f"Plugin '{dirname}' already exists. Overwriting...")
        shutil.rmtree(dest)

    shutil.copytree(source, dest)

    print_header("Plugin Installed")
    print_ok(f"Installed '{dirname}' to {dest}")
    print()
    print(f"  Validate: python omnix_cli.py plugin validate {dirname}")
    print(f"  Restart the server to load the plugin.")
    print()


def _install_from_zip(zip_path):
    """Install a plugin from a zip archive."""
    import zipfile

    if not zipfile.is_zipfile(zip_path):
        print_err(f"Not a valid zip file: {zip_path}")
        sys.exit(1)

    with zipfile.ZipFile(zip_path, "r") as zf:
        # Find the plugin directory in the zip
        names = zf.namelist()
        plugin_files = [n for n in names if n.endswith("omnix_plugin.py")]

        if not plugin_files:
            print_err("No omnix_plugin.py found in zip archive")
            sys.exit(1)

        # Determine the root directory
        plugin_path = plugin_files[0]
        parts = plugin_path.split("/")
        if len(parts) > 1:
            dirname = parts[0]
        else:
            dirname = os.path.splitext(os.path.basename(zip_path))[0]

        dest = os.path.join(PLUGINS_DIR, dirname)

        if os.path.exists(dest):
            print_warn(f"Plugin '{dirname}' already exists. Overwriting...")
            shutil.rmtree(dest)

        zf.extractall(PLUGINS_DIR)

    print_header("Plugin Installed")
    print_ok(f"Extracted and installed '{dirname}'")
    print()


def cmd_plugin_remove(args):
    """Remove a plugin."""
    name = args.name
    plugin_dir = os.path.join(PLUGINS_DIR, name)

    if not os.path.isdir(plugin_dir):
        print_err(f"Plugin not found: {name}")
        print(f"  Available plugins: {', '.join(get_plugin_dirs()) or 'none'}")
        sys.exit(1)

    # Confirm
    if not args.force:
        answer = input(f"  Remove plugin '{name}' from {plugin_dir}? [y/N] ")
        if answer.lower() != "y":
            print("  Cancelled.")
            return

    shutil.rmtree(plugin_dir)
    print_ok(f"Plugin '{name}' removed.")
    print("  Restart the server to unload the plugin.")


def cmd_plugin_validate(args):
    """Validate a plugin's structure and metadata."""
    name = args.name
    plugin_dir = os.path.join(PLUGINS_DIR, name)

    if not os.path.isdir(plugin_dir):
        print_err(f"Plugin directory not found: {plugin_dir}")
        sys.exit(1)

    print_header(f"Validating plugin: {name}")

    try:
        from omnix.plugins.validator import PluginValidator
        validator = PluginValidator()
    except ImportError:
        print_err("Cannot import PluginValidator. Ensure backend/ is in PYTHONPATH.")
        sys.exit(1)

    is_valid, errors = validator.validate(plugin_dir)

    # Show results
    error_count = sum(1 for e in errors if e.level == "error")
    warn_count = sum(1 for e in errors if e.level == "warning")

    for err in errors:
        if err.level == "error":
            print_err(err.message)
        else:
            print_warn(err.message)

    print()
    if is_valid:
        print_ok(f"Plugin is valid! ({warn_count} warning{'s' if warn_count != 1 else ''})")
    else:
        print_err(f"Validation failed: {error_count} error{'s' if error_count != 1 else ''}, "
                  f"{warn_count} warning{'s' if warn_count != 1 else ''}")

    # Try to import and validate meta at runtime
    if is_valid:
        print()
        print("  Attempting import...")
        try:
            from omnix.plugins.loader import PluginLoader
            loader = PluginLoader(PLUGINS_DIR)
            plugin = loader.load_from_dir(plugin_dir)
            if plugin and plugin.meta:
                print_ok(f"Import successful: {plugin.meta.name} v{plugin.meta.version}")
                meta_errors = validator.validate_meta(plugin.meta)
                for err in meta_errors:
                    if err.level == "error":
                        print_err(f"Meta: {err.message}")
                    else:
                        print_warn(f"Meta: {err.message}")
            elif plugin:
                print_warn("Plugin imported but has no meta attribute")
            else:
                print_err("Plugin import returned None")
        except Exception as e:
            print_err(f"Import failed: {e}")

    print()
    return 0 if is_valid else 1


# ── Meta extraction (quick, no import) ────────────────────

def _extract_meta_quick(plugin_file):
    """Try to extract PluginMeta fields from source without importing."""
    meta = {}
    if not os.path.isfile(plugin_file):
        return meta

    try:
        with open(plugin_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Simple regex-based extraction for display purposes
        import re
        for field_name in ("name", "version", "author", "description", "icon"):
            match = re.search(
                rf'{field_name}\s*=\s*["\']([^"\']+)["\']',
                content,
            )
            if match:
                meta[field_name] = match.group(1)
    except Exception:
        pass

    return meta


# ── Main ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="omnix",
        description="OMNIX Universal Robotics Control — CLI Tool",
    )
    subparsers = parser.add_subparsers(dest="category", help="Command category")

    # plugin subcommands
    plugin_parser = subparsers.add_parser("plugin", help="Plugin management")
    plugin_sub = plugin_parser.add_subparsers(dest="action", help="Plugin action")

    # plugin list
    list_parser = plugin_sub.add_parser("list", help="List installed plugins")
    list_parser.set_defaults(func=cmd_plugin_list)

    # plugin create
    create_parser = plugin_sub.add_parser("create", help="Create a new plugin from template")
    create_parser.add_argument("name", help="Plugin name (alphanumeric + underscores)")
    create_parser.set_defaults(func=cmd_plugin_create)

    # plugin install
    install_parser = plugin_sub.add_parser("install", help="Install a plugin from path or zip")
    install_parser.add_argument("path", help="Path to plugin directory or zip file")
    install_parser.set_defaults(func=cmd_plugin_install)

    # plugin remove
    remove_parser = plugin_sub.add_parser("remove", help="Remove a plugin")
    remove_parser.add_argument("name", help="Plugin name to remove")
    remove_parser.add_argument("-f", "--force", action="store_true", help="Skip confirmation")
    remove_parser.set_defaults(func=cmd_plugin_remove)

    # plugin validate
    validate_parser = plugin_sub.add_parser("validate", help="Validate a plugin")
    validate_parser.add_argument("name", help="Plugin name to validate")
    validate_parser.set_defaults(func=cmd_plugin_validate)

    args = parser.parse_args()

    if not args.category:
        parser.print_help()
        return

    if args.category == "plugin" and not args.action:
        plugin_parser.print_help()
        return

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
