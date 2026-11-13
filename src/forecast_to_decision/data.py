"""Load the committed raw extracts and build the monthly modelling table."""

from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"

HDD_BASE_TEMP_F = 65.0
# A month with fewer observed days than this is treated as incomplete.
MAX_MISSING_DAYS_PER_MONTH = 3

SECTORS = ("residential", "commercial")


def load_monthly_gas(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Monthly deliveries (MMcf) and prices ($ per Mcf) indexed by month start."""
    return pd.read_csv(raw_dir / "ma_gas_monthly.csv", index_col="month", parse_dates=True)


def load_customers(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Annual customer counts by sector, indexed by year."""
    return pd.read_csv(raw_dir / "ma_customers_annual.csv", index_col="year")


def load_daily_temps(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Daily max and min temperature in degrees Fahrenheit at Boston Logan."""
    return pd.read_csv(raw_dir / "boston_daily_temps.csv", index_col="date", parse_dates=True)


def monthly_degree_days(daily: pd.DataFrame, base_temp: float = HDD_BASE_TEMP_F) -> pd.DataFrame:
    """Sum daily heating degree days into months.

    Daily mean temperature is (max + min) / 2, the usual HDD convention.
    Days with no reading are filled with the mean HDD of the days that were
    observed in that month, so a few gaps do not bias the monthly total low.
    Months missing more than MAX_MISSING_DAYS_PER_MONTH days are dropped.
    """
    mean_temp = (daily["tmax_f"] + daily["tmin_f"]) / 2
    daily_hdd = (base_temp - mean_temp).clip(lower=0)

    grouped = daily_hdd.groupby(daily_hdd.index.to_period("M"))
    observed_days = grouped.count()
    mean_hdd = grouped.mean()
    days_in_month = observed_days.index.days_in_month

    table = pd.DataFrame(
        {
            "hdd": mean_hdd * days_in_month,
            "missing_days": days_in_month - observed_days,
        }
    )
    table = table[table["missing_days"] <= MAX_MISSING_DAYS_PER_MONTH]
    table.index = table.index.to_timestamp()
    table.index.name = "month"
    return table


def build_dataset(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """One row per month with deliveries, prices, weather, and customer counts.

    Customer counts are annual, so every month takes its calendar year's count.
    Years beyond the last published count are left empty.
    """
    gas = load_monthly_gas(raw_dir)
    weather = monthly_degree_days(load_daily_temps(raw_dir))
    customers = load_customers(raw_dir)

    table = gas.join(weather[["hdd"]], how="inner")
    table["days_in_month"] = table.index.days_in_month
    for column in customers.columns:
        table[column] = table.index.year.map(customers[column])

    sector_columns = [f"{sector}_mmcf" for sector in SECTORS]
    return table.dropna(subset=sector_columns + ["hdd"])
