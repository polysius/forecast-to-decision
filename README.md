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
| M4 | Excel workbook, Power BI model, business summary | Workbook, data model and summary done. The Power BI report is for the owner to build, see [powerbi/POWERBI_GUIDE.md](powerbi/POWERBI_GUIDE.md) |

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

Over the twelve periods actual revenue was $129.3M below a forecast of $13,724.9M, about 1%.
That small total hides large effects that cancel: price added $742.5M and mix added $57.7M,
while volume took off $654.5M and weather $275.1M. The weather effect was negative in ten of
twelve periods. In the three winters it was -$197.5M, +$62.3M and +$227.5M. The volume effect
was negative in eleven periods, so deliveries ran below even the weather adjusted forecast. It
holds both real demand changes and the model's own error, and this data cannot separate them.

The budget price is an assumption. The main table prices each month at the same month a year
earlier. Freezing the price at what was known when the forecast was made gives a forecast of
$13,816.9M and a gap of $221.3M, with price adding $647.0M. The size of the price effect and of
the total gap both depend on this rule.

## M4: reporting

The results are packaged for people who do not read code.

**Excel workbook.** [reports/forecast_to_decision.xlsx](reports/forecast_to_decision.xlsx) holds the
36 months by sector, the variance table, two real PivotTables (revenue by plan year and sector,
variance effects by period), a month lookup built on INDEX and MATCH, and a scenario sheet. The
scenario sheet changes demand and prices with formulas, and reads supply plan costs from the
optimisation runs by interpolating between the tested forecast errors. It does not re-run the
optimisation. The PivotTables are made by Excel itself, so rebuilding the workbook needs Excel for
Windows.

**Power BI model.** [powerbi/](powerbi/) holds the star schema data files, the DAX measures in
`measures.dax`, and a guide with the relationships, a suggested page layout and check values. The
measures have not been run in Power BI, so use the check values in the guide to confirm them.

**Business summary.** One page for a non-technical reader, below. It is generated from the results,
and it stops with an error if a finding that one of its sentences or recommendations rests on
stops holding.

### Dashboard

The dashboard has not been built yet. Build it from the guide, save the report as
`powerbi/forecast_to_decision.pbix`, and save a screenshot as `docs/figures/dashboard.png`. Then
add the screenshot here. The repository ignores `*.pbix` files.

## Business summary

<!-- business-summary:start -->
**The question.** A gas utility must decide months ahead how much gas to buy, and whether to
reserve emergency supply for the coldest weeks, without knowing the weather. This analysis asks
how well demand can be forecast, what the best purchasing plan looks like, and why revenue ends
up different from the forecast. It covers three years of Massachusetts gas deliveries to
homes and businesses (September 2023 to August 2026).

**What we found**

1. *The weather matters, but it is not the whole story.* Assuming normal weather, the forecast
   missed monthly demand by 13.3% on average, worse than assuming each
   month repeats the same month last year (10.0%). Even with the weather that
   actually happened it missed by 9.3%. Knowing the weather removes
   30% of the miss, and the rest is the forecast's own error.
2. *A smarter purchase plan saves little, and the saving is not certain.* The optimised plan cost
   $5,053.3M over three years against $5,077.4M for the usual
   rule (buy the forecast plus 5% and reserve emergency supply every
   winter), saving
   $24.1M, or 0.5%. If storage must be refilled to the same
   level every year, the optimised plan costs $8.9M more instead.
3. *Past winters did not separate the plans. A large demand surprise did.* Tested against
   30 past winters, both plans fell short in 5 and
   delivered 99.86% of demand on average. With demand
   15% above the forecast in every month, the usual rule delivered
   97.8% and the optimised plan 98.6%.
   Up to 10% above, every plan met all demand.
4. *Revenue landed close to the forecast, but only because large effects cancelled.* Actual
   revenue was $129.3M below the
   $13,724.9M forecast, a gap of 0.9%. Compared with the forecast,
   prices added $742.5M, volume took off $654.5M,
   weather took off $275.1M and the mix of home and business customers
   added $57.7M.

**What we recommend**

* Plan against a range of possible winters, not one forecast number. A single normal-weather
  forecast was no more accurate than last year's pattern.
* Stress test the plan against a demand surprise. A 15% surprise was the only
  case that separated the plans, and the optimised plan held up better.
* Weigh the purchase plan on how it copes with surprises, not on its small cost saving, which
  depends on how storage is managed.
* Check the budget's price assumptions first. Price was the largest of the effects that moved
  revenue away from the forecast, even though it pushed revenue up.

**What to keep in mind.** One weather station stands in for the whole state. The sizes of the
pipeline, storage and emergency supply, their fees and penalties, and the budget price are
assumptions, not measurements. Three years of data is a small sample.
<!-- business-summary:end -->

## Run it

```
pip install -e ".[dev]"
python scripts/fetch_data.py   # optional, the extracts are committed under data/raw
python scripts/run_m1.py       # rewrites STATS.md, docs/figures and results/
python scripts/run_m2.py       # needs the M1 results; rewrites OPTIMISATION.md
python scripts/run_m3.py       # needs the M1 results; rewrites VARIANCE.md
python scripts/run_m4.py       # needs M1 to M3; workbook (Excel for Windows), Power BI files, summary
pytest
```

Use `python scripts/run_m4.py --skip-workbook` on a machine without Excel.

## Layout

```
data/raw/                 committed extracts of the EIA and NOAA data
src/forecast_to_decision/ data loading, model, diagnostics, scenarios, supply plan optimiser,
                          variance decomposition, report tables, workbook, Power BI export,
                          business summary
scripts/                  fetch_data.py, run_m1.py to run_m4.py, add_pivots.ps1
results/                  M1 holdout forecasts and specs, M2 plan comparison and sensitivity,
                          M3 variance tables
reports/                  the Excel workbook
powerbi/                  data files, DAX measures and the build guide
BUSINESS_SUMMARY.md       the one page summary for a non-technical reader
docs/figures/             diagnostic and forecast plots
tests/                    unit tests that run offline
```

## Limitations

* One weather station stands in for the whole state.
* EIA deliveries partly follow billing cycles, which blurs the link to monthly weather.
* The holdout is one fixed 36-month window, so the error estimates are noisy.
