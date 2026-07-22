#!/usr/bin/env python3
"""Rewrite the template placeholders into a component's own names.

Usage::

    python scripts/rename.py aws-remote-state RemoteState

Substitutes ``component-template``, ``component_template``, and ``ExampleComponent``
throughout the repository, and renames ``tests/test_component.py`` to match. Nothing
else is touched, and a second run is a no-op.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()

#: Directories excluded from the rewrite.
SKIP = {".git", ".venv", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache", ".atlantis"}
#: Extensions included in the rewrite; lockfiles and binaries are excluded.
SUFFIXES = {".py", ".toml", ".md", ".yml", ".yaml", ".cfg", ".txt", ""}

KEBAB, SNAKE, CLASS = "component-template", "component_template", "ExampleComponent"

KEBAB_NAME = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
CLASS_NAME = re.compile(r"^[A-Z][A-Za-z0-9]*$")


def sources() -> list[Path]:
    """The files eligible for rewriting, excluding this script."""
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.resolve() != SELF
        and path.suffix in SUFFIXES
        and not SKIP & set(path.relative_to(ROOT).parts)
    )


def rewrite(path: Path, substitutions: dict[str, str]) -> bool:
    """Apply ``substitutions`` to ``path``. True when the file changed."""
    try:
        before = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False

    after = before
    for placeholder, replacement in substitutions.items():
        after = after.replace(placeholder, replacement)

    if after == before:
        return False
    path.write_text(after, encoding="utf-8")
    return True


def rename_test_module(snake: str) -> Path | None:
    """Rename ``tests/test_component.py`` to ``tests/test_<snake>.py``, if it exists."""
    module = ROOT / "tests" / "test_component.py"
    renamed = module.with_name(f"test_{snake}.py")
    if not module.exists() or renamed == module:
        return None
    module.rename(renamed)
    return renamed


def parse_args() -> argparse.Namespace:
    """The validated command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="repository / component name, kebab-case (aws-vpc)")
    parser.add_argument("cls", help="component class name, PascalCase (Vpc)")
    args = parser.parse_args()

    if not KEBAB_NAME.match(args.name):
        parser.error(f"{args.name!r} is not kebab-case (e.g. aws-remote-state)")
    if not CLASS_NAME.match(args.cls):
        parser.error(f"{args.cls!r} is not PascalCase (e.g. RemoteState)")
    return args


def main() -> int:
    args = parse_args()
    snake = args.name.replace("-", "_")
    substitutions = {KEBAB: args.name, SNAKE: snake, CLASS: args.cls}

    changed = [path for path in sources() if rewrite(path, substitutions)]
    if (renamed := rename_test_module(snake)) is not None:
        changed.append(renamed)

    for path in changed:
        print(path.relative_to(ROOT))
    print(f"\n{len(changed)} file(s) rewritten. Next: edit src/__init__.py and README.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
