"""The one page business summary, written for a reader with no statistics background.

Every number comes from the results tables. The recommendations rest on specific
findings, so `check_findings` raises an error if the data no longer supports them.
That way a rerun with different results cannot quietly publish advice that is wrong.
"""

from dataclasses import dataclass

import pandas as pd

from forecast_to_decision.datasets import ReportingTables, load_m1_column

RULE, OPTIMISED, HINDSIGHT = "Rule of thumb", "Optimised plan", "Perfect hindsight"
EFFECTS = ("weather", "volume", "mix", "price")
FULL_SERVICE_PERCENT = 99.995
CLOSE_TO_FORECAST_SHARE = 0.02


@dataclass(frozen=True)
class Findings:
    """The numbers the summary reports."""

    last_year_miss: float  # average monthly miss, percent, for "same month last year"
    normal_weather_miss: float
    actual_weather_miss: float
    rule_cost: float
    optimised_cost: float
    hindsight_cost: float
    strict_rule_cost: float
    strict_optimised_cost: float
    shortfall_error: float  # smallest realised demand error where any plan falls short
    last_full_service_error: float  # the largest tested error below that, where all plans met demand
    max_error: float
    rule_service_at_shortfall: float
    optimised_service_at_shortfall: float
    forecast_revenue: float
    actual_revenue: float
    effects: dict[str, float]

    @property
    def saving(self) -> float:
        return self.rule_cost - self.optimised_cost

    @property
    def strict_saving(self) -> float:
        return self.strict_rule_cost - self.strict_optimised_cost

    @property
    def revenue_gap(self) -> float:
        return self.actual_revenue - self.forecast_revenue


def _average_miss_percent(actual: pd.Series, forecast: pd.Series) -> float:
    return float(((actual - forecast).abs() / actual).mean() * 100)


def _plan_cost(frame: pd.DataFrame, plan: str) -> float:
    return float(frame.loc[frame["plan"] == plan, "cost_musd"].sum())


def compute_findings(tables: ReportingTables) -> Findings:
    actual = load_m1_column("actual_mmcf").sum(axis=1)
    misses = {
        name: _average_miss_percent(actual, load_m1_column(column).sum(axis=1))
        for name, column in (
            ("last_year", "seasonal_naive_mmcf"),
            ("normal", "regression_normal_weather_mmcf"),
            ("actual_weather", "regression_actual_weather_mmcf"),
        )
    }

    sensitivity = tables.sensitivity
    falls_short = sensitivity[sensitivity["served_percent"] < FULL_SERVICE_PERCENT]
    shortfall_error = (
        float(falls_short["forecast_error_percent"].min()) if len(falls_short) else float("nan")
    )
    at_shortfall = sensitivity[sensitivity["forecast_error_percent"] == shortfall_error]
    served = at_shortfall.set_index("plan")["served_percent"]
    tested_below = sensitivity.loc[
        sensitivity["forecast_error_percent"] < shortfall_error, "forecast_error_percent"
    ]
    last_full_service_error = float(tested_below.max()) if len(tested_below) else float("nan")

    variance = tables.monthly_variance
    sector = tables.monthly_sector
    plans, strict = tables.plan_comparison, tables.strict_storage
    return Findings(
        last_year_miss=misses["last_year"],
        normal_weather_miss=misses["normal"],
        actual_weather_miss=misses["actual_weather"],
        rule_cost=_plan_cost(plans, RULE),
        optimised_cost=_plan_cost(plans, OPTIMISED),
        hindsight_cost=_plan_cost(plans, HINDSIGHT),
        strict_rule_cost=_plan_cost(strict, RULE),
        strict_optimised_cost=_plan_cost(strict, OPTIMISED),
        shortfall_error=shortfall_error,
        last_full_service_error=last_full_service_error,
        max_error=float(sensitivity["forecast_error_percent"].max()),
        rule_service_at_shortfall=float(served.get(RULE, float("nan"))),
        optimised_service_at_shortfall=float(served.get(OPTIMISED, float("nan"))),
        forecast_revenue=float(sector["forecast_revenue_musd"].sum()),
        actual_revenue=float(sector["actual_revenue_musd"].sum()),
        effects={name: float(variance[f"{name}_musd"].sum()) for name in EFFECTS},
    )


def check_findings(f: Findings) -> None:
    """Raise if a finding the wording depends on no longer holds."""
    problems = []
    if not f.normal_weather_miss >= f.last_year_miss:
        problems.append("the forecast now beats 'same month last year', so item 1 needs rewording")
    if not f.actual_weather_miss < f.normal_weather_miss:
        problems.append("knowing the weather no longer reduces the miss")
    if not (f.saving > 0 and f.strict_saving <= 0):
        problems.append("the saving no longer flips sign under the strict storage rule")
    if not (f.shortfall_error == f.max_error and f.optimised_service_at_shortfall > f.rule_service_at_shortfall):
        problems.append("shortfalls no longer appear only at the largest demand surprise")
    largest = max(f.effects, key=lambda name: abs(f.effects[name]))
    if largest != "price":
        problems.append(f"the largest revenue effect is now {largest}, not price")
    if not abs(f.revenue_gap) / f.forecast_revenue <= CLOSE_TO_FORECAST_SHARE:
        problems.append("revenue is no longer within 2% of the forecast")
    if problems:
        raise ValueError("Rewrite the business summary: " + "; ".join(problems))


def _signed_money(value: float) -> str:
    return f"${abs(value):,.1f}M"


def _above_below(value: float) -> str:
    return "above" if value > 0 else "below"


def _added_or_took_off(value: float) -> str:
    return f"added {_signed_money(value)}" if value > 0 else f"took off {_signed_money(value)}"


def business_summary(tables: ReportingTables) -> str:
    f = compute_findings(tables)
    check_findings(f)
    effects = f.effects
    gap_share = abs(f.revenue_gap) / f.forecast_revenue * 100
    saving_share = f.saving / f.rule_cost * 100
    return f"""# What this analysis means for the business

**The question.** A gas utility must decide months ahead how much gas to buy, and whether to
reserve emergency supply for the coldest weeks, without knowing the weather. This analysis asks
how well demand can be forecast, what the best purchasing plan looks like, and why revenue ends
up different from the forecast. It covers three years of Massachusetts gas deliveries to homes
and businesses (September 2023 to August 2026), with Boston weather and published prices.

**What we found**

1. *The forecast is only as good as the weather guess.* Assuming normal weather, the forecast
   missed monthly demand by {f.normal_weather_miss:.1f}% on average. That is no better than
   assuming each month repeats the same month last year ({f.last_year_miss:.1f}%). Given the
   weather that actually happened, the miss falls to {f.actual_weather_miss:.1f}%.
2. *A smarter purchase plan saves little, and the saving is not certain.* The optimised plan cost
   ${f.optimised_cost:,.1f}M over the three years against ${f.rule_cost:,.1f}M for the usual
   rule of buying the forecast plus 5% and reserving emergency supply every winter. That saves
   {_signed_money(f.saving)}, or {saving_share:.1f}%. If storage must be refilled to the same
   level every year, the same comparison turns around and the optimised plan costs
   {_signed_money(f.strict_saving)} more.
3. *The plans differ most when demand surprises.* In every case tested up to
   {f.last_full_service_error:.0f}% more demand than forecast, every plan met all of it. At
   {f.shortfall_error:.0f}% more, the usual rule delivered {f.rule_service_at_shortfall:.1f}% of
   demand and the optimised plan {f.optimised_service_at_shortfall:.1f}%.
4. *Revenue landed close to the forecast, but only because large effects cancelled.* Actual
   revenue was {_signed_money(f.revenue_gap)} {_above_below(f.revenue_gap)} the
   ${f.forecast_revenue:,.1f}M forecast, a gap of {gap_share:.1f}%. Compared with the forecast,
   prices {_added_or_took_off(effects["price"])}, volume {_added_or_took_off(effects["volume"])},
   weather {_added_or_took_off(effects["weather"])} and the mix of home and business customers
   {_added_or_took_off(effects["mix"])}.

**What we recommend**

* Plan against a range of possible winters, not one forecast number. The weather is what the
  forecast could not know.
* Keep reserve capacity for a cold surprise of the size tested. The optimised plan did better
  exactly there.
* Weigh the purchase plan mainly on how it copes with a cold surprise. Its cost saving is small
  and depends on how storage is managed.
* Check the price assumptions in the budget first. Price was the largest source of the gap
  between forecast and actual revenue.

**What to keep in mind.** One weather station stands in for the whole state. The sizes of the
pipeline, storage and emergency supply, and their fees and penalties, are assumptions, not
measurements. The budget price is an assumption too. Three years of data is a small sample.
"""
