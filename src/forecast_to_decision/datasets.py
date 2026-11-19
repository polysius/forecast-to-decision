"""The tables behind the workbook, the Power BI model and the business summary.

Everything here is built from the committed outputs of M1 to M3, using the M3
variance functions, so the reports show the same numbers as VARIANCE.md.
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from forecast_to_decision.data import SECTORS, load_monthly_gas
from forecast_to_decision.variance import (
    MMCF_PRICE_TO_MUSD,
    MONTHS_PER_PERIOD,
    budget_prices,
    decompose_revenue_variance,
    sector_frame,
    sum_by_period,
)

RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"

SEASONS = {
    9: "Autumn", 10: "Autumn", 11: "Autumn",
    12: "Winter", 1: "Winter", 2: "Winter",
    3: "Spring", 4: "Spring", 5: "Spring",
    6: "Summer", 7: "Summer", 8: "Summer",
}  # fmt: skip


def load_m1_column(name: str, results_dir: Path = RESULTS_DIR) -> pd.DataFrame:
    """One column of the M1 holdout files, for every sector (MMcf)."""
    return sector_frame(
        {
            sector: pd.read_csv(
                results_dir / f"m1_{sector}_holdout.csv", index_col=0, parse_dates=True
            )[name]
            for sector in SECTORS
        }
    )


def load_m1_volumes(
    results_dir: Path = RESULTS_DIR,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Forecast, weather adjusted forecast and actual deliveries by month and sector (MMcf)."""
    return (
        load_m1_column("regression_normal_weather_mmcf", results_dir),
        load_m1_column("regression_actual_weather_mmcf", results_dir),
        load_m1_column("actual_mmcf", results_dir),
    )


def load_price_history() -> pd.DataFrame:
    """Residential and commercial prices ($/Mcf) for every month in the EIA series."""
    gas = load_monthly_gas()
    return sector_frame(
        {"residential": gas["residential_price"], "commercial": gas["commercial_price"]}
    )


def period_labels(months: pd.DatetimeIndex) -> pd.Series:
    """Label each month with its three month period, such as '2023-09 to 2023-11'."""
    labels = sum_by_period(pd.DataFrame({"n": 1}, index=months)).index
    return pd.Series(
        [labels[position // MONTHS_PER_PERIOD] for position in range(len(months))], index=months
    )


def plan_year_labels(months: pd.DatetimeIndex) -> pd.Series:
    """Label each month with its twelve month plan year, such as '2023-09 to 2024-08'."""
    months_per_year = 12
    labels = []
    for start in range(0, len(months), months_per_year):
        block = months[start : start + months_per_year]
        labels += [f"{block[0]:%Y-%m} to {block[-1]:%Y-%m}"] * len(block)
    return pd.Series(labels, index=months)


def monthly_sector_table(results_dir: Path = RESULTS_DIR) -> pd.DataFrame:
    """One row per month and sector with volumes, prices and revenue."""
    forecast, weather_adjusted, actual = load_m1_volumes(results_dir)
    history = load_price_history()
    months = forecast.index
    budget = budget_prices(history).loc[months]
    charged = history.loc[months]
    periods = period_labels(months)
    plan_years = plan_year_labels(months)

    rows = []
    for sector in SECTORS:
        rows.append(
            pd.DataFrame(
                {
                    "month": months,
                    "plan_year": plan_years.to_numpy(),
                    "period": periods.to_numpy(),
                    "season": [SEASONS[month.month] for month in months],
                    "sector": sector,
                    "forecast_mmcf": forecast[sector].to_numpy(),
                    "weather_adjusted_forecast_mmcf": weather_adjusted[sector].to_numpy(),
                    "actual_mmcf": actual[sector].to_numpy(),
                    "budget_price": budget[sector].to_numpy(),
                    "actual_price": charged[sector].to_numpy(),
                }
            )
        )
    table = pd.concat(rows, ignore_index=True)
    table["forecast_revenue_musd"] = (
        table["forecast_mmcf"] * table["budget_price"] * MMCF_PRICE_TO_MUSD
    )
    table["actual_revenue_musd"] = (
        table["actual_mmcf"] * table["actual_price"] * MMCF_PRICE_TO_MUSD
    )
    table["key"] = table["month"].dt.strftime("%Y-%m") + "|" + table["sector"]
    return table.sort_values(["month", "sector"], ignore_index=True)


def monthly_variance_table(results_dir: Path = RESULTS_DIR) -> pd.DataFrame:
    """The M3 variance effects by month, labelled with period and season."""
    forecast, weather_adjusted, actual = load_m1_volumes(results_dir)
    history = load_price_history()
    months = forecast.index
    monthly = decompose_revenue_variance(
        forecast, weather_adjusted, actual, budget_prices(history).loc[months], history.loc[months]
    )
    table = monthly.drop(columns="explained").add_suffix("_musd")
    table.insert(0, "season", [SEASONS[month.month] for month in months])
    table.insert(0, "period", period_labels(months).to_numpy())
    table.insert(0, "plan_year", plan_year_labels(months).to_numpy())
    table.index.name = "month"
    return table.reset_index()


def calendar_table(months: pd.DatetimeIndex) -> pd.DataFrame:
    """A daily date table covering the analysed months, for the Power BI model."""
    days = pd.date_range(months[0], months[-1] + pd.offsets.MonthEnd(0), freq="D")
    month_start = days.to_period("M").to_timestamp()
    periods = period_labels(months)
    plan_years = plan_year_labels(months)
    return pd.DataFrame(
        {
            "date": days,
            "month": month_start,
            "year": days.year,
            "month_number": days.month,
            "month_name": days.strftime("%b"),
            "season": [SEASONS[day.month] for day in days],
            "period": periods.loc[month_start].to_numpy(),
            "plan_year": plan_years.loc[month_start].to_numpy(),
        }
    )


@dataclass(frozen=True)
class ReportingTables:
    monthly_sector: pd.DataFrame
    monthly_variance: pd.DataFrame
    calendar: pd.DataFrame
    plan_comparison: pd.DataFrame
    sensitivity: pd.DataFrame
    commitments: pd.DataFrame
    strict_storage: pd.DataFrame


def build_reporting_tables(results_dir: Path = RESULTS_DIR) -> ReportingTables:
    monthly_sector = monthly_sector_table(results_dir)
    months = pd.DatetimeIndex(sorted(monthly_sector["month"].unique()))
    commitments = pd.read_csv(results_dir / "m2_commitments.csv")
    commitments["month"] = pd.to_datetime(commitments["month"])
    return ReportingTables(
        monthly_sector=monthly_sector,
        monthly_variance=monthly_variance_table(results_dir),
        calendar=calendar_table(months),
        plan_comparison=pd.read_csv(results_dir / "m2_plan_comparison.csv"),
        sensitivity=pd.read_csv(results_dir / "m2_sensitivity.csv"),
        commitments=commitments,
        strict_storage=pd.read_csv(results_dir / "m2_strict_storage.csv"),
    )
