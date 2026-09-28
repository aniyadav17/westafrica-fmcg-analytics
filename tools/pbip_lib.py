"""
pbip_lib.py - small helper library that writes Power BI projects (PBIP) as files:
a TMDL semantic model plus PBIR report pages. Used by build_powerbi.py.

Why build the reports as files instead of clicking in Power BI Desktop?
  * everything is version-controlled and reviewable in git
  * the same measure or page layout can be reused across projects
  * a report with 4-5 pages is rebuilt in seconds after a change
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

# ----------------------------------------------------------------------------------- styling
NAVY, BLUE, TEAL, INK, BG, BORDER, STRIPE = "#0D2B5C", "#1C5CAB", "#0E7C7B", "#1F2937", "#F3F5F9", "#D6DEEA", "#F5F8FC"
VC_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.12.0/schema.json"
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"
PAGES_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json"
W, H, MG, GAP = 1920, 1080, 20, 20
TITLE_Y, TITLE_H = 15, 72
KPI_Y, KPI_H = 107, 118
BODY_Y = 245
BODY_H = H - BODY_Y - MG

M_TYPE = {"string": "type text", "int64": "Int64.Type", "double": "type number",
          "dateTime": "type date", "boolean": "type logical"}


def gid() -> str:
    return str(uuid.uuid4())


# ----------------------------------------------------------------------------------- TMDL model
class Col:
    def __init__(self, name, dtype="string", fmt=None, hidden=False, summarize=None, sort_by=None,
                 source=None, blank_to_null=False, desc=None):
        self.name, self.dtype, self.fmt, self.hidden = name, dtype, fmt, hidden
        self.summarize = summarize or ("none" if dtype in ("string", "dateTime", "boolean") else "sum")
        self.sort_by, self.source, self.blank_to_null, self.desc = sort_by, source or name, blank_to_null, desc


class Measure:
    def __init__(self, name, dax, fmt=None, folder=None, desc=None, hidden=False):
        self.name, self.dax, self.fmt, self.folder, self.desc, self.hidden = name, dax, fmt, folder, desc, hidden


class Table:
    def __init__(self, name, file=None, columns=(), measures=(), desc=None, gz=False, dax=None,
                 date_table=False, hidden=False, computed=None):
        self.name, self.file, self.columns, self.measures = name, file, list(columns), list(measures)
        self.desc, self.gz, self.dax, self.date_table, self.hidden = desc, gz, dax, date_table, hidden
        self.computed = dict(computed or {})  # column name -> M expression, added before typing

    def m_expression(self) -> str:
        read = (f'Binary.Decompress(File.Contents(DataFolder & "{self.file}"), Compression.GZip)'
                if self.gz else f'File.Contents(DataFolder & "{self.file}")')
        types = ", ".join(f'{{"{c.name}", {M_TYPE[c.dtype]}}}' for c in self.columns)
        blanks = [c.name for c in self.columns if c.blank_to_null]
        steps = [
            f'    Source = Csv.Document({read}, [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
            "    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),",
            '    Renamed = Table.TransformColumnNames(Headers, each Text.Replace(_, "_", " ")),',
        ]
        last = "Renamed"
        if blanks:
            cols = ", ".join(f'"{b}"' for b in blanks)
            steps.append(f'    Blanks = Table.ReplaceValue(Renamed, "", null, Replacer.ReplaceValue, {{{cols}}}),')
            last = "Blanks"
        for i, (cname, expr) in enumerate(self.computed.items(), start=1):
            step = f"Added{i}"
            steps.append(f'    {step} = Table.AddColumn({last}, "{cname}", each {expr}),')
            last = step
        steps.append(f'    Typed = Table.TransformColumnTypes({last}, {{{types}}}, "en-US")')
        return "let\n" + "\n".join(steps) + "\nin\n    Typed"

    def tmdl(self) -> str:
        out = []
        if self.desc:
            out.append(f"/// {self.desc}")
        out.append(f"table {quote(self.name)}")
        out.append(f"\tlineageTag: {gid()}")
        if self.hidden:
            out.append("\tisHidden")
        if self.date_table:
            out.append("\tdataCategory: Time")
        out.append("")
        for me in self.measures:
            if me.desc:
                out.append(f"\t/// {me.desc}")
            out.append(f"\tmeasure {quote(me.name)} = {me.dax}")
            if me.fmt:
                out.append(f"\t\tformatString: {me.fmt}")
            if me.hidden:
                out.append("\t\tisHidden")
            if me.folder:
                out.append(f"\t\tdisplayFolder: {me.folder}")
            out.append(f"\t\tlineageTag: {gid()}")
            out.append("")
        for c in self.columns:
            if c.desc:
                out.append(f"\t/// {c.desc}")
            out.append(f"\tcolumn {quote(c.name)}")
            if self.date_table and c.dtype == "dateTime" and c.name == "Date":
                out.append("\t\tisUnique")
            out.append(f"\t\tdataType: {c.dtype}")
            if c.hidden:
                out.append("\t\tisHidden")
            if c.fmt:
                out.append(f"\t\tformatString: {c.fmt}")
            out.append(f"\t\tlineageTag: {gid()}")
            out.append(f"\t\tsummarizeBy: {c.summarize}")
            if c.sort_by:
                out.append(f"\t\tsortByColumn: {quote(c.sort_by)}")
            if self.dax:
                out.append("\t\tisNameInferred")
                out.append(f"\t\tsourceColumn: [{c.name}]")
            else:
                out.append(f"\t\tsourceColumn: {c.source}")
            out.append("")
        if self.dax:
            out.append(f"\tpartition {quote(self.name)} = calculated")
            out.append("\t\tmode: import")
            out.append("\t\tsource =")
            for line in self.dax.strip().splitlines():
                out.append(f"\t\t\t\t{line}")
        else:
            out.append(f"\tpartition {quote(self.name)} = m")
            out.append("\t\tmode: import")
            out.append("\t\tsource =")
            for line in self.m_expression().splitlines():
                out.append(f"\t\t\t\t{line}")
        out.append("")
        return "\n".join(out)


def quote(name: str) -> str:
    return name if name.replace("_", "").isalnum() else f"'{name}'"


def rel_name(ft, fc, tt, tc):
    return f"{ft}_{fc}_{tt}_{tc}".replace(" ", "_")


def write_model(model_dir: Path, tables: list[Table], relationships: list[tuple], data_folder: str):
    defn = model_dir / "definition"
    if defn.exists():
        shutil.rmtree(defn, ignore_errors=True)
    (defn / "tables").mkdir(parents=True, exist_ok=True)
    (defn / "cultures").mkdir(parents=True, exist_ok=True)
    (defn / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1606\n\n", encoding="utf-8")
    (defn / "cultures" / "en-US.tmdl").write_text("cultureInfo en-US\n\n", encoding="utf-8")
    (model_dir / "definition.pbism").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2", "settings": {}}, indent=2), encoding="utf-8")
    (defn / "expressions.tmdl").write_text(
        "/// Folder holding the CSV extracts produced by data/generate_data.py.\n"
        "/// Set this once per machine: Home > Transform data > Edit parameters.\n"
        f'expression DataFolder = "{data_folder}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
        f"\tlineageTag: {gid()}\n\n", encoding="utf-8")
    for t in tables:
        (defn / "tables" / f"{t.name}.tmdl").write_text(t.tmdl(), encoding="utf-8")
    rel_lines = []
    for ft, fc, tt, tc in relationships:
        rel_lines.append(f"relationship {quote(rel_name(ft, fc, tt, tc))}")
        rel_lines.append(f"\tfromColumn: {quote(ft)}.{quote(fc)}")
        rel_lines.append(f"\ttoColumn: {quote(tt)}.{quote(tc)}")
        rel_lines.append("")
    (defn / "relationships.tmdl").write_text("\n".join(rel_lines), encoding="utf-8")
    refs = "\n".join(f"ref table {quote(t.name)}" for t in tables)
    (defn / "model.tmdl").write_text(
        "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n"
        "\tdataAccessOptions\n\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n"
        "annotation __PBI_TimeIntelligenceEnabled = 0\n\nannotation PBI_ProTooling = [\"DevMode\"]\n\n"
        f"annotation PBI_QueryOrder = {json.dumps([t.name for t in tables])}\n\n{refs}\n\nref cultureInfo en-US\n\n",
        encoding="utf-8")


# ----------------------------------------------------------------------------------- PBIR report
def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def color(c):
    return {"solid": {"color": lit(f"'{c}'")}}


def measure_ref(name, entity="KPI"):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": name}}


def column_ref(entity, name):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": name}}


def M(name, disp=None):
    return (measure_ref(name), f"KPI.{name}", disp)


def C(entity, name, disp=None):
    return (column_ref(entity, name), f"{entity}.{name}", disp)


def _projection(field, ref, disp, active=False):
    p = {"field": field, "queryRef": ref, "nativeQueryRef": ref.split(".", 1)[1]}
    if disp:
        p["displayName"] = disp
    if active:
        p["active"] = True
    return p


def _container(title=None, bg="#FFFFFF"):
    o = {
        "background": [{"properties": {"show": lit("true"), "color": color(bg), "transparency": lit("0D")}}],
        "border": [{"properties": {"show": lit("true"), "color": color(BORDER), "radius": lit("8D")}}],
        "dropShadow": [{"properties": {"show": lit("false")}}],
        "padding": [{"properties": {"top": lit("6D"), "bottom": lit("6D"), "left": lit("10D"), "right": lit("10D")}}],
    }
    o["title"] = ([{"properties": {"show": lit("true"), "text": lit(f"'{title}'"), "fontColor": color(NAVY),
                                   "fontSize": lit("13D"), "bold": lit("true"), "fontFamily": lit("'Segoe UI Semibold'")}}]
                  if title else [{"properties": {"show": lit("false")}}])
    return o


def _pos(x, y, w, h, z):
    return {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z}


def textbox(name, x, y, w, h, z, title, subtitle):
    return {"$schema": VC_SCHEMA, "name": name, "position": _pos(x, y, w, h, z), "visual": {
        "visualType": "textbox",
        "objects": {"general": [{"properties": {"paragraphs": [
            {"textRuns": [{"value": title, "textStyle": {"fontWeight": "bold", "fontFamily": "Segoe UI Semibold",
                                                         "fontSize": "20pt", "color": "#FFFFFF"}}]},
            {"textRuns": [{"value": subtitle, "textStyle": {"fontFamily": "Segoe UI", "fontSize": "10.5pt",
                                                            "color": "#D7E3F5"}}]}]}}]},
        "visualContainerObjects": {
            "background": [{"properties": {"show": lit("true"), "color": color(NAVY), "transparency": lit("0D")}}],
            "border": [{"properties": {"show": lit("false")}}],
            "title": [{"properties": {"show": lit("false")}}],
            "padding": [{"properties": {"top": lit("10D"), "left": lit("18D")}}]},
        "drillFilterOtherVisuals": True}}


def card(name, x, y, w, h, z, measure_name, title, entity="KPI"):
    return {"$schema": VC_SCHEMA, "name": name, "position": _pos(x, y, w, h, z), "visual": {
        "visualType": "card",
        "query": {"queryState": {"Values": {"projections": [
            _projection(measure_ref(measure_name, entity), f"{entity}.{measure_name}", None)]}}},
        "objects": {
            "labels": [{"properties": {"fontSize": lit("28D"), "color": color(BLUE),
                                       "fontFamily": lit("'Segoe UI Semibold'")}}],
            "categoryLabels": [{"properties": {"show": lit("false")}}]},
        "visualContainerObjects": _container(title),
        "drillFilterOtherVisuals": True}}


def table_visual(name, x, y, w, h, z, title, fields, sort_field=None, descending=True, totals=True):
    q = {"queryState": {"Values": {"projections": [_projection(f, r, d) for f, r, d in fields]}}}
    if sort_field is not None:
        q["sortDefinition"] = {"sort": [{"field": sort_field, "direction": "Descending" if descending else "Ascending"}],
                               "isDefaultSort": True}
    return {"$schema": VC_SCHEMA, "name": name, "position": _pos(x, y, w, h, z), "visual": {
        "visualType": "tableEx", "query": q,
        "objects": {
            "columnHeaders": [{"properties": {"fontColor": color("#FFFFFF"), "backColor": color(BLUE),
                                              "bold": lit("true"), "fontSize": lit("10.5D"), "wordWrap": lit("true")}}],
            "values": [{"properties": {"backColorPrimary": color("#FFFFFF"), "backColorSecondary": color(STRIPE),
                                       "fontColorPrimary": color(INK), "fontColorSecondary": color(INK),
                                       "fontSize": lit("10.5D")}}],
            "total": [{"properties": {"totals": lit("true" if totals else "false"), "bold": lit("true"),
                                      "backColor": color("#E8EEF7")}}],
            "grid": [{"properties": {"gridHorizontal": lit("true"), "rowPadding": lit("3D")}}]},
        "visualContainerObjects": _container(title),
        "drillFilterOtherVisuals": True}}


def chart(name, x, y, w, h, z, title, visual_type, category=None, values=(), series=None, y2=(),
          sort_field=None, descending=True, legend=True, data_labels=False, legend_position="Bottom"):
    qs = {}
    if category is not None:
        f, r, d = category
        qs["Category"] = {"projections": [_projection(f, r, d, active=True)]}
    if series is not None:
        f, r, d = series
        qs["Series"] = {"projections": [_projection(f, r, d)]}
    if values:
        qs["Y"] = {"projections": [_projection(f, r, d) for f, r, d in values]}
    if y2:
        qs["Y2"] = {"projections": [_projection(f, r, d) for f, r, d in y2]}
    q = {"queryState": qs}
    if sort_field is not None:
        q["sortDefinition"] = {"sort": [{"field": sort_field, "direction": "Descending" if descending else "Ascending"}],
                               "isDefaultSort": True}
    objects = {
        "categoryAxis": [{"properties": {"showAxisTitle": lit("false"), "fontSize": lit("10D"),
                                         "labelColor": color(INK)}}],
        "valueAxis": [{"properties": {"showAxisTitle": lit("false"), "fontSize": lit("10D"), "labelColor": color(INK)}}],
        "labels": [{"properties": {"show": lit("true" if data_labels else "false"), "fontSize": lit("9D"),
                                   "color": color(INK)}}],
        "legend": [{"properties": {"show": lit("true" if (legend and (series or len(values) + len(y2) > 1)) else "false"),
                                   "position": lit(f"'{legend_position}'"), "showTitle": lit("false"),
                                   "fontSize": lit("10D"), "labelColor": color(INK)}}],
    }
    return {"$schema": VC_SCHEMA, "name": name, "position": _pos(x, y, w, h, z), "visual": {
        "visualType": visual_type, "query": q, "objects": objects,
        "visualContainerObjects": _container(title), "drillFilterOtherVisuals": True}}


def slicer(name, x, y, w, h, z, field, title=None, mode="Dropdown"):
    f, r, d = field
    return {"$schema": VC_SCHEMA, "name": name, "position": _pos(x, y, w, h, z), "visual": {
        "visualType": "slicer",
        "query": {"queryState": {"Values": {"projections": [_projection(f, r, d)]}}},
        "objects": {"data": [{"properties": {"mode": lit(f"'{mode}'")}}],
                    "header": [{"properties": {"show": lit("true"), "fontSize": lit("10D"), "fontColor": color(NAVY)}}]},
        "visualContainerObjects": _container(title),
        "drillFilterOtherVisuals": True}}


def kpi_row(cards):
    """4-6 KPI cards laid out across the page width."""
    n = len(cards)
    w = (W - 2 * MG - (n - 1) * GAP) // n
    return [card(f"kpi_{i + 1}", MG + i * (w + GAP), KPI_Y, w, KPI_H, 2000 + i * 10, m, t) for i, (m, t) in enumerate(cards)]


def _one_filter(name, entity, column_name, value):
    return {"name": name, "field": column_ref(entity, column_name), "type": "Categorical",
            "filter": {"Version": 2, "From": [{"Name": "d", "Entity": entity, "Type": 0}],
                       "Where": [{"Condition": {"In": {
                           "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "d"}}, "Property": column_name}}],
                           "Values": [[{"Literal": {"Value": value}}]]}}}]},
            "howCreated": "User"}


def _filter_config(specs):
    """specs: list of (entity, column, value literal) -> a PBIR filterConfig."""
    return {"filters": [_one_filter(f"flt{i}", *spec) for i, spec in enumerate(specs, start=1)]}


def write_report(report_dir: Path, pages: list[tuple], year_filter: tuple | None = None, unfiltered: tuple = ()):
    """pages: list of (page_id, display_name, [visuals]).

    year_filter is applied as a page-level filter to every page except those named in `unfiltered`,
    so an operational page (a shipment tracker, say) can still show everything that is open."""
    defn = report_dir / "definition"
    pages_dir = defn / "pages"
    if pages_dir.exists():
        shutil.rmtree(pages_dir, ignore_errors=True)
    pages_dir.mkdir(parents=True, exist_ok=True)
    for page_def in pages:
        pid, display, visuals = page_def[:3]
        extra = list(page_def[3]) if len(page_def) > 3 else []
        pd_ = pages_dir / pid
        (pd_ / "visuals").mkdir(parents=True, exist_ok=True)
        page = {"$schema": PAGE_SCHEMA, "name": pid, "displayName": display, "displayOption": "FitToPage",
                "height": H, "width": W,
                "objects": {"outspace": [{"properties": {"color": color(BG)}}],
                            "background": [{"properties": {"color": color(BG), "transparency": lit("0D")}}]}}
        specs = ([year_filter] if year_filter and pid not in unfiltered else []) + extra
        if specs:
            page["filterConfig"] = _filter_config(specs)
        (pd_ / "page.json").write_text(json.dumps(page, indent=2, ensure_ascii=False), encoding="utf-8")
        for v in visuals:
            vd = pd_ / "visuals" / v["name"]
            vd.mkdir(parents=True, exist_ok=True)
            (vd / "visual.json").write_text(json.dumps(v, indent=2, ensure_ascii=False), encoding="utf-8")
    (pages_dir / "pages.json").write_text(json.dumps({
        "$schema": PAGES_SCHEMA, "pageOrder": [p[0] for p in pages], "activePageName": pages[0][0]},
        indent=2), encoding="utf-8")
    report = json.loads((defn / "report.json").read_text(encoding="utf-8"))
    report.pop("filterConfig", None)
    (defn / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def scaffold(root: Path, project: str, template: Path):
    """Create <project>.pbip + .Report + .SemanticModel from an existing empty PBIP template."""
    rep, mod = root / f"{project}.Report", root / f"{project}.SemanticModel"
    for d in (rep, mod):
        for _ in range(5):  # OneDrive can hold a handle on a folder for a moment
            if not d.exists():
                break
            shutil.rmtree(d, ignore_errors=True)
            time.sleep(0.3)
    shutil.copytree(template / "template.Report", rep, dirs_exist_ok=True)
    shutil.copytree(template / "template.SemanticModel", mod, dirs_exist_ok=True)
    for folder, kind in ((rep, "Report"), (mod, "SemanticModel")):
        plat = folder / ".platform"
        data = json.loads(plat.read_text(encoding="utf-8"))
        data["metadata"]["displayName"] = project
        data["config"]["logicalId"] = gid()
        plat.write_text(json.dumps(data, indent=2), encoding="utf-8")
    (root / f"{project}.pbip").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{project}.Report"}}],
        "settings": {"enableAutoRecovery": True}}, indent=2), encoding="utf-8")
    (rep / "definition.pbir").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{project}.SemanticModel"}}}, indent=2),
        encoding="utf-8")
    return rep, mod
