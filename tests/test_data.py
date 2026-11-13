import pandas as pd
import pytest

from forecast_to_decision.data import MAX_MISSING_DAYS_PER_MONTH, monthly_degree_days


def make_daily(start: str, end: str, tmax: float, tmin: float) -> pd.DataFrame:
    days = pd.date_range(start, end, freq="D")
    return pd.DataFrame({"tmax_f": tmax, "tmin_f": tmin}, index=days)


def test_hdd_uses_mean_of_max_and_min_against_base_65():
    daily = make_daily("2024-01-01", "2024-01-31", tmax=40, tmin=20)  # mean 30F -> 35 HDD/day

    result = monthly_degree_days(daily)

    assert result.loc["2024-01-01", "hdd"] == pytest.approx(35 * 31)


def test_warm_days_contribute_zero_hdd():
    daily = make_daily("2024-07-01", "2024-07-31", tmax=90, tmin=70)

    result = monthly_degree_days(daily)

    assert result.loc["2024-07-01", "hdd"] == 0


def test_a_few_missing_days_are_filled_with_the_monthly_average():
    daily = make_daily("2024-01-01", "2024-01-31", tmax=40, tmin=20)
    daily = daily.drop(daily.index[:2])  # two days missing

    result = monthly_degree_days(daily)

    assert result.loc["2024-01-01", "hdd"] == pytest.approx(35 * 31)
    assert result.loc["2024-01-01", "missing_days"] == 2


def test_months_with_too_many_missing_days_are_dropped():
    daily = make_daily("2024-01-01", "2024-01-31", tmax=40, tmin=20)
    daily = daily.drop(daily.index[: MAX_MISSING_DAYS_PER_MONTH + 1])

    result = monthly_degree_days(daily)

    assert result.empty
