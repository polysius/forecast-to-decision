"""Milestone 1: fit the interpretable forecast and write STATS.md with its figures.

Every number in STATS.md is computed here; nothing is typed in by hand.
Run from the repo root:  python scripts/run_m1.py
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from forecast_to_decision.data import SECTORS, build_dataset
from forecast_to_decision.diagnostics import (
    ResidualTests,
    coefficient_table,
    plot_holdout_forecasts,
    plot_residual_diagnostics,
    run_residual_tests,
)
from forecast_to_decision.model import (
    BASE_TEMPS_F,
    HOLDOUT_MONTHS,
    ErrorScores,
    Spec,
    add_lagged_weather,
    choose_spec,
    fit_sector_model,
    normal_weather_forecast,
    predict,
    score,
    seasonal_naive,
    split_train_holdout,
)

ROOT = Path(__file__).resolve().parents[1]
FIGURES_DIR = ROOT / "docs" / "figures"
RESULTS_DIR = ROOT / "results"
STATS_PATH = ROOT / "STATS.md"


@dataclass
class SectorResult:
    sector: str
    spec: Spec
    train_start: str
    train_end: str
    holdout_start: str
    holdout_end: str
    n_train: int
    r_squared: float
    adj_r_squared: float
    coefficients: pd.DataFrame
    tests: ResidualTests
    holdout_scores: dict[str, ErrorScores]


def analyse_sector(sector: str, tables: dict[float, pd.DataFrame]) -> SectorResult:
    spec = choose_spec(tables, sector)
    table = tables[spec.base_temp_f]
    train, holdout = split_train_holdout(table)
    model = fit_sector_model(train, sector, spec)

    actual = holdout[f"{sector}_mmcf"]
    forecasts = {
        "Seasonal naive": seasonal_naive(table, holdout, sector),
        "Regression, normal weather": normal_weather_forecast(train, holdout, sector, spec),
        "Regression, actual weather": predict(model, holdout, spec),
    }
    plot_residual_diagnostics(model, sector, FIGURES_DIR / f"{sector}_diagnostics.png")
    plot_holdout_forecasts(actual, forecasts, sector, FIGURES_DIR / f"{sector}_holdout.png")
    save_holdout_forecasts(sector, actual, forecasts)

    window_start = max(train.index[0], pd.Timestamp(f"{spec.start_year}-01-01"))
    return SectorResult(
        sector=sector,
        spec=spec,
        train_start=f"{window_start:%Y-%m}",
        train_end=f"{train.index[-1]:%Y-%m}",
        holdout_start=f"{holdout.index[0]:%Y-%m}",
        holdout_end=f"{holdout.index[-1]:%Y-%m}",
        n_train=int(model.nobs),
        r_squared=float(model.rsquared),
        adj_r_squared=float(model.rsquared_adj),
        coefficients=coefficient_table(model),
        tests=run_residual_tests(model),
        holdout_scores={name: score(actual, f) for name, f in forecasts.items()},
    )


def save_holdout_forecasts(sector: str, actual: pd.Series, forecasts: dict[str, pd.Series]) -> None:
    """Keep the holdout forecasts so later milestones start from the same numbers."""
    table = pd.DataFrame({"actual_mmcf": actual})
    for name, forecast in forecasts.items():
        table[name.lower().replace(", ", "_").replace(" ", "_") + "_mmcf"] = forecast
    table.to_csv(RESULTS_DIR / f"m1_{sector}_holdout.csv", float_format="%.1f")


def markdown_table(frame: pd.DataFrame, decimals: int = 2) -> str:
    header = "| " + " | ".join([frame.index.name or ""] + list(frame.columns)) + " |"
    divider = "|" + "---|" * (len(frame.columns) + 1)
    rows = [
        "| " + " | ".join([str(index)] + [f"{value:.{decimals}f}" for value in row]) + " |"
        for index, row in frame.iterrows()
    ]
    return "\n".join([header, divider, *rows])


def coefficient_markdown(result: SectorResult) -> str:
    table = result.coefficients.rename_axis("term").copy()
    table["p_value"] = table["p_value"].map(lambda p: "<0.001" if p < 0.001 else f"{p:.3f}")
    header = "| term | coefficient | std error | 95% CI low | 95% CI high | p-value |"
    rows = [
        f"| {term} | {row.coefficient:.2f} | {row.std_error:.2f} | {row.ci_low:.2f} "
        f"| {row.ci_high:.2f} | {row.p_value} |"
        for term, row in table.iterrows()
    ]
    return "\n".join([header, "|---|---|---|---|---|---|", *rows])


def scores_markdown(result: SectorResult) -> str:
    rows = [
        f"| {name} | {s.mae:,.0f} | {s.rmse:,.0f} | {s.mape_percent:.1f} |"
        for name, s in result.holdout_scores.items()
    ]
    header = "| Forecast | MAE (MMcf) | RMSE (MMcf) | MAPE (%) |"
    return "\n".join([header, "|---|---|---|---|", *rows])


def verdict(result: SectorResult) -> str:
    naive = result.holdout_scores["Seasonal naive"].mape_percent
    normal = result.holdout_scores["Regression, normal weather"].mape_percent
    actual = result.holdout_scores["Regression, actual weather"].mape_percent
    ex_ante = "beats" if normal < naive else "does not beat"
    oracle = "beats" if actual < naive else "does not beat"
    return (
        f"With normal weather the regression {ex_ante} the seasonal-naive baseline "
        f"({normal:.1f}% vs {naive:.1f}% MAPE). With the weather that actually occurred it "
        f"{oracle} it ({actual:.1f}% vs {naive:.1f}%)."
    )


def sector_section(result: SectorResult) -> str:
    spec = result.spec
    tests = result.tests
    effects = "with month effects" if spec.month_effects else "without month effects"
    return f"""## {result.sector.capitalize()} deliveries

Chosen on validation: training from {spec.start_year}, HDD base {spec.base_temp_f:.0f} F, \
{effects}. Fitted on {result.train_start} to {result.train_end} ({result.n_train} months).

R² {result.r_squared:.3f} (adjusted {result.adj_r_squared:.3f}).

### Coefficients

Units: MMcf per unit of the driver. Standard errors and intervals are Newey-West (12 lags).

{coefficient_markdown(result)}

### Residual diagnostics

| Test | Statistic or p-value | Reading |
|---|---|---|
| Durbin-Watson | {tests.durbin_watson:.2f} | 2 means no first-order autocorrelation |
| Ljung-Box, 12 lags | p = {tests.ljung_box_p:.3g} | small p: residuals are autocorrelated |
| Breusch-Pagan | p = {tests.breusch_pagan_p:.3g} | small p: variance is not constant |
| Jarque-Bera | p = {tests.jarque_bera_p:.3g} | small p: residuals are not normal |

![{result.sector} diagnostics](docs/figures/{result.sector}_diagnostics.png)

### Out-of-sample error, {result.holdout_start} to {result.holdout_end}

{scores_markdown(result)}

{verdict(result)}

![{result.sector} holdout](docs/figures/{result.sector}_holdout.png)
"""


def write_stats(results: list[SectorResult], data_span: str) -> None:
    sections = "\n".join(sector_section(result) for result in results)
    STATS_PATH.write_text(
        f"""# Milestone 1: interpretable forecast

Massachusetts monthly natural gas deliveries (EIA) against heating degree days at
Boston Logan (NOAA). Data span: {data_span}. Regenerate with `python scripts/run_m1.py`.

## Method

Each sector (residential, commercial) is a linear regression on named drivers: heating degree
days (HDD, base temperature chosen below), last month's HDD for billing lag, and days in the
month. Monthly data has no day-of-week or holiday effect, so days in month replaces them.
Month effects are an optional candidate for the seasonal shape.

The first training year, HDD base temperature and month effects are chosen by validation. Each
candidate is fitted on the training period without its last {HOLDOUT_MONTHS} months and scored
on those {HOLDOUT_MONTHS} months using normal weather. The holdout of the final
{HOLDOUT_MONTHS} months is removed before this choice, scored once, and not used to tune
anything. Candidates: first year in 1989, 2000, 2008, 2013; base temperature in
{", ".join(f"{base:.0f}" for base in BASE_TEMPS_F)} F; month effects on or off.

Three forecasts are compared on the holdout:

* Seasonal naive: the same month one year earlier. It sees fresh data every month, which is
  generous to the baseline.
* Regression with normal weather: the fitted model with each month's HDD replaced by its
  30-year average from the training period. This is the honest forecast, because weather is
  unknown in advance. Later milestones use it.
* Regression with actual weather: the same model given the weather that occurred. It is not a
  forecast. It shows how much of the error is weather and how much is the model.

Context found while exploring (before the specification search): a linear time trend fitted
from 1989 extrapolates badly, because annual deliveries grew until about 2013 and were flat
afterwards. The trend was dropped and shorter training windows were added as candidates.

{sections}
## Limitations

* The weather driver is one station (Boston Logan) for a whole state.
* Deliveries include gas billed in a later month, so the month-to-month link to HDD is blurred.
* A 36-month holdout is one fixed window, not a rolling evaluation, so the error estimates are
  noisy.
* Residual autocorrelation (see the tests above) means the intervals are wider than plain OLS
  would show, and the model leaves predictable structure unexplained.
""",
        encoding="utf-8",
    )


def main() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(exist_ok=True)

    tables = {base: add_lagged_weather(build_dataset(base_temp=base)) for base in BASE_TEMPS_F}
    results = [analyse_sector(sector, tables) for sector in SECTORS]

    any_table = next(iter(tables.values()))
    data_span = f"{any_table.index[0]:%Y-%m} to {any_table.index[-1]:%Y-%m}"
    write_stats(results, data_span)

    chosen = {result.sector: asdict(result.spec) for result in results}
    (RESULTS_DIR / "m1_specs.json").write_text(json.dumps(chosen, indent=2), encoding="utf-8")
    print(json.dumps(chosen, indent=2))


if __name__ == "__main__":
    main()
