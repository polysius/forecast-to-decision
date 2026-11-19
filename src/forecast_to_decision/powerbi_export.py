"""Write the Power BI data model: star schema CSV files and a guide to build the report.

Power BI Desktop cannot be run here, so the report itself (the .pbix file) is built by
following the guide. The measures live in powerbi/measures.dax. A test checks that every
table and column they use exists in the files written here.
"""

from pathlib import Path

import pandas as pd

from forecast_to_decision.data import SECTORS
from forecast_to_decision.datasets import ReportingTables

SECTOR_LABELS = {"residential": "Residential", "commercial": "Commercial"}
RULE, OPTIMISED, HINDSIGHT = "Rule of thumb", "Optimised plan", "Perfect hindsight"


def powerbi_tables(tables: ReportingTables) -> dict[str, pd.DataFrame]:
    """The tables of the model, named as they should appear in Power BI."""
    sector = pd.DataFrame(
        {"sector": list(SECTORS), "sector_label": [SECTOR_LABELS[name] for name in SECTORS]}
    )
    return {
        "DimDate": tables.calendar,
        "DimSector": sector,
        "FactMonthlySector": tables.monthly_sector.drop(columns="key"),
        "FactVariance": tables.monthly_variance,
        "FactPlanComparison": tables.plan_comparison,
        "FactStrictStorage": tables.strict_storage,
        "FactSensitivity": tables.sensitivity,
        "FactCommitments": tables.commitments,
    }


def write_powerbi_data(tables: ReportingTables, directory: Path) -> list[str]:
    """Write one CSV per table into `directory` and return the file names."""
    directory.mkdir(parents=True, exist_ok=True)
    names = []
    for name, frame in powerbi_tables(tables).items():
        frame.to_csv(directory / f"{name}.csv", index=False, date_format="%Y-%m-%d")
        names.append(f"{name}.csv")
    return names


def _plan_total(frame: pd.DataFrame, plan: str) -> float:
    return float(frame.loc[frame["plan"] == plan, "cost_musd"].sum())


def check_values(tables: ReportingTables) -> list[tuple[str, str]]:
    """Measure names and the value each should show with no filters applied."""
    variance = tables.monthly_variance
    sector = tables.monthly_sector
    forecast = sector["forecast_revenue_musd"].sum()
    actual = sector["actual_revenue_musd"].sum()
    plans, strict = tables.plan_comparison, tables.strict_storage
    saving = _plan_total(plans, RULE) - _plan_total(plans, OPTIMISED)
    strict_saving = _plan_total(strict, RULE) - _plan_total(strict, OPTIMISED)
    return [
        ("Forecast Revenue ($M)", f"{forecast:,.1f}"),
        ("Actual Revenue ($M)", f"{actual:,.1f}"),
        ("Revenue Variance ($M)", f"{actual - forecast:,.1f}"),
        ("Weather Effect ($M)", f"{variance['weather_musd'].sum():,.1f}"),
        ("Volume Effect ($M)", f"{variance['volume_musd'].sum():,.1f}"),
        ("Mix Effect ($M)", f"{variance['mix_musd'].sum():,.1f}"),
        ("Price Effect ($M)", f"{variance['price_musd'].sum():,.1f}"),
        ("Variance Check ($M)", "0.0"),
        ("Rule of Thumb Cost ($M)", f"{_plan_total(plans, RULE):,.1f}"),
        ("Optimised Cost ($M)", f"{_plan_total(plans, OPTIMISED):,.1f}"),
        ("Hindsight Cost ($M)", f"{_plan_total(plans, HINDSIGHT):,.1f}"),
        ("Optimised Saving vs Rule ($M)", f"{saving:,.1f}"),
        ("Strict Storage Optimised Saving vs Rule ($M)", f"{strict_saving:,.1f}"),
    ]


def guide_text(tables: ReportingTables) -> str:
    """The step by step guide for building the Power BI report from these files."""
    checks = "\n".join(f"| {name} | {value} |" for name, value in check_values(tables))
    files = "\n".join(f"* `{name}`" for name in sorted(f"{key}.csv" for key in powerbi_tables(tables)))
    return f"""# Building the Power BI report

The data model and the measures are prepared. The report file is built in Power BI Desktop by
following these steps. Nothing here has been run in Power BI, so use the check values at the end
to confirm that each measure works.

Regenerate the data files with `python scripts/run_m4.py` after the earlier milestones.

## 1. Load the data

In Power BI Desktop choose Get data > Text/CSV and load every file in `powerbi/data/`:

{files}

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
{checks}

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
"""
