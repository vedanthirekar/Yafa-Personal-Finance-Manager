# Forecasting — what runs, and why

`apps/api/app/services/forecasting.py` fits **simple exponential smoothing** on
monthly spend totals: one method, the same one for every account, with the
smoothing parameter α estimated per user.

This document is the justification. The short version: the model was picked by
backtest, and the thing it replaced lost to doing nothing.

## What was there before

ARIMA(5,1,0), hardcoded. The order was inherited from the 2024 build and, as
far as the git history shows, was never compared against anything.

## The measurement

`uv run python -m ml.eval_forecasting` backtests eight candidates against the
real series in Postgres — expanding window, one-step-ahead, scored by mean
absolute error against a naive "next month looks like last month" baseline.

**demo — 18 months, $7,217/mo average, 10 folds**

| Model | MAE | vs naive |
|---|---|---|
| mean (all history) | $3,093 | **+32.9%** |
| mean (last 3) | $3,786 | +17.9% |
| ARIMA auto (AICc grid) | $3,844 | +16.6% |
| seasonal naive | $3,967 | +14.0% |
| ARIMA(0,1,1) | $4,191 | +9.1% |
| ETS / exponential smoothing | $4,236 | +8.1% |
| naive (last month) | $4,611 | — |
| **ARIMA(5,1,0) — the old default** | **$6,684** | **−45.0%** |

**demo_legacy — 75 months, $26,314/mo average, 67 folds**

| Model | MAE | vs naive |
|---|---|---|
| **naive (last month)** | **$15,833** | — |
| ETS / exponential smoothing | $16,515 | −4.3% |
| ARIMA(0,1,1) | $16,541 | −4.5% |
| mean (last 3) | $16,595 | −4.8% |
| ARIMA auto (AICc grid) | $16,846 | −6.4% |
| **ARIMA(5,1,0) — the old default** | **$18,448** | **−16.5%** |
| seasonal naive | $20,851 | −31.7% |
| mean (all history) | $23,325 | −47.3% |

Last of eight on one account, sixth of eight on the other. On demo it was 45%
*worse* than repeating last month's total.

### Why it lost

1. **Too many parameters for the data.** ARIMA(5,1,0) estimates five
   autoregressive coefficients. Differencing 18 monthly points leaves 17. The
   fit is dominated by whatever noise the recent months happen to contain —
   which is exactly the overfitting signature: worst on the short series
   (−45%), less bad on the long one (−16.5%).
2. **Monthly consumer spend is close to a level plus noise.** That's why the
   flat mean wins on demo and plain naive wins on demo_legacy. There isn't much
   autocorrelation for an AR model to find.
3. **Seasonality is weak here.** Seasonal naive beat ARIMA(5,1,0) on demo but
   came second-to-last on demo_legacy, so a December-spike story isn't
   supported. SARIMA is also unfittable on demo — seasonal terms at m=12 need
   two full cycles, and there are 18 months.

## Why exponential smoothing, and not the winner

The literal winner differs per account: mean-of-all-history on demo, naive on
demo_legacy. Picking either one globally would be trading one unjustified
constant for another, and selecting per user at request time was considered and
rejected as more machinery than this earns.

Exponential smoothing resolves that without any selection logic. It is a
weighted average of past months where recent months count more, and α — the one
estimated parameter — controls how much more:

```
α → 1     next month ≈ last month              (what won on demo_legacy)
α → 0     next month ≈ the long-run average     (what won on demo)
```

So it spans both winners and lands wherever a given account's data puts it. On
the seeded demo account α fits to **0.0** — the model chooses the mean, which is
precisely what the backtest said was best there. Same code, no branching.

It is also exactly ARIMA(0,1,1): the same family as the old default, with the
right number of parameters instead of five.

## What the service does beyond fitting

**Under 6 months, there is no forecast.** The series comes back with
`is_fitted: false`, an empty `forecast`, and `months_of_history` /
`months_required` so the client can count down ("3 of 6 months"). Below six
points α is fitted to three or four observations and the interval derived from
it is meaningless. The previous build filled this gap with a flat mean labelled
`mean-baseline`, which drew as a projection whatever the label said.

**The current month is excluded from the fit.** The newest bucket is only as
complete as today's date. Exponential smoothing weights the most recent
observation most heavily, so fitting on a half-finished month reads as a sudden
collapse in spending — and it is the point the model trusts most. It stays in
`history` for the chart; only the fit skips it. The forecast horizon is
anchored to the full series, so no month is ever both an observation and a
projection.

**Six or more consecutive empty months is treated as dormancy.** `_to_monthly`
zero-fills gaps, which is correct for a quiet month inside an active stretch and
wrong for an absence. `demo_legacy` has an 18-month hole (Mar 2024 – Aug 2025)
where the old app simply wasn't used; including it taught the model that
spending collapsed to nothing for a year and a half.

| demo_legacy | point forecast | 80% band | width |
|---|---|---|---|
| zero-filled through the gap | $7,274 | $0 – $37,650 | 8.35× |
| trimmed to the current era | $10,009 | $421 – $19,597 | 1.92× |

A filled zero and a real zero are indistinguishable by that point in the
pipeline, which is fine — six consecutive months of spending exactly nothing is
dormancy either way.

## Intervals

Closed-form ETS(A,N,N) variance, `σ²[1 + (h−1)α²]`, from Hyndman &
Athanasopoulos, *Forecasting: Principles and Practice* (3rd ed.) §7.7. Derived
from the model rather than bootstrapped, because there isn't enough history to
bootstrap from. The lower bound is clipped at zero — spend can't be negative.

Note that when α fits to 0 the band does not widen with horizon. That is
correct, not a bug: a pure-mean model is no less certain about six months out
than about one.

**The bands are still wide** — about 1.5× the point forecast on demo. That is
the data, not the method: monthly totals on that account range from roughly $2k
to $16k. The old ARIMA band was 2.07× on the same series, so this is an
improvement, but no model turns volatile spending into a tight interval. The
honest presentation is to show the range and say what it means.

## Deliberately not done

- **Per-user model selection at request time.** Would likely beat a single
  method, at the cost of fitting a candidate set on every request and a lot
  more code. Revisit if the single model proves inadequate.
- **SARIMA / STL / MSTL.** Seasonality isn't there (see above), and SARIMA needs
  ≥24 months, which most accounts won't have.
- **`statsforecast`.** Not worth a numba + llvmlite dependency at this scale.
- **Splitting recurring from discretionary spend** and forecasting them
  separately. The most promising direction by a distance — rent and
  subscriptions are nearly deterministic, and isolating them would shrink the
  variance the model has to explain. Needs merchant-level recurrence detection.
- **Anomaly detection is unchanged.** It is independent of the forecast model,
  uses per-category z-scores, and had no equivalent problem.

## Caveat on the backtest

`ml/eval_forecasting.py` scores candidates on the raw zero-filled series — it
does not apply the dormancy trim or the partial-month drop that the service
does. That is deliberate: it is a model-comparison harness, and every candidate
sees identical input, so the *ranking* is sound. The absolute MAEs above are
therefore pessimistic relative to what the service actually fits, particularly
on `demo_legacy` where the 18-month hole is included.

## Caveat on the data

`demo` is generated by `app/services/demo_seed.py`, so its ranking partly
reflects how the seeder draws months. `demo_legacy` is imported from the real
pre-revamp SQLite databases and is the more trustworthy of the two — and it is
the one where *nothing beats naive*, which is the classic result for monthly
household spend.
