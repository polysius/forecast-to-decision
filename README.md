# forecast-to-decision

From a gas demand forecast to a supply decision, using Massachusetts natural gas deliveries
(EIA) and Boston weather (NOAA).

The project asks one question: given a forecast that is wrong by a known amount, what should a
gas utility do, and how much does the forecast error cost? It is built in four milestones.

| Milestone | Topic | Status |
|---|---|---|
| M1 | Interpretable regression forecast | Done, see [STATS.md](STATS.md) |
| M2 | Supply plan optimisation (LP) | Not started |
| M3 | Forecast-vs-actual variance analysis | Not started |
| M4 | Excel workbook, Power BI model, business summary | Not started |

## Use case

The spec offers two use cases. This project takes its default: natural gas demand and weather
with an operations decision. Monthly residential and commercial deliveries for Massachusetts
come from the EIA bulk file. Daily temperatures at Boston Logan come from NOAA NCEI. Neither
source needs an API key.

Monthly data has no day-of-week or holiday effect, so the regression uses days in the month as
its calendar driver.

## M1 result

Each sector is a regression on heating degree days, last month's heating degree days, and days
in the month. Training start year, degree day base temperature and month effects are chosen by
validation inside the training period (see [STATS.md](STATS.md)). The out-of-sample window is the last 36 months (2023-09 to 2026-08).

| Sector | Seasonal naive MAPE | Regression, normal weather | Regression, actual weather |
|---|---|---|---|
| Residential | 10.2% | 12.8% | 7.9% |
| Commercial | 12.5% | 15.1% | 13.2% |

With actual weather the residential model beats the baseline. With normal weather, which is
all a forecaster knows in advance, it does not beat seasonal naive in either sector. Most of the
remaining error is weather the model cannot see ahead of time. M2 therefore treats the forecast
as uncertain and tests the plan against forecast error.

Residuals are autocorrelated and their variance is not constant, so the confidence intervals
should be read as approximate. The full tables, diagnostics and plots are in
[STATS.md](STATS.md).

## Run it

```
pip install -e ".[dev]"
python scripts/fetch_data.py   # optional, the extracts are committed under data/raw
python scripts/run_m1.py       # rewrites STATS.md, docs/figures and results/
pytest
```

## Layout

```
data/raw/                 committed extracts of the EIA and NOAA data
src/forecast_to_decision/ data loading, model, diagnostics
scripts/                  fetch_data.py, run_m1.py
results/                  holdout forecasts and chosen model specs
docs/figures/             diagnostic and forecast plots
tests/                    unit tests that run offline
```

## Limitations

* One weather station stands in for the whole state.
* EIA deliveries partly follow billing cycles, which blurs the link to monthly weather.
* The holdout is one fixed 36-month window, so the error estimates are noisy.
