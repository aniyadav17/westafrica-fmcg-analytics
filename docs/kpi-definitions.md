# KPI definitions

Every measure lives in the `KPI` table of its report and is grouped into display folders. Measures ending in
`(USD k)` or `(USD m)` are display versions of the same number, scaled for KPI cards and chart labels.

The `Date` table is marked as a date table, so all time intelligence (`SAMEPERIODLASTYEAR`) works on it. The financial
year runs **April to March**.

---

## Procurement Analytics

### 1. Purchasing
| Measure | Definition | DAX |
|---|---|---|
| PO Value | Value of purchase orders raised, at FOB — before freight and duty | `SUM('Purchase Orders'[FOB Value USD])` |
| PO Count | Number of purchase orders | `DISTINCTCOUNT('Purchase Orders'[PO No])` |
| Containers | 40ft containers booked | `SUM('Purchase Orders'[Containers])` |
| Cartons Ordered / Received | Order and receipt quantity | `SUM('PO Lines'[Qty Ordered Cartons])`, `SUM('Goods Receipts'[Qty Received Cartons])` |
| Suppliers Used | Suppliers ordered from in the period | `DISTINCTCOUNT('Purchase Orders'[Supplier ID])` |
| Avg FOB per Carton | Purchase price per carton | `DIVIDE(SUM('PO Lines'[FOB Value USD]), SUM('PO Lines'[Qty Ordered Cartons]))` |
| Avg Landed per Carton | Cost per carton delivered into the warehouse | `SUMX` of quantity × landed unit cost, divided by quantity |

### 2. Landed Cost
| Measure | Definition |
|---|---|
| Import Cost | All cost components of the shipments, including the goods |
| Goods / Freight / Duty / Clearing / Inland / Demurrage Cost | `Import Cost` filtered to one `Cost Component` with `KEEPFILTERS` |
| | The cost rows are joined to the model **through their shipment**, not through their own cost date, so `Import Cost` ties exactly to `Landed Value` and `Goods Cost` ties to the FOB value of the same shipments |
| Landed Value | Total cost of the imported goods delivered into the warehouse |
| **Landed Cost Uplift %** | `(Landed Value − FOB Value) ÷ FOB Value` — how much freight, duty and clearing add on top of the price of the goods. Around 30% in a normal year, far higher during the 2021-22 freight crisis |
| Freight % of Goods, Duty % of Goods | Each cost block as a share of the goods value |
| Cost per Container | `Landed Value ÷ Containers` |
| Import Growth % | Landed value vs the same period last year, blank when there is no comparable period |

### 3. Supplier Performance
| Measure | Definition |
|---|---|
| Shipments | Number of container shipments |
| On-Time % | Share of **arrived** shipments that arrived within **3 days** of the promised ETA |
| In-Full % | Share of **received** shipments where at least **95%** of the ordered cartons arrived |
| **OTIF %** | On time *and* in full, on received shipments — the headline supplier service measure |
| Avg Lead Time (days) | PO date to warehouse receipt |
| Avg Transit Days | Actual sailing to actual arrival |
| Avg Clearance Days | Port arrival to customs clearance |
| Avg Delay (days) | Actual arrival minus promised ETA; negative means early |
| Fill Rate % | Cartons received ÷ cartons ordered **on the same goods receipt**, so a PO raised in one period and received in the next cannot push it over 100% |
| Open Shipments / Open Pipeline Value | Shipments not yet received, and the value of the goods in them. Both are a *position*, so they use `REMOVEFILTERS('Date')` and ignore the period filter |

> A shipment that has not arrived has no actual arrival date, so it is placed on the calendar by its **expected**
> arrival. Service measures are calculated only on shipments that have actually arrived or been received, so a big
> order still at sea cannot drag OTIF down before it is late.

---

## Inventory Analytics

### 1. Stock
| Measure | Definition | Note |
|---|---|---|
| Stock Value | `SUM(Stock[Stock Value USD])` | month-end value; used for trends |
| **Closing Stock Value** | Stock at the **month-end of the selected period** | `CALCULATE([Stock Value], REMOVEFILTERS('Date'), Stock[Snapshot Date] = EOMONTH(MAX('Date'[Date]), 0))` — a point-in-time measure, so it does not add months together |
| Closing Cartons, Stock Lines, SKUs Stocked | Same as-of logic, on quantity and counts | |
| Issues Value / Receipts Value | Cost value of stock issued out and received in | `SUMX` of quantity × unit cost |
| **Days of Cover** | `Closing Stock Value ÷ (average daily issue value of the last three months)` | answers "how long will this stock last?" |
| **Stock Turns (12m)** | Issues of the last 12 months ÷ average month-end stock over those months | |

### 2. Health
| Measure | Definition |
|---|---|
| Out of Stock Lines / % | Location–SKU lines with no stock at the month-end |
| Low Stock Lines, Healthy Lines, Healthy % | Lines by status; norms are 30–100 days of cover for a warehouse, 7–30 days for a store |
| Overstock Value | Value of lines above the upper norm |
| **Slow & Non-moving Value / %** | Value of lines with more than 150 days of cover (60 in a store) or no movement at all — the working capital that is stuck |
| Share of Stock Value % | A row's share of the visible total (`ALLSELECTED`) |

### 3. Movements
| Measure | Definition |
|---|---|
| Movement Value | `SUM(Movements[Value USD])` |
| Goods Received Value / Inbound Cartons | Imports received into the warehouses |
| Transfers to Stores | Warehouse-to-store transfers, at cost |
| **Shrinkage Value / %** | Damage, expiry and stock-count adjustments, shown as a positive loss and as a share of issues |

---

## Sales Analytics

### 1. Sales
| Measure | Definition |
|---|---|
| **Net Sales** | Sales after discount and credit notes — the headline number |
| Gross Sales, Discount, Discount % | Before discount, the discount itself, and discount as a share of gross |
| Cartons Sold, Units Sold | Volume |
| Credit Notes, Return % | Returns, and returns as a share of gross sales |
| B2B Sales, Supermarket Sales | Net sales of each channel |
| Net Sales LY | Same period last year (`SAMEPERIODLASTYEAR`) |
| **Growth %** | `(Net Sales − Net Sales LY) ÷ Net Sales LY`, blank when there is no last year |
| Target | The monthly budget by country and channel |
| **Achievement %** | `Net Sales ÷ Target` |
| Variance to Target | `Net Sales − Target`, blank where no budget exists |
| Contribution % | A row's share of the visible total |

### 2. Margin
| Measure | Definition |
|---|---|
| COGS | Cost of goods sold at weighted-average **landed** cost |
| Gross Margin, **Gross Margin %** | `Net Sales − COGS`, and as a share of net sales |
| Margin per Carton | Gross margin ÷ cartons sold |

### 3. Customers & Stores
| Measure | Definition |
|---|---|
| Invoices | Distinct B2B invoice numbers, excluding credit notes |
| Avg Invoice Value | B2B sales ÷ invoices |
| Lines per Invoice | Average number of SKUs on a B2B invoice |
| Customers Billed, Active SKUs | Distinct customers and SKUs sold. Customers uses `DISTINCTCOUNTNOBLANK`, because supermarket rows carry no customer |
| Stores Trading, Sales per Store | Supermarkets that traded in the period, and average sales per store |

---

## Conventions used throughout

- **`KEEPFILTERS` on every hard-coded filter**, so a slicer on the same column is respected rather than overridden.
- **Point-in-time stock**: inventory measures take the snapshot at the month-end of the selected period instead of
  summing months.
- **Blank, not zero**: growth and variance return blank where there is no comparison, so charts do not show a
  misleading −100%.
- **Display measures**: `... (USD k)` and `... (USD m)` exist only so cards and data labels stay readable; the
  underlying measures are unscaled.
- **Channel pages**: the Supermarket and B2B pages carry a page-level channel filter, so a margin or return rate on
  those pages is always the channel's own number.
