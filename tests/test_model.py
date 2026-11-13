import numpy as np
import pandas as pd
import pytest

from forecast_to_decision.model import (
    Spec,
    add_lagged_weather,
    choose_spec,
    design_matrix,
    fit_sector_model,
    normal_hdd_by_month,
    normal_weather_forecast,
    predict,
    score,
    seasonal_naive,
    split_train_holdout,
    with_normal_weather,
)

SPEC = Spec(start_year=2010, base_temp_f=65.0, month_effects=False)


@pytest.fixture
def synthetic_table() -> pd.DataFrame:
    """Ten years of months where residential demand is exactly 100 + 2 * HDD."""
    months = pd.date_range("2010-01-01", "2019-12-01", freq="MS")
    rng = np.random.default_rng(0)
    seasonal_hdd = 600 * (1 + np.cos(2 * np.pi * (months.month - 1) / 12)) / 2
    table = pd.DataFrame({"hdd": seasonal_hdd + rng.uniform(-30, 30, len(months))}, index=months)
    table["days_in_month"] = months.days_in_month
    table["residential_mmcf"] = 100 + 2 * table["hdd"]
    table["commercial_mmcf"] = 50 + table["hdd"]
    return add_lagged_weather(table)


def test_fit_recovers_the_weather_coefficient(synthetic_table):
    model = fit_sector_model(synthetic_table, "residential", SPEC)

    assert model.params["hdd"] == pytest.approx(2, abs=0.05)


def test_fit_ignores_months_before_the_start_year(synthetic_table):
    late_spec = Spec(start_year=2015, base_temp_f=65.0, month_effects=False)

    model = fit_sector_model(synthetic_table, "residential", late_spec)

    months_from_2015 = (synthetic_table.index >= "2015-01-01").sum()
    assert model.nobs == months_from_2015


def test_month_effects_add_eleven_columns_with_january_as_reference(synthetic_table):
    spec = Spec(start_year=2010, base_temp_f=65.0, month_effects=True)

    design = design_matrix(synthetic_table, spec)

    assert "month_1" not in design.columns
    assert [c for c in design.columns if c.startswith("month_")] == [
        f"month_{m}" for m in range(2, 13)
    ]


def test_split_keeps_the_last_months_for_holdout(synthetic_table):
    train, holdout = split_train_holdout(synthetic_table, holdout_months=12)

    assert len(holdout) == 12
    assert train.index[-1] < holdout.index[0]


def test_normal_weather_replaces_hdd_with_calendar_month_average(synthetic_table):
    train, holdout = split_train_holdout(synthetic_table, holdout_months=12)
    normals = normal_hdd_by_month(train)

    scenario = with_normal_weather(train, holdout, normals)

    assert scenario["hdd"].iloc[0] == pytest.approx(normals[holdout.index[0].month])
    assert scenario["hdd_lag1"].iloc[0] == train["hdd"].iloc[-1]
    assert scenario["hdd_lag1"].iloc[1] == scenario["hdd"].iloc[0]


def test_normal_weather_forecast_does_not_use_future_weather(synthetic_table):
    train, holdout = split_train_holdout(synthetic_table, holdout_months=12)
    changed = holdout.copy()
    changed["hdd"] = changed["hdd"] + 500

    original = normal_weather_forecast(train, holdout, "residential", SPEC)
    after_change = normal_weather_forecast(train, changed, "residential", SPEC)

    pd.testing.assert_series_equal(original, after_change)


def test_predict_uses_the_supplied_weather(synthetic_table):
    model = fit_sector_model(synthetic_table, "residential", SPEC)
    cold, warm = synthetic_table.iloc[[0]].copy(), synthetic_table.iloc[[0]].copy()
    cold["hdd"], warm["hdd"] = 800, 100

    assert predict(model, cold, SPEC).iloc[0] > predict(model, warm, SPEC).iloc[0]


def test_seasonal_naive_repeats_the_same_month_last_year(synthetic_table):
    _, holdout = split_train_holdout(synthetic_table, holdout_months=12)

    forecast = seasonal_naive(synthetic_table, holdout, "residential")

    last_year = synthetic_table["residential_mmcf"].shift(12).loc[holdout.index]
    pd.testing.assert_series_equal(forecast, last_year)


def test_score_reports_mae_rmse_and_mape():
    actual = pd.Series([100.0, 200.0])
    forecast = pd.Series([110.0, 180.0])

    result = score(actual, forecast)

    assert result.mae == 15
    assert result.rmse == pytest.approx(np.sqrt(250))
    assert result.mape_percent == pytest.approx(10)


def test_choose_spec_never_reads_the_holdout(synthetic_table):
    tables = {base: synthetic_table for base in (60.0, 62.0, 65.0)}
    sabotaged = {base: table.copy() for base, table in tables.items()}
    for table in sabotaged.values():
        table.iloc[-36:, table.columns.get_loc("residential_mmcf")] = 1e9

    assert choose_spec(tables, "residential") == choose_spec(sabotaged, "residential")
