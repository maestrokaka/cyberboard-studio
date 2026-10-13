#!/usr/bin/env python3
"""Validate a config JSON against the CyberBoard schema — pre-write safety net.

Structural check (does the JSON match schemas/cyberboard-config.schema.json?),
complementary to cb_write.py's dry-run (which checks frame encoding). Run this
before a write to catch a malformed config early.

Degrades gracefully: if `jsonschema` isn't installed, it still does basic
sanity checks (required keys, page_data shape) and says so.

Usage: cb_verify.py CONFIG.json [SCHEMA.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "cyberboard-config.schema.json"


def _basic_checks(config: dict) -> list[str]:
    errors: list[str] = []
    for key in ("page_num", "page_data"):
        if key not in config:
            errors.append(f"missing required key: {key}")
    pages = config.get("page_data")
    if isinstance(pages, list):
        for i, pg in enumerate(pages):
            if "page_index" not in pg:
                errors.append(f"page_data/{i}: missing page_index")
    elif pages is not None:
        errors.append("page_data must be an array")
    return errors


def validate(config_path: str, schema_path: Path) -> int:
    config = json.load(open(config_path))
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        errors = _basic_checks(config)
        print("jsonschema not installed — basic checks only (pip install jsonschema for full validation).")
        for e in errors:
            print(f"  - {e}")
        print("OK (basic)" if not errors else f"{len(errors)} basic error(s)")
        return 0 if not errors else 1

    schema = json.load(open(schema_path))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(config), key=lambda e: list(e.path))
    if not errors:
        print(f"OK — {config_path} matches the schema.")
        return 0
    print(f"{len(errors)} schema error(s) in {config_path}:")
    for e in errors:
        path = "/".join(map(str, e.path)) or "(root)"
        print(f"  - {path}: {e.message}")
    return 1


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    schema = Path(sys.argv[2]) if len(sys.argv) > 2 else SCHEMA_PATH
    return validate(sys.argv[1], schema)


if __name__ == "__main__":
    sys.exit(main())
