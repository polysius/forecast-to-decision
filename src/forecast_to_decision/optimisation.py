"""A gas utility's monthly supply plan as a two-stage mixed integer program.

Before the plan year starts the utility commits to two things for every month:

* a pipeline nomination, the volume it buys at that month's citygate price,
* whether to contract peaking supply (LNG or propane) for that month, which
  costs a standby fee. This is the integer decision.

Once the weather and so the demand are known, it adjusts the rest at the
lowest cost: how much to withdraw from or inject into storage, how much
peaking gas to call, how much surplus gas to resell, and how much demand goes
unserved. `solve_supply_plan` handles both cases:

* many demand scenarios and free commitments: the plan that minimises
  expected cost,
* one demand path and fixed commitments: what a given plan costs when that
  demand happens.

Volumes are in MMcf per month, prices in dollars per Mcf, costs in millions
of dollars. Every assumption lives in `SupplyAssumptions`.
"""

from dataclasses import dataclass

import numpy as np
from ortools.linear_solver import pywraplp

# MMcf x $/Mcf is thousands of dollars, so divide by 1000 for millions.
MMCF_PRICE_TO_MUSD = 1 / 1000
SHORTFALL_TOLERANCE_MMCF = 1e-4

# How `assumptions_from_scenarios` sizes the infrastructure.
PIPELINE_SHARE_OF_PEAK = 0.8
STORAGE_SHARE_OF_ANNUAL_DEMAND = 0.12
PEAKING_SHARE_OF_PEAK = 0.08


@dataclass(frozen=True)
class SupplyAssumptions:
    """Physical limits and prices. None of these come from the data sources."""

    pipeline_capacity: float  # MMcf per month
    storage_capacity: float  # MMcf of working gas
    peaking_capacity: float  # MMcf per month when contracted
    pipeline_min_take_fraction: float = 0.3  # take-or-pay share of capacity
    storage_start_fraction: float = 0.8  # share full on the first day of the plan year
    storage_injection_limit_fraction: float = 0.25  # of capacity per month
    storage_withdrawal_limit_fraction: float = 0.35  # of capacity per month
    storage_injection_fee: float = 0.15  # $/Mcf
    storage_withdrawal_fee: float = 0.10  # $/Mcf
    peaking_price_multiple: float = 2.0  # of the citygate price
    peaking_standby_fee_musd: float = 2.0  # per contracted month
    unserved_penalty: float = 60.0  # $/Mcf, the cost of failing to deliver
    surplus_resale_fraction: float = 0.5  # of the citygate price

    @property
    def pipeline_min_take(self) -> float:
        return self.pipeline_capacity * self.pipeline_min_take_fraction


def assumptions_from_scenarios(demand_scenarios: np.ndarray) -> SupplyAssumptions:
    """Size the infrastructure relative to what the planner expects to deliver.

    The pipeline covers part of the expected peak month and the gap is what
    storage and peaking fill. See the three share constants above.
    """
    expected_demand = np.atleast_2d(demand_scenarios).mean(axis=0)
    peak = expected_demand.max()
    return SupplyAssumptions(
        pipeline_capacity=PIPELINE_SHARE_OF_PEAK * peak,
        storage_capacity=STORAGE_SHARE_OF_ANNUAL_DEMAND * expected_demand.sum(),
        peaking_capacity=PEAKING_SHARE_OF_PEAK * peak,
    )


@dataclass(frozen=True)
class Commitments:
    """The decisions made before the weather is known."""

    nominations: np.ndarray  # MMcf per month
    peaking_active: np.ndarray  # True for each contracted month


@dataclass(frozen=True)
class Outcome:
    """What one demand path cost and delivered under a set of commitments."""

    total_cost_musd: float
    unserved_mmcf: float
    served_fraction: float
    shortfall_months: int
    peaking_mmcf: float
    storage_withdrawn_mmcf: float
    surplus_resold_mmcf: float


@dataclass(frozen=True)
class SolvedPlan:
    commitments: Commitments
    expected_cost_musd: float
    outcomes: list[Outcome]


@dataclass
class _RecourseVariables:
    """The after-the-weather decisions for one scenario."""

    withdraw: list
    inject: list
    inventory: list
    peaking: list
    unserved: list
    surplus: list


def _add_recourse(
    solver: pywraplp.Solver,
    demand: np.ndarray,
    prices: np.ndarray,
    assumptions: SupplyAssumptions,
    nominations: list,
    peaking_active: list,
) -> tuple[_RecourseVariables, pywraplp.LinearExpr]:
    """Add one scenario's variables and constraints; return them with its cost."""
    a = assumptions
    months = range(len(demand))
    start_inventory = a.storage_start_fraction * a.storage_capacity
    terminal_value = prices.mean()  # leftover gas is worth the average price

    v = _RecourseVariables(
        withdraw=[
            solver.NumVar(0, a.storage_withdrawal_limit_fraction * a.storage_capacity, "")
            for _ in months
        ],
        inject=[
            solver.NumVar(0, a.storage_injection_limit_fraction * a.storage_capacity, "")
            for _ in months
        ],
        inventory=[solver.NumVar(0, a.storage_capacity, "") for _ in months],
        peaking=[solver.NumVar(0, solver.infinity(), "") for _ in months],
        unserved=[solver.NumVar(0, float(demand[t]), "") for t in months],
        surplus=[solver.NumVar(0, solver.infinity(), "") for _ in months],
    )

    for t in months:
        # Gas delivered to customers: what is bought and withdrawn, less what
        # is injected or resold, plus peaking gas. Demand not met is unserved.
        solver.Add(
            nominations[t] + v.withdraw[t] - v.inject[t] + v.peaking[t] - v.surplus[t]
            + v.unserved[t]
            == float(demand[t])
        )
        previous = start_inventory if t == 0 else v.inventory[t - 1]
        solver.Add(v.inventory[t] == previous + v.inject[t] - v.withdraw[t])
        solver.Add(v.peaking[t] <= a.peaking_capacity * peaking_active[t])

    cost = sum(
        a.storage_injection_fee * v.inject[t]
        + a.storage_withdrawal_fee * v.withdraw[t]
        + a.peaking_price_multiple * prices[t] * v.peaking[t]
        + a.unserved_penalty * v.unserved[t]
        - a.surplus_resale_fraction * prices[t] * v.surplus[t]
        for t in months
    ) - terminal_value * v.inventory[len(demand) - 1]
    return v, cost * MMCF_PRICE_TO_MUSD


def solve_supply_plan(
    demand_scenarios: np.ndarray,
    prices: np.ndarray,
    assumptions: SupplyAssumptions,
    fixed: Commitments | None = None,
) -> SolvedPlan:
    """Minimise expected cost over the scenarios, optionally with commitments fixed."""
    demand_scenarios = np.atleast_2d(demand_scenarios)
    if not (np.isfinite(demand_scenarios).all() and np.isfinite(prices).all()):
        raise ValueError("Demand and prices must be finite; fill or drop missing months first")
    n_months = demand_scenarios.shape[1]
    months = range(n_months)

    solver = pywraplp.Solver.CreateSolver("SCIP")
    if fixed is None:
        nominations = [
            solver.NumVar(assumptions.pipeline_min_take, assumptions.pipeline_capacity, "")
            for _ in months
        ]
        peaking_active = [solver.BoolVar("") for _ in months]
    else:
        # Fixed commitments are constants, which leaves a plain linear program.
        nominations = [float(volume) for volume in fixed.nominations]
        peaking_active = [int(active) for active in fixed.peaking_active]

    first_stage_cost = (
        sum(prices[t] * nominations[t] for t in months) * MMCF_PRICE_TO_MUSD
        + assumptions.peaking_standby_fee_musd * sum(peaking_active)
    )

    recourse = [
        _add_recourse(solver, demand, prices, assumptions, nominations, peaking_active)
        for demand in demand_scenarios
    ]

    average_recourse = sum(cost for _, cost in recourse) * (1 / len(recourse))
    solver.Minimize(first_stage_cost + average_recourse)

    if solver.Solve() != pywraplp.Solver.OPTIMAL:
        raise RuntimeError("The supply plan has no optimal solution")

    if fixed is None:
        chosen = Commitments(
            nominations=np.array([x.solution_value() for x in nominations]),
            peaking_active=np.array([y.solution_value() > 0.5 for y in peaking_active]),
        )
    else:
        chosen = fixed
    first_stage = (
        float(np.dot(prices, chosen.nominations)) * MMCF_PRICE_TO_MUSD
        + assumptions.peaking_standby_fee_musd * int(chosen.peaking_active.sum())
    )
    outcomes = [
        _read_outcome(variables, cost.solution_value() + first_stage, demand)
        for (variables, cost), demand in zip(recourse, demand_scenarios, strict=True)
    ]
    expected_cost = float(np.mean([outcome.total_cost_musd for outcome in outcomes]))
    return SolvedPlan(chosen, expected_cost, outcomes)


def _read_outcome(variables: _RecourseVariables, total_cost: float, demand: np.ndarray) -> Outcome:
    unserved = np.array([u.solution_value() for u in variables.unserved])
    return Outcome(
        total_cost_musd=total_cost,
        unserved_mmcf=float(unserved.sum()),
        served_fraction=float(1 - unserved.sum() / demand.sum()),
        shortfall_months=int((unserved > SHORTFALL_TOLERANCE_MMCF).sum()),
        peaking_mmcf=float(sum(p.solution_value() for p in variables.peaking)),
        storage_withdrawn_mmcf=float(sum(w.solution_value() for w in variables.withdraw)),
        surplus_resold_mmcf=float(sum(s.solution_value() for s in variables.surplus)),
    )


def rule_of_thumb_commitments(
    forecast: np.ndarray,
    calendar_months: np.ndarray,
    assumptions: SupplyAssumptions,
    reserve_fraction: float = 0.05,
    peaking_months: tuple[int, ...] = (12, 1, 2),
) -> Commitments:
    """A planner's usual plan: buy the forecast plus a reserve, contract peaking in winter.

    Nominations are limited to the pipeline's minimum take and capacity.
    """
    nominations = np.clip(
        forecast * (1 + reserve_fraction),
        assumptions.pipeline_min_take,
        assumptions.pipeline_capacity,
    )
    return Commitments(
        nominations=nominations,
        peaking_active=np.isin(calendar_months, peaking_months),
    )


def evaluate_commitments(
    commitments: Commitments,
    demand: np.ndarray,
    prices: np.ndarray,
    assumptions: SupplyAssumptions,
) -> Outcome:
    """Cost and service when `demand` happens after `commitments` were made."""
    return solve_supply_plan(demand, prices, assumptions, fixed=commitments).outcomes[0]


def perfect_hindsight_outcome(
    demand: np.ndarray, prices: np.ndarray, assumptions: SupplyAssumptions
) -> Outcome:
    """The cheapest possible plan if the demand had been known in advance.

    No real plan can reach this cost, so it is the floor that measures how
    much the uncertainty about demand costs.
    """
    return solve_supply_plan(demand, prices, assumptions).outcomes[0]
