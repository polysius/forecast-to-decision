"""Plot of the revenue variance components by period."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # write files only, no display needed

import matplotlib.pyplot as plt
import pandas as pd

from forecast_to_decision.variance import COMPONENTS


def plot_variance_components(periods: pd.DataFrame, path: Path) -> None:
    """Stacked bars of the four effects per period, with the total variance marked."""
    figure, axis = plt.subplots(figsize=(13, 5))
    positions = range(len(periods))
    positive_base = pd.Series(0.0, index=periods.index)
    negative_base = pd.Series(0.0, index=periods.index)

    for component in COMPONENTS:
        values = periods[component]
        # Positive effects stack upward from zero, negative effects downward.
        bottoms = positive_base.where(values >= 0, negative_base)
        axis.bar(positions, values, bottom=bottoms, label=component.capitalize())
        positive_base = positive_base + values.clip(lower=0)
        negative_base = negative_base + values.clip(upper=0)

    axis.plot(
        positions, periods["total_variance"], color="black", marker="D", linestyle="none", label="Total"
    )
    axis.axhline(0, color="black", linewidth=0.8)
    axis.set_xticks(
        list(positions), [label.replace(" to ", "\nto ") for label in periods.index], fontsize=7
    )
    axis.set(ylabel="Actual minus forecast revenue ($M)", title="Revenue variance by component")
    axis.legend(ncol=5, fontsize=8)
    figure.tight_layout()
    figure.savefig(path, dpi=130)
    plt.close(figure)
