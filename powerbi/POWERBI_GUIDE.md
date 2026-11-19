# Building the Power BI report

The data model and the measures are prepared. The report file is built in Power BI Desktop by
following these steps. Nothing here has been run in Power BI, so use the check values at the end
to confirm that each measure works.

Regenerate the data files with `python scripts/run_m4.py` after the earlier milestones.

## 1. Load the data

In Power BI Desktop choose Get data > Text/CSV and load every file in `powerbi/data/`:

* `DimDate.csv`
* `DimSector.csv`
* `FactCommitments.csv`
* `FactMonthlySector.csv`
* `FactPlanComparison.csv`
* `FactSensitivity.csv`
* `FactStrictStorage.csv`
* `FactVariance.csv`

Then check the column types in Power Query. `date`, `month` and the `month` column of
`FactCommitments` are Date. Columns ending in `_mmcf`, `_musd`, `_percent`, `_price` and
`price_per_mcf` are Decimal number. `shortfall_months` is Whole number. Everything else is Text.

## 2. Build the relationships (Model view)

| From (one side) | To (many side) |
|---|---|
| `DimDate[date]` | `FactMonthlySector[month]` |
| `DimDate[date]` | `FactVariance[month]` |
| `DimDate[date]` | `FactCommitments[month]` |
| `DimSector[sector]` | `FactMonthlySector[sector]` |

`FactPlanComparison`, `FactStrictStorage` and `FactSensitivity` stand alone. Their `plan` and
`plan_year` columns are used directly on visuals and slicers.

Select `DimDate`, then Table tools > Mark as date table, and choose the `date` column. The
monthly facts match the first day of each month, so they connect to those dates.

## 3. Add the measures

Open `powerbi/measures.dax`. For each measure choose Modeling > New measure and paste it. If a
measure shows an error, check that the table and column names in the formula match the loaded
tables exactly. Put them in a table called `Measures` if you want them grouped.

## 4. Check the measures

With no filters on a card visual, each measure should show this value:

| Measure | Value |
|---|---|
| Forecast Revenue ($M) | 13,724.9 |
| Actual Revenue ($M) | 13,595.6 |
| Revenue Variance ($M) | -129.3 |
| Weather Effect ($M) | -275.1 |
| Volume Effect ($M) | -654.5 |
| Mix Effect ($M) | 57.7 |
| Price Effect ($M) | 742.5 |
| Variance Check ($M) | 0.0 |
| Rule of Thumb Cost ($M) | 5,077.4 |
| Optimised Cost ($M) | 5,053.3 |
| Hindsight Cost ($M) | 5,007.5 |
| Optimised Saving vs Rule ($M) | 24.1 |
| Strict Storage Optimised Saving vs Rule ($M) | -8.9 |

## 5. Suggested pages

**Forecast vs actual.** Cards for Forecast Revenue, Actual Revenue, Revenue Variance and Revenue
Variance %. A clustered column chart with `DimDate[period]` on the axis and Forecast Revenue and
Actual Revenue as values. Slicers for `DimDate[plan_year]` and `DimSector[sector_label]`.

**Why it differed.** A stacked column chart with `DimDate[period]` on the axis and Weather Effect,
Volume Effect, Mix Effect and Price Effect as values. A card for Variance Check, which should be
0. A matrix with the periods as rows and the same four measures as values.

**Supply plans.** A clustered bar chart with `FactPlanComparison[plan]` on the axis and Plan Cost
as the value, and a `plan_year` slicer. Cards for Optimised Saving vs Rule, Gap to Hindsight
Closed % and Strict Storage Optimised Saving vs Rule. Show the last card next to the first one,
because the saving changes sign under the strict storage rule.

**Forecast error.** A line chart with `FactSensitivity[forecast_error_percent]` on the axis,
Sensitivity Cost as the value and `FactSensitivity[plan]` as the legend. A second line chart for
Sensitivity Service Level %.

## 6. Save and share

Save the report as `powerbi/forecast_to_decision.pbix`. The repository ignores `*.pbix` files, so
remove that line from `.gitignore` if you want to commit it. Take a screenshot of the first page
and save it as `docs/figures/dashboard.png`, then add it to the README.
