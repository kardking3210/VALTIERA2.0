# Quantitative Model Documentation (Current Prototype)

All current calculations run locally in `backend/app/engines/core.py` on caller-supplied historical arrays. They report a calculation timestamp and input source, not data provenance. Outputs are research measurements; they do not claim profitability or trigger orders.

| Engine | Method and key inputs | Limitations |
|---|---|---|
| Heston | Full-truncation Euler Monte Carlo for correlated spot/variance paths; kappa, theta, xi, rho, v0, horizon, path count and seed | Parameters are editable scenarios, not calibrated to an options surface; paths do not predict direction |
| SABR | Hagan lognormal implied-volatility approximation across a generated strike grid; forward, expiry, alpha, beta, rho, nu | Uses last historical close as a zero-carry forward proxy by default; no options feed, observed IV, calibration, or fit error is available |
| Two-state HMM | Gaussian emissions with deterministic Baum–Welch fitting; return-based historical state posteriors, transition matrix, volatility and mean-return characterization | Exactly two states; no configurable state count or likelihood diagnostic exposed; state meaning is inferred from sample characteristics |
| ARIMA | Statsmodels ARIMA on log price levels with a conditional one-step interval | Order selection is fixed; stationarity and interval calibration are not guaranteed |
| Kalman filter | Scalar local-level filter on log prices | Process/measurement noise assumptions are fixed; not a trading strategy by itself |
| Ornstein–Uhlenbeck | Discrete log-price mean-reversion fit | OU behavior/stationarity may not hold; estimate is sample dependent |
| Moving average | SMA or EMA crossover; prices, fast/slow windows | One latest comparison; not a standalone strategy validation |
| RSI | Wilder-smoothed RSI; prices, lookback and thresholds | Latest oscillator value; no explicit crossing history |
| MACD | EMA(12)-EMA(26), EMA(9) signal | EMA initialization is first observation |
| Bollinger | Rolling mean and sample standard deviation | Latest standardized price distance |
| VWAP | Sum(price × volume)/sum(volume) | Requires aligned price/volume; uses supplied price proxy |
| Statistical arbitrage | OLS log-price relationship, Engle-Granger, rolling spread Z-score, Kalman hedge ratio | In-sample relationship estimation; multiple testing and structural breaks not handled |
| Pairs trading | OLS log spread and rolling Z-score | No borrow/funding/corporate-action modeling |
| Mean reversion | Rolling Z-score and conditional level-change slope/half-life | Half-life is conditional OLS estimate; stationarity is not guaranteed |
| Momentum | Log return, realized volatility, trend filter | Fixed observation annualization assumption |
| Volatility breakout | Prior high/low range and average true range | Requires aligned OHLC; execution rules are simplistic |
| GARCH | Gaussian GARCH(1,1) MLE with stationarity constraint | Conditional model assumptions; convergence and sample stability matter |
| Monte Carlo | Seeded geometric Brownian motion on sample log returns | Scenario distribution under constant parameters, not forecast/confidence interval |
| Black–Scholes | European option call/put prices and analytical Greeks from spot, strike, expiry, rate, and implied volatility | Theoretical baseline; assumes European exercise and supplied volatility/rate; not a market quote |
| Gradient boosting | Deterministic squared-error regression stumps with chronological holdout | Minimal research implementation; no tuning, feature library, or independent profitability validation |

The Quant Research UI presents the four requested workspaces. Heston and GARCH run in stochastic-volatility research; SABR is scenario-only; HMM is a fixed two-state return model; Gradient Boosting is the only implemented ML model. The other original 17 research methods remain accessible in the existing-method library. XGBoost, Random Forest, LSTM, Transformer, ensembles, FinBERT, sentiment, NER and topic models are explicitly identified as unavailable because this repo has no trained inference runtime or news/document ingestion.

Market history is shared through `/market-data/history`: Binance candles are public and cached briefly; Alpaca IEX and FMP require backend credentials and entitlement. Alpaca/FMP/Binance candle requests retry only transient transport, 429 and 5xx failures a bounded number of times; access-denied responses are not retried. The prior Stooq 403 message is not present in this source tree; the current app does not use Stooq.

Backtesting is disabled for calculation-only models that do not produce a validated, causal trading signal (including ARIMA, Kalman Filter, Ornstein–Uhlenbeck, Black–Scholes, and Gradient Boosting). Passing automated tests means the outputs have structured implementation coverage; it does not establish profitable performance, data quality, or investment suitability.
