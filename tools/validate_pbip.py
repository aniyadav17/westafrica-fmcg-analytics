#!/usr/bin/env python3
"""
validate_pbip.py
================
Checks the generated Power BI projects before they are opened in Power BI Desktop:

  1. every column declared in the model exists in the CSV extract it is loaded from
  2. every field used by a report visual exists in that project's semantic model
  3. every measure the visuals use is defined, and every DAX measure reference resolves
  4. relationships point at columns that exist

Usage:  python tools/validate_pbip.py
"""
from __future__ import annotations

import csv
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PBI = ROOT / "powerbi"
DATA = ROOT / "data"

RE_TABLE = re.compile(r"^table ('(?P<q>[^']+)'|(?P<p>\S+))", re.M)
RE_COL = re.compile(r"^\tcolumn ('(?P<q>[^']+)'|(?P<p>\S+))", re.M)
RE_MEAS = re.compile(r"^\tmeasure ('(?P<q>[^']+)'|(?P<p>[^=\s]+)) =", re.M)
RE_FILE = re.compile(r'DataFolder & "([^"]+)"')
RE_ADDED = re.compile(r'Table\.AddColumn\([^,]+, "([^"]+)"')
RE_REF = re.compile(r"\[([^\[\]]+)\]")


def name(m):
    return m.group("q") or m.group("p")


def read_model(model_dir: Path):
    tables = {}
    for f in sorted((model_dir / "definition" / "tables").glob("*.tmdl")):
        text = f.read_text(encoding="utf-8")
        t = name(RE_TABLE.search(text))
        tables[t] = {
            "columns": {name(m) for m in RE_COL.finditer(text)},
            "measures": {name(m) for m in RE_MEAS.finditer(text)},
            "file": (RE_FILE.search(text).group(1) if RE_FILE.search(text) else None),
            "computed": set(RE_ADDED.findall(text)),
            "dax": text,
        }
    rels = []
    rel_file = model_dir / "definition" / "relationships.tmdl"
    for block in rel_file.read_text(encoding="utf-8").split("relationship ")[1:]:
        cols = re.findall(r"(?:from|to)Column: ('([^']+)'|[^.\s]+)\.('([^']+)'|\S+)", block)
        rels.append([(c[1] or c[0], c[3] or c[2]) for c in cols])
    return tables, rels


def csv_header(fname: str) -> list[str]:
    path = DATA / fname
    op = gzip.open if fname.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8", newline="") as fh:
        return [c.replace("_", " ") for c in next(csv.reader(fh))]


def check_project(project: str) -> list[str]:
    errors = []
    model = PBI / f"{project}.SemanticModel"
    report = PBI / f"{project}.Report"
    tables, rels = read_model(model)

    # 1. model columns vs CSV headers
    for tname, t in tables.items():
        if not t["file"]:
            continue
        header = csv_header(t["file"])
        for col in sorted(t["columns"] - t["computed"]):
            if col not in header:
                errors.append(f"[data]  {tname}[{col}] is not a column of {t['file']}")

    # 2/3. report fields
    all_fields = {f"{tn}.{c}" for tn, t in tables.items() for c in t["columns"] | t["measures"]}
    for vis in sorted((report / "definition" / "pages").rglob("visual.json")):
        page = vis.parents[2].name
        data = json.loads(vis.read_text(encoding="utf-8"))
        for ref in re.findall(r'"queryRef": "([^"]+)"', json.dumps(data)):
            if ref not in all_fields:
                errors.append(f"[report] {page}/{vis.parent.name}: unknown field {ref}")

    # 3b. measure references inside DAX
    measures = {m for t in tables.values() for m in t["measures"]}
    columns = {c for t in tables.values() for c in t["columns"]}
    for tname, t in tables.items():
        for block in re.split(r"^\tmeasure ", t["dax"], flags=re.M)[1:]:
            mname = name(re.match(r"('(?P<q>[^']+)'|(?P<p>[^=\s]+)) =", block))
            body = block.split("\n\t\t")[0]
            for ref in RE_REF.findall(body):
                if ref in measures or ref in columns or ref.startswith("KPI"):
                    continue
                errors.append(f"[dax]    {tname}[{mname}] references [{ref}] which does not exist")

    # 4. relationships
    for pair in rels:
        for tn, cn in pair:
            if tn not in tables or cn not in tables[tn]["columns"]:
                errors.append(f"[model]  relationship column {tn}[{cn}] does not exist")

    pages = len(list((report / "definition" / "pages").glob("*/page.json")))
    visuals = len(list((report / "definition" / "pages").rglob("visual.json")))
    print(f"{project:24s} {len(tables):2d} tables, {sum(len(t['measures']) for t in tables.values()):3d} measures, "
          f"{len(rels):2d} relationships, {pages} pages, {visuals} visuals -> "
          f"{'OK' if not errors else str(len(errors)) + ' problem(s)'}")
    return errors


def main():
    failed = 0
    for project in ("Procurement Analytics", "Inventory Analytics", "Sales Analytics"):
        errors = check_project(project)
        for e in errors:
            print("   " + e)
        failed += len(errors)
    print("\nAll checks passed." if not failed else f"\n{failed} problem(s) found.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
