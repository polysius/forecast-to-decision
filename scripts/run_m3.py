"""Milestone 3: break the forecast-vs-actual revenue gap into weather, volume, mix and price.

Needs the outputs of run_m1.py (results/m1_*). Every number in VARIANCE.md is computed
here. Run from the repo root:  python scripts/run_m3.py
"""

from pathlib import Path

import pandas as pd

from forecast_to_decision.data import SECTORS, load_monthly_gas
from forecast_to_decision.report import markdown_table
from forecast_to_decision.variance import (
    COMPONENTS,
    MONTHS_PER_PERIOD,
    budget_prices,
    decompose_revenue_variance,
    sector_frame,
    sum_by_period,
    volume_variance,
)
from forecast_to_decision.variance_plots import plot_variance_components

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results"
FIGURES_DIR = ROOT / "docs" / "figures"
DOC_PATH = ROOT / "VARIANCE.md"

REVENUE_COLUMNS = {
    "period": ("Period", ""),
    "forecast_revenue": ("Forecast ($M)", ",.1f"),
    "actual_revenue": ("Actual ($M)", ",.1f"),
    "total_variance": ("Variance ($M)", "+,.1f"),
    "weather": ("Weather", "+,.1f"),
    "volume": ("Volume", "+,.1f"),
    "mix": ("Mix", "+,.1f"),
    "price": ("Price", "+,.1f"),
}
VOLUME_COLUMNS = {
    "period": ("Period", ""),
    "forecast_mmcf": ("Forecast (MMcf)", ",.0f"),
    "actual_mmcf": ("Actual (MMcf)", ",.0f"),
    "weather_mmcf": ("Explained by weather", "+,.0f"),
    "other_mmcf": ("Not explained by weather", "+,.0f"),
}


def load_volumes() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Forecast, weather adjusted forecast, and actual deliveries by month and sector."""
    holdouts = {
        sector: pd.read_csv(RESULTS_DIR / f"m1_{sector}_holdout.csv", index_col=0, parse_dates=True)
        for sector in SECTORS
    }

    def column(name: str) -> pd.DataFrame:
        return sector_frame({sector: holdouts[sector][name] for sector in SECTORS})

    return (
        column("regression_normal_weather_mmcf"),
        column("regression_actual_weather_mmcf"),
        column("actual_mmcf"),
    )


def load_prices(months: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Budget prices (same month last year) and actual prices for the given months."""
    gas = load_monthly_gas()
    history = sector_frame(
        {
            "residential": gas["residential_price"],
            "commercial": gas["commercial_price"],
        }
    )
    forecast_price = budget_prices(history).loc[months]
    actual_price = history.loc[months]
    if forecast_price.isna().any().any() or actual_price.isna().any().any():
        raise ValueError("A sector price is missing for one of the months being analysed")
    return forecast_price, actual_price


def verdict(periods: pd.DataFrame) -> str:
    """One paragraph on the totals and the largest effects, all computed."""
    totals = periods.sum()
    direction = "above" if totals["total_variance"] > 0 else "below"
    effects = ", ".join(f"{name} {totals[name]:+,.1f}" for name in COMPONENTS)
    largest = max(COMPONENTS, key=lambda name: abs(totals[name]))
    weather_share = periods["weather"].abs().sum() / periods[list(COMPONENTS)].abs().sum().sum()
    return (
        f"Over the {len(periods)} periods actual revenue was ${abs(totals['total_variance']):,.1f}M "
        f"{direction} the forecast of ${totals['forecast_revenue']:,.1f}M. The effects in $M were: "
        f"{effects}. The largest effect over the whole span is {largest}. Weather accounts for "
        f"{weather_share:.0%} of the absolute variance summed over all four effects and all periods, "
        "and it moves in both directions from period to period."
    )


def write_document(
    periods: pd.DataFrame, volume_periods: pd.DataFrame, check_gap: float
) -> None:
    total_row = periods.sum().to_frame("Total").T.rename_axis("period").reset_index()
    total_row["period"] = "Total"
    revenue_view = pd.concat([periods.reset_index(), total_row], ignore_index=True)

    volume_total = volume_periods.sum().to_frame("Total").T.rename_axis("period").reset_index()
    volume_total["period"] = "Total"
    volume_view = pd.concat([volume_periods.reset_index(), volume_total], ignore_index=True)

    DOC_PATH.write_text(
        f"""# Milestone 3: variance analysis

How far was the forecast from what happened, and why? This milestone takes the M1 normal
weather forecast for the last {len(periods) * MONTHS_PER_PERIOD} months and explains the gap
to actual gas revenue with four named effects. Regenerate with `python scripts/run_m3.py`
after `python scripts/run_m1.py`.

## Method

Revenue is deliveries times the price each sector pays, summed over residential and
commercial customers. The forecast is the M1 normal weather forecast priced at a budget price.
The actual is what was delivered at the price that was charged. The gap is moved from forecast
to actual in four steps, and each step changes one thing, so the effects add up to the total:

1. **Weather.** Replace normal weather with the weather that happened, using the M1 regression
   for both. Effect: (weather adjusted forecast minus forecast) times budget price.
2. **Volume.** Move total deliveries from the weather adjusted forecast to the actual total,
   keeping the forecast split between sectors. Effect: change in total volume times the budget
   price of the forecast mix.
3. **Mix.** Move from the forecast split between residential and commercial to the actual
   split. Residential gas sells at a higher price, so shifting toward commercial lowers revenue.
   Effect: actual volume times the change in each sector's share times its budget price.
4. **Price.** Charge the actual prices. Effect: actual volume times (actual minus budget price).

Positive means actual is above forecast. Periods are consecutive blocks of
{MONTHS_PER_PERIOD} months starting in September, so each period is one season. The effects
are computed month by month and added up within each period.

The budget price is the same month one year earlier, from the EIA residential and commercial
price series. It stands in for the price a planner would have assumed.

## Revenue variance

Millions of dollars. The four effects add up to the variance in every period. The largest
difference between their sum and the variance is {check_gap:.1e}, which is rounding.

{markdown_table(revenue_view, REVENUE_COLUMNS)}

{verdict(periods)}

![Revenue variance by component](docs/figures/m3_variance.png)

## Volume variance

The same periods in gas volume. Weather is what the M1 regression attributes to the weather
that happened. The rest is everything the regression does not explain.

{markdown_table(volume_view, VOLUME_COLUMNS)}

## Limitations

* Volume holds two things that this data cannot separate: real changes in how much gas
  customers use, and the regression's own error.
* The weather effect comes from the same regression that made the forecast, so it inherits
  that model's weaknesses (see STATS.md).
* The budget price is an assumption. A different rule for it moves revenue between the price
  effect and the others.
* Revenue here is deliveries times retail price. It is not margin, because the cost of buying
  the gas is not netted off.
* Customer counts are annual and stop in 2024, so the volume effect is not split into customer
  growth and use per customer.
""",
        encoding="utf-8",
    )


def main() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    forecast, weather_adjusted, actual = load_volumes()
    forecast_price, actual_price = load_prices(forecast.index)

    monthly = decompose_revenue_variance(
        forecast, weather_adjusted, actual, forecast_price, actual_price
    )
    periods = sum_by_period(monthly)
    volume_periods = sum_by_period(volume_variance(forecast, weather_adjusted, actual))
    check_gap = float((monthly["explained"] - monthly["total_variance"]).abs().max())

    monthly.to_csv(RESULTS_DIR / "m3_variance_monthly.csv", float_format="%.4f")
    periods.to_csv(RESULTS_DIR / "m3_variance_by_period.csv", float_format="%.4f")
    volume_periods.to_csv(RESULTS_DIR / "m3_volume_by_period.csv", float_format="%.1f")
    plot_variance_components(periods, FIGURES_DIR / "m3_variance.png")
    write_document(periods, volume_periods, check_gap)
    print(periods.round(1).to_string())


if __name__ == "__main__":
    main()
