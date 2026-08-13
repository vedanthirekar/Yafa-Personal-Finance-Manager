# YAFA — Power BI

A checked-in Power BI Project (PBIP). The semantic model is **TMDL**, which is
plain text — so it diffs, reviews, and merges like source code, unlike a binary
`.pbix`.

```
powerbi/
├── YAFA.pbip                      open this in Power BI Desktop
├── sql/star_schema.sql            the seven views the model reads
├── YAFA.SemanticModel/
│   └── definition/
│       ├── model.tmdl             parameters + relationships
│       └── tables/*.tmdl          6 tables, 20 DAX measures
└── YAFA.Report/
    └── definition/pages/          3 pages (visuals: see "Building the report")
```

## Setup

**1. Create the views** (once, and again after any schema change):

```sh
docker compose exec -T postgres psql -U yafa -d yafa < powerbi/sql/star_schema.sql
```

**2. Install the PostgreSQL connector.** Power BI needs Npgsql to reach
Postgres. Power BI Desktop prompts with a download link the first time you
refresh; install it and restart Desktop.

**3. Open `YAFA.pbip`** in Power BI Desktop.

**4. Point it at your database.** *Home → Transform data → Edit parameters*:

| Parameter | Default | Notes |
|---|---|---|
| `ServerParam` | `localhost:55432` | Host **and port**, colon-separated. 55432 is what compose publishes — a local PostgreSQL install usually owns 5432 and 5433 already. |
| `DatabaseParam` | `yafa` | |

**5. Refresh.** Credentials are Database auth, `yafa` / `yafa` for the compose
defaults. On the encryption prompt choose **not** encrypted — the compose
Postgres doesn't serve TLS.

**6. Mark the date table** (only needed if Desktop doesn't detect it): select
`dim_date` → *Table tools → Mark as date table* → `date_key`. Time-intelligence
measures (`MoM Change %`, `Spend YTD`) return wrong results without this.

## The model

Star schema. Three dimensions filter three facts, one direction only —
bidirectional filtering would create ambiguous paths and make totals depend on
visual layout.

```
        dim_date ──┐
                   ├──> fct_transactions   (grain: one transaction)
    dim_category ──┤──> fct_monthly_spend  (grain: category-month)
                   │──> budget_variance    (grain: category-month)
    dim_merchant ──┘
```

**Why views instead of the base tables.** `vw_powerbi_fct_transactions` uses
`DISTINCT ON` to attach only the *latest* prediction per transaction. Joining
`transactions` to `category_predictions` directly fans the fact table out to one
row per prediction and silently multiplies every total — the classic star-schema
fan trap. (Verified: base rows 2923 = view rows 2923, sums identical.)

### Measures

All 20 live on `fct_transactions`.

| Group | Measures |
|---|---|
| Spend | `Total Spend`, `Transaction Count`, `Avg Transaction`, `Spend Prior Month`, `MoM Change %`, `Spend YTD`, `Category Share %`, `Rolling 3M Avg` |
| Categorization | `Avg Categorization Confidence`, `Auto-Categorized Count`, `Categorization Acceptance %`, `Low Confidence Count` |
| Voice | `Voice Entry Count`, `Voice Entry %` |
| Budget | `Total Budget`, `Budget Variance`, `Budget Utilization %`, `Over Budget Flag` |

Two deliberate choices worth knowing:

- **`Avg Categorization Confidence` filters out nulls.** Manually-entered rows
  never went through the model. Counting them as zero would drag the average
  down for a reason unrelated to model quality.
- **`Category Share %` uses `ALLSELECTED`, not `ALL`.** The share is relative to
  the current slicer selection, so it still totals 100% when the user filters.

## Building the report

The three pages ship **empty by design**. Power BI's visual-container JSON is
undocumented and version-sensitive; hand-writing it produces files that fail to
open in subtly different ways across Desktop releases. The semantic model is the
part that carries the analytical work, and it is complete — dropping fields onto
a canvas takes about ten minutes.

**Page 1 — Spend Overview**
- Cards: `Total Spend`, `Transaction Count`, `Avg Transaction`, `MoM Change %`
- Line chart: X `dim_date[year_month]`, Y `Total Spend`, plus `Rolling 3M Avg`
- Donut: Legend `dim_category[category_name]`, Values `Total Spend`
- Bar: Y `dim_merchant[merchant_name]`, X `Total Spend`, Top-N 10 by `Total Spend`
- Slicers: `dim_date[year]`, `dim_category[category_name]`

**Page 2 — Forecast & Budget**
- Line: X `dim_date[month_start]`, Y `Total Spend` — add the API's projection
  from `GET /powerbi/fct_forecast` as a second query if you want the forecast
  band on the same axis (`series_type` splits actual from forecast)
- Clustered bar: Y `dim_category[category_name]`, X `Total Spend` and `Total Budget`
- Table: `budget_variance` — category, actual, budget, variance, `pct_of_budget`
- Conditional formatting: background on variance driven by `Over Budget Flag`
- Gauge: `Budget Utilization %`, max 1

**Page 3 — Semantic Categorization**
- Cards: `Avg Categorization Confidence`, `Categorization Acceptance %`,
  `Auto-Categorized Count`, `Low Confidence Count`
- Stacked column: X `dim_date[year_month]`, Legend
  `fct_transactions[confidence_band]`, Y `Transaction Count`
- Matrix: rows `predicted_category`, columns `category_key`, values
  `Transaction Count` — this is the confusion matrix, and where the
  Tourism/Subscription weakness shows up
- Table: low-confidence transactions — description, predicted category,
  confidence, corrected_to
- Card: `Voice Entry %`

## Refresh

Import mode: the data is copied at refresh. Re-refresh after adding
transactions. For live data, switch the partitions in each `*.tmdl` from
`mode: import` to `mode: directQuery` — DirectQuery is more finicky about
credentials and doesn't support every DAX pattern, so Import is the default
here.

## Alternative: no database connection

Every view is also exposed as a REST feed for Power BI's Web connector — see
`/powerbi/*` in the API (`fct_transactions`, `dim_category`, `dim_merchant`,
`dim_date`, `fct_forecast`, `fct_anomaly`), each with `?format=csv`. Same column
names, so the measures work unchanged. Requires a bearer token in the request
header; refresh is slower than a direct connection.
