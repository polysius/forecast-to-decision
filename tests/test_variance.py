import numpy as np
import pandas as pd
import pytest

from forecast_to_decision.variance import (
    COMPONENTS,
    budget_prices,
    decompose_revenue_variance,
    sum_by_period,
    volume_variance,
)

MONTH = pd.DatetimeIndex(["2024-01-01"])


def one_month(residential: float, commercial: float) -> pd.DataFrame:
    return pd.DataFrame({"residential": [residential], "commercial": [commercial]}, index=MONTH)


def worked_example() -> pd.DataFrame:
    """Forecast 100 and 100, weather adds 10 to residential, actual 100 and 130."""
    return decompose_revenue_variance(
        forecast=one_month(100, 100),
        weather_adjusted_forecast=one_month(110, 100),
        actual=one_month(100, 130),
        forecast_price=one_month(10, 5),
        actual_price=one_month(11, 5),
    )


def test_each_effect_matches_a_hand_calculation():
    result = worked_example().iloc[0]

    assert result["forecast_revenue"] == pytest.approx(1.5)
    assert result["actual_revenue"] == pytest.approx(1.75)
    assert result["weather"] == pytest.approx(0.1)  # 10 MMcf at $10
    assert result["volume"] == pytest.approx(0.15238, abs=1e-5)  # 20 MMcf at the forecast mix price
    assert result["mix"] == pytest.approx(-0.10238, abs=1e-5)  # shift toward cheaper commercial gas
    assert result["price"] == pytest.approx(0.1)  # residential price up $1 on 100 MMcf


def test_effects_add_up_to_the_total_variance():
    result = worked_example().iloc[0]

    assert result["explained"] == pytest.approx(result["total_variance"])
    assert result["total_variance"] == pytest.approx(0.25)


def test_effects_add_up_for_random_inputs():
    rng = np.random.default_rng(3)
    months = pd.date_range("2024-01-01", periods=12, freq="MS")

    def volumes() -> pd.DataFrame:
        return pd.DataFrame(rng.uniform(50, 500, (12, 2)), index=months, columns=["residential", "commercial"])

    def prices() -> pd.DataFrame:
        return pd.DataFrame(rng.uniform(5, 30, (12, 2)), index=months, columns=["residential", "commercial"])

    result = decompose_revenue_variance(volumes(), volumes(), volumes(), prices(), prices())

    np.testing.assert_allclose(result["explained"], result["total_variance"])


def test_a_forecast_that_is_exactly_right_has_no_variance():
    volumes = one_month(100, 200)
    prices = one_month(10, 5)

    result = decompose_revenue_variance(volumes, volumes, volumes, prices, prices).iloc[0]

    assert all(result[component] == pytest.approx(0) for component in COMPONENTS)


def test_only_weather_differs_when_actual_equals_the_weather_adjusted_forecast():
    prices = one_month(10, 5)
    result = decompose_revenue_variance(
        one_month(100, 100), one_month(120, 90), one_month(120, 90), prices, prices
    ).iloc[0]

    assert result["weather"] == pytest.approx((20 * 10 - 10 * 5) / 1000)
    assert result["volume"] == pytest.approx(0)
    assert result["mix"] == pytest.approx(0)
    assert result["price"] == pytest.approx(0)


def test_budget_price_is_the_same_month_one_year_earlier():
    months = pd.date_range("2022-01-01", periods=14, freq="MS")
    prices = pd.DataFrame({"residential": np.arange(14.0)}, index=months)

    budget = budget_prices(prices)

    assert budget.loc["2023-02-01", "residential"] == prices.loc["2022-02-01", "residential"]
    assert budget.iloc[:12].isna().all().all()


def test_volume_variance_separates_weather_from_everything_else():
    result = volume_variance(one_month(100, 100), one_month(110, 100), one_month(100, 130)).iloc[0]

    assert result["weather_mmcf"] == 10
    assert result["other_mmcf"] == 20  # 30 above forecast in total, 10 of it weather


def test_periods_add_months_and_are_labelled_by_first_and_last_month():
    months = pd.date_range("2023-09-01", periods=6, freq="MS")
    monthly = pd.DataFrame({"weather": [1.0, 2, 3, 4, 5, 6]}, index=months)

    periods = sum_by_period(monthly)

    assert periods["weather"].tolist() == [6, 15]
    assert periods.index.tolist() == ["2023-09 to 2023-11", "2023-12 to 2024-02"]


def test_a_partial_period_is_rejected():
    monthly = pd.DataFrame({"weather": [1.0] * 5}, index=pd.date_range("2023-09-01", periods=5, freq="MS"))

    with pytest.raises(ValueError, match="whole periods"):
        sum_by_period(monthly)
