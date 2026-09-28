#!/usr/bin/env python3
"""
sanitise_paths.py
=================
Resets the `DataFolder` parameter of every Power BI project to a neutral placeholder, and checks that no
file about to be committed carries a local path.

Power BI Desktop writes the folder you are actually using into the semantic model, so run this before
committing (or after saving a project from Desktop):

    python tools/sanitise_paths.py          # rewrite and check
    python tools/sanitise_paths.py --check  # check only, non-zero exit if a local path is found
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "C:\\\\westafrica-fmcg-analytics\\\\data\\\\"
RE_PARAM = re.compile(r'(expression DataFolder = ")([^"]*)(")')
# anything that looks like a real user folder rather than the placeholder
RE_LOCAL = re.compile(r"[A-Za-z]:\\(?:Users|Documents)|OneDrive[\\/ ]-|/Users/", re.I)
SKIP_DIRS = {".git", ".pbi", "__pycache__", "data"}


def files_to_check():
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix.lower() in {".tmdl", ".json", ".pbip", ".pbir", ".pbism", ".md", ".py", ".gitignore", ""}:
            yield path


def main() -> int:
    check_only = "--check" in sys.argv
    changed = []
    for model in sorted(ROOT.glob("powerbi/*.SemanticModel/definition/expressions.tmdl")):
        text = model.read_text(encoding="utf-8")
        current = RE_PARAM.search(text)
        if current and current.group(2) != PLACEHOLDER.replace("\\\\", "\\"):
            if not check_only:
                model.write_text(RE_PARAM.sub(lambda m: m.group(1) + PLACEHOLDER.replace("\\\\", "\\") + m.group(3), text),
                                 encoding="utf-8")
            changed.append(model.relative_to(ROOT))

    problems = []
    for path in files_to_check():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), start=1):
            if RE_LOCAL.search(line) and "sanitise_paths" not in path.name:
                problems.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:110]}")

    for c in changed:
        print(("would reset " if check_only else "reset ") + str(c))
    if problems:
        print("\nLocal paths still present:")
        for p in problems:
            print("  " + p)
        return 1
    print("No local paths in the files to be committed." if not changed or check_only else
          "\nNo local paths in the files to be committed.")
    return 1 if (check_only and changed) else 0


if __name__ == "__main__":
    sys.exit(main())
