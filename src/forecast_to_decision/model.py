"""Interpretable demand regression, its normal-weather forecast, and baselines.

Each sector is modelled as

    deliveries = b0 + b1 * HDD + b2 * HDD(previous month) + b3 * days in month
                 [+ one effect per calendar month]

Heating degree days (HDD) are the weather driver. The previous month's HDD
captures billing lag: some deliveries are recorded when meters are read, a
few weeks after the gas was burned. Monthly data has no day of week or
holiday effect, so days in month is the calendar driver instead. Month
effects absorb the seasonal shape that HDD alone misses (base load, and how
quickly heating systems switch on in the shoulder months).

Three choices are made by validation inside the training period, never on
the holdout: the first year of training data, the HDD base temperature, and
whether month effects are included. See `choose_spec`.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.regression.linear_model import RegressionResultsWrapper

NORMAL_WINDOW_YEARS = 30
HAC_LAGS = 12
HOLDOUT_MONTHS = 36
VALIDATION_MONTHS = 36

# Annual deliveries were flat after about 2013 but grew before it, so a short
# window is a real candidate next to the full history.
START_YEARS = (1989, 2000, 2008, 2013)
BASE_TEMPS_F = (60.0, 62.0, 65.0)


@dataclass(frozen=True)
class Spec:
    start_year: int
    base_temp_f: float
    month_effects: bool


CANDIDATE_SPECS = [
    Spec(start_year, base_temp, month_effects)
    for start_year in START_YEARS
    for base_temp in BASE_TEMPS_F
    for month_effects in (False, True)
]


def add_lagged_weather(table: pd.DataFrame) -> pd.DataFrame:
    """Add last month's HDD; the first month has no lag and is dropped.

    Later code shifts by rows (lags, the 12 month baseline, the holdout split),
    so a gap in the months would silently misalign them. Fail loudly instead.
    """
    expected = pd.date_range(table.index[0], table.index[-1], freq="MS")
    if not table.index.equals(expected):
        missing = expected.difference(table.index)
        raise ValueError(f"Monthly table has gaps: {[f'{m:%Y-%m}' for m in missing]}")
    table = table.copy()
    table["hdd_lag1"] = table["hdd"].shift(1)
    return table.dropna(subset=["hdd_lag1"])


def split_train_holdout(
    table: pd.DataFrame, holdout_months: int = HOLDOUT_MONTHS
) -> tuple[pd.DataFrame, pd.DataFrame]:
    return table.iloc[:-holdout_months], table.iloc[-holdout_months:]


def design_matrix(table: pd.DataFrame, spec: Spec) -> pd.DataFrame:
    """The regression inputs for each month, including the constant."""
    design = table[["hdd", "hdd_lag1", "days_in_month"]].copy()
    if spec.month_effects:
        for month in range(2, 13):  # January is the reference month
            design[f"month_{month}"] = (table.index.month == month).astype(float)
    return sm.add_constant(design, has_constant="add")


def fit_sector_model(
    train: pd.DataFrame, sector: str, spec: Spec
) -> RegressionResultsWrapper:
    """Fit OLS with Newey-West (HAC) errors, since monthly residuals are autocorrelated."""
    window = train[train.index >= f"{spec.start_year}-01-01"]
    target = window[f"{sector}_mmcf"]
    return sm.OLS(target, design_matrix(window, spec)).fit(
        cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS}
    )


def predict(model: RegressionResultsWrapper, table: pd.DataFrame, spec: Spec) -> pd.Series:
    return model.predict(design_matrix(table, spec))


def normal_hdd_by_month(train: pd.DataFrame, years: int = NORMAL_WINDOW_YEARS) -> pd.Series:
    """Average HDD for each calendar month over the last `years` years of training data."""
    recent = train[train.index > train.index[-1] - pd.DateOffset(years=years)]
    return recent.groupby(recent.index.month)["hdd"].mean()


def with_normal_weather(
    train: pd.DataFrame, future: pd.DataFrame, normals: pd.Series
) -> pd.DataFrame:
    """Copy the future rows, replacing actual HDD with the normal for each month.

    This is what a forecaster knows at the forecast origin: the calendar is
    known, the weather is not. The first future month's lag uses the last
    observed training month.
    """
    scenario = future.copy()
    scenario["hdd"] = scenario.index.month.map(normals)
    scenario["hdd_lag1"] = scenario["hdd"].shift(1)
    scenario.iloc[0, scenario.columns.get_loc("hdd_lag1")] = train["hdd"].iloc[-1]
    return scenario


def normal_weather_forecast(
    train: pd.DataFrame, future: pd.DataFrame, sector: str, spec: Spec
) -> pd.Series:
    """Fit on `train`, then forecast `future` assuming normal weather."""
    model = fit_sector_model(train, sector, spec)
    scenario = with_normal_weather(train, future, normal_hdd_by_month(train))
    return predict(model, scenario, spec)


def seasonal_naive(table: pd.DataFrame, future: pd.DataFrame, sector: str) -> pd.Series:
    """Forecast each month with the same month one year earlier.

    This gives the baseline fresh data for every month, which is generous:
    a true 36-month-ahead forecast could not see the previous year.
    """
    actual = table[f"{sector}_mmcf"]
    return actual.shift(12).loc[future.index]


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


def choose_spec(tables_by_base_temp: dict[float, pd.DataFrame], sector: str) -> Spec:
    """Pick the candidate with the lowest normal-weather error on a validation slice.

    The slice is the last VALIDATION_MONTHS of the training period, and the
    holdout is removed first so it never influences the choice.
    """
    scores = {}
    for spec in CANDIDATE_SPECS:
        train, _ = split_train_holdout(tables_by_base_temp[spec.base_temp_f])
        fit_part, validation = split_train_holdout(train, VALIDATION_MONTHS)
        forecast = normal_weather_forecast(fit_part, validation, sector, spec)
        scores[spec] = score(validation[f"{sector}_mmcf"], forecast).mape_percent
    return min(scores, key=scores.get)
