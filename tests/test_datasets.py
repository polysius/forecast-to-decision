import pandas as pd
import pytest

from forecast_to_decision.datasets import (
    RESULTS_DIR,
    SEASONS,
    build_reporting_tables,
    period_labels,
    plan_year_labels,
)

HOLDOUT = pd.date_range("2023-09-01", periods=36, freq="MS")


@pytest.fixture(scope="module")
def tables():
    return build_reporting_tables()


def test_every_month_has_one_row_per_sector(tables):
    counts = tables.monthly_sector.groupby("month").size()

    assert len(counts) == 36
    assert (counts == 2).all()


def test_the_key_column_is_unique_for_lookups(tables):
    assert tables.monthly_sector["key"].is_unique


def test_monthly_revenue_matches_the_m3_variance_table(tables):
    by_month = tables.monthly_sector.groupby("month")[
        ["forecast_revenue_musd", "actual_revenue_musd"]
    ].sum()
    variance = tables.monthly_variance.set_index("month")

    pd.testing.assert_series_equal(
        by_month["forecast_revenue_musd"], variance["forecast_revenue_musd"], check_names=False
    )
    pd.testing.assert_series_equal(
        by_month["actual_revenue_musd"], variance["actual_revenue_musd"], check_names=False
    )


def test_variance_effects_add_up_to_the_total_every_month(tables):
    variance = tables.monthly_variance
    effects = variance[["weather_musd", "volume_musd", "mix_musd", "price_musd"]].sum(axis=1)

    pd.testing.assert_series_equal(effects, variance["total_variance_musd"], check_names=False)


def test_monthly_variance_matches_the_committed_m3_results(tables):
    committed = pd.read_csv(RESULTS_DIR / "m3_variance_monthly.csv", index_col=0, parse_dates=True)

    for name in ("weather", "volume", "mix", "price"):
        assert tables.monthly_variance[f"{name}_musd"].to_numpy() == pytest.approx(
            committed[name].to_numpy(), abs=1e-3
        )


def test_period_labels_group_months_in_threes():
    labels = period_labels(HOLDOUT)

    assert labels.iloc[0] == "2023-09 to 2023-11"
    assert labels.iloc[3] == "2023-12 to 2024-02"
    assert labels.nunique() == 12


def test_plan_year_labels_group_months_in_twelves():
    labels = plan_year_labels(HOLDOUT)

    assert labels.iloc[0] == "2023-09 to 2024-08"
    assert labels.iloc[-1] == "2025-09 to 2026-08"
    assert labels.nunique() == 3


def test_every_calendar_month_has_a_season():
    assert sorted(SEASONS) == list(range(1, 13))


def test_the_calendar_covers_every_day_of_the_holdout(tables):
    calendar = tables.calendar

    assert calendar["date"].is_unique
    assert calendar["date"].min() == pd.Timestamp("2023-09-01")
    assert calendar["date"].max() == pd.Timestamp("2026-08-31")
    assert set(calendar["month"]) == set(HOLDOUT)


def test_commitments_cover_every_month(tables):
    assert tables.commitments["month"].is_unique
    assert len(tables.commitments) == 36
