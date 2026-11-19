"""Split the gap between forecast and actual gas revenue into named components.

Revenue is deliveries times the price paid by each sector. The forecast is the M1
normal-weather forecast at a budget price. The actual is what was delivered at the
price that was charged. The gap is moved from forecast to actual in four steps, and
each step changes one thing, so the four effects add up exactly to the total:

1. Weather: use the weather that happened instead of normal weather.
2. Volume: move total deliveries to what was actually delivered, keeping the sector
   split the forecast had.
3. Mix: move from the forecast split between residential and commercial to the
   actual split. Residential gas is sold at a higher price, so the split matters.
4. Price: charge the prices that were actually charged.

Volume is whatever total demand differs from the weather adjusted forecast. It holds
both genuine changes in demand and the regression's own error, which this data cannot
tell apart. Positive means actual is above forecast.
"""

import numpy as np
import pandas as pd

from forecast_to_decision.data import SECTORS

# MMcf times $/Mcf is thousands of dollars, so divide by 1000 for millions.
MMCF_PRICE_TO_MUSD = 1 / 1000
MONTHS_PER_PERIOD = 3
COMPONENTS = ("weather", "volume", "mix", "price")


def budget_prices(price_history: pd.DataFrame) -> pd.DataFrame:
    """The price assumed when the forecast was made: the same month one year earlier."""
    return price_history.shift(12)


def decompose_revenue_variance(
    forecast: pd.DataFrame,
    weather_adjusted_forecast: pd.DataFrame,
    actual: pd.DataFrame,
    forecast_price: pd.DataFrame,
    actual_price: pd.DataFrame,
) -> pd.DataFrame:
    """One row per month with the revenue effects in millions of dollars.

    Every frame has one column per sector, in `SECTORS`, indexed by month. Volumes
    are MMcf and prices are $/Mcf. The result has forecast and actual revenue, the
    four effects, and their sum, which equals actual minus forecast.
    """
    forecast_volume = weather_adjusted_forecast.sum(axis=1)
    actual_volume = actual.sum(axis=1)
    forecast_share = weather_adjusted_forecast.div(forecast_volume, axis=0)
    actual_share = actual.div(actual_volume, axis=0)

    weather = ((weather_adjusted_forecast - forecast) * forecast_price).sum(axis=1)
    forecast_mix_price = (forecast_share * forecast_price).sum(axis=1)
    volume = (actual_volume - forecast_volume) * forecast_mix_price
    mix = actual_volume * ((actual_share - forecast_share) * forecast_price).sum(axis=1)
    price = (actual * (actual_price - forecast_price)).sum(axis=1)

    table = pd.DataFrame(
        {
            "forecast_revenue": (forecast * forecast_price).sum(axis=1),
            "actual_revenue": (actual * actual_price).sum(axis=1),
            "weather": weather,
            "volume": volume,
            "mix": mix,
            "price": price,
        }
    )
    table = table * MMCF_PRICE_TO_MUSD
    table["total_variance"] = table["actual_revenue"] - table["forecast_revenue"]
    table["explained"] = table[list(COMPONENTS)].sum(axis=1)
    return table


def volume_variance(
    forecast: pd.DataFrame, weather_adjusted_forecast: pd.DataFrame, actual: pd.DataFrame
) -> pd.DataFrame:
    """Total deliveries (MMcf) and how much of the gap weather explains."""
    table = pd.DataFrame(
        {
            "forecast_mmcf": forecast.sum(axis=1),
            "actual_mmcf": actual.sum(axis=1),
            "weather_mmcf": (weather_adjusted_forecast - forecast).sum(axis=1),
        }
    )
    table["other_mmcf"] = table["actual_mmcf"] - table["forecast_mmcf"] - table["weather_mmcf"]
    return table


def sum_by_period(monthly: pd.DataFrame, months_per_period: int = MONTHS_PER_PERIOD) -> pd.DataFrame:
    """Add up consecutive blocks of months, labelled by their first and last month.

    The effects are additive, so a period's effects are the sum of its months'.
    """
    if len(monthly) % months_per_period:
        raise ValueError(f"{len(monthly)} months do not fill whole periods of {months_per_period}")
    block = np.arange(len(monthly)) // months_per_period
    periods = monthly.groupby(block).sum()
    first = monthly.index.to_series().groupby(block).first()
    last = monthly.index.to_series().groupby(block).last()
    periods.index = [f"{start:%Y-%m} to {end:%Y-%m}" for start, end in zip(first, last, strict=True)]
    periods.index.name = "period"
    return periods


def sector_frame(values_by_sector: dict[str, pd.Series]) -> pd.DataFrame:
    """Build a frame with the sector columns in the order `SECTORS`."""
    return pd.DataFrame({sector: values_by_sector[sector] for sector in SECTORS})
