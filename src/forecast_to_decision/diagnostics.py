"""Residual diagnostics and plots for the fitted regressions."""

from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # write files only, no display needed

import matplotlib.pyplot as plt
import pandas as pd
import statsmodels.api as sm
from statsmodels.regression.linear_model import RegressionResultsWrapper
from statsmodels.stats.diagnostic import acorr_ljungbox, het_breuschpagan
from statsmodels.stats.stattools import durbin_watson, jarque_bera

LJUNG_BOX_LAGS = 12


@dataclass(frozen=True)
class ResidualTests:
    durbin_watson: float
    ljung_box_p: float
    breusch_pagan_p: float
    jarque_bera_p: float


def run_residual_tests(model: RegressionResultsWrapper) -> ResidualTests:
    """Autocorrelation, heteroskedasticity and normality checks on the residuals.

    Small p-values reject the null: no autocorrelation (Ljung-Box), constant
    variance (Breusch-Pagan), normal errors (Jarque-Bera). A Durbin-Watson
    value near 2 means no first-order autocorrelation.
    """
    residuals = model.resid
    ljung_box = acorr_ljungbox(residuals, lags=[LJUNG_BOX_LAGS])
    _, breusch_pagan_p, _, _ = het_breuschpagan(residuals, model.model.exog)
    _, jarque_bera_p, _, _ = jarque_bera(residuals)
    return ResidualTests(
        durbin_watson=float(durbin_watson(residuals)),
        ljung_box_p=float(ljung_box["lb_pvalue"].iloc[0]),
        breusch_pagan_p=float(breusch_pagan_p),
        jarque_bera_p=float(jarque_bera_p),
    )


def coefficient_table(model: RegressionResultsWrapper) -> pd.DataFrame:
    """Coefficient, HAC standard error, 95% interval and p-value for each term."""
    intervals = model.conf_int()
    return pd.DataFrame(
        {
            "coefficient": model.params,
            "std_error": model.bse,
            "ci_low": intervals[0],
            "ci_high": intervals[1],
            "p_value": model.pvalues,
        }
    )


def plot_residual_diagnostics(model: RegressionResultsWrapper, sector: str, path: Path) -> None:
    """Four panels: fit, residuals vs fitted, residuals over time, normal Q-Q."""
    figure, axes = plt.subplots(2, 2, figsize=(11, 8))
    fitted = model.fittedvalues
    actual = model.model.endog

    axes[0, 0].scatter(fitted, actual, s=8)
    low, high = min(fitted.min(), actual.min()), max(fitted.max(), actual.max())
    axes[0, 0].plot([low, high], [low, high], color="black", linewidth=1)
    axes[0, 0].set(title="Actual vs fitted", xlabel="Fitted (MMcf)", ylabel="Actual (MMcf)")

    axes[0, 1].scatter(fitted, model.resid, s=8)
    axes[0, 1].axhline(0, color="black", linewidth=1)
    axes[0, 1].set(title="Residuals vs fitted", xlabel="Fitted (MMcf)", ylabel="Residual (MMcf)")

    axes[1, 0].plot(model.resid.index, model.resid, linewidth=0.8)
    axes[1, 0].axhline(0, color="black", linewidth=1)
    axes[1, 0].set(title="Residuals over time", ylabel="Residual (MMcf)")

    sm.qqplot(model.resid, line="s", ax=axes[1, 1], markersize=3)
    axes[1, 1].set_title("Normal Q-Q of residuals")

    figure.suptitle(f"Massachusetts {sector} gas deliveries: residual diagnostics")
    figure.tight_layout()
    figure.savefig(path, dpi=130)
    plt.close(figure)


def plot_holdout_forecasts(
    actual: pd.Series, forecasts: dict[str, pd.Series], sector: str, path: Path
) -> None:
    """Actual deliveries against each forecast over the holdout months."""
    figure, axis = plt.subplots(figsize=(11, 4.5))
    axis.plot(actual.index, actual, color="black", linewidth=2, label="Actual")
    for label, forecast in forecasts.items():
        axis.plot(forecast.index, forecast, linewidth=1.3, linestyle="--", label=label)
    axis.set(title=f"Massachusetts {sector} gas deliveries: holdout forecasts", ylabel="MMcf")
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=130)
    plt.close(figure)
