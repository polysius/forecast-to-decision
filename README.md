# forecast-to-decision

From a gas demand forecast to a supply decision, using Massachusetts natural gas deliveries
(EIA) and Boston weather (NOAA).

The project asks one question: given a forecast that is wrong by a known amount, what should a
gas utility do, and how much does the forecast error cost? It is built in four milestones.

| Milestone | Topic | Status |
|---|---|---|
| M1 | Interpretable regression forecast | Done, see [STATS.md](STATS.md) |
| M2 | Supply plan optimisation (MIP) | Done, see [OPTIMISATION.md](OPTIMISATION.md) |
| M3 | Forecast-vs-actual variance analysis | Done, see [VARIANCE.md](VARIANCE.md) |
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
all a forecaster knows in advance, it does not beat seasonal naive on MAPE or MAE in either
sector, although its RMSE is lower. Knowing the weather removes about half of the residential
error and little of the commercial error, so the rest comes from the model itself. M2 treats the
forecast as uncertain and tests the plan against forecast error.

Residuals are autocorrelated and their variance is not constant, so the confidence intervals
should be read as approximate. The full tables, diagnostics and plots are in
[STATS.md](STATS.md).

## M2 result

The forecast feeds a supply plan: how much pipeline gas to buy each month, and whether to
contract peaking supply, before the weather is known. Storage, peaking and resale then adjust to
the demand that happens. Peaking is a yes or no choice per month, so the plan is a mixed integer
program, solved with OR-Tools. The formulation and every assumption are in
[OPTIMISATION.md](OPTIMISATION.md). Pipeline, storage and peaking sizes, fees and penalties are
assumptions, not data.

Three plans are scored on the actual demand of the three holdout plan years (September to
August):

| Plan | Cost over three years | Demand served |
|---|---|---|
| Rule of thumb (forecast plus 5%, peaking in winter) | $5,077M | 100% |
| Optimised over 30 weather scenarios | $5,053M | 100% |
| Perfect hindsight (a floor, not a plan) | $5,008M | 100% |

The optimised plan is $24M cheaper than the rule of thumb and closes about a third of the gap to
hindsight. In the second plan year it costs slightly more than the rule, so the gain is not
uniform. The two plans differ most when demand surprises on the high side. If realised demand is
15% above the forecast, the rule of thumb costs $2,540M per year and serves 97.8% of demand,
while the optimised plan costs $2,385M and serves 98.6%.

The saving depends on how leftover storage gas is treated. The results above value it at the
average price. If storage must instead end each year as full as it began, the optimised plan
costs $5,834M against $5,825M for the rule of thumb, so it is $9M more expensive. The plan is a
sound way to hedge demand risk, but this data does not show that it saves money in every
setting.

## M3 result

[VARIANCE.md](VARIANCE.md) explains the gap between the M1 forecast and actual gas revenue over
twelve seasons (September to August, three months each). Revenue is deliveries times the retail
price for residential and commercial customers. The gap is split into weather, volume, mix
(residential against commercial) and price, and the four effects add up to the variance in every
period.

Over the twelve periods actual revenue was $129M below a forecast of $13,725M, about 1%. That
small total hides large effects that cancel: price added $743M, while volume took off $655M,
weather $275M, and mix added $58M. Weather matters most in winter and changes sign from one
winter to the next. The volume effect is negative in most periods, which means deliveries ran
below even the weather adjusted forecast. It holds both real demand changes and the model's
own error, and this data cannot separate them. The budget price is an assumption (the same
month a year earlier), so the split between price and the other effects depends on it.

## Run it

```
pip install -e ".[dev]"
python scripts/fetch_data.py   # optional, the extracts are committed under data/raw
python scripts/run_m1.py       # rewrites STATS.md, docs/figures and results/
python scripts/run_m2.py       # needs the M1 results; rewrites OPTIMISATION.md
python scripts/run_m3.py       # needs the M1 results; rewrites VARIANCE.md
pytest
```

## Layout

```
data/raw/                 committed extracts of the EIA and NOAA data
src/forecast_to_decision/ data loading, model, diagnostics, scenarios, supply plan optimiser,
                          variance decomposition
scripts/                  fetch_data.py, run_m1.py, run_m2.py, run_m3.py
results/                  M1 holdout forecasts and specs, M2 plan comparison and sensitivity,
                          M3 variance tables
docs/figures/             diagnostic and forecast plots
tests/                    unit tests that run offline
```

## Limitations

* One weather station stands in for the whole state.
* EIA deliveries partly follow billing cycles, which blurs the link to monthly weather.
* The holdout is one fixed 36-month window, so the error estimates are noisy.
