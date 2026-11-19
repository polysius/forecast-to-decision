# Building the Power BI report

The data model and the measures are prepared. The report file is built in Power BI Desktop by
following these steps. Nothing here has been run in Power BI, so use the check values in step 4
to confirm that every measure works.

Regenerate the data files with `python scripts/run_m4.py` after the earlier milestones.

## 1. Load the data

Before loading, open File > Options and settings > Options > Data Load and untick Autodetect new
relationships after data is loaded. Power BI would otherwise link columns that share a name, such
as `month`, and some of those links would be wrong.

Choose Get data > Text/CSV and load every file in `powerbi/data/`:

* `DimDate.csv`
* `DimPlanYear.csv`
* `DimSector.csv`
* `FactCommitments.csv`
* `FactMonthlySector.csv`
* `FactPlanComparison.csv`
* `FactSensitivity.csv`
* `FactStrictStorage.csv`
* `FactVariance.csv`

Then check the column types in Power Query. The column `date` and every column named `month`
are Date, except `month_name`, which is Text. `year` and `month_number` are
Whole number. Columns ending in `_mmcf`, `_musd`,
`_percent`, `_price`, and `price_per_mcf`, and the column `shortfall_months`, are Decimal number.
Everything else is Text. Do not make `shortfall_months` a Whole number, because the sensitivity
table holds averages such as 1.67.

## 2. Build the relationships (Model view)

If Power BI created any relationships by itself, delete them first. Then create these, each
from the one side to the many side with a single filter direction:

| From (one side) | To (many side) |
|---|---|
| `DimPlanYear[plan_year]` | `DimDate[plan_year]` |
| `DimPlanYear[plan_year]` | `FactPlanComparison[plan_year]` |
| `DimPlanYear[plan_year]` | `FactStrictStorage[plan_year]` |
| `DimDate[date]` | `FactMonthlySector[month]` |
| `DimDate[date]` | `FactVariance[month]` |
| `DimDate[date]` | `FactCommitments[month]` |
| `DimSector[sector]` | `FactMonthlySector[sector]` |

Use `DimPlanYear[plan_year]` for every plan year slicer. It filters the dates, the monthly facts
and the plan tables together, so cards that compare the main and strict storage results always
cover the same plan years. `FactCommitments` is filtered through its month, so it has no direct
link to `DimPlanYear`: a second path would make the model ambiguous. `FactSensitivity` is not
connected, because its numbers are averages over the plan years.

Select `DimDate`, then Table tools > Mark as date table, and choose the `date` column. The
monthly facts match the first day of each month, so they connect to those dates.

## 3. Add the measures

Open `powerbi/measures.dax`. For each measure choose Modeling > New measure and paste it. If a
measure shows an error, check that the table and column names in the formula match the loaded
tables exactly. Put them in a table called `Measures` if you want them grouped.

Format the measures that end in `%` as Percentage with one decimal place. They return fractions.
On card visuals set Display units to None, so values show as 13,724.9 and not 13.72K.

## 4. Check the measures

With no filters on a card visual, each measure should show this value:

| Measure | Value |
|---|---|
| Forecast Revenue ($M) | 13,724.9 |
| Actual Revenue ($M) | 13,595.6 |
| Revenue Variance ($M) | -129.3 |
| Revenue Variance % | -0.9% |
| Weather Effect ($M) | -275.1 |
| Volume Effect ($M) | -654.5 |
| Mix Effect ($M) | 57.7 |
| Price Effect ($M) | 742.5 |
| Explained Variance ($M) | -129.3 |
| Variance Check ($M) | 0.0 |
| Forecast Volume (MMcf) | 707,588 |
| Weather Adjusted Forecast Volume (MMcf) | 691,825 |
| Actual Volume (MMcf) | 658,788 |
| Volume Error % | -6.9% |
| Average Monthly Miss % | 13.3% |
| Plan Cost ($M) | 15,138.3 |
| Rule of Thumb Cost ($M) | 5,077.4 |
| Optimised Cost ($M) | 5,053.3 |
| Hindsight Cost ($M) | 5,007.5 |
| Optimised Saving vs Rule ($M) | 24.1 |
| Gap to Hindsight Closed % | 34.5% |
| Service Level % | 100.0% |
| Strict Storage Optimised Saving vs Rule ($M) | -8.9 |
| Sensitivity Cost ($M) | 1,868.7 |
| Sensitivity Service Level % | 99.8% |

## 5. Suggested pages

**Forecast vs actual.** Cards for Forecast Revenue, Actual Revenue, Revenue Variance and Revenue
Variance %. A clustered column chart with `DimDate[period]` on the axis and Forecast Revenue and
Actual Revenue as values. Slicers for `DimPlanYear[plan_year]` and `DimSector[sector_label]`.

**Why it differed.** A stacked column chart with `DimDate[period]` on the axis and Weather Effect,
Volume Effect, Mix Effect and Price Effect as values. A card for Variance Check, which should be
0. A matrix with the periods as rows and the same four measures as values.

**Supply plans.** A clustered bar chart with `FactPlanComparison[plan]` on the axis and Plan Cost
as the value, and a `DimPlanYear[plan_year]` slicer. Cards for Optimised Saving vs Rule, Gap to
Hindsight Closed % and Strict Storage Optimised Saving vs Rule. Show the last card next to the
first one, because the saving changes sign under the strict storage rule.

**Forecast error.** A line chart with `FactSensitivity[forecast_error_percent]` on the axis,
Sensitivity Cost as the value and `FactSensitivity[plan]` as the legend. A second line chart for
Sensitivity Service Level %.

## 6. Save and share

Save the report as `powerbi/forecast_to_decision.pbix`. The repository ignores `*.pbix` files, so
remove that line from `.gitignore` if you want to commit it. Take a screenshot of the first page
and save it as `docs/figures/dashboard.png`, then add it to the README.
