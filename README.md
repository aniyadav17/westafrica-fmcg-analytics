# West Africa FMCG Import & Distribution Analytics — Power BI

Three connected Power BI reports for **Atlantic Foods Trading Ltd.**, a fictional food & beverage importer and
distributor operating in **Sierra Leone, the Gambia and Liberia**. The company buys from suppliers in Europe, China,
India, the USA and France, brings the goods in by sea container, and sells them two ways: **B2B** (wholesalers,
retailers, HORECA and institutions) and through its own **Atlantic Mart supermarkets** (4 in Sierra Leone, 2 in the
Gambia, 2 in Liberia).

| Report | Question it answers |
|---|---|
| **Procurement Analytics** | What do imported goods really cost once freight, duty and clearing are added, and which suppliers deliver on time and in full? |
| **Inventory Analytics** | Where is the stock, how long will it last, and how much working capital is stuck in slow-moving lines? |
| **Sales Analytics** | How are the three markets and two channels performing against budget, last year and on margin? |

Everything in this repository is generated from one deterministic Python script — no confidential data is used.

---

## The business in numbers (FY 2025-26, year ended 31-Mar-2026)

| | |
|---|---|
| Net sales | **$23.12 m** (B2B $15.35 m · supermarkets $7.77 m) |
| By market | Sierra Leone $10.04 m · Liberia $7.82 m · Gambia $5.27 m |
| Achievement vs budget | **96.8%** ($23.89 m budget) |
| Gross margin | **25.0%** at landed cost |
| Imports landed | **$18.21 m** across 393 shipments / 444 containers |
| Supplier OTIF | **58.8%**, average lead time **64 days** PO to warehouse, fill rate **99.6%** |
| Landed-cost uplift | **27.2%** over FOB in FY 2025-26 (duty, ocean freight, insurance, clearing, inland and demurrage) |
| Closing stock 31-Mar-2026 | **$3.80 m** — healthy $1.94 m, overstock $0.92 m, slow & non-moving $0.77 m |

Five financial years are included, so every report supports year-on-year comparison:

| FY | Net sales | Gross margin % |
|---|---|---|
| 2021-22 | $16.33 m | 20.2% |
| 2022-23 | $17.59 m | 19.4% |
| 2023-24 | $20.12 m | 22.4% |
| 2024-25 | $21.69 m | 24.1% |
| 2025-26 | $23.12 m | 25.0% |

---

## What is deliberately planted in the data

The dataset is not random noise — it contains the events an analyst would be asked to explain in an interview:

- **Container freight crisis 2021-22** — the freight index runs at roughly 3× normal, landed-cost uplift peaks and then
  normalises through 2023.
- **Red Sea disruption, Jan–Sep 2024** — +12 transit days from Asia and a second freight spike.
- **Food commodity price spike FY 2022-23** — costs rise 26%, selling prices follow with a lag, so gross margin dips to
  19.4% before recovering.
- **Weak suppliers** — tier "c" suppliers (Ningbo, Guangzhou, Delhi Rice) deliver late and short, which shows up as low
  OTIF and low fill rate.
- **Store openings** — Kairaba Avenue (Dec-2021), Bo Town (Jan-2023) and Paynesville (Oct-2023) each ramp up over about
  six months.
- **Seasonality** — Ramadan / Eid lift on staples and beverages, December festive peak on confectionery, biscuits,
  evaporated milk and cooking oil.
- **Delisted SKUs** leave slow and non-moving stock behind, visible on the Stock Health page.
- **An open import pipeline at 31-Mar-2026** — shipments still in transit or sitting at the port.

---

## Data model

Each report has its **own star-schema semantic model**, built for the questions on its pages.

```
Procurement                      Inventory                        Sales
  Date  Supplier  Product          Date  Product  Location          Date  Product  Location
  Location                                                          Customer  Channel  Market
    |                                 |                                 |
  Purchase Orders -- PO Lines      Stock                             Sales
  Shipments                        Movements                         Target
  Landed Cost                      Goods Receipts
  Goods Receipts
```

- Single-direction relationships only, no bi-directional filters and no ambiguous paths.
- Landed-cost rows join through their **shipment**, so the cost build-up always ties back to the landed value of the
  same containers.
- `Date` is a marked date table covering 01-Apr-2021 to 31-Mar-2027, with an **April–March financial year**; it runs a
  year past the transactions so shipments still at sea have an arrival month.
- All measures live in a dedicated `KPI` table and are grouped into display folders.
- Shipments that have not arrived yet are placed on the calendar by their expected arrival, so the open pipeline is
  still visible inside a period filter.

## Pages

**Procurement Analytics** — Procurement Overview · Supplier Performance · Landed Cost · Shipment Tracker
**Inventory Analytics** — Inventory Overview · Stock by Location & Product · Movements & Turnover · Stock Health
**Sales Analytics** — Sales Overview · Market & Channel · Supermarket Performance · B2B Customers · Product & Margin

Every page follows the same layout: a title band, six KPI cards, two charts and one or two detail tables.

---

## How to open the reports

1. **Generate the data** (once, about a minute):

   ```bash
   python data/generate_data.py
   ```

   This writes the CSV extracts into `data/` (about 11 MB; they are not committed).

2. Open any of the three projects in **Power BI Desktop** (December 2023 or later, with *Power BI Project (.pbip)
   save* enabled):

   ```
   powerbi/Procurement Analytics.pbip
   powerbi/Inventory Analytics.pbip
   powerbi/Sales Analytics.pbip
   ```

3. Go to **Home → Transform data → Edit parameters** and set `DataFolder` to your own `...\westafrica-fmcg-analytics\data\`
   — include the trailing backslash. Then click **Refresh**.

Each report opens filtered to **FY 2025-26** — the filter sits on each page, so you can change it per page in the
Filters pane. The **Shipment Tracker** is deliberately left unfiltered, with its own year and status slicers, because
open shipments belong to no completed period.

## Rebuilding the reports from code

The models and report pages are generated, not hand-clicked, so a change to a measure or a page is one script run:

```bash
python tools/build_powerbi.py          # writes the three .pbip projects
python tools/validate_pbip.py          # checks fields, measures and relationships
```

`tools/pbip_lib.py` writes the TMDL semantic model and the PBIR report pages; `tools/build_powerbi.py` holds the
definition of the three projects (tables, relationships, DAX and page layouts).

## Repository layout

```
data/       generate_data.py — the simulation; the CSV extracts land here
docs/       data dictionary and KPI definitions
powerbi/    the three .pbip projects (semantic model + report, as files)
tools/      pbip_lib.py, build_powerbi.py, validate_pbip.py
screenshots/
```

## Documentation

- [Data dictionary](docs/data-dictionary.md) — every table and column
- [KPI definitions](docs/kpi-definitions.md) — what each measure means and how it is calculated

## Notes

- Currency is **USD** throughout; there is no multi-currency conversion.
- Costing is weighted-average landed cost, so gross margin is a true landed-cost margin.
- All companies, suppliers, customers and stores are fictional.
