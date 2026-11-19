import numpy as np
import pandas as pd
import pytest

from forecast_to_decision.model import Spec, add_lagged_weather, fit_sector_model
from forecast_to_decision.scenarios import (
    SectorFit,
    plan_year_months,
    weather_year_scenarios,
)

SPEC = Spec(start_year=2000, base_temp_f=65.0, month_effects=False)


def make_fit(sector: str, weather_slope: float, table: pd.DataFrame) -> SectorFit:
    table = table.copy()
    table[f"{sector}_mmcf"] = 100 + weather_slope * table["hdd"]
    return SectorFit(table, fit_sector_model(table, sector, SPEC), SPEC)


@pytest.fixture
def training_table() -> pd.DataFrame:
    """Twelve full September to August years of synthetic weather."""
    months = pd.date_range("2005-01-01", "2016-12-01", freq="MS")
    rng = np.random.default_rng(1)
    seasonal_hdd = 600 * (1 + np.cos(2 * np.pi * (months.month - 1) / 12)) / 2
    table = pd.DataFrame({"hdd": seasonal_hdd + rng.uniform(-40, 40, len(months))}, index=months)
    table["days_in_month"] = months.days_in_month
    return add_lagged_weather(table)


def test_plan_years_are_consecutive_blocks_of_twelve_months():
    holdout = pd.date_range("2023-09-01", periods=24, freq="MS")

    first, second = plan_year_months(holdout)

    assert first[0] == pd.Timestamp("2023-09-01")
    assert second[0] == pd.Timestamp("2024-09-01")
    assert len(first) == len(second) == 12


def test_a_partial_plan_year_is_rejected():
    with pytest.raises(ValueError, match="whole number"):
        plan_year_months(pd.date_range("2023-09-01", periods=20, freq="MS"))


def test_one_scenario_per_complete_weather_year(training_table):
    fits = {"residential": make_fit("residential", 2.0, training_table)}
    plan_months = pd.date_range("2017-09-01", periods=12, freq="MS")

    scenarios = weather_year_scenarios(fits, plan_months, weather_years=5)

    assert scenarios.shape == (5, 12)


def test_colder_weather_years_give_higher_winter_demand(training_table):
    fits = {"residential": make_fit("residential", 2.0, training_table)}
    plan_months = pd.date_range("2017-09-01", periods=12, freq="MS")

    scenarios = weather_year_scenarios(fits, plan_months, weather_years=5)

    weather_by_year = [
        training_table.loc[f"{year}-09-01":f"{year + 1}-08-01", "hdd"].sum()
        for year in range(2011, 2016)
    ]
    coldest, warmest = np.argmax(weather_by_year), np.argmin(weather_by_year)
    assert scenarios[coldest].sum() > scenarios[warmest].sum()


def test_scenarios_add_the_sectors_together(training_table):
    residential = make_fit("residential", 2.0, training_table)
    commercial = make_fit("commercial", 1.0, training_table)
    plan_months = pd.date_range("2017-09-01", periods=12, freq="MS")

    one_sector = weather_year_scenarios({"residential": residential}, plan_months, 3)
    both_sectors = weather_year_scenarios(
        {"residential": residential, "commercial": commercial}, plan_months, 3
    )

    assert (both_sectors > one_sector).all()
