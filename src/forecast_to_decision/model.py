"""Interpretable demand regression, its normal-weather forecast, and baselines.

Each sector is modelled as

    deliveries = b0 + b1 * HDD + b2 * HDD(previous month) + b3 * days in month
                 + b4 * years since 1989 + b5 * COVID period

Heating degree days (HDD) are the weather driver. The previous month's HDD
captures billing lag: some deliveries are recorded when meters are read, a
few weeks after the gas was burned. Monthly data has no day of week or
holiday effect, so days in month is the calendar driver instead.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.regression.linear_model import RegressionResultsWrapper

DRIVERS = ["hdd", "hdd_lag1", "days_in_month", "years_since_1989", "covid"]
COVID_START = pd.Timestamp("2020-03-01")
COVID_END = pd.Timestamp("2021-06-01")
NORMAL_WINDOW_YEARS = 30
HAC_LAGS = 12
HOLDOUT_MONTHS = 36


def add_drivers(table: pd.DataFrame) -> pd.DataFrame:
    """Add the lagged weather, trend, and COVID columns to the monthly table."""
    table = table.copy()
    table["hdd_lag1"] = table["hdd"].shift(1)
    table["years_since_1989"] = (table.index.year - 1989) + (table.index.month - 1) / 12
    table["covid"] = ((table.index >= COVID_START) & (table.index <= COVID_END)).astype(int)
    return table.dropna(subset=["hdd_lag1"])


def split_train_holdout(
    table: pd.DataFrame, holdout_months: int = HOLDOUT_MONTHS
) -> tuple[pd.DataFrame, pd.DataFrame]:
    return table.iloc[:-holdout_months], table.iloc[-holdout_months:]


def fit_sector_model(train: pd.DataFrame, sector: str) -> RegressionResultsWrapper:
    """Fit OLS with Newey-West (HAC) errors, since monthly residuals are autocorrelated."""
    target = train[f"{sector}_mmcf"]
    design = sm.add_constant(train[DRIVERS])
    return sm.OLS(target, design).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})


def predict(model: RegressionResultsWrapper, features: pd.DataFrame) -> pd.Series:
    design = sm.add_constant(features[DRIVERS], has_constant="add")
    return model.predict(design)


def normal_hdd_by_month(train: pd.DataFrame, years: int = NORMAL_WINDOW_YEARS) -> pd.Series:
    """Average HDD for each calendar month over the last `years` years of training data."""
    recent = train[train.index > train.index[-1] - pd.DateOffset(years=years)]
    return recent.groupby(recent.index.month)["hdd"].mean()


def with_normal_weather(
    train: pd.DataFrame, holdout: pd.DataFrame, normals: pd.Series
) -> pd.DataFrame:
    """Copy the holdout drivers, replacing actual HDD with the normal for each month.

    This is what a forecaster knows at the forecast origin: the calendar and
    trend are known, the weather is not. The first holdout month's lag uses
    the last observed training month.
    """
    scenario = holdout.copy()
    scenario["hdd"] = scenario.index.month.map(normals)
    scenario["hdd_lag1"] = scenario["hdd"].shift(1)
    scenario.iloc[0, scenario.columns.get_loc("hdd_lag1")] = train["hdd"].iloc[-1]
    return scenario


def seasonal_naive(table: pd.DataFrame, holdout: pd.DataFrame, sector: str) -> pd.Series:
    """Forecast each month with the same month one year earlier."""
    actual = table[f"{sector}_mmcf"]
    return actual.shift(12).loc[holdout.index]


@dataclass(frozen=True)
class ErrorScores:
    mae: float
    rmse: float
    mape_percent: float


def score(actual: pd.Series, forecast: pd.Series) -> ErrorScores:
    error = actual - forecast
    return ErrorScores(
        mae=float(error.abs().mean()),
        rmse=float(np.sqrt((error**2).mean())),
        mape_percent=float((error.abs() / actual).mean() * 100),
    )
