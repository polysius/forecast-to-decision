"""The one page business summary, written for a reader with no statistics background.

Every number comes from the results tables. Each recommendation rests on specific
findings, so `check_findings` raises an error if the data no longer supports them.
That way a rerun with different results cannot quietly publish advice that is wrong.
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from forecast_to_decision.datasets import RESULTS_DIR, ReportingTables, load_m1_column

RULE, OPTIMISED, HINDSIGHT = "Rule of thumb", "Optimised plan", "Perfect hindsight"
EFFECTS = ("weather", "volume", "mix", "price")
FULL_SERVICE_PERCENT = 99.995
CLOSE_TO_FORECAST_SHARE = 0.02
SMALL_SAVING_SHARE = 0.01
ALIKE_SERVICE_POINTS = 0.05


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
    last_full_service_error: float  # largest tested error below that, where all plans met demand
    max_error: float
    rule_service_at_shortfall: float
    optimised_service_at_shortfall: float
    scenarios: int  # past winters tested
    rule_short_scenarios: int  # winters in which the plan fell short, worst plan year
    optimised_short_scenarios: int
    rule_scenario_service: float  # average share of demand delivered across winters, percent
    optimised_scenario_service: float
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

    @property
    def weather_share_of_miss(self) -> float:
        """Share of the normal-weather miss that disappears when the weather is known."""
        return (self.normal_weather_miss - self.actual_weather_miss) / self.normal_weather_miss


def _average_miss_percent(actual: pd.Series, forecast: pd.Series) -> float:
    return float(((actual - forecast).abs() / actual).mean() * 100)


def _plan_cost(frame: pd.DataFrame, plan: str) -> float:
    return float(frame.loc[frame["plan"] == plan, "cost_musd"].sum())


def compute_findings(tables: ReportingTables, results_dir: Path = RESULTS_DIR) -> Findings:
    actual = load_m1_column("actual_mmcf", results_dir).sum(axis=1)
    misses = {
        name: _average_miss_percent(actual, load_m1_column(column, results_dir).sum(axis=1))
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

    scenarios = pd.read_csv(results_dir / "m2_weather_scenarios.csv").groupby("plan")
    short_scenarios = scenarios["scenarios_with_shortfall"].max()
    scenario_service = scenarios["expected_served_percent"].mean()

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
        scenarios=int(pd.read_csv(results_dir / "m2_weather_scenarios.csv")["scenarios"].max()),
        rule_short_scenarios=int(short_scenarios[RULE]),
        optimised_short_scenarios=int(short_scenarios[OPTIMISED]),
        rule_scenario_service=float(scenario_service[RULE]),
        optimised_scenario_service=float(scenario_service[OPTIMISED]),
        forecast_revenue=float(sector["forecast_revenue_musd"].sum()),
        actual_revenue=float(sector["actual_revenue_musd"].sum()),
        effects={name: float(variance[f"{name}_musd"].sum()) for name in EFFECTS},
    )


def check_findings(f: Findings) -> None:
    """Raise if a finding that a sentence or recommendation depends on no longer holds."""
    problems = []
    if not f.normal_weather_miss >= f.last_year_miss:
        problems.append("the forecast now beats 'same month last year' (item 1, recommendation 1)")
    if not f.actual_weather_miss < f.normal_weather_miss:
        problems.append("knowing the weather no longer reduces the miss (item 1)")
    if not (f.saving > 0 and f.strict_saving <= 0):
        problems.append("the saving no longer flips sign under the strict storage rule (item 2)")
    if not f.saving / f.rule_cost <= SMALL_SAVING_SHARE:
        problems.append("the saving is no longer small (item 2, recommendation 3)")
    both_alike = (
        f.rule_short_scenarios == f.optimised_short_scenarios
        and abs(f.rule_scenario_service - f.optimised_scenario_service) <= ALIKE_SERVICE_POINTS
    )
    if not both_alike:
        problems.append("the plans no longer behave alike across past winters (item 3)")
    if not (
        f.shortfall_error == f.max_error
        and f.optimised_service_at_shortfall > f.rule_service_at_shortfall
    ):
        problems.append("the plans no longer separate only at the largest demand surprise (item 3)")
    largest = max(f.effects, key=lambda name: abs(f.effects[name]))
    if largest != "price":
        problems.append(f"the largest revenue effect is now {largest}, not price (recommendation 4)")
    if not abs(f.revenue_gap) / f.forecast_revenue <= CLOSE_TO_FORECAST_SHARE:
        problems.append("revenue is no longer within 2% of the forecast (item 4)")
    if problems:
        raise ValueError("Rewrite the business summary: " + "; ".join(problems))


def _signed_money(value: float) -> str:
    return f"${abs(value):,.1f}M"


def _above_below(value: float) -> str:
    return "above" if value > 0 else "below"


def _added_or_took_off(value: float) -> str:
    return f"added {_signed_money(value)}" if value > 0 else f"took off {_signed_money(value)}"


def business_summary(tables: ReportingTables, results_dir: Path = RESULTS_DIR) -> str:
    f = compute_findings(tables, results_dir)
    check_findings(f)
    effects = f.effects
    gap_share = abs(f.revenue_gap) / f.forecast_revenue * 100
    saving_share = f.saving / f.rule_cost * 100
    return f"""# What this analysis means for the business

**The question.** A gas utility must decide months ahead how much gas to buy, and whether to
reserve emergency supply for the coldest weeks, without knowing the weather. This analysis asks
how well demand can be forecast, what the best purchasing plan looks like, and why revenue ends
up different from the forecast. It covers three years of Massachusetts gas deliveries to homes
and businesses (September 2023 to August 2026).

**What we found**

1. *The weather matters, but it is not the whole story.* Assuming normal weather, the forecast
   missed monthly demand by {f.normal_weather_miss:.1f}% on average, worse than assuming each
   month repeats the same month last year ({f.last_year_miss:.1f}%). Even with the weather that
   actually happened it missed by {f.actual_weather_miss:.1f}%. Knowing the weather removes
   {f.weather_share_of_miss:.0%} of the miss, and the rest is the forecast's own error.
2. *A smarter purchase plan saves little, and the saving is not certain.* The optimised plan cost
   ${f.optimised_cost:,.1f}M over three years against ${f.rule_cost:,.1f}M for the usual rule
   (buy the forecast plus 5% and reserve emergency supply every winter), saving
   {_signed_money(f.saving)}, or {saving_share:.1f}%. If storage must be refilled to the same
   level every year, the optimised plan costs {_signed_money(f.strict_saving)} more instead.
3. *Past winters did not separate the plans. A large demand surprise did.* Tested against
   {f.scenarios} past winters, both plans fell short in {f.optimised_short_scenarios} and
   delivered {f.optimised_scenario_service:.2f}% of demand on average. With demand
   {f.shortfall_error:.0f}% above the forecast in every month, the usual rule delivered
   {f.rule_service_at_shortfall:.1f}% and the optimised plan {f.optimised_service_at_shortfall:.1f}%.
   Up to {f.last_full_service_error:.0f}% above, every plan met all demand.
4. *Revenue landed close to the forecast, but only because large effects cancelled.* Actual
   revenue was {_signed_money(f.revenue_gap)} {_above_below(f.revenue_gap)} the
   ${f.forecast_revenue:,.1f}M forecast, a gap of {gap_share:.1f}%. Compared with the forecast,
   prices {_added_or_took_off(effects["price"])}, volume {_added_or_took_off(effects["volume"])},
   weather {_added_or_took_off(effects["weather"])} and the mix of home and business customers
   {_added_or_took_off(effects["mix"])}.

**What we recommend**

* Plan against a range of possible winters, not one forecast number. A single normal-weather
  forecast was no more accurate than last year's pattern.
* Stress test the plan against a demand surprise. A {f.shortfall_error:.0f}% surprise was the only
  case that separated the plans, and the optimised plan held up better.
* Weigh the purchase plan on how it copes with surprises, not on its small cost saving, which
  depends on how storage is managed.
* Check the budget's price assumptions first. Price was the largest of the effects that moved
  revenue away from the forecast, even though it pushed revenue up.

**What to keep in mind.** One weather station stands in for the whole state. The sizes of the
pipeline, storage and emergency supply, their fees and penalties, and the budget price are
assumptions, not measurements. Three years of data is a small sample.
"""
