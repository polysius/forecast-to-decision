"""Write the Power BI data model: star schema CSV files and a guide to build the report.

Power BI Desktop cannot be run here, so the report itself (the .pbix file) is built by
following the guide. The measures live in powerbi/measures.dax. A test checks that every
table and column they use exists in the files written here, and that the guide gives a
check value for every measure.
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
    plan_year = pd.DataFrame({"plan_year": list(dict.fromkeys(tables.calendar["plan_year"]))})
    return {
        "DimDate": tables.calendar,
        "DimSector": sector,
        "DimPlanYear": plan_year,
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
    """Every measure with the value it should show with no filters applied.

    Percent measures are fractions in the model, so they are shown here as percentages
    for a card formatted as Percentage with one decimal place.
    """
    variance = tables.monthly_variance
    sector = tables.monthly_sector
    forecast = sector["forecast_revenue_musd"].sum()
    actual = sector["actual_revenue_musd"].sum()
    plans, strict, sensitivity = tables.plan_comparison, tables.strict_storage, tables.sensitivity

    forecast_volume = sector["forecast_mmcf"].sum()
    adjusted_volume = sector["weather_adjusted_forecast_mmcf"].sum()
    actual_volume = sector["actual_mmcf"].sum()
    monthly_total = sector.groupby("month")[["forecast_mmcf", "actual_mmcf"]].sum()
    monthly_miss = (
        (monthly_total["actual_mmcf"] - monthly_total["forecast_mmcf"]).abs()
        / monthly_total["actual_mmcf"]
    ).mean()

    rule, optimised, hindsight = (_plan_total(plans, plan) for plan in (RULE, OPTIMISED, HINDSIGHT))
    saving = rule - optimised
    strict_saving = _plan_total(strict, RULE) - _plan_total(strict, OPTIMISED)
    effects = {name: variance[f"{name}_musd"].sum() for name in ("weather", "volume", "mix", "price")}

    return [
        ("Forecast Revenue ($M)", f"{forecast:,.1f}"),
        ("Actual Revenue ($M)", f"{actual:,.1f}"),
        ("Revenue Variance ($M)", f"{actual - forecast:,.1f}"),
        ("Revenue Variance %", f"{(actual - forecast) / forecast:.1%}"),
        ("Weather Effect ($M)", f"{effects['weather']:,.1f}"),
        ("Volume Effect ($M)", f"{effects['volume']:,.1f}"),
        ("Mix Effect ($M)", f"{effects['mix']:,.1f}"),
        ("Price Effect ($M)", f"{effects['price']:,.1f}"),
        ("Explained Variance ($M)", f"{sum(effects.values()):,.1f}"),
        ("Variance Check ($M)", "0.0"),
        ("Forecast Volume (MMcf)", f"{forecast_volume:,.0f}"),
        ("Weather Adjusted Forecast Volume (MMcf)", f"{adjusted_volume:,.0f}"),
        ("Actual Volume (MMcf)", f"{actual_volume:,.0f}"),
        ("Volume Error %", f"{(actual_volume - forecast_volume) / forecast_volume:.1%}"),
        ("Average Monthly Miss %", f"{monthly_miss:.1%}"),
        ("Plan Cost ($M)", f"{plans['cost_musd'].sum():,.1f}"),
        ("Rule of Thumb Cost ($M)", f"{rule:,.1f}"),
        ("Optimised Cost ($M)", f"{optimised:,.1f}"),
        ("Hindsight Cost ($M)", f"{hindsight:,.1f}"),
        ("Optimised Saving vs Rule ($M)", f"{saving:,.1f}"),
        ("Gap to Hindsight Closed %", f"{saving / (rule - hindsight):.1%}"),
        ("Service Level %", f"{plans['served_percent'].mean() / 100:.1%}"),
        ("Strict Storage Optimised Saving vs Rule ($M)", f"{strict_saving:,.1f}"),
        ("Sensitivity Cost ($M)", f"{sensitivity['cost_musd'].mean():,.1f}"),
        ("Sensitivity Service Level %", f"{sensitivity['served_percent'].mean() / 100:.1%}"),
    ]


def guide_text(tables: ReportingTables) -> str:
    """The step by step guide for building the Power BI report from these files."""
    checks = "\n".join(f"| {name} | {value} |" for name, value in check_values(tables))
    names = sorted(f"{key}.csv" for key in powerbi_tables(tables))
    files = "\n".join(f"* `{name}`" for name in names)
    return f"""# Building the Power BI report

The data model and the measures are prepared. The report file is built in Power BI Desktop by
following these steps. Nothing here has been run in Power BI, so use the check values in step 4
to confirm that every measure works.

Regenerate the data files with `python scripts/run_m4.py` after the earlier milestones.

## 1. Load the data

Before loading, open File > Options and settings > Options > Data Load and untick Autodetect new
relationships after data is loaded. Power BI would otherwise link columns that share a name, such
as `month`, and some of those links would be wrong.

Choose Get data > Text/CSV and load every file in `powerbi/data/`:

{files}

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
{checks}

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
"""
