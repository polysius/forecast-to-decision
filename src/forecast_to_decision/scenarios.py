"""Demand scenarios for a plan year, one for each historical weather year.

The planner does not know the coming weather, but it has seen many winters.
Each scenario asks: what would demand be if this year's weather, month by
month, repeated in the plan year? The M1 regressions turn weather into demand.
Only weather from before the forecast origin is used.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from statsmodels.regression.linear_model import RegressionResultsWrapper

from forecast_to_decision.data import SECTORS
from forecast_to_decision.model import (
    Spec,
    fit_sector_model,
    predict,
    split_train_holdout,
)

PLAN_YEAR_START_MONTH = 9  # September: storage is full and winter is ahead
MONTHS_PER_YEAR = 12
WEATHER_YEARS = 30


@dataclass(frozen=True)
class SectorFit:
    """A sector's training table, fitted model, and the specification it uses."""

    train: pd.DataFrame
    model: RegressionResultsWrapper
    spec: Spec


def fit_sectors(tables_by_base_temp: dict[float, pd.DataFrame], specs: dict[str, Spec]) -> dict:
    """Refit each sector on the M1 training period with its chosen specification."""
    fits = {}
    for sector in SECTORS:
        spec = specs[sector]
        train, _ = split_train_holdout(tables_by_base_temp[spec.base_temp_f])
        fits[sector] = SectorFit(train, fit_sector_model(train, sector, spec), spec)
    return fits


def plan_year_months(holdout_index: pd.DatetimeIndex) -> list[pd.DatetimeIndex]:
    """Split the holdout into consecutive plan years of 12 months."""
    if len(holdout_index) % MONTHS_PER_YEAR:
        raise ValueError("The holdout must be a whole number of plan years")
    return [
        holdout_index[start : start + MONTHS_PER_YEAR]
        for start in range(0, len(holdout_index), MONTHS_PER_YEAR)
    ]


def weather_year_scenarios(
    fits: dict[str, SectorFit],
    plan_months: pd.DatetimeIndex,
    weather_years: int = WEATHER_YEARS,
) -> np.ndarray:
    """Total deliveries (residential plus commercial) per scenario and plan month.

    Returns an array of shape (scenarios, 12). The calendar (days in month) is
    the plan year's; the weather is a past year's.
    """
    reference_train = next(iter(fits.values())).train
    window_starts = _complete_window_starts(reference_train.index)[-weather_years:]

    scenarios = []
    for window_start in window_starts:
        scenario_demand = np.zeros(MONTHS_PER_YEAR)
        for fit in fits.values():
            window = fit.train.loc[window_start : window_start + pd.DateOffset(months=11)]
            weather = pd.DataFrame(
                {
                    "hdd": window["hdd"].to_numpy(),
                    "hdd_lag1": window["hdd_lag1"].to_numpy(),
                    "days_in_month": plan_months.days_in_month,
                },
                index=plan_months,
            )
            scenario_demand += predict(fit.model, weather, fit.spec).to_numpy()
        scenarios.append(scenario_demand)
    return np.array(scenarios)


def _complete_window_starts(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """Each September from which a full 12 months of weather is available."""
    starts = []
    for year in range(index[0].year, index[-1].year + 1):
        start = pd.Timestamp(year=year, month=PLAN_YEAR_START_MONTH, day=1)
        end = start + pd.DateOffset(months=MONTHS_PER_YEAR - 1)
        if start >= index[0] and end <= index[-1]:
            starts.append(start)
    return starts
