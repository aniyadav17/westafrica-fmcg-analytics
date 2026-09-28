#!/usr/bin/env python3
"""
build_powerbi.py
================
Builds the three Power BI projects of this repository from one definition:

    powerbi/Procurement Analytics.pbip   PO -> shipment -> customs -> landed cost
    powerbi/Inventory Analytics.pbip     stock health, cover, movements, turnover
    powerbi/Sales Analytics.pbip         B2B and supermarket sales, margin, targets

Each project is a self-contained PBIP: a TMDL semantic model (tables, relationships,
DAX measures) plus PBIR report pages (KPI cards, charts and tables).

Usage:  python tools/build_powerbi.py [--data-folder "C:\\path\\to\\data\\"]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from pbip_lib import (BODY_H, BODY_Y, GAP, MG, TITLE_H, TITLE_Y, W, C, Col, M, Measure, Table, card, chart, column_ref,
                      kpi_row, measure_ref, scaffold, slicer, table_visual, textbox, write_model, write_report)

ROOT = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent
PBI = ROOT / "powerbi"
USD = "\\$#,##0"
USD2 = "\\$#,##0.00"
PCT = "0.0%"
PCT0 = "0%"
NUM = "#,##0"
NUM1 = "#,##0.0"
DAYS = "0.0"
SUB = "Atlantic Foods Trading Ltd.  |  Sierra Leone · Gambia · Liberia  |  FY Apr-Mar, all values in USD"

# ----------------------------------------------------------------------------------- shared dimensions
def dim_date():
    return Table("Date", "dim_date.csv", date_table=True, desc="Calendar Apr-2021 to Mar-2026 with financial year (Apr-Mar).", columns=[
        Col("Date", "dateTime", fmt="dd-MMM-yyyy"),
        Col("Year", "int64", fmt="0", summarize="none"),
        Col("Month No", "int64", hidden=True, summarize="none"),
        Col("Month", "string", sort_by="Month No"),
        Col("Month Year", "string", sort_by="Month Year Sort"),
        Col("Month Year Sort", "int64", hidden=True, summarize="none"),
        Col("Month Start", "dateTime", fmt="MMM-yyyy"),
        Col("Quarter", "string"),
        Col("Financial Year", "string"),
        Col("FY Quarter", "string"),
        Col("FY Month No", "int64", hidden=True, summarize="none"),
    ])


def dim_product():
    return Table("Product", "dim_product.csv", desc="SKU master: Category > Sub-category > Brand > SKU, with import duty rate and pack data.", columns=[
        Col("SKU ID", "string"), Col("SKU Code", "string"), Col("Product Name", "string"), Col("Brand", "string"),
        Col("Category", "string"), Col("Sub Category", "string"), Col("Variant", "string"), Col("Pack Size", "string"),
        Col("Units Per Carton", "int64", summarize="none"), Col("CBM Per Carton", "double", fmt="0.000", summarize="none"),
        Col("Duty Rate Pct", "double", fmt="0", summarize="none"), Col("Shelf Life Days", "int64", summarize="none"),
        Col("Origin Country", "string"), Col("Supplier ID", "string", hidden=True), Col("Status", "string"),
    ])


def dim_location():
    return Table("Location", "dim_location.csv", desc="Warehouses and supermarkets by country.", columns=[
        Col("Location ID", "string"), Col("Location Name", "string"), Col("Location Type", "string"),
        Col("Country Code", "string", hidden=True), Col("Country", "string"), Col("City", "string"),
        Col("Opening Date", "dateTime", fmt="dd-MMM-yyyy"), Col("Warehouse ID", "string", hidden=True),
    ])


def dim_supplier():
    return Table("Supplier", "dim_supplier.csv", desc="Overseas suppliers with origin country, port of loading and terms.", columns=[
        Col("Supplier ID", "string"), Col("Supplier Name", "string"), Col("Origin Country", "string"),
        Col("Tier", "string", desc="Internal supplier rating: a = reliable, b = average, c = weak."),
        Col("Payment Terms", "string"), Col("Region", "string"), Col("Port of Loading", "string"), Col("Incoterm", "string"),
    ])


def kpi_table(measures):
    return Table("KPI", desc="All report measures (the table itself holds no data).",
                 dax='ROW("KPI", BLANK())', columns=[Col("KPI", "string", hidden=True)], measures=measures)


# ===================================================================================== PROCUREMENT
def procurement_model():
    po = Table("Purchase Orders", "fact_purchase_orders.csv", desc="Import purchase orders (one row per PO).", columns=[
        Col("PO No", "string"), Col("PO Date", "dateTime", fmt="dd-MMM-yyyy"), Col("Supplier ID", "string", hidden=True),
        Col("Supplier Name", "string"), Col("Origin Country", "string"), Col("Incoterm", "string"),
        Col("Payment Terms", "string"), Col("Warehouse ID", "string", hidden=True), Col("Country Code", "string", hidden=True),
        Col("Country", "string"), Col("Lines", "int64"), Col("Qty Ordered Cartons", "int64", fmt=NUM),
        Col("FOB Value USD", "double", fmt=USD), Col("Containers", "int64", fmt=NUM), Col("CBM", "double", fmt=NUM1),
        Col("Shipment No", "string"), Col("Status", "string"),
    ])
    pol = Table("PO Lines", "fact_po_lines.csv", desc="Purchase order lines with FOB and landed unit cost.", columns=[
        Col("PO No", "string", hidden=True), Col("PO Date", "dateTime", hidden=True), Col("Supplier ID", "string", hidden=True),
        Col("Warehouse ID", "string", hidden=True), Col("SKU ID", "string", hidden=True),
        Col("Qty Ordered Cartons", "int64", fmt=NUM), Col("FOB Unit Cost USD", "double", fmt=USD2),
        Col("FOB Value USD", "double", fmt=USD), Col("Landed Unit Cost USD", "double", fmt=USD2),
        Col("Qty Received Cartons", "int64", fmt=NUM), Col("Status", "string"),
    ])
    ship = Table("Shipments", "fact_shipments.csv", desc="Container shipments: sailing, arrival, customs clearance and landed value.",
                 computed={"Arrival Date": "if [ATA] <> null then [ATA] else [ETA]"}, columns=[
        Col("Arrival Date", "dateTime", fmt="dd-MMM-yyyy", hidden=True,
            desc="Actual arrival, or the expected arrival while the shipment is still open. Used to place every shipment on the calendar."),
        Col("Shipment No", "string"), Col("PO No", "string"), Col("Supplier ID", "string", hidden=True),
        Col("Supplier Name", "string"), Col("Origin Country", "string"), Col("Port of Loading", "string"),
        Col("Port of Discharge", "string"), Col("Warehouse ID", "string", hidden=True), Col("Country Code", "string", hidden=True),
        Col("Country", "string"), Col("Containers", "int64", fmt=NUM), Col("Container Type", "string"),
        Col("CBM", "double", fmt=NUM1), Col("Qty Cartons", "int64", fmt=NUM),
        Col("ETD", "dateTime", fmt="dd-MMM-yyyy"), Col("ATD", "dateTime", fmt="dd-MMM-yyyy"),
        Col("ETA", "dateTime", fmt="dd-MMM-yyyy"), Col("ATA", "dateTime", fmt="dd-MMM-yyyy", blank_to_null=True),
        Col("Customs Cleared Date", "dateTime", fmt="dd-MMM-yyyy", blank_to_null=True),
        Col("Warehouse Receipt Date", "dateTime", fmt="dd-MMM-yyyy", blank_to_null=True),
        Col("Transit Days", "int64", summarize="none", blank_to_null=True),
        Col("Clearance Days", "int64", summarize="none", blank_to_null=True),
        Col("Total Lead Time Days", "int64", summarize="none", blank_to_null=True),
        Col("Delay Days", "int64", summarize="none", blank_to_null=True),
        Col("On Time", "boolean", blank_to_null=True), Col("In Full", "boolean", blank_to_null=True),
        Col("OTIF", "boolean", blank_to_null=True),
        Col("FOB Value USD", "double", fmt=USD), Col("Landed Value USD", "double", fmt=USD),
        Col("Landed Cost Uplift Pct", "double", fmt=NUM1, summarize="none"), Col("Status", "string"),
    ])
    # the cost rows hang off their shipment rather than off their own date, so every component sits in the
    # same period as the shipment it belongs to and Import Cost ties back to Landed Value
    lc = Table("Landed Cost", "fact_landed_cost.csv", desc="Cost build-up per shipment: goods, freight, insurance, duty, clearing, inland, demurrage.", columns=[
        Col("Shipment No", "string", hidden=True), Col("PO No", "string", hidden=True),
        Col("Cost Date", "dateTime", fmt="dd-MMM-yyyy", hidden=True), Col("Warehouse ID", "string", hidden=True),
        Col("Country", "string", hidden=True), Col("Origin Country", "string", hidden=True),
        Col("Cost Component", "string"), Col("Amount USD", "double", fmt=USD),
    ])
    grn = Table("Goods Receipts", "fact_goods_receipts.csv", desc="Warehouse receipts (GRN) with landed unit cost.", columns=[
        Col("GRN No", "string"), Col("GRN Date", "dateTime", fmt="dd-MMM-yyyy"), Col("PO No", "string"),
        Col("Shipment No", "string", hidden=True), Col("Warehouse ID", "string", hidden=True), Col("SKU ID", "string", hidden=True),
        Col("Qty Ordered Cartons", "int64", fmt=NUM), Col("Qty Received Cartons", "int64", fmt=NUM),
        Col("Landed Unit Cost USD", "double", fmt=USD2), Col("Landed Value USD", "double", fmt=USD),
    ])
    S, P, T, D = "1. Purchasing", "2. Landed Cost", "3. Supplier Performance", "4. Display"
    m = [
        Measure("PO Value", "SUM('Purchase Orders'[FOB Value USD])", USD, S, "Value of purchase orders raised (FOB, before freight and duty)."),
        Measure("PO Count", "DISTINCTCOUNT('Purchase Orders'[PO No])", NUM, S),
        Measure("Containers", "SUM('Purchase Orders'[Containers])", NUM, S),
        Measure("Cartons Ordered", "SUM('PO Lines'[Qty Ordered Cartons])", NUM, S),
        Measure("Cartons Received", "SUM('Goods Receipts'[Qty Received Cartons])", NUM, S),
        Measure("Goods Received Value", "SUM('Goods Receipts'[Landed Value USD])", USD, S),
        Measure("Suppliers Used", "DISTINCTCOUNT('Purchase Orders'[Supplier ID])", NUM, S),
        Measure("Avg PO Value", "DIVIDE([PO Value], [PO Count])", USD, S),
        Measure("Avg FOB per Carton", "DIVIDE(SUM('PO Lines'[FOB Value USD]), SUM('PO Lines'[Qty Ordered Cartons]))", USD2, S),
        Measure("Avg Landed per Carton", "DIVIDE(SUMX('PO Lines', 'PO Lines'[Qty Ordered Cartons] * 'PO Lines'[Landed Unit Cost USD]), SUM('PO Lines'[Qty Ordered Cartons]))", USD2, S),
        # ---- landed cost ----
        Measure("Import Cost", "SUM('Landed Cost'[Amount USD])", USD, P, "All cost components of the shipments, including the goods themselves."),
        Measure("Goods Cost", 'CALCULATE([Import Cost], KEEPFILTERS(\'Landed Cost\'[Cost Component] = "FOB / Goods"))', USD, P),
        Measure("Freight Cost", 'CALCULATE([Import Cost], KEEPFILTERS(\'Landed Cost\'[Cost Component] = "Ocean Freight"))', USD, P),
        Measure("Duty Cost", 'CALCULATE([Import Cost], KEEPFILTERS(\'Landed Cost\'[Cost Component] = "Customs Duty"))', USD, P),
        Measure("Clearing Cost", 'CALCULATE([Import Cost], KEEPFILTERS(\'Landed Cost\'[Cost Component] = "Clearing & Port Charges"))', USD, P),
        Measure("Inland Cost", 'CALCULATE([Import Cost], KEEPFILTERS(\'Landed Cost\'[Cost Component] = "Inland Transport"))', USD, P),
        Measure("Demurrage Cost", 'CALCULATE([Import Cost], KEEPFILTERS(\'Landed Cost\'[Cost Component] = "Demurrage"))', USD, P),
        Measure("Landed Value", "SUM(Shipments[Landed Value USD])", USD, P, "Total cost of imported goods delivered into the warehouse."),
        Measure("Shipment FOB Value", "SUM(Shipments[FOB Value USD])", USD, P, hidden=True),
        Measure("Landed Cost Uplift %", "DIVIDE([Landed Value] - [Shipment FOB Value], [Shipment FOB Value])", PCT, P,
                "How much freight, duty and clearing add on top of the FOB price of the goods."),
        Measure("Freight % of Goods", "DIVIDE([Freight Cost], [Goods Cost])", PCT, P),
        Measure("Duty % of Goods", "DIVIDE([Duty Cost], [Goods Cost])", PCT, P),
        Measure("Cost per Container", "DIVIDE([Landed Value], SUM(Shipments[Containers]))", USD, P),
        Measure("Landed Value LY", "CALCULATE([Landed Value], SAMEPERIODLASTYEAR('Date'[Date]))", USD, P),
        Measure("Import Growth %", "VAR _ly = [Landed Value LY] RETURN IF(NOT ISBLANK(_ly) && _ly <> 0, DIVIDE([Landed Value] - _ly, _ly))", "+0.0%;-0.0%;0.0%", P),
        # ---- supplier performance ----
        Measure("Shipments", "COUNTROWS(Shipments)", NUM, T),
        Measure("Arrived Shipments", 'CALCULATE([Shipments], KEEPFILTERS(Shipments[Status] <> "In Transit"))', NUM, T, hidden=True),
        Measure("Received Shipments", 'CALCULATE([Shipments], KEEPFILTERS(Shipments[Status] = "Received"))', NUM, T,
                "Shipments already booked into the warehouse; the service measures are calculated on these."),
        Measure("On-Time %", "DIVIDE(CALCULATE([Shipments], KEEPFILTERS(Shipments[On Time] = TRUE())), [Arrived Shipments])", PCT, T,
                "Shipments arriving within 3 days of the promised ETA. Shipments still at sea are excluded."),
        Measure("In-Full %", "DIVIDE(CALCULATE([Shipments], KEEPFILTERS(Shipments[In Full] = TRUE())), [Received Shipments])", PCT, T),
        Measure("OTIF %", "DIVIDE(CALCULATE([Shipments], KEEPFILTERS(Shipments[OTIF] = TRUE())), [Received Shipments])", PCT, T,
                "On time and in full: the headline supplier service measure, on received shipments."),
        Measure("Avg Lead Time (days)", "AVERAGE(Shipments[Total Lead Time Days])", DAYS, T, "PO date to warehouse receipt."),
        Measure("Avg Transit Days", "AVERAGE(Shipments[Transit Days])", DAYS, T),
        Measure("Avg Clearance Days", "AVERAGE(Shipments[Clearance Days])", DAYS, T, "Port arrival to customs clearance."),
        Measure("Avg Delay (days)", "AVERAGE(Shipments[Delay Days])", DAYS, T, "Actual arrival vs promised ETA."),
        Measure("Fill Rate %", "DIVIDE([Cartons Received], SUM('Goods Receipts'[Qty Ordered Cartons]))", PCT, T,
                "Cartons received against cartons ordered on the same receipt, so a PO raised in one period and "
                "received in the next cannot distort it."),
        Measure("Open Shipments", "CALCULATE([Shipments], KEEPFILTERS(Shipments[Status] <> \"Received\"), REMOVEFILTERS('Date'))", NUM, T,
                "Shipments still at sea or at the port. This is a position, so it ignores the period filter."),
        Measure("Open Pipeline Value", "CALCULATE([Landed Value], KEEPFILTERS(Shipments[Status] <> \"Received\"), REMOVEFILTERS('Date'))", USD, T,
                "Value of the goods that are still on the water or waiting at the port."),
        # ---- display ----
        Measure("Landed Value (USD m)", "DIVIDE([Landed Value], 1000000)", '\$0.00" m"', D),
        Measure("PO Value (USD m)", "DIVIDE([PO Value], 1000000)", '\$0.00" m"', D),
        Measure("Open Pipeline (USD m)", "DIVIDE([Open Pipeline Value], 1000000)", '\$0.00" m"', D),
        Measure("Landed Value (USD k)", "DIVIDE([Landed Value], 1000)", '\$#,##0" k"', D),
        Measure("Import Cost (USD k)", "DIVIDE([Import Cost], 1000)", '\$#,##0" k"', D),
        Measure("Freight Cost (USD k)", "DIVIDE([Freight Cost], 1000)", '\$#,##0" k"', D),
        Measure("Duty Cost (USD k)", "DIVIDE([Duty Cost], 1000)", '\$#,##0" k"', D),
        Measure("Clearing Cost (USD k)", "DIVIDE([Clearing Cost], 1000)", '\$#,##0" k"', D),
        Measure("Inland Cost (USD k)", "DIVIDE([Inland Cost], 1000)", '\$#,##0" k"', D),
        Measure("Demurrage Cost (USD k)", "DIVIDE([Demurrage Cost], 1000)", '\$#,##0" k"', D),
        Measure("Goods Received (USD k)", "DIVIDE([Goods Received Value], 1000)", '\$#,##0" k"', D),
    ]
    tables = [dim_date(), dim_product(), dim_location(), dim_supplier(), po, pol, ship, lc, grn, kpi_table(m)]
    rels = [
        ("Purchase Orders", "PO Date", "Date", "Date"),
        ("Purchase Orders", "Supplier ID", "Supplier", "Supplier ID"),
        ("Purchase Orders", "Warehouse ID", "Location", "Location ID"),
        ("PO Lines", "PO No", "Purchase Orders", "PO No"),
        ("PO Lines", "SKU ID", "Product", "SKU ID"),
        ("Shipments", "Arrival Date", "Date", "Date"),
        ("Shipments", "Supplier ID", "Supplier", "Supplier ID"),
        ("Shipments", "Warehouse ID", "Location", "Location ID"),
        ("Landed Cost", "Shipment No", "Shipments", "Shipment No"),
        ("Goods Receipts", "GRN Date", "Date", "Date"),
        ("Goods Receipts", "Warehouse ID", "Location", "Location ID"),
        ("Goods Receipts", "SKU ID", "Product", "SKU ID"),
    ]
    return tables, rels


def procurement_report():
    pages = []
    half = (W - 2 * MG - GAP) // 2
    top_h = 360
    bot_y = BODY_Y + top_h + GAP
    bot_h = BODY_H - top_h - GAP

    # ---- P1 overview ----
    v = [textbox("title", MG, TITLE_Y, W - 2 * MG, TITLE_H, 1000, "Procurement & Import Overview",
                 f"{SUB}  |  Period: set in the Filters pane (default FY 2025-26)")]
    v += kpi_row([("Landed Value (USD m)", "Landed Value of Imports"), ("Landed Cost Uplift %", "Landed Cost Uplift"),
                  ("Avg Lead Time (days)", "Avg Lead Time (days)"), ("OTIF %", "Supplier OTIF"),
                  ("Containers", "Containers Imported"), ("Open Pipeline (USD m)", "Open Import Pipeline")])
    v.append(chart("chart_trend", MG, BODY_Y, half, top_h, 5000, "Imports landed by month (USD k)", "clusteredColumnChart",
                   category=C("Date", "Month Year"), values=[M("Landed Value (USD k)", "Landed value")],
                   sort_field=column_ref("Date", "Month Year Sort"), descending=False))
    v.append(chart("chart_components", MG + half + GAP, BODY_Y, half, top_h, 5100, "Import cost build-up", "donutChart",
                   category=C("Landed Cost", "Cost Component"), values=[M("Import Cost (USD k)", "Cost")],
                   legend=True, legend_position="Right"))
    v.append(table_visual("tbl_origin", MG, bot_y, half, bot_h, 5200, "By origin country",
                          [C("Purchase Orders", "Origin Country", "Origin"), M("PO Count", "POs"), M("Containers"),
                           M("Landed Value (USD k)", "Landed (USD k)"), M("Landed Cost Uplift %", "Uplift %"),
                           M("Avg Lead Time (days)", "Lead time"), M("OTIF %")],
                          measure_ref("Landed Value (USD k)")))
    v.append(table_visual("tbl_country", MG + half + GAP, bot_y, half, bot_h, 5300, "By destination market",
                          [C("Location", "Country"), C("Location", "Location Name", "Warehouse"), M("PO Count", "POs"),
                           M("Containers"), M("Landed Value (USD k)", "Landed (USD k)"), M("Duty Cost (USD k)", "Duty (USD k)"),
                           M("Avg Clearance Days", "Clearance days")], measure_ref("Landed Value (USD k)")))
    pages.append(("p1_overview", "Procurement Overview", v))

    # ---- P2 supplier performance ----
    v = [textbox("title", MG, TITLE_Y, W - 2 * MG, TITLE_H, 1000, "Supplier Performance",
                 f"{SUB}  |  On-time / in-full delivery, lead time and price per carton by supplier")]
    v += kpi_row([("Suppliers Used", "Suppliers Used"), ("OTIF %", "OTIF"), ("On-Time %", "On-Time Arrival"),
                  ("Fill Rate %", "Fill Rate"), ("Avg Lead Time (days)", "Avg Lead Time (days)"),
                  ("Avg Delay (days)", "Avg Delay vs ETA (days)")])
    v.append(chart("chart_otif", MG, BODY_Y, half, top_h, 5000, "OTIF % by supplier", "clusteredBarChart",
                   category=C("Supplier", "Supplier Name", "Supplier"), values=[M("OTIF %")],
                   sort_field=measure_ref("OTIF %"), descending=True, data_labels=True))
    v.append(chart("chart_lead", MG + half + GAP, BODY_Y, half, top_h, 5100, "Average lead time by supplier (days)",
                   "clusteredBarChart", category=C("Supplier", "Supplier Name", "Supplier"),
                   values=[M("Avg Lead Time (days)", "Lead time")], sort_field=measure_ref("Avg Lead Time (days)"),
                   descending=True, data_labels=True))
    v.append(table_visual("tbl_supplier", MG, bot_y, W - 2 * MG, bot_h, 5200, "Supplier scorecard",
                          [C("Supplier", "Supplier Name", "Supplier"), C("Supplier", "Origin Country", "Origin"),
                           C("Supplier", "Tier"), C("Supplier", "Incoterm"), C("Supplier", "Payment Terms", "Terms"),
                           M("PO Count", "POs"), M("Containers"), M("Landed Value (USD k)", "Landed (USD k)"),
                           M("Avg Lead Time (days)", "Lead time"), M("Avg Delay (days)", "Delay"), M("On-Time %"),
                           M("In-Full %"), M("OTIF %"), M("Avg FOB per Carton", "FOB / carton")],
                          measure_ref("Landed Value (USD k)")))
    pages.append(("p2_supplier", "Supplier Performance", v))

    # ---- P3 landed cost ----
    v = [textbox("title", MG, TITLE_Y, W - 2 * MG, TITLE_H, 1000, "Landed Cost Analysis",
                 f"{SUB}  |  What the goods really cost once freight, duty and clearing are added")]
    v += kpi_row([("Goods Cost", "Goods (FOB)"), ("Freight Cost", "Ocean Freight"), ("Duty Cost", "Customs Duty"),
                  ("Clearing Cost", "Clearing & Port"), ("Demurrage Cost", "Demurrage"),
                  ("Cost per Container", "Cost per Container")])
    v.append(chart("chart_stack", MG, BODY_Y, half + 180, top_h, 5000, "Import cost by month and component (USD k)",
                   "columnChart", category=C("Date", "Month Year"), series=C("Landed Cost", "Cost Component"),
                   values=[M("Import Cost (USD k)", "Cost")], sort_field=column_ref("Date", "Month Year Sort"),
                   descending=False))
    v.append(chart("chart_freight", MG + half + 180 + GAP, BODY_Y, W - 2 * MG - half - 180 - GAP, top_h, 5100,
                   "Freight and duty as % of goods value", "lineChart", category=C("Date", "Month Year"),
                   values=[M("Freight % of Goods", "Freight %"), M("Duty % of Goods", "Duty %")],
                   sort_field=column_ref("Date", "Month Year Sort"), descending=False))
    v.append(table_visual("tbl_category_cost", MG, bot_y, half, bot_h, 5200, "Landed cost per carton by category",
                          [C("Product", "Category"), M("Cartons Ordered", "Cartons"), M("Avg FOB per Carton", "FOB / carton"),
                           M("Avg Landed per Carton", "Landed / carton")], measure_ref("Cartons Ordered")))
    v.append(table_visual("tbl_shipment_cost", MG + half + GAP, bot_y, half, bot_h, 5300, "Cost by shipment",
                          [C("Shipments", "Shipment No", "Shipment"), C("Shipments", "Origin Country", "Origin"),
                           C("Shipments", "Country", "Market"), M("Containers"), M("Landed Value (USD k)", "Landed (USD k)"),
                           M("Landed Cost Uplift %", "Uplift %")], measure_ref("Landed Value (USD k)")))
    pages.append(("p3_landed_cost", "Landed Cost", v))

    # ---- P4 shipment tracker ----
    slicer_w = 280
    v = [textbox("title", MG, TITLE_Y, W - 2 * MG - 2 * (slicer_w + GAP), TITLE_H, 1000, "Shipment Tracker",
                 f"{SUB}  |  Where every container is: sailing, at port, cleared or received"),
         slicer("slc_year", W - MG - 2 * slicer_w - GAP, TITLE_Y, slicer_w, TITLE_H, 1010,
                C("Date", "Financial Year"), "Financial year"),
         slicer("slc_status", W - MG - slicer_w, TITLE_Y, slicer_w, TITLE_H, 1020,
                C("Shipments", "Status"), "Shipment status")]
    v += kpi_row([("Shipments", "Shipments"), ("Open Shipments", "Open Shipments"),
                  ("Open Pipeline (USD m)", "Open Pipeline Value"), ("Avg Transit Days", "Avg Transit (days)"),
                  ("Avg Clearance Days", "Avg Clearance (days)"), ("Containers", "Containers")])
    v.append(chart("chart_status", MG, BODY_Y, 560, top_h, 5000, "Shipments by status", "clusteredBarChart",
                   category=C("Shipments", "Status"), values=[M("Shipments")], sort_field=measure_ref("Shipments"),
                   data_labels=True))
    v.append(chart("chart_port", MG + 560 + GAP, BODY_Y, 560, top_h, 5100, "Clearance days by port of discharge",
                   "clusteredBarChart", category=C("Shipments", "Port of Discharge", "Port"),
                   values=[M("Avg Clearance Days", "Clearance days")], sort_field=measure_ref("Avg Clearance Days"),
                   data_labels=True))
    v.append(chart("chart_month_ship", MG + 2 * (560 + GAP), BODY_Y, W - 2 * MG - 2 * (560 + GAP), top_h, 5200,
                   "Containers arriving by month", "clusteredColumnChart", category=C("Date", "Month Year"),
                   values=[M("Containers")], sort_field=column_ref("Date", "Month Year Sort"), descending=False))
    v.append(table_visual("tbl_shipments", MG, bot_y, W - 2 * MG, bot_h, 5300, "Shipment register",
                          [C("Shipments", "Shipment No", "Shipment"), C("Shipments", "PO No", "PO"),
                           C("Shipments", "Supplier Name", "Supplier"), C("Shipments", "Origin Country", "Origin"),
                           C("Shipments", "Port of Discharge", "Discharge port"), C("Shipments", "Status"),
                           M("Containers"), M("Landed Value (USD k)", "Landed (USD k)"),
                           M("Avg Transit Days", "Transit"), M("Avg Clearance Days", "Clearance"),
                           M("Avg Delay (days)", "Delay"), M("OTIF %")], measure_ref("Landed Value (USD k)")))
    pages.append(("p4_shipments", "Shipment Tracker", v))
    return pages


# ===================================================================================== INVENTORY
def inventory_model():
    stock = Table("Stock", "fact_stock_snapshot.csv.gz", gz=True,
                  desc="Month-end stock by location and SKU, valued at landed cost, with days of cover and health status.", columns=[
        Col("Snapshot Date", "dateTime", fmt="dd-MMM-yyyy", hidden=True), Col("Location ID", "string", hidden=True),
        Col("SKU ID", "string", hidden=True), Col("Opening Cartons", "int64", fmt=NUM),
        Col("Receipts Cartons", "int64", fmt=NUM), Col("Issues Cartons", "int64", fmt=NUM),
        Col("Adjustment Cartons", "int64", fmt=NUM), Col("Closing Cartons", "int64", fmt=NUM),
        Col("Unit Cost USD", "double", fmt=USD2, summarize="none"), Col("Stock Value USD", "double", fmt=USD),
        Col("Days of Cover", "double", fmt=NUM1, summarize="none"),
        Col("Stock Status", "string", sort_by="Status Order"), Col("Status Order", "int64", hidden=True, summarize="none"),
        Col("Stock Norm Days", "string"),
    ])
    mov = Table("Movements", "fact_stock_movements.csv.gz", gz=True,
                desc="Stock ledger: goods receipts, warehouse-to-store transfers and adjustments (sales issues are in the sales model).", columns=[
        Col("Movement Date", "dateTime", fmt="dd-MMM-yyyy", hidden=True), Col("Movement Type", "string"),
        Col("Location ID", "string", hidden=True), Col("SKU ID", "string", hidden=True),
        Col("Qty Cartons", "int64", fmt=NUM), Col("Value USD", "double", fmt=USD), Col("Reference", "string"),
    ])
    grn = Table("Goods Receipts", "fact_goods_receipts.csv", desc="Inbound receipts from imports.", columns=[
        Col("GRN No", "string"), Col("GRN Date", "dateTime", fmt="dd-MMM-yyyy", hidden=True), Col("PO No", "string"),
        Col("Shipment No", "string"), Col("Warehouse ID", "string", hidden=True), Col("SKU ID", "string", hidden=True),
        Col("Qty Ordered Cartons", "int64", fmt=NUM), Col("Qty Received Cartons", "int64", fmt=NUM),
        Col("Landed Unit Cost USD", "double", fmt=USD2), Col("Landed Value USD", "double", fmt=USD),
    ])
    A, B, C_, D = "1. Stock", "2. Health", "3. Movements", "4. Display"
    m = [
        Measure("Stock Value", "SUM(Stock[Stock Value USD])", USD, A, "Month-end stock at landed cost."),
        Measure("Stock Date", "EOMONTH(MAX('Date'[Date]), 0)", "dd-MMM-yyyy", A, hidden=True),
        Measure("Closing Stock Value", "VAR _d = [Stock Date] RETURN CALCULATE([Stock Value], REMOVEFILTERS('Date'), Stock[Snapshot Date] = _d)", USD, A,
                "Stock at the month-end of the selected period."),
        Measure("Closing Cartons", "VAR _d = [Stock Date] RETURN CALCULATE(SUM(Stock[Closing Cartons]), REMOVEFILTERS('Date'), Stock[Snapshot Date] = _d)", NUM, A),
        Measure("Stock Lines", "VAR _d = [Stock Date] RETURN CALCULATE(COUNTROWS(Stock), REMOVEFILTERS('Date'), Stock[Snapshot Date] = _d)", NUM, A),
        Measure("SKUs Stocked", "VAR _d = [Stock Date] RETURN CALCULATE(DISTINCTCOUNT(Stock[SKU ID]), REMOVEFILTERS('Date'), Stock[Snapshot Date] = _d)", NUM, A),
        Measure("Issues Value", "SUMX(Stock, Stock[Issues Cartons] * Stock[Unit Cost USD])", USD, A, "Cost value of stock issued (sold or transferred out)."),
        Measure("Receipts Value", "SUMX(Stock, Stock[Receipts Cartons] * Stock[Unit Cost USD])", USD, A),
        Measure("Issues Value 3M", "VAR _d = [Stock Date] RETURN CALCULATE([Issues Value], REMOVEFILTERS('Date'), Stock[Snapshot Date] > EDATE(_d, -3), Stock[Snapshot Date] <= _d)", USD, A, hidden=True),
        Measure("Days of Cover", "DIVIDE([Closing Stock Value], DIVIDE([Issues Value 3M], 91))", DAYS, A,
                "Closing stock divided by the average daily issue value of the last three months."),
        Measure("Stock Turns (12m)", "VAR _d = [Stock Date] VAR _iss = CALCULATE([Issues Value], REMOVEFILTERS('Date'), Stock[Snapshot Date] > EDATE(_d, -12), Stock[Snapshot Date] <= _d) VAR _avg = CALCULATE(AVERAGEX(VALUES(Stock[Snapshot Date]), [Stock Value]), REMOVEFILTERS('Date'), Stock[Snapshot Date] > EDATE(_d, -12), Stock[Snapshot Date] <= _d) RETURN DIVIDE(_iss, _avg)", NUM1, A),
        # ---- health ----
        Measure("Out of Stock Lines", 'CALCULATE([Stock Lines], KEEPFILTERS(Stock[Stock Status] = "Out of Stock"))', NUM, B),
        Measure("Out of Stock %", "DIVIDE([Out of Stock Lines], [Stock Lines])", PCT, B),
        Measure("Low Stock Lines", 'CALCULATE([Stock Lines], KEEPFILTERS(Stock[Stock Status] = "Low Stock"))', NUM, B),
        Measure("Healthy Lines", 'CALCULATE([Stock Lines], KEEPFILTERS(Stock[Stock Status] = "Healthy"))', NUM, B),
        Measure("Healthy %", "DIVIDE([Healthy Lines], [Stock Lines])", PCT, B),
        Measure("Overstock Value", 'CALCULATE([Closing Stock Value], KEEPFILTERS(Stock[Stock Status] = "Overstock"))', USD, B),
        Measure("Slow & Non-moving Value", 'CALCULATE([Closing Stock Value], KEEPFILTERS(Stock[Stock Status] IN {"Slow-moving", "Non-moving"}))', USD, B,
                "Stock with more than the slow-moving norm of cover, or no movement at all."),
        Measure("Slow & Non-moving %", "DIVIDE([Slow & Non-moving Value], [Closing Stock Value])", PCT, B),
        Measure("Share of Stock Value %", "DIVIDE([Closing Stock Value], CALCULATE([Closing Stock Value], ALLSELECTED()))", PCT, B),
        # ---- movements ----
        Measure("Movement Value", "SUM(Movements[Value USD])", USD, C_),
        Measure("Goods Received Value", "SUM('Goods Receipts'[Landed Value USD])", USD, C_),
        Measure("Inbound Cartons", "SUM('Goods Receipts'[Qty Received Cartons])", NUM, C_),
        Measure("Transfers to Stores", 'CALCULATE([Movement Value], KEEPFILTERS(Movements[Movement Type] = "Transfer In"))', USD, C_),
        Measure("Shrinkage Value", '-CALCULATE([Movement Value], KEEPFILTERS(Movements[Movement Type] = "Adjustment / Damage"))', USD, C_,
                "Damage, expiry and stock-count adjustments."),
        Measure("Shrinkage %", "DIVIDE([Shrinkage Value], [Issues Value])", PCT, C_),
        # ---- display ----
        Measure("Stock Value (USD m)", "DIVIDE([Closing Stock Value], 1000000)", '\$0.00" m"', D),
        Measure("Stock Value (USD k)", "DIVIDE([Closing Stock Value], 1000)", '\$#,##0" k"', D),
        Measure("Month-End Stock (USD k)", "DIVIDE([Stock Value], 1000)", '\$#,##0" k"', D),
        Measure("Slow & Non-moving (USD k)", "DIVIDE([Slow & Non-moving Value], 1000)", '\$#,##0" k"', D),
        Measure("Overstock (USD k)", "DIVIDE([Overstock Value], 1000)", '\$#,##0" k"', D),
        Measure("Issues Value (USD k)", "DIVIDE([Issues Value], 1000)", '\$#,##0" k"', D),
        Measure("Receipts Value (USD k)", "DIVIDE([Receipts Value], 1000)", '\$#,##0" k"', D),
        Measure("Goods Received (USD k)", "DIVIDE([Goods Received Value], 1000)", '\$#,##0" k"', D),
        Measure("Shrinkage (USD k)", "DIVIDE([Shrinkage Value], 1000)", '\$#,##0" k"', D),
    ]
    tables = [dim_date(), dim_product(), dim_location(), stock, mov, grn, kpi_table(m)]
    rels = [
        ("Stock", "Snapshot Date", "Date", "Date"), ("Stock", "Location ID", "Location", "Location ID"),
        ("Stock", "SKU ID", "Product", "SKU ID"),
        ("Movements", "Movement Date", "Date", "Date"), ("Movements", "Location ID", "Location", "Location ID"),
        ("Movements", "SKU ID", "Product", "SKU ID"),
        ("Goods Receipts", "GRN Date", "Date", "Date"), ("Goods Receipts", "Warehouse ID", "Location", "Location ID"),
        ("Goods Receipts", "SKU ID", "Product", "SKU ID"),
    ]
    return tables, rels


def inventory_report():
    pages = []
    half = (W - 2 * MG - GAP) // 2
    top_h = 360
    bot_y = BODY_Y + top_h + GAP
    bot_h = BODY_H - top_h - GAP

    v = [textbox("title", MG, TITLE_Y, W - 2 * MG, TITLE_H, 1000, "Inventory Overview",
                 f"{SUB}  |  Stock at the month-end of the selected period, valued at landed cost")]
    v += kpi_row([("Stock Value (USD m)", "Stock Value"), ("Days of Cover", "Days of Cover"),
                  ("Stock Turns (12m)", "Stock Turns (12m)"), ("Out of Stock %", "Out of Stock Lines"),
                  ("Slow & Non-moving (USD k)", "Slow & Non-moving"), ("SKUs Stocked", "SKUs Stocked")])
    v.append(chart("chart_trend", MG, BODY_Y, half, top_h, 5000, "Month-end stock value (USD k)", "clusteredColumnChart",
                   category=C("Date", "Month Year"), values=[M("Month-End Stock (USD k)", "Stock value")],
                   sort_field=column_ref("Date", "Month Year Sort"), descending=False))
    v.append(chart("chart_status", MG + half + GAP, BODY_Y, half, top_h, 5100, "Stock value by health status", "donutChart",
                   category=C("Stock", "Stock Status"), values=[M("Stock Value (USD k)", "Stock")],
                   legend=True, legend_position="Right"))
    v.append(table_visual("tbl_location", MG, bot_y, half, bot_h, 5200, "Stock by location",
                          [C("Location", "Location Name", "Location"), C("Location", "Location Type", "Type"),
                           C("Location", "Country"), M("Stock Value (USD k)", "Stock (USD k)"), M("Days of Cover", "Cover (days)"),
                           M("Out of Stock %"), M("Slow & Non-moving (USD k)", "Slow+Non-moving")],
                          measure_ref("Stock Value (USD k)")))
    v.append(table_visual("tbl_category", MG + half + GAP, bot_y, half, bot_h, 5300, "Stock by category",
                          [C("Product", "Category"), M("Closing Cartons", "Cartons"), M("Stock Value (USD k)", "Stock (USD k)"),
                           M("Days of Cover", "Cover (days)"), M("Share of Stock Value %", "Share %")],
                          measure_ref("Stock Value (USD k)")))
    pages.append(("p1_overview", "Inventory Overview", v))

    v = [textbox("title", MG, TITLE_Y, W - 2 * MG, TITLE_H, 1000, "Stock by Location & Product",
                 f"{SUB}  |  Warehouse norm 30-100 days of cover, supermarket norm 7-30 days")]
    v += kpi_row([("Stock Value (USD m)", "Stock Value"), ("Closing Cartons", "Cartons in Stock"),
                  ("Stock Lines", "Location-SKU Lines"), ("Healthy %", "Healthy Lines"),
                  ("Overstock (USD k)", "Overstock Value"), ("Days of Cover", "Days of Cover")])
    v.append(chart("chart_cat", MG, BODY_Y, half, top_h, 5000, "Stock value by category (USD k)", "clusteredBarChart",
                   category=C("Product", "Category"), values=[M("Stock Value (USD k)", "Stock")],
                   sort_field=measure_ref("Stock Value (USD k)"), data_labels=True))
    v.append(chart("chart_loc_status", MG + half + GAP, BODY_Y, half, top_h, 5100, "Stock value by location and status",
                   "columnChart", category=C("Location", "Location Name", "Location"), series=C("Stock", "Stock Status"),
                   values=[M("Stock Value (USD k)", "Stock")], sort_field=measure_ref("Stock Value (USD k)")))
    v.append(table_visual("tbl_sku", MG, bot_y, W - 2 * MG, bot_h, 5200, "Stock by SKU",
                          [C("Product", "Product Name", "SKU"), C("Product", "Category"), C("Product", "Brand"),
                           M("Closing Cartons", "Cartons"), M("Stock Value (USD k)", "Stock (USD k)"),
                           M("Days of Cover", "Cover (days)"), M("Issues Value (USD k)", "Issued (USD k)"),
                           M("Share of Stock Value %", "Share %")], measure_ref("Stock Value (USD k)")))
    pages.append(("p2_location_product", "Stock by Location & Product", v))

    v = [textbox("title", MG, TITLE_Y, W - 2 * MG, TITLE_H, 1000, "Movements & Turnover",
                 f"{SUB}  |  Goods receipts, warehouse-to-store transfers, issues and shrinkage")]
    v += kpi_row([("Goods Received (USD k)", "Goods Received"), ("Inbound Cartons", "Inbound Cartons"),
                  ("Issues Value (USD k)", "Stock Issued"), ("Transfers to Stores", "Transfers to Stores"),
                  ("Shrinkage (USD k)", "Shrinkage"), ("Shrinkage %", "Shrinkage % of Issues")])
    v.append(chart("chart_flow", MG, BODY_Y, half + 140, top_h, 5000, "Receipts vs issues by month (USD k)",
                   "lineClusteredColumnComboChart", category=C("Date", "Month Year"),
                   values=[M("Receipts Value (USD k)", "Receipts")], y2=[M("Issues Value (USD k)", "Issues")],
                   sort_field=column_ref("Date", "Month Year Sort"), descending=False))
    v.append(chart("chart_movetype", MG + half + 140 + GAP, BODY_Y, W - 2 * MG - half - 140 - GAP, top_h, 5100,
                   "Movement value by type", "clusteredBarChart", category=C("Movements", "Movement Type", "Type"),
                   values=[M("Movement Value", "Value")], sort_field=measure_ref("Movement Value"), data_labels=True))
    v.append(table_visual("tbl_move_loc", MG, bot_y, W - 2 * MG, bot_h, 5200, "Movements by location",
                          [C("Location", "Location Name", "Location"), C("Location", "Location Type", "Type"),
                           M("Goods Received (USD k)", "Received (USD k)"), M("Receipts Value (USD k)", "Receipts (USD k)"),
                           M("Issues Value (USD k)", "Issues (USD k)"), M("Shrinkage (USD k)", "Shrinkage (USD k)"),
                           M("Shrinkage %"), M("Stock Turns (12m)", "Turns (12m)")], measure_ref("Issues Value (USD k)")))
    pages.append(("p3_movements", "Movements & Turnover", v))

    v = [textbox("title", MG, TITLE_Y, W - 2 * MG, TITLE_H, 1000, "Stock Health & Slow-moving",
                 f"{SUB}  |  Where working capital is stuck and where the shelves are empty")]
    v += kpi_row([("Out of Stock Lines", "Out of Stock Lines"), ("Low Stock Lines", "Low Stock Lines"),
                  ("Overstock (USD k)", "Overstock Value"), ("Slow & Non-moving (USD k)", "Slow & Non-moving"),
                  ("Slow & Non-moving %", "Slow & Non-moving %"), ("Healthy %", "Healthy Lines")])
    v.append(chart("chart_status_lines", MG, BODY_Y, half, top_h, 5000, "Location-SKU lines by status", "clusteredBarChart",
                   category=C("Stock", "Stock Status"), values=[M("Stock Lines", "Lines")],
                   sort_field=column_ref("Stock", "Status Order"), descending=False, data_labels=True))
    v.append(chart("chart_slow_cat", MG + half + GAP, BODY_Y, half, top_h, 5100, "Slow & non-moving value by category",
                   "clusteredBarChart", category=C("Product", "Category"),
                   values=[M("Slow & Non-moving (USD k)", "Slow+Non-moving")],
                   sort_field=measure_ref("Slow & Non-moving (USD k)"), data_labels=True))
    v.append(table_visual("tbl_slow", MG, bot_y, W - 2 * MG, bot_h, 5200, "Slow-moving and out-of-stock detail",
                          [C("Product", "Product Name", "SKU"), C("Location", "Location Name", "Location"),
                           C("Stock", "Stock Status", "Status"), C("Stock", "Stock Norm Days", "Norm"),
                           M("Closing Cartons", "Cartons"), M("Stock Value (USD k)", "Stock (USD k)"),
                           M("Days of Cover", "Cover (days)")], measure_ref("Stock Value (USD k)")))
    pages.append(("p4_health", "Stock Health", v))
    return pages


# ===================================================================================== SALES
def sales_model():
    sales = Table("Sales", "fact_sales.csv.gz", gz=True,
                  desc="Sales lines: B2B invoices (daily) and supermarket POS summaries (weekly), with credit notes.", columns=[
        Col("Date", "dateTime", fmt="dd-MMM-yyyy", hidden=True), Col("Channel", "string"),
        Col("Country Code", "string", hidden=True), Col("Country", "string"), Col("Location ID", "string", hidden=True),
        Col("Customer ID", "string", hidden=True, blank_to_null=True), Col("Customer Segment", "string"),
        Col("SKU ID", "string", hidden=True), Col("Document No", "string"), Col("Qty Cartons", "int64", fmt=NUM),
        Col("Qty Units", "int64", fmt=NUM), Col("Gross Sales USD", "double", fmt=USD),
        Col("Discount USD", "double", fmt=USD), Col("Net Sales USD", "double", fmt=USD),
        Col("COGS USD", "double", fmt=USD), Col("Transaction Type", "string"),
        Col("Gross Margin USD", "double", fmt=USD),
    ])
    target = Table("Target", "fact_sales_target.csv", desc="Monthly sales budget by country and channel.", columns=[
        Col("Month Date", "dateTime", hidden=True), Col("Country Code", "string", hidden=True),
        Col("Country", "string", hidden=True), Col("Channel", "string", hidden=True), Col("Target USD", "double", fmt=USD),
    ])
    customer = Table("Customer", "dim_customer.csv", desc="B2B customers: wholesalers, retailers, HORECA and institutions.", columns=[
        Col("Customer ID", "string"), Col("Customer Name", "string"), Col("Segment", "string"),
        Col("Country Code", "string", hidden=True), Col("Country", "string"), Col("City", "string"),
        Col("Credit Days", "int64", summarize="none"), Col("Status", "string"),
    ])
    channel = Table("Channel", dax='DATATABLE("Channel", STRING, {{"B2B"}, {"Supermarket"}})',
                    desc="Route to market.", columns=[Col("Channel", "string")])
    country = Table("Market", dax='SELECTCOLUMNS(SUMMARIZE(Location, Location[Country Code], Location[Country]), "Country Code", Location[Country Code], "Market", Location[Country])',
                    desc="Countries of operation (shared by sales and budget).",
                    columns=[Col("Country Code", "string", hidden=True), Col("Market", "string")])
    A, B, C_, D = "1. Sales", "2. Margin", "3. Customers & Stores", "4. Display"
    m = [
        Measure("Net Sales", "SUM(Sales[Net Sales USD])", USD, A, "Sales after discount and credit notes."),
        Measure("Gross Sales", "SUM(Sales[Gross Sales USD])", USD, A),
        Measure("Discount", "SUM(Sales[Discount USD])", USD, A),
        Measure("Discount %", "DIVIDE([Discount], [Gross Sales])", PCT, A),
        Measure("Cartons Sold", "SUM(Sales[Qty Cartons])", NUM, A),
        Measure("Units Sold", "SUM(Sales[Qty Units])", NUM, A),
        Measure("Credit Notes", '-CALCULATE([Net Sales], KEEPFILTERS(Sales[Transaction Type] = "Credit Note"))', USD, A),
        Measure("Return %", 'DIVIDE([Credit Notes], CALCULATE([Net Sales], KEEPFILTERS(Sales[Transaction Type] = "Sale")))', PCT, A),
        Measure("B2B Sales", 'CALCULATE([Net Sales], KEEPFILTERS(Sales[Channel] = "B2B"))', USD, A),
        Measure("Supermarket Sales", 'CALCULATE([Net Sales], KEEPFILTERS(Sales[Channel] = "Supermarket"))', USD, A),
        Measure("Net Sales LY", "CALCULATE([Net Sales], SAMEPERIODLASTYEAR('Date'[Date]))", USD, A),
        Measure("Growth %", "VAR _ly = [Net Sales LY] RETURN IF(NOT ISBLANK(_ly) && _ly <> 0, DIVIDE([Net Sales] - _ly, _ly))", "+0.0%;-0.0%;0.0%", A),
        Measure("Target", "SUM(Target[Target USD])", USD, A, "Monthly budget set by country and channel."),
        Measure("Achievement %", "DIVIDE([Net Sales], [Target])", PCT, A),
        Measure("Variance to Target", "IF(NOT ISBLANK([Target]), [Net Sales] - [Target])", USD, A),
        Measure("Contribution %", "DIVIDE([Net Sales], CALCULATE([Net Sales], ALLSELECTED()))", PCT, A),
        # ---- margin ----
        Measure("COGS", "SUM(Sales[COGS USD])", USD, B, "Cost of goods sold at landed cost."),
        Measure("Gross Margin", "SUM(Sales[Gross Margin USD])", USD, B),
        Measure("Gross Margin %", "DIVIDE([Gross Margin], [Net Sales])", PCT, B),
        Measure("Gross Margin LY", "CALCULATE([Gross Margin], SAMEPERIODLASTYEAR('Date'[Date]))", USD, B),
        Measure("Margin per Carton", "DIVIDE([Gross Margin], [Cartons Sold])", USD2, B),
        # ---- customers & stores ----
        Measure("Invoices", 'CALCULATE(DISTINCTCOUNT(Sales[Document No]), KEEPFILTERS(Sales[Channel] = "B2B"), KEEPFILTERS(Sales[Transaction Type] = "Sale"))', NUM, C_),
        Measure("Avg Invoice Value", "DIVIDE([B2B Sales], [Invoices])", USD, C_),
        Measure("Customers Billed", "DISTINCTCOUNTNOBLANK(Sales[Customer ID])", NUM, C_,
                "B2B customers invoiced; supermarket rows carry no customer, so the blank is not counted."),
        Measure("Active SKUs", "DISTINCTCOUNT(Sales[SKU ID])", NUM, C_),
        Measure("Stores Trading", 'CALCULATE(DISTINCTCOUNT(Sales[Location ID]), KEEPFILTERS(Sales[Channel] = "Supermarket"))', NUM, C_),
        Measure("Sales per Store", "DIVIDE([Supermarket Sales], [Stores Trading])", USD, C_),
        Measure("Lines per Invoice", 'DIVIDE(CALCULATE(COUNTROWS(Sales), KEEPFILTERS(Sales[Channel] = "B2B")), [Invoices])', NUM1, C_),
        # ---- display ----
        Measure("Net Sales (USD m)", "DIVIDE([Net Sales], 1000000)", '\$0.00" m"', D),
        Measure("Net Sales (USD k)", "DIVIDE([Net Sales], 1000)", '\$#,##0" k"', D),
        Measure("B2B Sales (USD k)", "DIVIDE([B2B Sales], 1000)", '\$#,##0" k"', D),
        Measure("Supermarket Sales (USD k)", "DIVIDE([Supermarket Sales], 1000)", '\$#,##0" k"', D),
        Measure("Net Sales LY (USD k)", "DIVIDE([Net Sales LY], 1000)", '\$#,##0" k"', D),
        Measure("Target (USD k)", "DIVIDE([Target], 1000)", '\$#,##0" k"', D),
        Measure("Gross Margin (USD k)", "DIVIDE([Gross Margin], 1000)", '\$#,##0" k"', D),
        Measure("Variance (USD k)", "DIVIDE([Variance to Target], 1000)", '\$#,##0" k"', D),
        Measure("Gross Margin (USD m)", "DIVIDE([Gross Margin], 1000000)", '\$0.00" m"', D),
        Measure("Supermarket Sales (USD m)", "DIVIDE([Supermarket Sales], 1000000)", '\$0.00" m"', D),
        Measure("B2B Sales (USD m)", "DIVIDE([B2B Sales], 1000000)", '\$0.00" m"', D),
    ]
    tables = [dim_date(), dim_product(), dim_location(), customer, channel, country, sales, target, kpi_table(m)]
    rels = [
        ("Sales", "Date", "Date", "Date"), ("Sales", "SKU ID", "Product", "SKU ID"),
        ("Sales", "Location ID", "Location", "Location ID"), ("Sales", "Customer ID", "Customer", "Customer ID"),
        ("Sales", "Channel", "Channel", "Channel"),
        ("Location", "Country Code", "Market", "Country Code"),
        ("Target", "Month Date", "Date", "Date"), ("Target", "Country Code", "Market", "Country Code"),
        ("Target", "Channel", "Channel", "Channel"),
    ]
    return tables, rels


def sales_report():
    pages = []
    half = (W - 2 * MG - GAP) // 2
    top_h = 360
    bot_y = BODY_Y + top_h + GAP
    bot_h = BODY_H - top_h - GAP

    v = [textbox("title", MG, TITLE_Y, W - 2 * MG, TITLE_H, 1000, "Sales Overview",
                 f"{SUB}  |  Period: set in the Filters pane (default FY 2025-26)")]
    v += kpi_row([("Net Sales (USD m)", "Net Sales"), ("Growth %", "Growth vs Last Year"),
                  ("Achievement %", "Achievement vs Budget"), ("Gross Margin %", "Gross Margin"),
                  ("Cartons Sold", "Cartons Sold"), ("Customers Billed", "Customers Billed")])
    v.append(chart("chart_trend", MG, BODY_Y, half + 140, top_h, 5000, "Net sales by month vs last year (USD k)",
                   "lineClusteredColumnComboChart", category=C("Date", "Month Year"),
                   values=[M("Net Sales (USD k)", "Net sales")], y2=[M("Net Sales LY (USD k)", "Last year")],
                   sort_field=column_ref("Date", "Month Year Sort"), descending=False))
    v.append(chart("chart_channel", MG + half + 140 + GAP, BODY_Y, W - 2 * MG - half - 140 - GAP, top_h, 5100,
                   "Sales by channel", "donutChart", category=C("Channel", "Channel"),
                   values=[M("Net Sales (USD k)", "Net sales")], legend=True, legend_position="Right"))
    v.append(table_visual("tbl_market", MG, bot_y, half, bot_h, 5200, "Performance by market",
                          [C("Market", "Market"), M("Net Sales (USD k)", "Net sales (USD k)"), M("Target (USD k)", "Budget (USD k)"),
                           M("Achievement %", "Ach %"), M("Growth %"), M("Gross Margin %", "Margin %"),
                           M("Contribution %", "Share %")], measure_ref("Net Sales (USD k)")))
    v.append(table_visual("tbl_category", MG + half + GAP, bot_y, half, bot_h, 5300, "Performance by category",
                          [C("Product", "Category"), M("Net Sales (USD k)", "Net sales (USD k)"), M("Cartons Sold", "Cartons"),
                           M("Growth %"), M("Gross Margin %", "Margin %"), M("Contribution %", "Share %")],
                          measure_ref("Net Sales (USD k)")))
    pages.append(("p1_overview", "Sales Overview", v))

    v = [textbox("title", MG, TITLE_Y, W - 2 * MG, TITLE_H, 1000, "Market & Channel Performance",
                 f"{SUB}  |  Sierra Leone, Gambia and Liberia across B2B and own supermarkets")]
    v += kpi_row([("Net Sales (USD m)", "Net Sales"), ("B2B Sales (USD m)", "B2B Sales"),
                  ("Supermarket Sales (USD m)", "Supermarket Sales"), ("Achievement %", "Achievement vs Budget"),
                  ("Variance (USD k)", "Variance to Budget"), ("Growth %", "Growth vs LY")])
    v.append(chart("chart_market", MG, BODY_Y, half, top_h, 5000, "Net sales by market and channel (USD k)",
                   "clusteredColumnChart", category=C("Market", "Market"), series=C("Channel", "Channel"),
                   values=[M("Net Sales (USD k)", "Net sales")], sort_field=measure_ref("Net Sales (USD k)")))
    v.append(chart("chart_channel_trend", MG + half + GAP, BODY_Y, half, top_h, 5100, "Channel trend by month (USD k)",
                   "lineChart", category=C("Date", "Month Year"), series=C("Channel", "Channel"),
                   values=[M("Net Sales (USD k)", "Net sales")], sort_field=column_ref("Date", "Month Year Sort"),
                   descending=False))
    v.append(table_visual("tbl_market_channel", MG, bot_y, W - 2 * MG, bot_h, 5200, "Market x channel scorecard",
                          [C("Market", "Market"), C("Channel", "Channel"), M("Net Sales (USD k)", "Net sales (USD k)"),
                           M("Target (USD k)", "Budget (USD k)"), M("Achievement %", "Ach %"), M("Variance (USD k)", "Variance"),
                           M("Growth %"), M("Gross Margin (USD k)", "Margin (USD k)"), M("Gross Margin %", "Margin %"),
                           M("Cartons Sold", "Cartons")], measure_ref("Net Sales (USD k)")))
    pages.append(("p2_market_channel", "Market & Channel", v))

    v = [textbox("title", MG, TITLE_Y, W - 2 * MG, TITLE_H, 1000, "Supermarket Performance",
                 f"{SUB}  |  8 Atlantic Mart stores: 4 Sierra Leone, 2 Gambia, 2 Liberia")]
    v += kpi_row([("Supermarket Sales (USD m)", "Supermarket Sales"), ("Sales per Store", "Sales per Store"),
                  ("Gross Margin %", "Gross Margin"), ("Discount %", "Promotional Discount"),
                  ("Cartons Sold", "Cartons Sold"), ("Stores Trading", "Stores Trading")])
    v.append(chart("chart_store", MG, BODY_Y, half, top_h, 5000, "Net sales by store (USD k)", "clusteredBarChart",
                   category=C("Location", "Location Name", "Store"), values=[M("Supermarket Sales (USD k)", "Net sales")],
                   sort_field=measure_ref("Supermarket Sales (USD k)"), data_labels=True))
    v.append(chart("chart_store_trend", MG + half + GAP, BODY_Y, half, top_h, 5100, "Store sales trend (USD k)",
                   "lineChart", category=C("Date", "Month Year"), series=C("Location", "Location Name", "Store"),
                   values=[M("Supermarket Sales (USD k)", "Net sales")], sort_field=column_ref("Date", "Month Year Sort"),
                   descending=False))
    v.append(table_visual("tbl_store", MG, bot_y, half, bot_h, 5200, "Store scorecard",
                          [C("Location", "Location Name", "Store"), C("Location", "Country"), C("Location", "City"),
                           M("Supermarket Sales (USD k)", "Net sales (USD k)"), M("Growth %"), M("Gross Margin %", "Margin %"),
                           M("Discount %"), M("Cartons Sold", "Cartons")], measure_ref("Supermarket Sales (USD k)")))
    v.append(table_visual("tbl_store_cat", MG + half + GAP, bot_y, half, bot_h, 5300, "Best sellers in store",
                          [C("Product", "Product Name", "SKU"), C("Product", "Category"),
                           M("Supermarket Sales (USD k)", "Net sales (USD k)"), M("Units Sold", "Units"),
                           M("Gross Margin %", "Margin %")], measure_ref("Supermarket Sales (USD k)")))
    pages.append(("p3_supermarket", "Supermarket Performance", v, [("Channel", "Channel", "'Supermarket'")]))

    v = [textbox("title", MG, TITLE_Y, W - 2 * MG, TITLE_H, 1000, "B2B Customer Performance",
                 f"{SUB}  |  Wholesalers, retailers, HORECA and institutional customers")]
    v += kpi_row([("B2B Sales (USD m)", "B2B Sales"), ("Invoices", "Invoices"), ("Avg Invoice Value", "Avg Invoice Value"),
                  ("Customers Billed", "Customers Billed"), ("Lines per Invoice", "Lines per Invoice"),
                  ("Return %", "Credit Notes %")])
    v.append(chart("chart_segment", MG, BODY_Y, half, top_h, 5000, "B2B sales by customer segment", "donutChart",
                   category=C("Customer", "Segment"), values=[M("B2B Sales (USD k)", "Net sales")],
                   legend=True, legend_position="Right"))
    v.append(chart("chart_top_cust", MG + half + GAP, BODY_Y, half, top_h, 5100, "Top customers (USD k)", "clusteredBarChart",
                   category=C("Customer", "Customer Name", "Customer"), values=[M("B2B Sales (USD k)", "Net sales")],
                   sort_field=measure_ref("B2B Sales (USD k)"), data_labels=True))
    v.append(table_visual("tbl_customer", MG, bot_y, W - 2 * MG, bot_h, 5200, "Customer scorecard",
                          [C("Customer", "Customer Name", "Customer"), C("Customer", "Segment"), C("Customer", "Country"),
                           C("Customer", "Credit Days", "Credit days"), M("B2B Sales (USD k)", "Net sales (USD k)"),
                           M("Growth %"), M("Invoices"), M("Avg Invoice Value", "Avg invoice"), M("Gross Margin %", "Margin %"),
                           M("Return %")], measure_ref("B2B Sales (USD k)")))
    pages.append(("p4_b2b", "B2B Customers", v, [("Channel", "Channel", "'B2B'")]))

    v = [textbox("title", MG, TITLE_Y, W - 2 * MG, TITLE_H, 1000, "Product & Margin Analysis",
                 f"{SUB}  |  Category, brand and SKU performance at landed-cost margin")]
    v += kpi_row([("Net Sales (USD m)", "Net Sales"), ("Gross Margin (USD m)", "Gross Margin"),
                  ("Gross Margin %", "Margin %"), ("Margin per Carton", "Margin per Carton"),
                  ("Active SKUs", "SKUs Sold"), ("Discount %", "Discount %")])
    v.append(chart("chart_cat", MG, BODY_Y, half, top_h, 5000, "Net sales and margin by category (USD k)",
                   "lineClusteredColumnComboChart", category=C("Product", "Category"),
                   values=[M("Net Sales (USD k)", "Net sales")], y2=[M("Gross Margin (USD k)", "Gross margin")],
                   sort_field=measure_ref("Net Sales (USD k)")))
    v.append(chart("chart_brand", MG + half + GAP, BODY_Y, half, top_h, 5100, "Top brands (USD k)", "clusteredBarChart",
                   category=C("Product", "Brand"), values=[M("Net Sales (USD k)", "Net sales")],
                   sort_field=measure_ref("Net Sales (USD k)"), data_labels=True))
    v.append(table_visual("tbl_sku", MG, bot_y, W - 2 * MG, bot_h, 5200, "SKU performance",
                          [C("Product", "Product Name", "SKU"), C("Product", "Category"), C("Product", "Brand"),
                           C("Product", "Origin Country", "Origin"), M("Net Sales (USD k)", "Net sales (USD k)"),
                           M("Cartons Sold", "Cartons"), M("Growth %"), M("Gross Margin (USD k)", "Margin (USD k)"),
                           M("Gross Margin %", "Margin %"), M("Contribution %", "Share %")],
                          measure_ref("Net Sales (USD k)")))
    pages.append(("p5_product", "Product & Margin", v))
    return pages


# =====================================================================================
PROJECTS = {
    # project: (model builder, report builder, pages that keep showing every period)
    "Procurement Analytics": (procurement_model, procurement_report, ("p4_shipments",)),
    "Inventory Analytics": (inventory_model, inventory_report, ()),
    "Sales Analytics": (sales_model, sales_report, ()),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-folder", default="C:\\westafrica-fmcg-analytics\\data\\",
                    help="folder holding the CSV extracts (set per machine in Power BI: Transform data > Edit parameters)")
    args = ap.parse_args()
    PBI.mkdir(parents=True, exist_ok=True)
    for project, (model_fn, report_fn, unfiltered) in PROJECTS.items():
        rep, mod = scaffold(PBI, project, TOOLS / "template")
        tables, rels = model_fn()
        write_model(mod, tables, rels, args.data_folder)
        write_report(rep, report_fn(), year_filter=("Date", "Financial Year", "'FY 2025-26'"), unfiltered=unfiltered)
        n_meas = sum(len(t.measures) for t in tables)
        pages = report_fn()
        print(f"{project:24s} {len(tables):2d} tables | {len(rels):2d} relationships | {n_meas:3d} measures | "
              f"{len(pages)} pages | {sum(len(p[2]) for p in pages)} visuals")
    print(f"\nData folder parameter: {args.data_folder}")


if __name__ == "__main__":
    main()
