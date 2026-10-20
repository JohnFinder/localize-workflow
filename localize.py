#!/usr/bin/env python3
"""Run the same localization CLI bundled with the portable agent skill."""

from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "skills/localize-apple-app/scripts/localize.py"),
                  run_name="__main__")
