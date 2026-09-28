#!/usr/bin/env python3
"""
generate_data.py
================
Deterministic data generator for the West Africa FMCG import & distribution
analytics project (Atlantic Foods Trading Ltd - fictional).

Business simulated (FY Apr-2021 .. Mar-2026, 60 months):

  * Imports of Food & Beverages from Europe, France, China, India and the USA.
  * Full import cycle: purchase order -> supplier -> container shipment ->
    port arrival -> customs clearance -> warehouse receipt, with freight,
    duty, clearing and inland costs building a LANDED COST per carton.
  * Distribution in Sierra Leone, Gambia and Liberia: one central warehouse per
    country, plus 8 "Atlantic Mart" supermarkets (4 SL, 2 GM, 2 LR).
  * Two sales channels: B2B (wholesalers, retailers, HORECA, institutions) and
    the company's own supermarkets (weekly POS summary per store x SKU).
  * Stock is real: warehouse receipts feed B2B sales and store transfers;
    stores sell from their own stock; shortages cause lost sales.

Everything is generated from one seed, so the output is reproducible.
Money is USD throughout.

Output (data/):
    dim_date.csv                 calendar with Indian-style FY (Apr-Mar)
    dim_product.csv              SKU master with duty rate, pack, CBM, prices
    dim_supplier.csv             suppliers with origin country and port
    dim_location.csv             3 warehouses + 8 supermarkets
    dim_customer.csv             B2B customers by country and segment
    fact_purchase_orders.csv     PO header level (one row per PO)
    fact_po_lines.csv            PO line level with ordered / received qty
    fact_shipments.csv           container shipments with dates and cost build-up
    fact_landed_cost.csv         cost components per shipment (freight, duty, ...)
    fact_goods_receipts.csv      warehouse receipts with landed unit cost
    fact_stock_movements.csv     receipts, transfers, issues, adjustments
    fact_stock_snapshot.csv      month-end stock by location x SKU
    fact_sales.csv.gz            B2B invoice lines + supermarket weekly POS lines
    fact_sales_target.csv        monthly sales budget by country x channel
    _generation_notes.json       patterns deliberately planted in the data

Usage:
    python data/generate_data.py [--seed 42] [--scale 1.0]
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
START = pd.Timestamp("2021-04-01")
END = pd.Timestamp("2026-03-31")
N_MONTHS = 60
MONTH_START = pd.date_range(START, periods=N_MONTHS + 1, freq="MS")
COMPANY = "Atlantic Foods Trading Ltd."

# ----------------------------------------------------------------------------------
# Geography, locations, suppliers
# ----------------------------------------------------------------------------------
COUNTRIES = {
    # code: (name, capital, market size index, duty uplift, port)
    "SL": dict(name="Sierra Leone", capital="Freetown", size=1.00, port="Freetown (Queen Elizabeth II Quay)"),
    "GM": dict(name="Gambia", capital="Banjul", size=0.55, port="Banjul Port"),
    "LR": dict(name="Liberia", capital="Monrovia", size=0.75, port="Freeport of Monrovia"),
}

WAREHOUSES = [
    ("WH-SL", "Freetown Central Warehouse", "SL", "Freetown", 0),
    ("WH-GM", "Banjul Distribution Centre", "GM", "Banjul", 0),
    ("WH-LR", "Monrovia Central Warehouse", "LR", "Monrovia", 0),
]
# store code, name, country, city, month the store opened (0 = open from the start)
STORES = [
    ("ST-SL1", "Atlantic Mart Lumley", "SL", "Freetown", 0),
    ("ST-SL2", "Atlantic Mart Wilkinson Road", "SL", "Freetown", 0),
    ("ST-SL3", "Atlantic Mart Aberdeen", "SL", "Freetown", 0),
    ("ST-SL4", "Atlantic Mart Bo Town", "SL", "Bo", 21),          # opened Jan-2023
    ("ST-GM1", "Atlantic Mart Serrekunda", "GM", "Serrekunda", 0),
    ("ST-GM2", "Atlantic Mart Kairaba Avenue", "GM", "Banjul", 8),  # opened Dec-2021
    ("ST-LR1", "Atlantic Mart Sinkor", "LR", "Monrovia", 0),
    ("ST-LR2", "Atlantic Mart Paynesville", "LR", "Monrovia", 30),  # opened Oct-2023
]

# origin: (port of loading, transit days min/max, freight index, supplier count)
ORIGINS = {
    "Netherlands": dict(region="Europe", port="Rotterdam", transit=(21, 28), freight=1.00),
    "France": dict(region="Europe", port="Le Havre", transit=(20, 27), freight=1.02),
    "China": dict(region="Asia", port="Shanghai", transit=(34, 46), freight=1.25),
    "India": dict(region="Asia", port="Nhava Sheva", transit=(26, 36), freight=1.10),
    "USA": dict(region="Americas", port="Houston", transit=(28, 38), freight=1.18),
}

SUPPLIERS = [
    # name, origin, tier (a = reliable, b = average, c = weak), payment terms
    ("Rotterdam Food Exports BV", "Netherlands", "a", "LC at sight"),
    ("Holland Dairy Ingredients BV", "Netherlands", "a", "LC 30 days"),
    ("Amsterdam Beverage Traders", "Netherlands", "b", "TT 30 days"),
    ("Le Havre Gourmet SAS", "France", "a", "LC at sight"),
    ("Provence Oils & Foods SAS", "France", "b", "LC 60 days"),
    ("Marseille Confiserie SARL", "France", "b", "TT 45 days"),
    ("Shanghai Golden Harvest Co.", "China", "b", "TT 30 days"),
    ("Ningbo Canned Foods Ltd.", "China", "c", "TT 45 days"),
    ("Qingdao Beverage Industries", "China", "b", "LC at sight"),
    ("Guangzhou Snack Foods Ltd.", "China", "c", "TT 60 days"),
    ("Mumbai Agro Exports Pvt Ltd", "India", "a", "LC at sight"),
    ("Kandla Edible Oils Pvt Ltd", "India", "b", "LC 30 days"),
    ("Chennai Spice House Pvt Ltd", "India", "b", "TT 30 days"),
    ("Delhi Rice Millers Pvt Ltd", "India", "c", "LC 60 days"),
    ("Houston Grain Exporters Inc.", "USA", "a", "LC at sight"),
    ("Midwest Dairy Products Inc.", "USA", "a", "LC 30 days"),
    ("Atlanta Beverage Corp.", "USA", "b", "TT 45 days"),
]

# ----------------------------------------------------------------------------------
# Product master: category, sub-category, brand, variants, pack, FOB per carton,
# cartons per CBM, duty %, seasonality key, tier
# ----------------------------------------------------------------------------------
PRODUCTS = [
    # (category, sub_category, brand, variants, pack, units/carton, FOB USD/carton, CBM/carton, duty %, season, origin)
    ("Staples", "Rice", "Sahel Gold", ["Parboiled 5%", "Long Grain", "Basmati"], "25 kg bag", 1, 21.0, 0.033, 10, "ramadan", "India"),
    ("Staples", "Rice", "Harvest King", ["Parboiled 100%", "Broken Rice"], "50 kg bag", 1, 38.0, 0.062, 10, "ramadan", "India"),
    ("Staples", "Flour & Pasta", "Bella Pasta", ["Spaghetti", "Macaroni", "Penne"], "500 g x 20", 20, 14.5, 0.030, 20, "flat", "Netherlands"),
    ("Staples", "Flour & Pasta", "Golden Wheat", ["All Purpose Flour", "Semolina"], "1 kg x 10", 10, 11.0, 0.022, 10, "flat", "France"),
    ("Staples", "Sugar & Sweeteners", "Sweet Delta", ["White Refined", "Brown Sugar", "Cube Sugar"], "1 kg x 20", 20, 19.5, 0.028, 20, "ramadan", "Netherlands"),
    ("Cooking Essentials", "Edible Oil", "Palma Chef", ["Palm Oil", "Vegetable Oil"], "5 L x 4", 4, 32.0, 0.030, 20, "flat", "India"),
    ("Cooking Essentials", "Edible Oil", "Olivia", ["Sunflower Oil", "Olive Oil Blend"], "1 L x 12", 12, 26.5, 0.024, 20, "festive", "France"),
    ("Cooking Essentials", "Seasonings", "Savour", ["Bouillon Cubes", "Curry Powder", "Mixed Spice"], "Display x 24", 24, 15.0, 0.018, 20, "flat", "India"),
    ("Cooking Essentials", "Tomato Paste", "Rossa", ["70 g Sachet", "400 g Tin", "2.2 kg Catering"], "Carton x 48", 48, 22.0, 0.026, 20, "flat", "China"),
    ("Dairy", "Milk Powder", "Nutrimilk", ["Full Cream 400 g", "Full Cream 900 g", "Instant 2.5 kg"], "Carton x 12", 12, 46.0, 0.028, 5, "flat", "Netherlands"),
    ("Dairy", "Milk Powder", "DairyBest", ["Growing Up Formula", "Skimmed Powder"], "Carton x 12", 12, 58.0, 0.028, 5, "flat", "USA"),
    ("Dairy", "Evaporated & Condensed", "CreamTop", ["Evaporated Milk", "Condensed Milk"], "170 g x 48", 48, 28.0, 0.026, 10, "festive", "Netherlands"),
    ("Canned Foods", "Fish & Meat", "Marina", ["Sardines in Oil", "Sardines in Tomato", "Mackerel"], "125 g x 50", 50, 24.0, 0.022, 20, "flat", "China"),
    ("Canned Foods", "Vegetables & Fruit", "GreenField", ["Sweet Corn", "Green Peas", "Fruit Cocktail"], "400 g x 24", 24, 18.5, 0.024, 20, "flat", "China"),
    ("Beverages", "Juice", "Tropicana Delight", ["Orange 1 L", "Mango 1 L", "Mixed Fruit 250 ml"], "Carton x 12", 12, 13.5, 0.026, 20, "hot", "France"),
    ("Beverages", "Carbonated", "FizzUp", ["Cola 330 ml", "Lemon 330 ml", "Orange 1.5 L"], "Carton x 24", 24, 11.0, 0.030, 20, "hot", "Netherlands"),
    ("Beverages", "Water & Energy", "AquaPure", ["Still Water 1.5 L", "Sparkling 750 ml", "Energy Drink 250 ml"], "Carton x 12", 12, 9.0, 0.028, 20, "hot", "China"),
    ("Beverages", "Tea & Coffee", "Mount Coffee", ["Instant Coffee 100 g", "Tea Bags x100", "Green Tea x50"], "Carton x 24", 24, 33.0, 0.020, 20, "cool", "India"),
    ("Snacks & Confectionery", "Biscuits", "CrispBite", ["Cream Biscuits", "Digestive", "Wafer Rolls"], "Carton x 36", 36, 17.5, 0.030, 20, "festive", "China"),
    ("Snacks & Confectionery", "Confectionery", "SweetHarbour", ["Fruit Candy", "Chocolate Bars", "Chewing Gum"], "Display x 40", 40, 21.0, 0.022, 20, "festive", "France"),
    ("Baby & Health", "Baby Food", "LittleStar", ["Infant Cereal 400 g", "Baby Formula Stage 1", "Baby Formula Stage 2"], "Carton x 12", 12, 52.0, 0.024, 5, "flat", "USA"),
    ("Baby & Health", "Breakfast Cereal", "MorningGold", ["Corn Flakes", "Oats 1 kg", "Choco Pops"], "Carton x 14", 14, 29.0, 0.032, 20, "flat", "USA"),
]

SEASON = {  # month-of-year multipliers (Jan..Dec)
    "flat":    [1.00, 0.97, 1.00, 1.00, 1.00, 0.96, 0.94, 0.96, 1.00, 1.03, 1.06, 1.10],
    "hot":     [1.10, 1.15, 1.25, 1.30, 1.25, 1.00, 0.85, 0.85, 0.90, 1.00, 1.05, 1.15],
    "cool":    [1.05, 1.02, 0.95, 0.90, 0.88, 1.00, 1.10, 1.12, 1.08, 1.02, 1.05, 1.10],
    "festive": [0.95, 0.92, 0.95, 0.98, 1.00, 0.95, 0.92, 0.95, 1.00, 1.05, 1.15, 1.35],
    "ramadan": [1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.02, 1.05, 1.10],
}
# Eid al-Fitr dates: demand lifts in the ~5 weeks before (Ramadan)
EID = [pd.Timestamp(d) for d in ["2021-05-13", "2022-05-02", "2023-04-21", "2024-04-10", "2025-03-30", "2026-03-20"]]

CUSTOMER_SEGMENTS = {
    # segment: (share of customers, order frequency per month, avg lines, price index, credit days)
    "Wholesaler": (0.18, 2.6, 9, 0.93, 30),
    "Retailer / Mini-mart": (0.46, 1.6, 5, 1.00, 14),
    "HORECA (Hotel & Restaurant)": (0.22, 1.9, 4, 1.06, 21),
    "Institution / NGO": (0.14, 0.9, 6, 1.02, 45),
}
CUSTOMER_PREFIX = ["Kamara", "Sesay", "Bangura", "Conteh", "Jallow", "Ceesay", "Touray", "Njie", "Doe", "Weah",
                   "Johnson", "Cooper", "Mansaray", "Turay", "Barrie", "Sowe", "Gomez", "Diallo", "Bah", "Koroma"]
CUSTOMER_SUFFIX = {
    "Wholesaler": ["Trading Enterprise", "& Sons Wholesale", "General Merchants", "Distribution Ltd"],
    "Retailer / Mini-mart": ["Mini Mart", "Provision Store", "Superette", "Corner Shop", "Food Store"],
    "HORECA (Hotel & Restaurant)": ["Hotel", "Restaurant & Bar", "Beach Resort", "Catering Services"],
    "Institution / NGO": ["Relief Foundation", "Community Hospital", "International School", "Mission Society"],
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def fy_label(ts: pd.Timestamp | pd.Series):
    """Financial year Apr-Mar, e.g. FY 2024-25."""
    y = ts.dt.year if hasattr(ts, "dt") else ts.year
    m = ts.dt.month if hasattr(ts, "dt") else ts.month
    start = np.where(m >= 4, y, y - 1)
    return pd.Series([f"FY {s}-{str(s + 1)[2:]}" for s in np.atleast_1d(start)])


def day_or_blank(ts):
    """A date string, or blank when the event is still in the future at the cut-off."""
    return str(ts.date()) if ts <= END else ""


def int_or_blank(value, ts):
    """A whole number, or blank when the event it measures has not happened yet."""
    return int(value) if ts <= END else ""


def month_index(ts) -> np.ndarray:
    ts = pd.to_datetime(ts)
    return ((ts.dt.year - START.year) * 12 + ts.dt.month - START.month).to_numpy()


def build_masters(rng, scale):
    # ---------------- products ----------------
    rows = []
    # each variant is imported in 2-3 pack formats (carton sizes), which is what makes up the SKU list
    PACK_FORMATS = [("Standard", 1.00, 1.00), ("Economy Pack", 1.85, 1.90), ("Catering Pack", 3.10, 3.20)]
    for (cat, sub, brand, variants, pack, upc, fob, cbm, duty, season, origin) in PRODUCTS:
        for v in variants:
            n_fmt = 2 if len(variants) > 2 else 3
            for fmt, cost_mult, vol_mult in PACK_FORMATS[:n_fmt]:
                rows.append(dict(Category=cat, Sub_Category=sub, Brand=brand, Variant=v,
                                 Pack_Size=pack if fmt == "Standard" else f"{pack} - {fmt}",
                                 Pack_Format=fmt, Units_Per_Carton=int(round(upc * (1 if fmt == "Standard" else vol_mult))),
                                 FOB_Cost_USD=fob * cost_mult, CBM_Per_Carton=cbm * vol_mult, Duty_Rate_Pct=duty,
                                 Season=season, Origin_Country=origin))
    p = pd.DataFrame(rows)
    n = len(p)
    p.insert(0, "SKU_ID", [f"SKU-{i + 1:04d}" for i in range(n)])
    p["Product_Name"] = p.Brand + " " + p.Variant + " (" + p.Pack_Size + ")"
    p["SKU_Code"] = [f"{c[:2].upper()}{b[:3].upper()}{i + 1:03d}" for i, (c, b) in enumerate(zip(p.Category, p.Brand))]
    # cost / price variation per SKU
    p["FOB_Cost_USD"] = (p.FOB_Cost_USD * rng.uniform(0.9, 1.12, n)).round(2)
    p["CBM_Per_Carton"] = (p.CBM_Per_Carton * rng.uniform(0.9, 1.1, n)).round(4)
    # popularity: a few fast movers, a long tail
    p["Popularity"] = np.clip(rng.lognormal(0, 0.55, n), 0.15, 4.0)
    p.loc[p.Sub_Category.isin(["Rice", "Edible Oil", "Tomato Paste"]), "Popularity"] *= 2.4
    p.loc[p.Category == "Beverages", "Popularity"] *= 2.0
    p.loc[p.Category == "Snacks & Confectionery", "Popularity"] *= 1.5
    p.loc[p.Sub_Category == "Milk Powder", "Popularity"] *= 1.15
    # margin policy: B2B mark-up on landed cost, retail mark-up on landed cost
    p["B2B_Markup"] = np.where(p.Category == "Staples", rng.uniform(1.10, 1.18, n), rng.uniform(1.16, 1.30, n)).round(3)
    p["Retail_Markup"] = (p.B2B_Markup * rng.uniform(1.12, 1.24, n)).round(3)
    p["Shelf_Life_Days"] = np.select(
        [p.Category == "Dairy", p.Category == "Beverages", p.Category == "Baby & Health"], [365, 300, 540], 480)
    p["Status"] = "Active"
    # a small number of SKUs are delisted during the period (slow movers)
    slow = rng.choice(n, size=4, replace=False)
    p.loc[slow, "Status"] = "Delisted"
    p["Delist_Month"] = -1
    p.loc[slow, "Delist_Month"] = rng.integers(40, 56, len(slow))

    # ---------------- suppliers ----------------
    s = pd.DataFrame(SUPPLIERS, columns=["Supplier_Name", "Origin_Country", "Tier", "Payment_Terms"])
    s.insert(0, "Supplier_ID", [f"SUP-{i + 1:03d}" for i in range(len(s))])
    s["Region"] = s.Origin_Country.map(lambda o: ORIGINS[o]["region"])
    s["Port_of_Loading"] = s.Origin_Country.map(lambda o: ORIGINS[o]["port"])
    s["Incoterm"] = np.where(s.Tier == "a", "FOB", rng.choice(["FOB", "CIF"], len(s)))
    # reliability: average delay vs promised transit and fill rate
    s["Delay_Mean"] = s.Tier.map({"a": 1.5, "b": 4.5, "c": 9.0})
    s["Delay_SD"] = s.Tier.map({"a": 2.0, "b": 4.0, "c": 7.0})
    s["Fill_Rate"] = s.Tier.map({"a": 0.995, "b": 0.975, "c": 0.945})

    # each SKU is sourced from one supplier in its origin country
    p["Supplier_ID"] = [rng.choice(s.loc[s.Origin_Country == o, "Supplier_ID"].to_numpy()) for o in p.Origin_Country]

    # ---------------- locations ----------------
    loc_rows = []
    for code, name, c, city, open_m in WAREHOUSES:
        loc_rows.append(dict(Location_ID=code, Location_Name=name, Location_Type="Warehouse", Country_Code=c,
                             Country=COUNTRIES[c]["name"], City=city, Open_Month=open_m))
    for code, name, c, city, open_m in STORES:
        loc_rows.append(dict(Location_ID=code, Location_Name=name, Location_Type="Supermarket", Country_Code=c,
                             Country=COUNTRIES[c]["name"], City=city, Open_Month=open_m))
    loc = pd.DataFrame(loc_rows)
    loc["Opening_Date"] = [str((START + pd.DateOffset(months=int(m))).date()) if m else str(START.date()) for m in loc.Open_Month]
    loc["Warehouse_ID"] = loc.Country_Code.map({c: f"WH-{c}" for c in COUNTRIES})

    # ---------------- B2B customers ----------------
    cust_rows = []
    for c, meta in COUNTRIES.items():
        n_cust = int(round(95 * meta["size"] * scale))
        for i in range(n_cust):
            seg = rng.choice(list(CUSTOMER_SEGMENTS), p=[v[0] for v in CUSTOMER_SEGMENTS.values()])
            name = f"{rng.choice(CUSTOMER_PREFIX)} {rng.choice(CUSTOMER_SUFFIX[seg])}"
            cust_rows.append(dict(Customer_Name=name, Segment=seg, Country_Code=c, Country=meta["name"],
                                  City=meta["capital"], Credit_Days=CUSTOMER_SEGMENTS[seg][4],
                                  Size_Index=float(np.clip(rng.lognormal(0, 0.5), 0.25, 4.0))))
    cu = pd.DataFrame(cust_rows)
    cu.insert(0, "Customer_ID", [f"CUS-{i + 1:04d}" for i in range(len(cu))])
    cu["Onboard_Month"] = np.where(rng.random(len(cu)) < 0.82, 0, rng.integers(1, 50, len(cu)))
    cu["Status"] = np.where(rng.random(len(cu)) < 0.95, "Active", "Dormant")
    return p, s, loc, cu


def demand_profile(rng, prod, loc, cust, scale):
    """Monthly demand (cartons) per location/customer x SKU, before stock constraints."""
    n_sku = len(prod)
    months = np.arange(N_MONTHS)
    dates = MONTH_START[:N_MONTHS]
    moy = dates.month.to_numpy() - 1

    # seasonality per SKU x month
    seas = np.array([SEASON[s] for s in prod.Season])[:, moy]                       # (sku, month)
    # Ramadan lift for staples/beverages in the weeks before Eid
    ram = np.ones(N_MONTHS)
    for eid in EID:
        mi = (eid.year - START.year) * 12 + eid.month - START.month
        for off, lift in ((-1, 1.28), (0, 1.18)):
            if 0 <= mi + off < N_MONTHS:
                ram[mi + off] *= lift
    staple = prod.Category.isin(["Staples", "Cooking Essentials", "Beverages"]).to_numpy()
    seas = seas * np.where(staple[:, None], ram[None, :], 1 + (ram[None, :] - 1) * 0.35)

    # growth + price inflation environment
    trend = np.exp(0.085 * months / 12)
    # 2022 global food price spike hits volumes slightly (affordability)
    trend[9:21] *= np.linspace(1.0, 0.94, 12)
    lifecycle = np.ones((n_sku, N_MONTHS))
    for i, dm in enumerate(prod.Delist_Month):
        if dm >= 0:
            lifecycle[i, dm:] = 0
            lifecycle[i, max(0, dm - 6):dm] *= np.linspace(0.8, 0.2, dm - max(0, dm - 6))
    base = prod.Popularity.to_numpy()[:, None] * seas * trend[None, :] * lifecycle
    return base * rng.lognormal(0, 0.10, base.shape)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scale", type=float, default=1.0)
    args = ap.parse_args()
    t0 = time.time()
    rng = np.random.default_rng(args.seed)

    log("Building masters ...")
    prod, sup, loc, cust = build_masters(rng, args.scale)
    n_sku = len(prod)
    stores = loc[loc.Location_Type == "Supermarket"].reset_index(drop=True)
    whs = loc[loc.Location_Type == "Warehouse"].reset_index(drop=True)
    log(f"  {n_sku} SKUs | {len(sup)} suppliers | {len(loc)} locations | {len(cust)} B2B customers")

    base = demand_profile(rng, prod, loc, cust, args.scale)

    # ------------------------------------------------------------------ store assortment & demand
    # each store stocks the faster-moving SKUs; B2B carries everything
    store_assort = {}
    for _, st in stores.iterrows():
        k = int(rng.integers(int(0.55 * n_sku), int(0.8 * n_sku)))
        w = prod.Popularity.to_numpy() + 0.05
        store_assort[st.Location_ID] = np.sort(rng.choice(n_sku, size=k, replace=False, p=w / w.sum()))

    store_share = 0.30 * args.scale   # share of country demand sold through own supermarkets
    country_units = {c: COUNTRIES[c]["size"] * 11500 * args.scale for c in COUNTRIES}  # cartons per month

    # ---------------- B2B customer monthly demand ----------------
    cust_idx = {cid: i for i, cid in enumerate(cust.Customer_ID)}
    cust_country = cust.Country_Code.to_numpy()
    cust_seg = cust.Segment.to_numpy()
    cust_size = cust.Size_Index.to_numpy()
    seg_freq = np.array([CUSTOMER_SEGMENTS[s][1] for s in cust_seg])
    seg_lines = np.array([CUSTOMER_SEGMENTS[s][2] for s in cust_seg])
    seg_price = np.array([CUSTOMER_SEGMENTS[s][3] for s in cust_seg])

    log("Simulating procurement, stock and sales month by month ...")
    # state
    wh_stock = {w: np.zeros(n_sku) for w in whs.Location_ID}          # cartons
    wh_cost = {w: prod.FOB_Cost_USD.to_numpy() * 1.45 for w in whs.Location_ID}  # weighted-average landed cost
    st_stock = {s: np.zeros(n_sku) for s in stores.Location_ID}
    st_cost = {s: prod.FOB_Cost_USD.to_numpy() * 1.45 for s in stores.Location_ID}
    # opening stock: the company is a going concern, warehouses start with ~2.5 months of cover
    for _, wh0 in whs.iterrows():
        c0 = wh0.Country_Code
        opening_units = base[:, 0] / base[:, 0].sum() * COUNTRIES[c0]["size"] * 11500 * args.scale * 2.5
        wh_stock[wh0.Location_ID] = np.floor(opening_units * rng.uniform(0.8, 1.2, n_sku))

    po_rows, po_line_rows, ship_rows, cost_rows, grn_rows = [], [], [], [], []
    mov_rows, snap_rows, sales_rows = [], [], []
    pending = []          # shipments in transit -> (arrival_month, rows)
    po_seq = ship_seq = grn_seq = inv_seq = 0

    duty = prod.Duty_Rate_Pct.to_numpy() / 100
    cbm = prod.CBM_Per_Carton.to_numpy()
    fob0 = prod.FOB_Cost_USD.to_numpy()
    sup_of_sku = prod.Supplier_ID.to_numpy()
    sup_meta = sup.set_index("Supplier_ID")

    # freight market index by month (2021-22 container crisis, 2024 Red Sea)
    freight_index = np.ones(N_MONTHS)
    freight_index[0:9] = np.linspace(2.9, 3.3, 9)        # Apr-21 .. Dec-21 peak
    freight_index[9:18] = np.linspace(3.2, 1.5, 9)       # 2022 normalising
    freight_index[18:33] = np.linspace(1.45, 1.05, 15)
    freight_index[33:45] = np.linspace(1.05, 1.55, 12)   # Red Sea disruption 2024
    freight_index[45:] = np.linspace(1.5, 1.15, N_MONTHS - 45)
    # FOB cost inflation (food commodity prices)
    cost_index = np.ones(N_MONTHS)
    cost_index[0:12] = np.linspace(1.00, 1.09, 12)
    cost_index[12:24] = np.linspace(1.09, 1.26, 12)      # 2022-23 food price spike
    cost_index[24:36] = np.linspace(1.26, 1.22, 12)
    cost_index[36:48] = np.linspace(1.22, 1.27, 12)
    cost_index[48:] = np.linspace(1.27, 1.33, N_MONTHS - 48)
    # real price drift on top of landed cost (mark-ups are applied to the landed cost itself,
    # so cost inflation is already passed through; this is the small extra margin drift)
    price_drift = 1 + 0.012 * np.arange(N_MONTHS) / 12
    price_drift[12:26] *= np.linspace(0.985, 0.955, 14)   # FY22-23: costs rose faster than shelf prices

    transit_extra = np.zeros(N_MONTHS)
    transit_extra[33:42] = 12       # Red Sea re-routing adds ~12 days for Asia

    def day_in_month(m, rng_local, lo=1, hi=28):
        return MONTH_START[m] + pd.Timedelta(days=int(rng_local.integers(lo, hi)))

    for m in range(N_MONTHS):
        month_start = MONTH_START[m]
        month_end = MONTH_START[m + 1] - pd.Timedelta(days=1)
        opening_wh = {w: wh_stock[w].copy() for w in wh_stock}
        opening_st = {s: st_stock[s].copy() for s in st_stock}
        recv_wh = {w: np.zeros(n_sku) for w in wh_stock}
        recv_st = {s: np.zeros(n_sku) for s in st_stock}
        out_wh = {w: np.zeros(n_sku) for w in wh_stock}
        out_st = {s: np.zeros(n_sku) for s in st_stock}
        adj_wh = {w: np.zeros(n_sku) for w in wh_stock}
        adj_st = {s: np.zeros(n_sku) for s in st_stock}

        # ---------------------------------------------------------- 1. arrivals (receipts)
        still = []
        for sh in pending:
            if sh["receipt_month"] == m:
                w = sh["warehouse"]
                q = sh["qty_received"]
                unit_landed = sh["unit_landed"]
                # weighted average cost update
                old_val = wh_stock[w] * wh_cost[w]
                wh_stock[w] += q
                new_val = old_val + q * unit_landed
                wh_cost[w] = np.where(wh_stock[w] > 0, new_val / np.maximum(wh_stock[w], 1e-9), wh_cost[w])
                recv_wh[w] += q
                grn_seq += 1
                grn_no = f"GRN-{grn_seq:05d}"
                for i in np.nonzero(q)[0]:
                    grn_rows.append(dict(GRN_No=grn_no, GRN_Date=str(sh["receipt_date"].date()), PO_No=sh["po_no"],
                                         Shipment_No=sh["shipment_no"], Warehouse_ID=w, SKU_ID=prod.SKU_ID.iloc[i],
                                         Qty_Ordered_Cartons=int(sh["qty_ordered"][i]), Qty_Received_Cartons=int(q[i]),
                                         Landed_Unit_Cost_USD=round(float(unit_landed[i]), 3),
                                         Landed_Value_USD=round(float(q[i] * unit_landed[i]), 2)))
                    mov_rows.append(dict(Movement_Date=str(sh["receipt_date"].date()), Movement_Type="Goods Receipt",
                                         Location_ID=w, SKU_ID=prod.SKU_ID.iloc[i], Qty_Cartons=int(q[i]),
                                         Value_USD=round(float(q[i] * unit_landed[i]), 2), Reference=grn_no))
            else:
                still.append(sh)
        pending = still

        # ---------------------------------------------------------- 2. demand for this month
        # store demand
        store_demand = {}
        for _, st in stores.iterrows():
            if m < st.Open_Month:
                store_demand[st.Location_ID] = np.zeros(n_sku)
                continue
            a = store_assort[st.Location_ID]
            d = np.zeros(n_sku)
            share = country_units[st.Country_Code] * store_share / max(1, (stores.Country_Code == st.Country_Code).sum())
            w = base[a, m]
            ramp = min(1.0, 0.45 + 0.55 * (m - st.Open_Month) / 6) if st.Open_Month else 1.0
            d[a] = w / w.sum() * share * ramp * rng.lognormal(0, 0.08)
            store_demand[st.Location_ID] = d

        # B2B demand by country
        b2b_country = {}
        for c in COUNTRIES:
            b2b_country[c] = base[:, m] / base[:, m].sum() * country_units[c] * (1 - store_share)

        # ---------------------------------------------------------- 3. replenishment (imports)
        for _, wh in whs.iterrows():
            w = wh.Location_ID
            c = wh.Country_Code
            # forecast monthly consumption at the warehouse = B2B demand + store transfers
            fc = b2b_country[c] + sum(store_demand[s.Location_ID] for _, s in stores.iterrows() if s.Country_Code == c)
            fc = np.maximum(fc, 0)
            in_transit = np.zeros(n_sku)
            for sh in pending:
                if sh["warehouse"] == w:
                    in_transit += sh["qty_ordered"]
            cover_target = 4.5      # months: import lead time is ~2 months plus the ordering cycle
            need = fc * cover_target - (wh_stock[w] + in_transit)
            dl = prod.Delist_Month.to_numpy()
            need = np.where((dl < 0) | (dl > m + 2), need, 0)
            need = np.maximum(need, 0)
            if need.sum() <= 0:
                continue
            # group the requirement by supplier and raise one PO (one container) per supplier
            for sid in np.unique(sup_of_sku[need > 0]):
                sel = (sup_of_sku == sid) & (need > 0)
                q = np.ceil(need * sel).astype(int)
                if q.sum() == 0:
                    continue
                vol = float((q * cbm).sum())
                if vol < 25 and rng.random() < 0.7:
                    continue                      # wait until there is enough to fill a container
                # a PO is shipped as one consolidated booking of up to 8 x 40ft containers
                max_cbm = 58.0 * 8
                if vol > max_cbm:
                    q = np.floor(q * max_cbm / vol).astype(int)
                    vol = float((q * cbm).sum())
                if q.sum() == 0:
                    continue
                meta = sup_meta.loc[sid]
                origin = meta.Origin_Country
                po_seq += 1
                po_no = f"PO-{po_seq:05d}"
                po_date = day_in_month(m, rng, 1, 25)
                fob_unit = fob0 * cost_index[m] * rng.uniform(0.98, 1.03)
                fob_value = float((q * fob_unit).sum())
                containers = max(1, math.ceil(vol / 58.0))
                # ---- shipment & landed cost ----
                tmin, tmax = ORIGINS[origin]["transit"]
                transit = int(rng.integers(tmin, tmax)) + (int(transit_extra[m]) if ORIGINS[origin]["region"] == "Asia" else 0)
                delay = max(-2, int(rng.normal(meta.Delay_Mean, meta.Delay_SD)))
                etd = po_date + pd.Timedelta(days=int(rng.integers(10, 25)))       # production + booking
                atd = etd + pd.Timedelta(days=max(0, int(rng.normal(2, 3))))
                eta = etd + pd.Timedelta(days=transit + 3)          # promised arrival (with buffer)
                ata = atd + pd.Timedelta(days=transit + delay)
                clearance_days = int(np.clip(rng.normal({"SL": 9, "GM": 7, "LR": 11}[c], 4), 2, 40))
                cleared = ata + pd.Timedelta(days=clearance_days)
                receipt = cleared + pd.Timedelta(days=int(rng.integers(1, 4)))
                rec_m = (receipt.year - START.year) * 12 + receipt.month - START.month
                if rec_m >= N_MONTHS:
                    status = "In Transit" if ata > END else "At Port / Clearing"
                else:
                    status = "Received"
                freight = round(max(vol / 58.0, 0.35 * containers) * 1.06 * 2400 * ORIGINS[origin]["freight"] * freight_index[m] * rng.uniform(0.95, 1.08), 2)
                insurance = round(fob_value * 0.006, 2)
                cif = fob_value + freight + insurance
                duty_amt = round(float((q * fob_unit * duty).sum()) + freight * 0.10, 2)
                clearing = round(containers * 950 * rng.uniform(0.9, 1.2) + cif * 0.012, 2)
                inland = round(containers * {"SL": 420, "GM": 380, "LR": 460}[c] * rng.uniform(0.9, 1.15), 2)
                demurrage = round(max(0, clearance_days - 14) * containers * 110 * rng.uniform(0.8, 1.2), 2)
                other_costs = freight + insurance + duty_amt + clearing + inland + demurrage
                landed_total = fob_value + other_costs
                # allocate landed overhead by FOB value
                fill = float(meta.Fill_Rate)
                short = (rng.random(n_sku) > fill) & (q > 0)          # a few lines arrive short (damage / supply)
                q_recv = np.where(short, np.floor(q * rng.uniform(0.75, 0.95, n_sku)), q).astype(int)
                unit_landed = np.where(q > 0, fob_unit * (landed_total / max(fob_value, 1e-9)), 0)
                ship_seq += 1
                shipment_no = f"SHP-{ship_seq:05d}"
                po_rows.append(dict(
                    PO_No=po_no, PO_Date=str(po_date.date()), Supplier_ID=sid, Supplier_Name=meta.Supplier_Name,
                    Origin_Country=origin, Incoterm=meta.Incoterm, Payment_Terms=meta.Payment_Terms,
                    Warehouse_ID=w, Country_Code=c, Country=COUNTRIES[c]["name"],
                    Lines=int((q > 0).sum()), Qty_Ordered_Cartons=int(q.sum()), FOB_Value_USD=round(fob_value, 2),
                    Containers=containers, CBM=round(vol, 2), Shipment_No=shipment_no, Status=status))
                for i in np.nonzero(q)[0]:
                    po_line_rows.append(dict(
                        PO_No=po_no, PO_Date=str(po_date.date()), Supplier_ID=sid, Warehouse_ID=w,
                        SKU_ID=prod.SKU_ID.iloc[i], Qty_Ordered_Cartons=int(q[i]),
                        FOB_Unit_Cost_USD=round(float(fob_unit[i]), 3), FOB_Value_USD=round(float(q[i] * fob_unit[i]), 2),
                        Landed_Unit_Cost_USD=round(float(unit_landed[i]), 3),
                        Qty_Received_Cartons=int(q_recv[i]) if status == "Received" else 0,
                        Status=status))
                on_time = bool(ata <= eta + pd.Timedelta(days=3))
                in_full = bool(q_recv.sum() >= q.sum() * 0.95)
                ship_rows.append(dict(
                    Shipment_No=shipment_no, PO_No=po_no, Supplier_ID=sid, Supplier_Name=meta.Supplier_Name,
                    Origin_Country=origin, Port_of_Loading=ORIGINS[origin]["port"], Port_of_Discharge=COUNTRIES[c]["port"],
                    Warehouse_ID=w, Country_Code=c, Country=COUNTRIES[c]["name"], Containers=containers,
                    Container_Type="40ft", CBM=round(vol, 2), Qty_Cartons=int(q.sum()),
                    # events after the cut-off have not happened yet, so they are left empty:
                    # a shipment still at sea has no actual arrival, clearance or receipt date
                    ETD=str(etd.date()), ATD=str(atd.date()), ETA=str(eta.date()),
                    ATA=day_or_blank(ata), Customs_Cleared_Date=day_or_blank(cleared),
                    Warehouse_Receipt_Date=day_or_blank(receipt),
                    Transit_Days=int_or_blank((ata - atd).days, ata), Clearance_Days=int_or_blank(clearance_days, cleared),
                    Total_Lead_Time_Days=int_or_blank((receipt - po_date).days, receipt),
                    Delay_Days=int_or_blank((ata - eta).days, ata),
                    On_Time=on_time if ata <= END else "", In_Full=in_full if receipt <= END else "",
                    OTIF=bool(on_time and in_full) if receipt <= END else "",
                    FOB_Value_USD=round(fob_value, 2), Landed_Value_USD=round(landed_total, 2),
                    Landed_Cost_Uplift_Pct=round((landed_total / fob_value - 1) * 100, 2), Status=status))
                for label, amount in (("FOB / Goods", fob_value), ("Ocean Freight", freight), ("Insurance", insurance),
                                      ("Customs Duty", duty_amt), ("Clearing & Port Charges", clearing),
                                      ("Inland Transport", inland), ("Demurrage", demurrage)):
                    if amount > 0:
                        cost_rows.append(dict(Shipment_No=shipment_no, PO_No=po_no, Cost_Date=str(receipt.date()),
                                              Warehouse_ID=w, Country=COUNTRIES[c]["name"], Origin_Country=origin,
                                              Cost_Component=label, Amount_USD=round(float(amount), 2)))
                if status == "Received":
                    pending.append(dict(receipt_month=rec_m, receipt_date=receipt, warehouse=w, po_no=po_no,
                                        shipment_no=shipment_no, qty_ordered=q, qty_received=q_recv, unit_landed=unit_landed))

        # ---------------------------------------------------------- 4+5. weekly store cycle: replenish, then sell
        weeks = pd.date_range(month_start, month_end, freq="W-MON")
        if len(weeks) == 0:
            weeks = pd.DatetimeIndex([month_start])
        for wk in weeks:
            week_end = min(wk + pd.Timedelta(days=6), month_end)
            for _, st in stores.iterrows():
                if m < st.Open_Month:
                    continue
                s_id, w_id = st.Location_ID, st.Warehouse_ID
                weekly = store_demand[s_id] / len(weeks)

                # --- replenishment from the country warehouse (target ~2.5 weeks of cover) ---
                need = np.maximum(np.ceil(weekly * 3.0 - st_stock[s_id]), 0)
                need = np.minimum(need, wh_stock[w_id])
                idx = np.nonzero(need)[0]
                if idx.size > 45:                                  # ship the 45 most urgent lines
                    idx = idx[np.argsort(-need[idx])][:45]
                if idx.size:
                    inv_seq += 1
                    ref = f"TRF-{inv_seq:06d}"
                    cost = wh_cost[w_id][idx]
                    old_val = st_stock[s_id][idx] * st_cost[s_id][idx]
                    wh_stock[w_id][idx] -= need[idx]
                    st_stock[s_id][idx] += need[idx]
                    st_cost[s_id][idx] = np.where(st_stock[s_id][idx] > 0,
                                                  (old_val + need[idx] * cost) / np.maximum(st_stock[s_id][idx], 1e-9),
                                                  st_cost[s_id][idx])
                    out_wh[w_id][idx] += need[idx]
                    recv_st[s_id][idx] += need[idx]
                    for j, i in enumerate(idx):
                        mov_rows.append(dict(Movement_Date=str(wk.date()), Movement_Type="Transfer Out", Location_ID=w_id,
                                             SKU_ID=prod.SKU_ID.iloc[i], Qty_Cartons=-int(need[i]),
                                             Value_USD=-round(float(need[i] * cost[j]), 2), Reference=ref))
                        mov_rows.append(dict(Movement_Date=str(wk.date()), Movement_Type="Transfer In", Location_ID=s_id,
                                             SKU_ID=prod.SKU_ID.iloc[i], Qty_Cartons=int(need[i]),
                                             Value_USD=round(float(need[i] * cost[j]), 2), Reference=ref))

                # --- weekly POS sales (limited by what is on the shelf) ---
                want = weekly * rng.lognormal(0, 0.12, n_sku)
                sold = np.minimum(np.floor(want), st_stock[s_id])
                sidx = np.nonzero(sold)[0]
                if sidx.size > 90:                                 # weekly POS summary keeps the 90 best sellers
                    sidx = sidx[np.argsort(-sold[sidx])][:90]
                if sidx.size == 0:
                    continue
                unit_cost = st_cost[s_id][sidx]
                retail = np.round(unit_cost * prod.Retail_Markup.to_numpy()[sidx] * price_drift[m]
                                  / np.maximum(prod.Units_Per_Carton.to_numpy()[sidx], 1), 2)
                promo = np.where(rng.random(sidx.size) < 0.14, rng.uniform(0.05, 0.22, sidx.size), 0)
                units = sold[sidx] * prod.Units_Per_Carton.to_numpy()[sidx]
                gross = units * retail
                disc = np.round(gross * promo, 2)
                st_stock[s_id][sidx] -= sold[sidx]
                out_st[s_id][sidx] += sold[sidx]
                doc = f"POS-{s_id}-{week_end.strftime('%Y%m%d')}"
                for j, i in enumerate(sidx):
                    sales_rows.append(dict(
                        Date=str(week_end.date()), Channel="Supermarket", Country_Code=st.Country_Code,
                        Country=st.Country, Location_ID=s_id, Customer_ID="", Customer_Segment="Retail Consumer",
                        SKU_ID=prod.SKU_ID.iloc[i], Document_No=doc,
                        Qty_Cartons=int(sold[i]), Qty_Units=int(units[j]),
                        Gross_Sales_USD=round(float(gross[j]), 2), Discount_USD=float(disc[j]),
                        Net_Sales_USD=round(float(gross[j] - disc[j]), 2),
                        COGS_USD=round(float(sold[i] * unit_cost[j]), 2)))
                    mov_rows.append(dict(Movement_Date=str(week_end.date()), Movement_Type="Sales Issue", Location_ID=s_id,
                                         SKU_ID=prod.SKU_ID.iloc[i], Qty_Cartons=-int(sold[i]),
                                         Value_USD=-round(float(sold[i] * unit_cost[j]), 2), Reference=doc))

        # ---------------------------------------------------------- 6. B2B sales (invoices)
        for c, wh in zip(whs.Country_Code, whs.Location_ID):
            cust_c = np.nonzero((cust_country == c) & (cust.Onboard_Month.to_numpy() <= m))[0]
            if cust_c.size == 0:
                continue
            demand_c = b2b_country[c]
            weight = cust_size[cust_c] * np.where(cust.Status.to_numpy()[cust_c] == "Active", 1.0, 0.25)
            weight = weight / weight.sum()
            n_orders = rng.poisson(seg_freq[cust_c] * np.where(cust.Status.to_numpy()[cust_c] == "Active", 1.0, 0.3))
            for k, ci in enumerate(cust_c):
                for _ in range(int(n_orders[k])):
                    n_lines = max(1, int(rng.poisson(seg_lines[ci])))
                    pick = rng.choice(n_sku, size=n_lines, replace=False,
                                      p=(demand_c + 1e-9) / (demand_c.sum() + 1e-9 * n_sku))
                    inv_date = day_in_month(m, rng, 1, 28)
                    inv_seq += 1
                    inv_no = f"INV-{inv_seq:06d}"
                    cust_month_cartons = demand_c.sum() * weight[k]
                    per_line = cust_month_cartons / max(1, int(n_orders[k])) / n_lines
                    for i in pick:
                        want = max(1, int(round(per_line * rng.lognormal(0, 0.45))))
                        qty = int(min(want, wh_stock[wh][i]))
                        if qty <= 0:
                            continue
                        unit_cost = wh_cost[wh][i]
                        price = unit_cost * prod.B2B_Markup.iloc[i] * price_drift[m] * seg_price[ci]
                        gross = qty * price
                        disc = gross * (rng.uniform(0.0, 0.05) if rng.random() < 0.45 else 0)
                        wh_stock[wh][i] -= qty
                        out_wh[wh][i] += qty
                        sales_rows.append(dict(
                            Date=str(inv_date.date()), Channel="B2B", Country_Code=c, Country=COUNTRIES[c]["name"],
                            Location_ID=wh, Customer_ID=cust.Customer_ID.iloc[ci], Customer_Segment=cust_seg[ci],
                            SKU_ID=prod.SKU_ID.iloc[i], Document_No=inv_no, Qty_Cartons=qty,
                            Qty_Units=int(qty * prod.Units_Per_Carton.iloc[i]),
                            Gross_Sales_USD=round(float(gross), 2), Discount_USD=round(float(disc), 2),
                            Net_Sales_USD=round(float(gross - disc), 2), COGS_USD=round(float(qty * unit_cost), 2)))
                        mov_rows.append(dict(Movement_Date=str(inv_date.date()), Movement_Type="Sales Issue",
                                             Location_ID=wh, SKU_ID=prod.SKU_ID.iloc[i], Qty_Cartons=-qty,
                                             Value_USD=-round(float(qty * unit_cost), 2), Reference=inv_no))

        # ---------------------------------------------------------- 7. shrinkage / damage + month-end snapshot
        for store_id, stock in list(wh_stock.items()) + list(st_stock.items()):
            is_wh = store_id in wh_stock
            # damage, expiry and count differences: a quarter of the lines are hit in any month,
            # drawn from a Poisson so small positions also lose the occasional carton
            loss_rate = rng.uniform(0.0005, 0.0025)
            hit = rng.random(len(stock)) < 0.25
            loss = np.minimum(rng.poisson(np.where(hit, stock * loss_rate * 4.0, 0.0)), stock).astype(float)
            if loss.sum() > 0:
                idx = np.nonzero(loss)[0]
                cost_arr = wh_cost[store_id] if is_wh else st_cost[store_id]
                stock[idx] -= loss[idx]
                (adj_wh if is_wh else adj_st)[store_id][idx] -= loss[idx]
                for i in idx:
                    mov_rows.append(dict(Movement_Date=str(month_end.date()), Movement_Type="Adjustment / Damage",
                                         Location_ID=store_id, SKU_ID=prod.SKU_ID.iloc[i], Qty_Cartons=-int(loss[i]),
                                         Value_USD=-round(float(loss[i] * cost_arr[i]), 2), Reference="ADJ"))

        for loc_id in list(wh_stock) + list(st_stock):
            is_wh = loc_id in wh_stock
            stock = wh_stock[loc_id] if is_wh else st_stock[loc_id]
            cost_arr = wh_cost[loc_id] if is_wh else st_cost[loc_id]
            opening = (opening_wh if is_wh else opening_st)[loc_id]
            recv = (recv_wh if is_wh else recv_st)[loc_id]
            out = (out_wh if is_wh else out_st)[loc_id]
            adj = (adj_wh if is_wh else adj_st)[loc_id]
            live = (stock > 0) | (opening > 0) | (recv > 0) | (out > 0)
            for i in np.nonzero(live)[0]:
                snap_rows.append(dict(
                    Snapshot_Date=str(month_end.date()), Location_ID=loc_id, SKU_ID=prod.SKU_ID.iloc[i],
                    Opening_Cartons=int(opening[i]), Receipts_Cartons=int(recv[i]), Issues_Cartons=int(out[i]),
                    Adjustment_Cartons=int(adj[i]), Closing_Cartons=int(stock[i]),
                    Unit_Cost_USD=round(float(cost_arr[i]), 3),
                    Stock_Value_USD=round(float(stock[i] * cost_arr[i]), 2)))

        if (m + 1) % 12 == 0:
            log(f"  simulated {m + 1} months | sales lines {len(sales_rows):,} | POs {po_seq}")

    # ------------------------------------------------------------------ frames
    log("Assembling tables ...")
    sales = pd.DataFrame(sales_rows)
    sales["Transaction_Type"] = "Sale"
    # credit notes: a small share of B2B lines is returned (damage / short-dated stock) in the following weeks
    b2b = sales.index[(sales.Channel == "B2B")].to_numpy()
    take = rng.choice(b2b, size=int(len(b2b) * 0.012), replace=False)
    cn = sales.loc[take].copy()
    cn["Date"] = (pd.to_datetime(cn.Date) + pd.to_timedelta(rng.integers(5, 26, len(cn)), unit="D")).dt.strftime("%Y-%m-%d")
    cn = cn[cn.Date <= str(END.date())]
    for col in ["Qty_Cartons", "Qty_Units", "Gross_Sales_USD", "Discount_USD", "Net_Sales_USD", "COGS_USD"]:
        cn[col] = -cn[col]
    cn["Transaction_Type"] = "Credit Note"
    cn["Document_No"] = ["CRN-" + d.split("-")[-1] for d in cn.Document_No]
    sales = pd.concat([sales, cn], ignore_index=True)
    sales["Gross_Margin_USD"] = (sales.Net_Sales_USD - sales.COGS_USD).round(2)
    snap = pd.DataFrame(snap_rows)
    mov = pd.DataFrame(mov_rows)
    po = pd.DataFrame(po_rows)
    pol = pd.DataFrame(po_line_rows)
    ship = pd.DataFrame(ship_rows)
    costs = pd.DataFrame(cost_rows)
    grn = pd.DataFrame(grn_rows)

    # days of cover & status on the stock snapshot (3-month average issues)
    snap["m"] = month_index(snap.Snapshot_Date)
    snap = snap.sort_values(["Location_ID", "SKU_ID", "m"])
    grp = snap.groupby(["Location_ID", "SKU_ID"], sort=False).Issues_Cartons
    avg3 = grp.transform(lambda s: s.rolling(3, min_periods=1).mean())
    daily = avg3 / 30.0
    snap["Days_of_Cover"] = np.where(daily > 0, (snap.Closing_Cartons / daily).round(1), np.where(snap.Closing_Cartons > 0, 999, 0))
    # stock norms differ by location type: a warehouse holds months of import cover, a shop holds weeks
    is_wh = snap.Location_ID.str.startswith("WH")
    low = np.where(is_wh, 30, 7)
    over = np.where(is_wh, 100, 30)
    slow = np.where(is_wh, 150, 60)
    snap["Stock_Status"] = np.select(
        [snap.Closing_Cartons <= 0, avg3 <= 0, snap.Days_of_Cover > slow, snap.Days_of_Cover > over, snap.Days_of_Cover < low],
        ["Out of Stock", "Non-moving", "Slow-moving", "Overstock", "Low Stock"], "Healthy")
    snap["Stock_Norm_Days"] = np.where(is_wh, "30-100 days", "7-30 days")
    snap["Status_Order"] = snap.Stock_Status.map({"Out of Stock": 1, "Low Stock": 2, "Healthy": 3, "Overstock": 4,
                                                  "Slow-moving": 5, "Non-moving": 6})
    snap = snap.drop(columns="m")

    # sales budget: last year actual + plan growth, by country x channel x month
    s2 = sales.copy()
    s2["m"] = month_index(s2.Date)
    act = s2.pivot_table(index=["Country_Code", "Channel"], columns="m", values="Net_Sales_USD", aggfunc="sum").fillna(0)
    tgt_rows = []
    for (c, ch), row in act.iterrows():
        for m in range(N_MONTHS):
            base_v = row.get(m - 12, np.nan)
            if np.isnan(base_v) or base_v <= 0:
                base_v = row.get(m, 0) * rng.uniform(0.98, 1.08)
                growth = 1.0
            else:
                growth = 1 + rng.normal(0.10, 0.03)
            tgt_rows.append(dict(Month_Date=str(MONTH_START[m].date()), Country_Code=c, Country=COUNTRIES[c]["name"],
                                 Channel=ch, Target_USD=round(float(base_v * growth) / 100) * 100))
    target = pd.DataFrame(tgt_rows)

    # calendar
    # the calendar runs one financial year past the data so shipments still at sea have a month to arrive in
    dates = pd.date_range(START, END + pd.DateOffset(years=1), freq="D")
    dim_date = pd.DataFrame({"Date": dates.strftime("%Y-%m-%d"), "Year": dates.year, "Month_No": dates.month,
                             "Month": dates.strftime("%b"), "Month_Year": dates.strftime("%b-%Y"),
                             "Month_Year_Sort": dates.year * 100 + dates.month,
                             "Month_Start": dates.to_period("M").start_time.strftime("%Y-%m-%d"),
                             "Quarter": "Q" + dates.quarter.astype(str)})
    fy_start = np.where(dates.month >= 4, dates.year, dates.year - 1)
    dim_date["Financial_Year"] = [f"FY {y}-{str(y + 1)[2:]}" for y in fy_start]
    dim_date["FY_Quarter"] = "Q" + (((dates.month - 4) % 12) // 3 + 1).astype(str)
    dim_date["FY_Month_No"] = ((dates.month - 4) % 12) + 1

    # ------------------------------------------------------------------ write
    log("Writing files ...")
    out = ROOT
    dim_date.to_csv(out / "dim_date.csv", index=False)
    prod_out = prod[["SKU_ID", "SKU_Code", "Product_Name", "Brand", "Category", "Sub_Category", "Variant", "Pack_Size",
                     "Units_Per_Carton", "CBM_Per_Carton", "Duty_Rate_Pct", "Shelf_Life_Days", "Origin_Country",
                     "Supplier_ID", "Status"]]
    prod_out.to_csv(out / "dim_product.csv", index=False)
    sup.drop(columns=["Delay_Mean", "Delay_SD", "Fill_Rate"]).to_csv(out / "dim_supplier.csv", index=False)
    loc.drop(columns=["Open_Month"]).to_csv(out / "dim_location.csv", index=False)
    cust.drop(columns=["Size_Index", "Onboard_Month"]).to_csv(out / "dim_customer.csv", index=False)
    po.to_csv(out / "fact_purchase_orders.csv", index=False)
    pol.to_csv(out / "fact_po_lines.csv", index=False)
    ship.to_csv(out / "fact_shipments.csv", index=False)
    costs.to_csv(out / "fact_landed_cost.csv", index=False)
    grn.to_csv(out / "fact_goods_receipts.csv", index=False)
    mov[mov.Movement_Type != "Sales Issue"].to_csv(out / "fact_stock_movements.csv.gz", index=False, compression="gzip")
    snap.to_csv(out / "fact_stock_snapshot.csv.gz", index=False, compression="gzip")
    sales.to_csv(out / "fact_sales.csv.gz", index=False, compression="gzip")
    target.to_csv(out / "fact_sales_target.csv", index=False)

    notes = {
        "company": COMPANY, "seed": args.seed, "period": "2021-04-01 to 2026-03-31", "currency": "USD",
        "row_counts": {"sales": len(sales), "stock_movements": int((mov.Movement_Type != "Sales Issue").sum()), "stock_snapshot": len(snap),
                       "po_lines": len(pol), "purchase_orders": len(po), "shipments": len(ship),
                       "goods_receipts": len(grn), "landed_cost_rows": len(costs), "targets": len(target),
                       "products": len(prod), "customers": len(cust), "locations": len(loc), "suppliers": len(sup)},
        "planted_patterns": [
            "Container freight crisis 2021-22: freight index ~3x, landed-cost uplift peaks, then normalises through 2023",
            "Red Sea disruption Jan-2024 to Sep-2024: +12 transit days from Asia, freight index rises again",
            "Food commodity price spike FY 2022-23 (cost index +26%), selling prices follow with a lag -> margin dip",
            "Supplier tiers: tier 'c' suppliers (Ningbo, Guangzhou, Delhi Rice) deliver late and short -> low OTIF",
            "New stores: Kairaba Avenue (Dec-2021), Bo Town (Jan-2023), Paynesville (Oct-2023) ramp up over ~6 months",
            "Ramadan / Eid demand lift on staples and beverages in the weeks before Eid each year",
            "December festive peak on confectionery, biscuits, evaporated milk and cooking oil",
            "Delisted SKUs late in the period leave slow / non-moving stock behind",
            "Shipments still in transit or at port at 31-Mar-2026 (open import pipeline)",
        ],
    }
    (out / "_generation_notes.json").write_text(json.dumps(notes, indent=2), encoding="utf-8")
    log(f"Done in {time.time() - t0:.0f}s")
    for k, v in notes["row_counts"].items():
        log(f"  {k:20s} {v:>9,}")


if __name__ == "__main__":
    main()
