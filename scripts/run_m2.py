"""Milestone 2: compare supply plans on the M1 forecast and write OPTIMISATION.md.

Needs the outputs of run_m1.py (results/m1_*). Every number in OPTIMISATION.md is
computed here. Run from the repo root:  python scripts/run_m2.py
"""

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from forecast_to_decision.data import SECTORS, build_dataset
from forecast_to_decision.model import BASE_TEMPS_F, Spec, add_lagged_weather
from forecast_to_decision.optimisation import (
    PEAKING_SHARE_OF_PEAK,
    PIPELINE_SHARE_OF_PEAK,
    STORAGE_SHARE_OF_ANNUAL_DEMAND,
    Commitments,
    Outcome,
    SupplyAssumptions,
    assumptions_from_scenarios,
    evaluate_commitments,
    perfect_hindsight_outcome,
    rule_of_thumb_commitments,
    solve_supply_plan,
)
from forecast_to_decision.optimisation_plots import plot_nominations, plot_sensitivity
from forecast_to_decision.scenarios import fit_sectors, plan_year_months, weather_year_scenarios

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results"
FIGURES_DIR = ROOT / "docs" / "figures"
DOC_PATH = ROOT / "OPTIMISATION.md"

RULE = "Rule of thumb"
OPTIMISED = "Optimised plan"
HINDSIGHT = "Perfect hindsight"
PLAN_NAMES = (RULE, OPTIMISED, HINDSIGHT)
FORECAST_ERRORS = (-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15)
RULE_RESERVE = 0.05
RULE_PEAKING_MONTHS = (12, 1, 2)


@dataclass
class PlanYear:
    """Everything known and unknown about one plan year."""

    label: str
    months: pd.DatetimeIndex
    scenarios: np.ndarray  # weather-year demand scenarios, MMcf
    assumptions: SupplyAssumptions
    prices: np.ndarray  # citygate price, $/Mcf
    forecast: np.ndarray  # M1 forecast under normal weather, MMcf
    actual: np.ndarray  # demand that happened, MMcf
    rule: Commitments
    optimised: Commitments


def load_plan_years() -> tuple[list[PlanYear], list[str]]:
    """Combine the M1 forecasts, the weather scenarios and prices into plan years.

    Also returns the months whose citygate price was missing and was filled by
    linear interpolation, so the document can say so.
    """
    specs = {
        sector: Spec(**fields)
        for sector, fields in json.loads((RESULTS_DIR / "m1_specs.json").read_text()).items()
    }
    tables = {base: add_lagged_weather(build_dataset(base_temp=base)) for base in BASE_TEMPS_F}
    fits = fit_sectors(tables, specs)

    holdouts = {
        sector: pd.read_csv(RESULTS_DIR / f"m1_{sector}_holdout.csv", index_col=0, parse_dates=True)
        for sector in SECTORS
    }
    total = sum(holdouts.values())
    prices = tables[BASE_TEMPS_F[0]]["citygate_price"].loc[total.index[0] : total.index[-1]]
    imputed_months = [f"{month:%Y-%m}" for month in prices[prices.isna()].index]
    prices = prices.interpolate(limit_area="inside")

    plan_years = []
    for months in plan_year_months(total.index):
        scenarios = weather_year_scenarios(fits, months)
        assumptions = assumptions_from_scenarios(scenarios)
        forecast = total.loc[months, "regression_normal_weather_mmcf"].to_numpy()
        month_prices = prices.loc[months].to_numpy()
        plan_years.append(
            PlanYear(
                label=f"{months[0]:%Y-%m} to {months[-1]:%Y-%m}",
                months=months,
                scenarios=scenarios,
                assumptions=assumptions,
                prices=month_prices,
                forecast=forecast,
                actual=total.loc[months, "actual_mmcf"].to_numpy(),
                rule=rule_of_thumb_commitments(
                    forecast, months.month.to_numpy(), assumptions, RULE_RESERVE, RULE_PEAKING_MONTHS
                ),
                optimised=solve_supply_plan(scenarios, month_prices, assumptions).commitments,
            )
        )
    return plan_years, imputed_months


def outcome_row(plan_year: str, plan: str, outcome: Outcome) -> dict:
    return {
        "plan_year": plan_year,
        "plan": plan,
        "cost_musd": outcome.total_cost_musd,
        "served_percent": outcome.served_fraction * 100,
        "shortfall_months": outcome.shortfall_months,
        "unserved_mmcf": outcome.unserved_mmcf,
        "peaking_mmcf": outcome.peaking_mmcf,
        "storage_withdrawn_mmcf": outcome.storage_withdrawn_mmcf,
        "surplus_resold_mmcf": outcome.surplus_resold_mmcf,
    }


def outcomes_for_demand(year: PlanYear, demand: np.ndarray) -> dict[str, Outcome]:
    """Run all three plans against one demand path."""
    return {
        RULE: evaluate_commitments(year.rule, demand, year.prices, year.assumptions),
        OPTIMISED: evaluate_commitments(year.optimised, demand, year.prices, year.assumptions),
        HINDSIGHT: perfect_hindsight_outcome(demand, year.prices, year.assumptions),
    }


def actual_demand_results(years: list[PlanYear]) -> pd.DataFrame:
    rows = []
    for year in years:
        for plan, outcome in outcomes_for_demand(year, year.actual).items():
            rows.append(outcome_row(year.label, plan, outcome))
    return pd.DataFrame(rows)


def weather_scenario_results(years: list[PlanYear]) -> pd.DataFrame:
    """Expected cost and service of the two real plans over the weather scenarios."""
    rows = []
    for year in years:
        for plan, commitments in ((RULE, year.rule), (OPTIMISED, year.optimised)):
            solved = solve_supply_plan(year.scenarios, year.prices, year.assumptions, commitments)
            rows.append(
                {
                    "plan_year": year.label,
                    "plan": plan,
                    "expected_cost_musd": solved.expected_cost_musd,
                    "expected_served_percent": np.mean(
                        [o.served_fraction for o in solved.outcomes]
                    )
                    * 100,
                    "scenarios_with_shortfall": sum(o.shortfall_months > 0 for o in solved.outcomes),
                    "scenarios": len(solved.outcomes),
                }
            )
    return pd.DataFrame(rows)


def strict_storage_results(years: list[PlanYear]) -> pd.DataFrame:
    """Repeat the comparison when storage must end each year as full as it began.

    The optimised plan is solved again under this rule, because the rule changes
    what the best plan is. The rule of thumb keeps its nominations.
    """
    rows = []
    for year in years:
        strict = replace(year.assumptions, require_cyclic_storage=True)
        optimised = solve_supply_plan(year.scenarios, year.prices, strict).commitments
        outcomes = {
            RULE: evaluate_commitments(year.rule, year.actual, year.prices, strict),
            OPTIMISED: evaluate_commitments(optimised, year.actual, year.prices, strict),
            HINDSIGHT: perfect_hindsight_outcome(year.actual, year.prices, strict),
        }
        for plan, outcome in outcomes.items():
            rows.append(outcome_row(year.label, plan, outcome))
    return pd.DataFrame(rows)


def sensitivity_results(years: list[PlanYear]) -> pd.DataFrame:
    """Plans are made on the forecast; realised demand is the forecast times (1 + error)."""
    rows = []
    for error in FORECAST_ERRORS:
        per_plan: dict[str, list[Outcome]] = {name: [] for name in PLAN_NAMES}
        for year in years:
            for plan, outcome in outcomes_for_demand(year, year.forecast * (1 + error)).items():
                per_plan[plan].append(outcome)
        for plan, outcomes in per_plan.items():
            rows.append(
                {
                    "forecast_error_percent": error * 100,
                    "plan": plan,
                    "cost_musd": np.mean([o.total_cost_musd for o in outcomes]),
                    "served_percent": np.mean([o.served_fraction for o in outcomes]) * 100,
                    "shortfall_months": np.mean([o.shortfall_months for o in outcomes]),
                }
            )
    return pd.DataFrame(rows)


def commitments_table(years: list[PlanYear]) -> pd.DataFrame:
    frames = []
    for year in years:
        frames.append(
            pd.DataFrame(
                {
                    "plan_year": year.label,
                    "month": year.months.strftime("%Y-%m"),
                    "price_per_mcf": year.prices,
                    "forecast_mmcf": year.forecast,
                    "actual_mmcf": year.actual,
                    "pipeline_capacity_mmcf": year.assumptions.pipeline_capacity,
                    "rule_nomination_mmcf": year.rule.nominations,
                    "rule_peaking": year.rule.peaking_active,
                    "optimised_nomination_mmcf": year.optimised.nominations,
                    "optimised_peaking": year.optimised.peaking_active,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def markdown_table(frame: pd.DataFrame, columns: dict[str, tuple[str, str]]) -> str:
    """Render a DataFrame as a Markdown table.

    `columns` lists, in display order, each column with its header text and format spec.
    """
    header = "| " + " | ".join(title for title, _ in columns.values()) + " |"
    divider = "|" + "---|" * len(columns)
    rows = [
        "| " + " | ".join(format(row[name], spec) for name, (_, spec) in columns.items()) + " |"
        for _, row in frame.iterrows()
    ]
    return "\n".join([header, divider, *rows])


TOTALS_COLUMNS = {
    "plan": ("Plan", ""),
    "cost_musd": ("Cost ($M)", ".1f"),
    "served_percent": ("Demand served (%)", ".2f"),
    "shortfall_months": ("Months with shortfall", "d"),
    "peaking_mmcf": ("Peaking gas used (MMcf)", ",.0f"),
}
PER_YEAR_COLUMNS = {"plan_year": ("Plan year", ""), **TOTALS_COLUMNS}
SCENARIO_COLUMNS = {
    "plan_year": ("Plan year", ""),
    "plan": ("Plan", ""),
    "expected_cost_musd": ("Expected cost ($M)", ".1f"),
    "expected_served_percent": ("Expected demand served (%)", ".2f"),
    "scenarios_with_shortfall": ("Scenarios with shortfall", "d"),
    "scenarios": ("Scenarios", "d"),
}


def error_columns(decimals: str) -> dict[str, tuple[str, str]]:
    """Columns for a table with one row per forecast error and one column per plan."""
    return {
        "forecast_error_percent": ("Realised demand vs forecast (%)", "+.0f"),
        **{plan: (plan, decimals) for plan in PLAN_NAMES},
    }


def totals_over_years(actual: pd.DataFrame, total_demand_mmcf: float) -> pd.DataFrame:
    totals = actual.groupby("plan", sort=False).agg(
        cost_musd=("cost_musd", "sum"),
        unserved_mmcf=("unserved_mmcf", "sum"),
        shortfall_months=("shortfall_months", "sum"),
        peaking_mmcf=("peaking_mmcf", "sum"),
    )
    totals["served_percent"] = (1 - totals["unserved_mmcf"] / total_demand_mmcf) * 100
    return totals.reset_index()[
        ["plan", "cost_musd", "served_percent", "shortfall_months", "peaking_mmcf"]
    ]


def assumptions_markdown(years: list[PlanYear]) -> str:
    a = years[0].assumptions

    def volumes(attribute: str) -> str:
        """The attribute for each plan year, for example '32,534, 32,534, 32,534 MMcf'."""
        values = [getattr(year.assumptions, attribute) for year in years]
        return ", ".join(f"{value:,.0f}" for value in values) + " MMcf"

    storage_capacity = (
        f"{STORAGE_SHARE_OF_ANNUAL_DEMAND:.0%} of expected annual demand: "
        f"{volumes('storage_capacity')}"
    )
    peaking_capacity = (
        f"{PEAKING_SHARE_OF_PEAK:.0%} of the expected peak month when contracted: "
        f"{volumes('peaking_capacity')}"
    )
    injection_limit = f"{a.storage_injection_limit_fraction:.0%}"
    withdrawal_limit = f"{a.storage_withdrawal_limit_fraction:.0%}"
    rows = [
        (
            "Pipeline capacity",
            f"{PIPELINE_SHARE_OF_PEAK:.0%} of the expected peak month: {volumes('pipeline_capacity')}",
        ),
        ("Pipeline minimum take", f"{a.pipeline_min_take_fraction:.0%} of capacity each month"),
        ("Storage working capacity", storage_capacity),
        ("Storage at the start of the plan year", f"{a.storage_start_fraction:.0%} full"),
        (
            "Storage injection and withdrawal limits",
            f"{injection_limit} and {withdrawal_limit} of capacity per month",
        ),
        (
            "Storage fees",
            f"${a.storage_injection_fee:.2f} per Mcf in, ${a.storage_withdrawal_fee:.2f} per Mcf out",
        ),
        ("Leftover storage gas", "valued at the plan year's average citygate price"),
        ("Peaking capacity", peaking_capacity),
        ("Peaking price", f"{a.peaking_price_multiple:.1f} times the citygate price"),
        ("Peaking standby fee", f"${a.peaking_standby_fee_musd:.1f}M per contracted month"),
        ("Cost of unserved demand", f"${a.unserved_penalty:.0f} per Mcf"),
        ("Resale of surplus gas", f"{a.surplus_resale_fraction:.0%} of the citygate price"),
        ("Pipeline gas price", "the month's EIA citygate price, treated as known in advance"),
    ]
    return "\n".join(["| Item | Value |", "|---|---|", *(f"| {k} | {v} |" for k, v in rows)])


FORMULATION = """\
**Sets and data.** Months `t = 1..12` of a plan year starting in September. Scenarios `s`,
one per historical weather year, each with equal probability `1/S`. Demand `D[s,t]` in MMcf,
citygate price `p[t]` in $/Mcf. The parameters named below are the assumptions in the table.

**First-stage decisions, made before the weather is known.**

```
x[t]  in [minTake, pipelineCap]    pipeline nomination, MMcf, bought at p[t]
y[t]  in {0, 1}                    1 if peaking supply is contracted in month t
```

**Second-stage decisions, made once the scenario is known, for every `s` and `t`.**

```
w[s,t] in [0, wLimit]      storage withdrawal
i[s,t] in [0, iLimit]      storage injection
v[s,t] in [0, storageCap]  storage inventory at the end of the month
g[s,t] >= 0                peaking gas called
r[s,t] >= 0                surplus gas resold
u[s,t] in [0, D[s,t]]      demand left unserved
```

**Constraints.**

```
x[t] + w[s,t] - i[s,t] + g[s,t] - r[s,t] + u[s,t] = D[s,t]     demand balance
v[s,t] = v[s,t-1] + i[s,t] - w[s,t],  v[s,0] = startFraction * storageCap
g[s,t] <= peakingCap * y[t]                                     peaking only if contracted
```

**Objective: minimise expected total cost, in $M.** A volume in MMcf times a price in $/Mcf is
thousands of dollars, so `k = 1/1000` converts those terms to $M. The standby fee is already in $M.

```
k * sum_t p[t] x[t] + standbyFee * sum_t y[t]
+ (k/S) * sum_s sum_t ( injFee*i + wdFee*w + peakMultiple*p[t]*g
                        + penalty*u - resaleFraction*p[t]*r )
- (k/S) * avgPrice * sum_s v[s,12]
```

The last term values the gas left in storage at the plan year's average price. Without it the
model would empty storage for free at the end of the year. The robustness section below replaces
it with a requirement that `v[s,12]` is at least the starting inventory.

Because `y` is binary, this is a mixed integer program. It is solved as one deterministic
equivalent problem with SCIP through OR-Tools. The same model, with `x` and `y` fixed and a
single demand path, scores any plan against what actually happened. With one demand path and
`x` and `y` free it gives the perfect hindsight cost, which no real plan can beat.
"""


def verdict(actual_totals: pd.DataFrame) -> str:
    cost = actual_totals.set_index("plan")["cost_musd"]
    saving = cost[RULE] - cost[OPTIMISED]
    gap = cost[RULE] - cost[HINDSIGHT]
    served = actual_totals.set_index("plan")["served_percent"]
    direction = "cheaper" if saving > 0 else "more expensive"
    sentence = (
        f"Over the three plan years the optimised plan cost ${cost[OPTIMISED]:.1f}M against "
        f"${cost[RULE]:.1f}M for the rule of thumb, which is ${abs(saving):.1f}M {direction}. "
        f"Perfect hindsight cost ${cost[HINDSIGHT]:.1f}M. "
    )
    if abs(served[OPTIMISED] - served[RULE]) < 0.005:
        sentence += f"Both plans served {served[RULE]:.2f}% of demand."
    else:
        sentence += (
            f"The optimised plan served {served[OPTIMISED]:.2f}% of demand against "
            f"{served[RULE]:.2f}% for the rule of thumb."
        )
    if saving > 0 and gap > 0:
        sentence += f" It closes {saving / gap * 100:.0f}% of the gap between the rule and hindsight."
    return sentence


def strict_storage_verdict(strict_totals: pd.DataFrame) -> str:
    cost = strict_totals.set_index("plan")["cost_musd"]
    saving = cost[RULE] - cost[OPTIMISED]
    if saving > 0:
        outcome = f"the optimised plan is ${saving:.1f}M cheaper than the rule of thumb"
    else:
        outcome = f"the optimised plan is ${-saving:.1f}M more expensive than the rule of thumb"
    return (
        f"Under this rule the three plans cost ${cost[RULE]:.1f}M (rule of thumb), "
        f"${cost[OPTIMISED]:.1f}M (optimised) and ${cost[HINDSIGHT]:.1f}M (perfect hindsight), so "
        f"{outcome}. The size and even the sign of the saving depend on how leftover storage gas "
        "is treated."
    )


def sensitivity_verdict(sensitivity: pd.DataFrame) -> str:
    """Say where the plans differ most: the largest demand surprise in each direction."""
    cost = sensitivity.pivot(index="forecast_error_percent", columns="plan", values="cost_musd")
    served = sensitivity.pivot(
        index="forecast_error_percent", columns="plan", values="served_percent"
    )
    parts = []
    for error in (cost.index.max(), cost.index.min()):
        parts.append(
            f"At {error:+.0f}% the rule of thumb costs ${cost.loc[error, RULE]:.1f}M and serves "
            f"{served.loc[error, RULE]:.2f}% of demand, the optimised plan ${cost.loc[error, OPTIMISED]:.1f}M "
            f"and {served.loc[error, OPTIMISED]:.2f}%, and perfect hindsight "
            f"${cost.loc[error, HINDSIGHT]:.1f}M."
        )
    return " ".join(parts)


def write_document(
    years: list[PlanYear],
    actual: pd.DataFrame,
    totals: pd.DataFrame,
    scenarios: pd.DataFrame,
    sensitivity: pd.DataFrame,
    strict_totals: pd.DataFrame,
    imputed_price_months: list[str],
) -> None:
    imputed_note = (
        f"* The EIA citygate price is missing for {', '.join(imputed_price_months)}. It was filled "
        "by linear interpolation between the neighbouring months."
        if imputed_price_months
        else ""
    )
    sensitivity_view = sensitivity.pivot(
        index="forecast_error_percent", columns="plan", values="cost_musd"
    )[list(PLAN_NAMES)].reset_index()
    service_view = sensitivity.pivot(
        index="forecast_error_percent", columns="plan", values="served_percent"
    )[list(PLAN_NAMES)].reset_index()

    DOC_PATH.write_text(
        f"""# Milestone 2: supply plan optimisation

A gas utility must decide, before winter, how much pipeline gas to buy each month and whether
to contract peaking supply. The M1 forecast sets the expected demand. This milestone turns that
forecast into a plan, then compares the plan with a simple rule of thumb on cost and service
level. Regenerate with `python scripts/run_m2.py` after `python scripts/run_m1.py`.

## Formulation

{FORMULATION}
## Assumptions

The data sources supply demand, weather and citygate prices. Everything else below is an
assumption chosen to make the problem realistic, not a measured fact. The results depend on
these numbers, so change them in `SupplyAssumptions` and rerun to test other cases.

{assumptions_markdown(years)}

## The plans compared

* **Rule of thumb.** Buy the M1 normal-weather forecast plus a {RULE_RESERVE:.0%} reserve each
  month, within the pipeline's minimum take and capacity. Contract peaking in December, January
  and February.
* **Optimised plan.** The stochastic program above, over {len(years[0].scenarios)} demand
  scenarios. Each scenario is a past winter's weather (September to August) run through the M1
  regressions. Only weather from before the M1 forecast origin is used.
* **Perfect hindsight.** The cheapest plan if the realised demand had been known in advance.
  It is a floor, not a plan anyone could make.

All three face the same limits, and every plan is scored with the best storage, peaking and
resale decisions for the demand that happened.

## Results on the demand that happened

Plan years run September to August over the M1 holdout. Demand is the actual EIA residential
plus commercial deliveries. Service is the share of demand delivered.

{markdown_table(totals, TOTALS_COLUMNS)}

{verdict(totals)}

By plan year:

{markdown_table(actual, PER_YEAR_COLUMNS)}

![Nominations by plan](docs/figures/m2_nominations.png)

## Results over the weather scenarios

The same two plans, scored on the {len(years[0].scenarios)} weather scenarios the optimiser
saw. This isolates weather risk from model error.

The scenarios differ between plan years only in days per month, so the three plan years see
nearly the same weather risk.

{markdown_table(scenarios, SCENARIO_COLUMNS)}

## Sensitivity to forecast error

Both plans are made on the forecast. Realised demand is then the forecast times (1 + error)
in every month, averaged over the three plan years. The hindsight column re-plans for each
error. The gap to it is not only the cost of a wrong forecast: at 0% error the rule of thumb
and the optimised plan are still above it, because a plan made for the average case is not the
best plan for any single case.

Cost per plan year, $M:

{markdown_table(sensitivity_view, error_columns(".1f"))}

Share of demand served, %:

{markdown_table(service_view, error_columns(".2f"))}

{sensitivity_verdict(sensitivity)}

## Robustness to the end-of-year storage rule

The main results let a plan end the year with less gas in storage than it began with, and value
the leftover gas at the plan year's average price. A stricter rule requires storage to end
each year at least as full as it began, with leftover gas earning nothing. The optimised plan
is solved again under that rule. Totals over the three plan years, on actual demand:

{markdown_table(strict_totals, TOTALS_COLUMNS)}

{strict_storage_verdict(strict_totals)}

![Sensitivity to forecast error](docs/figures/m2_sensitivity.png)

## Limitations

* The infrastructure sizes, fees and penalties are assumptions. A different penalty for unserved
  demand or a different standby fee can change which plan wins.
* Pipeline gas is priced at the month's realised citygate price, so price risk is out of scope.
  Only demand is uncertain.
* In this EIA series the Massachusetts citygate price is usually at or above its winter level in
  summer. Averaged over 1989 to 1999, 2000 to 2012, 2013 to 2023 and 2024 to 2026, summer is
  higher in every period, although not in every single year. The plans respond to that price
  shape, so the usual buy cheap in summer and store logic is weak here. A different price series
  would change the storage behaviour.
* The saving depends on the end-of-year storage rule (see the robustness section above).
{imputed_note}
* The scenarios hold the weather of a past year fixed across the whole plan year and ignore the
  M1 model's own error, which is why the error sensitivity above is reported separately.
* Storage and peaking are dispatched with knowledge of the whole year's demand, which flatters
  every plan equally. Real operations dispatch month by month.
* Monthly steps hide the daily peaks that drive real peaking decisions.
* Three plan years are a small sample.
""",
        encoding="utf-8",
    )


def main() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    years, imputed_price_months = load_plan_years()

    actual = actual_demand_results(years)
    totals = totals_over_years(actual, sum(year.actual.sum() for year in years))
    scenarios = weather_scenario_results(years)
    sensitivity = sensitivity_results(years)
    strict = strict_storage_results(years)
    strict_totals = totals_over_years(strict, sum(year.actual.sum() for year in years))
    commitments = commitments_table(years)

    actual.to_csv(RESULTS_DIR / "m2_plan_comparison.csv", index=False, float_format="%.3f")
    scenarios.to_csv(RESULTS_DIR / "m2_weather_scenarios.csv", index=False, float_format="%.3f")
    sensitivity.to_csv(RESULTS_DIR / "m2_sensitivity.csv", index=False, float_format="%.3f")
    commitments.to_csv(RESULTS_DIR / "m2_commitments.csv", index=False, float_format="%.1f")
    (RESULTS_DIR / "m2_assumptions.json").write_text(
        json.dumps({y.label: asdict(y.assumptions) for y in years}, indent=2), encoding="utf-8"
    )
    plot_nominations(commitments, FIGURES_DIR / "m2_nominations.png")
    plot_sensitivity(sensitivity, FIGURES_DIR / "m2_sensitivity.png")
    strict.to_csv(RESULTS_DIR / "m2_strict_storage.csv", index=False, float_format="%.3f")
    write_document(years, actual, totals, scenarios, sensitivity, strict_totals, imputed_price_months)
    print(totals.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
