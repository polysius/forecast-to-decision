import numpy as np
import pytest

from forecast_to_decision.optimisation import (
    Commitments,
    SupplyAssumptions,
    assumptions_from_scenarios,
    evaluate_commitments,
    perfect_hindsight_outcome,
    rule_of_thumb_commitments,
    solve_supply_plan,
)

N_MONTHS = 4
PRICES = np.full(N_MONTHS, 10.0)


def make_assumptions(**overrides) -> SupplyAssumptions:
    """Small, easy to reason about: 100 MMcf pipeline, no storage, no peaking."""
    settings = {
        "pipeline_capacity": 100.0,
        "storage_capacity": 0.0,
        "peaking_capacity": 0.0,
        "pipeline_min_take_fraction": 0.0,
    }
    settings.update(overrides)
    return SupplyAssumptions(**settings)


def test_demand_within_pipeline_capacity_costs_the_gas_bought():
    demand = np.array([40.0, 50.0, 60.0, 70.0])

    plan = solve_supply_plan(demand, PRICES, make_assumptions())

    assert plan.expected_cost_musd == pytest.approx(demand.sum() * 10 / 1000)
    assert plan.outcomes[0].served_fraction == pytest.approx(1)
    assert not plan.commitments.peaking_active.any()


def test_missing_prices_are_rejected_instead_of_solved():
    demand = np.array([40.0, 50.0, 60.0, 70.0])
    prices = np.array([10.0, np.nan, 10.0, 10.0])

    with pytest.raises(ValueError, match="finite"):
        solve_supply_plan(demand, prices, make_assumptions())


def test_demand_above_pipeline_capacity_without_other_supply_goes_unserved():
    demand = np.array([100.0, 150.0, 100.0, 100.0])

    outcome = solve_supply_plan(demand, PRICES, make_assumptions()).outcomes[0]

    assert outcome.unserved_mmcf == pytest.approx(50)
    assert outcome.shortfall_months == 1


def test_peaking_is_contracted_only_when_it_is_cheaper_than_the_shortfall():
    demand = np.array([100.0, 130.0, 100.0, 100.0])
    assumptions = make_assumptions(peaking_capacity=30.0, peaking_standby_fee_musd=0.1)

    plan = solve_supply_plan(demand, PRICES, assumptions)

    assert plan.commitments.peaking_active.tolist() == [False, True, False, False]
    assert plan.outcomes[0].peaking_mmcf == pytest.approx(30)


def test_peaking_standby_fee_is_not_paid_when_peaking_is_not_needed():
    demand = np.array([50.0, 50.0, 50.0, 50.0])
    assumptions = make_assumptions(peaking_capacity=30.0)

    plan = solve_supply_plan(demand, PRICES, assumptions)

    assert not plan.commitments.peaking_active.any()


def test_storage_moves_cheap_summer_gas_to_a_winter_peak():
    prices = np.array([5.0, 5.0, 20.0, 20.0])
    demand = np.array([50.0, 50.0, 150.0, 150.0])
    assumptions = make_assumptions(
        storage_capacity=100.0,
        storage_start_fraction=0.0,
        storage_injection_limit_fraction=1.0,
        storage_withdrawal_limit_fraction=1.0,
        storage_injection_fee=0.0,
        storage_withdrawal_fee=0.0,
    )

    outcome = solve_supply_plan(demand, prices, assumptions).outcomes[0]

    assert outcome.storage_withdrawn_mmcf > 0
    assert outcome.served_fraction == pytest.approx(1)


def test_fixed_commitments_are_respected():
    demand = np.array([60.0, 60.0, 60.0, 60.0])
    commitments = Commitments(
        nominations=np.array([80.0, 80.0, 80.0, 80.0]), peaking_active=np.zeros(4, dtype=bool)
    )

    plan = solve_supply_plan(demand, PRICES, make_assumptions(), fixed=commitments)

    np.testing.assert_allclose(plan.commitments.nominations, commitments.nominations)
    assert plan.outcomes[0].surplus_resold_mmcf == pytest.approx(80)


def test_over_buying_costs_more_than_buying_what_is_needed():
    demand = np.array([60.0, 60.0, 60.0, 60.0])
    assumptions = make_assumptions()
    exact = Commitments(demand.copy(), np.zeros(4, dtype=bool))
    generous = Commitments(demand + 30, np.zeros(4, dtype=bool))

    exact_cost = evaluate_commitments(exact, demand, PRICES, assumptions).total_cost_musd
    generous_cost = evaluate_commitments(generous, demand, PRICES, assumptions).total_cost_musd

    assert generous_cost > exact_cost


def test_perfect_hindsight_is_never_costlier_than_any_fixed_plan():
    demand = np.array([60.0, 90.0, 120.0, 70.0])
    assumptions = make_assumptions(peaking_capacity=30.0)
    forecast = np.array([70.0, 70.0, 70.0, 70.0])
    rule = rule_of_thumb_commitments(forecast, np.array([9, 10, 11, 12]), assumptions)

    floor = perfect_hindsight_outcome(demand, PRICES, assumptions).total_cost_musd
    rule_cost = evaluate_commitments(rule, demand, PRICES, assumptions).total_cost_musd

    assert floor <= rule_cost + 1e-9


def test_rule_of_thumb_adds_a_reserve_caps_at_the_pipeline_and_contracts_winter_peaking():
    assumptions = make_assumptions()
    forecast = np.array([50.0, 90.0, 99.0, 40.0])

    rule = rule_of_thumb_commitments(forecast, np.array([9, 12, 1, 5]), assumptions)

    np.testing.assert_allclose(rule.nominations, [52.5, 94.5, 100.0, 42.0])
    assert rule.peaking_active.tolist() == [False, True, True, False]


def test_stochastic_plan_covers_a_likely_cold_scenario():
    mild = np.array([50.0, 50.0, 50.0, 50.0])
    cold = np.array([50.0, 50.0, 130.0, 50.0])
    assumptions = make_assumptions(
        pipeline_capacity=100.0, peaking_capacity=30.0, peaking_standby_fee_musd=0.1
    )

    plan = solve_supply_plan(np.array([mild, cold, cold, cold]), PRICES, assumptions)

    assert plan.commitments.peaking_active[2]


def test_assumptions_scale_with_expected_demand():
    scenarios = np.array([[10.0, 40.0, 20.0], [10.0, 60.0, 20.0]])

    assumptions = assumptions_from_scenarios(scenarios)

    assert assumptions.pipeline_capacity == pytest.approx(0.8 * 50)
    assert assumptions.storage_capacity == pytest.approx(0.12 * 80)
    assert assumptions.peaking_capacity == pytest.approx(0.08 * 50)
