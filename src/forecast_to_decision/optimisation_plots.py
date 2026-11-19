"""Plots for the supply plan comparison."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # write files only, no display needed

import matplotlib.pyplot as plt
import pandas as pd


def plot_nominations(commitments: pd.DataFrame, path: Path) -> None:
    """One panel per plan year: demand against what each plan buys from the pipeline."""
    plan_years = commitments["plan_year"].unique()
    figure, axes = plt.subplots(len(plan_years), 1, figsize=(10, 3.4 * len(plan_years)))
    for axis, plan_year in zip(axes, plan_years, strict=True):
        year = commitments[commitments["plan_year"] == plan_year]
        months = pd.to_datetime(year["month"])
        axis.plot(months, year["actual_mmcf"], color="black", linewidth=2, label="Actual demand")
        axis.plot(months, year["forecast_mmcf"], color="gray", linestyle=":", label="Forecast")
        axis.step(months, year["rule_nomination_mmcf"], where="mid", label="Rule of thumb buys")
        axis.step(months, year["optimised_nomination_mmcf"], where="mid", label="Optimised buys")
        axis.axhline(year["pipeline_capacity_mmcf"].iloc[0], color="red", linewidth=0.8)
        axis.set(title=f"Plan year {plan_year}", ylabel="MMcf per month")
    axes[0].legend(ncol=3, fontsize=8)
    figure.tight_layout()
    figure.savefig(path, dpi=130)
    plt.close(figure)


def plot_sensitivity(sensitivity: pd.DataFrame, path: Path) -> None:
    """Average cost and share of demand served as realised demand departs from the forecast."""
    figure, (cost_axis, service_axis) = plt.subplots(1, 2, figsize=(11, 4.2))
    for plan, rows in sensitivity.groupby("plan", sort=False):
        cost_axis.plot(rows["forecast_error_percent"], rows["cost_musd"], marker="o", label=plan)
        service_axis.plot(
            rows["forecast_error_percent"], rows["served_percent"], marker="o", label=plan
        )
    cost_axis.set(xlabel="Realised demand vs forecast (%)", ylabel="Cost per plan year ($M)")
    service_axis.set(xlabel="Realised demand vs forecast (%)", ylabel="Demand served (%)")
    cost_axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=130)
    plt.close(figure)
