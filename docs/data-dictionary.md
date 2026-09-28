# Data dictionary

All files are written by `data/generate_data.py` into `data/`. Column names use underscores in the CSV; Power Query
replaces them with spaces, so `FOB_Value_USD` becomes `FOB Value USD` in the reports.

Transactions cover **01-Apr-2021 to 31-Mar-2026**; the calendar runs one financial year further, to 31-Mar-2027,
so shipments still at sea at the cut-off have a month to arrive in. Currency: **USD**. Seed: **42**, so regenerating
gives byte-identical files.

| File | Rows | Grain |
|---|---|---|
| `dim_date.csv` | 2,191 | one day |
| `dim_product.csv` | 132 | one SKU |
| `dim_supplier.csv` | 17 | one supplier |
| `dim_location.csv` | 11 | one warehouse or supermarket |
| `dim_customer.csv` | 218 | one B2B customer |
| `fact_purchase_orders.csv` | 1,835 | one purchase order |
| `fact_po_lines.csv` | 13,447 | one PO line (PO × SKU) |
| `fact_shipments.csv` | 1,835 | one shipment (one PO ships as one shipment) |
| `fact_landed_cost.csv` | 11,159 | one cost component of one shipment |
| `fact_goods_receipts.csv` | 12,907 | one GRN line (receipt × SKU) |
| `fact_stock_movements.csv.gz` | 180,097 | one stock movement |
| `fact_stock_snapshot.csv.gz` | 59,353 | month-end × location × SKU |
| `fact_sales.csv.gz` | 240,976 | one sales line |
| `fact_sales_target.csv` | 360 | month × country × channel |

---

## Dimensions

### dim_date
| Column | Type | Notes |
|---|---|---|
| `Date` | date | primary key, marked date table |
| `Year`, `Month_No`, `Month`, `Month_Year`, `Month_Year_Sort`, `Month_Start`, `Quarter` | | calendar attributes; `Month` sorts by `Month_No`, `Month_Year` by `Month_Year_Sort` |
| `Financial_Year` | text | April–March, e.g. `FY 2025-26` |
| `FY_Quarter`, `FY_Month_No` | | financial quarter (Apr–Jun = Q1) and month position in the FY |

### dim_product
| Column | Notes |
|---|---|
| `SKU_ID`, `SKU_Code`, `Product_Name` | key and names |
| `Brand`, `Category`, `Sub_Category`, `Variant`, `Pack_Size` | product hierarchy: Category › Sub-category › Brand › SKU |
| `Units_Per_Carton`, `CBM_Per_Carton` | pack data; CBM drives container utilisation |
| `Duty_Rate_Pct` | import duty rate applied to the CIF value |
| `Shelf_Life_Days` | drives expiry write-offs |
| `Origin_Country`, `Supplier_ID` | where the SKU is bought from |
| `Status` | `Active` or `Delisted` |

Categories: Beverages, Dairy, Staples, Cooking Essentials, Snacks & Confectionery, Canned Foods, Baby & Health.

### dim_supplier
| Column | Notes |
|---|---|
| `Supplier_ID`, `Supplier_Name`, `Origin_Country` | Netherlands (3), France (3), China (4), India (4), USA (3) |
| `Region` | `Europe`, `Asia`, `Americas` |
| `Tier` | internal rating: `a` reliable, `b` average, `c` weak (drives delay and short shipment) |
| `Payment_Terms` | `LC at sight`, `LC 30 days`, `LC 60 days`, `TT 30/45/60 days` |
| `Port_of_Loading`, `Incoterm` | `FOB` or `CIF` |

### dim_location
| Column | Notes |
|---|---|
| `Location_ID`, `Location_Name`, `Location_Type` | `Warehouse` (3) or `Supermarket` (8) |
| `Country_Code`, `Country`, `City` | SL Sierra Leone · GM Gambia · LR Liberia |
| `Opening_Date` | three stores open during the period |
| `Warehouse_ID` | the warehouse that supplies a store |

### dim_customer
`Customer_ID`, `Customer_Name`, `Segment` (Wholesaler, Retailer / Mini-mart, HORECA, Institution / NGO),
`Country_Code`, `Country`, `City`, `Credit_Days`, `Status`.

---

## Procurement facts

### fact_purchase_orders — one row per PO
`PO_No`, `PO_Date`, `Supplier_ID`, `Supplier_Name`, `Origin_Country`, `Incoterm`, `Payment_Terms`, `Warehouse_ID`,
`Country_Code`, `Country`, `Lines`, `Qty_Ordered_Cartons`, `FOB_Value_USD`, `Containers`, `CBM`, `Shipment_No`,
`Status` (`In Transit` · `At Port / Clearing` · `Received`).

### fact_po_lines — one row per PO × SKU
`PO_No`, `PO_Date`, `Supplier_ID`, `Warehouse_ID`, `SKU_ID`, `Qty_Ordered_Cartons`, `FOB_Unit_Cost_USD`,
`FOB_Value_USD`, `Landed_Unit_Cost_USD` (FOB plus its share of freight, duty and clearing),
`Qty_Received_Cartons`, `Status`.

### fact_shipments — one row per container shipment
| Column | Notes |
|---|---|
| `Shipment_No`, `PO_No`, `Supplier_ID`, `Supplier_Name`, `Origin_Country` | |
| `Port_of_Loading` | Rotterdam, Le Havre, Shanghai, Nhava Sheva, Houston |
| `Port_of_Discharge` | Freetown (Queen Elizabeth II Quay), Banjul Port, Freeport of Monrovia |
| `Containers`, `Container_Type`, `CBM`, `Qty_Cartons` | 40ft containers, 58 CBM usable |
| `ETD`, `ATD`, `ETA`, `ATA` | planned and actual sailing and arrival |
| `Customs_Cleared_Date`, `Warehouse_Receipt_Date` | |
| `Transit_Days`, `Clearance_Days`, `Total_Lead_Time_Days` | PO date to warehouse receipt |
| `Delay_Days` | actual arrival minus promised ETA |
| `On_Time`, `In_Full`, `OTIF` | booleans; on time = arrived within 3 days of ETA, in full = at least 95% of the ordered cartons received |
| `FOB_Value_USD`, `Landed_Value_USD`, `Landed_Cost_Uplift_Pct` | |
| `Status` | `In Transit` · `At Port / Clearing` · `Received` |

**Open shipments**: an event that has not happened by the cut-off is left empty. A shipment still at sea therefore has
no `ATA`, `Customs_Cleared_Date`, `Warehouse_Receipt_Date`, `Transit_Days`, `Delay_Days` or service flags — exactly what
an ERP extract looks like mid-voyage. 60 shipments are in transit and 15 are at the port on 31-Mar-2026.

The report adds a calculated `Arrival Date` = actual arrival, or the expected arrival while the shipment is still open,
so open shipments still sit on the calendar.

### fact_landed_cost — cost build-up per shipment
`Shipment_No`, `PO_No`, `Cost_Date`, `Warehouse_ID`, `Country`, `Origin_Country`, `Cost_Component`, `Amount_USD`.

Components: `FOB / Goods`, `Ocean Freight`, `Insurance`, `Customs Duty`, `Clearing & Port Charges`,
`Inland Transport`, `Demurrage`. In the report these rows are related to `Shipments`, not to the calendar, so each
component sits in the same period as the shipment it belongs to. Freight is allocated to SKUs pro-rata on CBM, duty on the CIF value at the SKU's own
duty rate; the rest is spread pro-rata on value.

### fact_goods_receipts — GRN lines
`GRN_No`, `GRN_Date`, `PO_No`, `Shipment_No`, `Warehouse_ID`, `SKU_ID`, `Qty_Ordered_Cartons`,
`Qty_Received_Cartons`, `Landed_Unit_Cost_USD`, `Landed_Value_USD`.

---

## Inventory facts

### fact_stock_movements
`Movement_Date`, `Movement_Type`, `Location_ID`, `SKU_ID`, `Qty_Cartons`, `Value_USD`, `Reference`.

Movement types: `Goods Receipt` (import into a warehouse), `Transfer Out` / `Transfer In` (warehouse to store),
`Adjustment / Damage` (damage, expiry and stock-count differences). Sales issues are not repeated here — they are in
the sales fact.

### fact_stock_snapshot — month-end position
`Snapshot_Date`, `Location_ID`, `SKU_ID`, `Opening_Cartons`, `Receipts_Cartons`, `Issues_Cartons`,
`Adjustment_Cartons`, `Closing_Cartons`, `Unit_Cost_USD` (weighted-average landed cost), `Stock_Value_USD`,
`Days_of_Cover`, `Stock_Status`, `Stock_Norm_Days`, `Status_Order`.

`Stock_Status` is calculated against the norm for the location type — warehouses 30–100 days, supermarkets 7–30 days:

| Status | Meaning |
|---|---|
| `Out of Stock` | closing quantity is zero |
| `Non-moving` | stock on hand, but no issues in the last three months |
| `Slow-moving` | cover above 150 days (warehouse) or 60 days (store) |
| `Overstock` | cover above 100 days (warehouse) or 30 days (store) |
| `Low Stock` | cover below 30 days (warehouse) or 7 days (store) |
| `Healthy` | within the norm |

The statuses are evaluated in that order, so `Out of Stock` wins over `Non-moving`, and `Slow-moving` over `Overstock`.
Days of cover uses the average issues of the last three months.

---

## Sales facts

### fact_sales
| Column | Notes |
|---|---|
| `Date`, `Channel` | `B2B` (daily invoices) or `Supermarket` (weekly POS summary per store) |
| `Country_Code`, `Country`, `Location_ID` | the warehouse or store that supplied the sale |
| `Customer_ID`, `Customer_Segment` | blank for supermarket sales |
| `SKU_ID`, `Document_No` | invoice number, or store-week reference |
| `Qty_Cartons`, `Qty_Units` | |
| `Gross_Sales_USD`, `Discount_USD`, `Net_Sales_USD` | |
| `COGS_USD`, `Gross_Margin_USD` | at weighted-average landed cost |
| `Transaction_Type` | `Sale` or `Credit Note` (returns carry negative values) |

### fact_sales_target
`Month_Date`, `Country_Code`, `Country`, `Channel`, `Target_USD` — the budget, set per month, country and channel.
