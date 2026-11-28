export type Model = {
  id: string;
  number: string;
  name: string;
  short: string;
  family: string;
  description: string;
  method: string;
  needsPeer?: boolean;
  needsVolume?: boolean;
  needsHighLow?: boolean;
  needsOptions?: boolean;
  backtestable?: boolean;
};

export const models: Model[] = [
  { id: 'heston', number: 'SV-01', name: 'Heston Stochastic Volatility', short: 'HESTON', family: 'Stochastic volatility', description: 'Simulate correlated price and variance paths under the Heston stochastic-volatility process.', method: 'Full-truncation Euler Monte Carlo with user-editable scenario parameters; no option calibration is claimed.' },
  { id: 'sabr', number: '02', name: 'SABR Implied Volatility Smile', short: 'SABR', family: 'Options volatility', description: 'Calculate a strike-dependent implied-volatility smile from the Hagan SABR approximation.', method: 'Hagan lognormal implied-volatility approximation. Market calibration is unavailable without an options quote surface.' },
  { id: 'market_regime', number: 'HMM', name: 'HMM Market Regime Detection', short: 'HMM REGIME', family: 'Regime detection', description: 'Fit a two-state Gaussian hidden Markov model to historical log returns and infer regime probabilities.', method: 'Deterministic Baum–Welch EM with filtered posterior probabilities and a fitted state transition matrix.' },
  { id: 'arima', number: '01', name: 'ARIMA Forecast', short: 'ARIMA', family: 'Statistical', description: 'Fit an autoregressive integrated moving-average model to historical log prices.', method: 'Statsmodels ARIMA(p,d,q) with a conditional 95% interval and explicitly reported convergence status.', backtestable: false },
  { id: 'garch', number: '02', name: 'GARCH Volatility Forecast', short: 'GARCH(1,1)', family: 'Statistical', description: 'Estimate conditional variance persistence and the next observation volatility.', method: 'Gaussian GARCH(1,1) maximum-likelihood fit with a stationarity constraint; fit errors are reported.', backtestable: true },
  { id: 'kalman_filter', number: '03', name: 'Kalman Filter', short: 'KALMAN', family: 'Statistical', description: 'Estimate a changing latent price level while accounting for observation noise.', method: 'Scalar local-level Kalman filter over log prices with explicit process and observation variances.', backtestable: false },
  { id: 'ornstein_uhlenbeck', number: '04', name: 'Ornstein–Uhlenbeck', short: 'OU PROCESS', family: 'Statistical', description: 'Estimate mean-reversion speed and equilibrium from a discrete log-price relationship.', method: 'OLS of log-price increments on lagged log prices; reports mean reversion only for a stable discrete fit.', backtestable: false },
  { id: 'moving_average', number: '05', name: 'Moving Average Crossover', short: 'SMA / EMA', family: 'Trend', description: 'Compare a fast and slow price average to study directional persistence.', method: 'Fast and slow simple or exponential averages, with the position signal lagged one observation for simulation.' },
  { id: 'rsi', number: '06', name: 'RSI Momentum', short: 'RSI', family: 'Momentum', description: 'Measure the balance of recent gains and losses on a bounded oscillator.', method: 'Wilder smoothed relative strength index. Threshold crossings are reported as historical research signals.' },
  { id: 'macd', number: '07', name: 'MACD Trend', short: 'MACD', family: 'Trend', description: 'Study trend changes through the convergence and divergence of exponential averages.', method: '12/26 period EMA difference, 9 period signal EMA, and histogram.' },
  { id: 'bollinger', number: '08', name: 'Bollinger Mean Reversion', short: 'BOLLINGER', family: 'Mean reversion', description: 'Measure price distance from a rolling mean in units of rolling dispersion.', method: 'Rolling mean and sample standard deviation bands. The signal is descriptive and does not assert reversion.' },
  { id: 'vwap', number: '09', name: 'VWAP Strategy', short: 'VWAP', family: 'Execution research', needsVolume: true, description: 'Compare price with a volume weighted average over the supplied observation window.', method: 'Cumulative price times volume divided by cumulative volume. Requires aligned, caller supplied volume bars.' },
  { id: 'statistical_arbitrage', number: '10', name: 'Statistical Arbitrage', short: 'STAT ARB', family: 'Relative value', needsPeer: true, description: 'Study residual relationships between two aligned price series.', method: 'OLS log price hedge ratio, Engle–Granger cointegration test, rolling spread Z-score, and correlation diagnostics.' },
  { id: 'pairs_trading', number: '11', name: 'Pairs Trading', short: 'PAIRS', family: 'Relative value', needsPeer: true, description: 'Evaluate a two asset spread and its rolling standardized deviation.', method: 'OLS hedge ratio on log prices, then a rolling spread Z-score on the supplied aligned pair.' },
  { id: 'mean_reversion', number: '12', name: 'Z-Score Mean Reversion', short: 'Z-SCORE', family: 'Mean reversion', description: 'Quantify how far the latest observation sits from its rolling historical mean.', method: 'Rolling mean, sample standard deviation, standardized deviation, and conditional OLS half-life estimate.' },
  { id: 'momentum', number: '13', name: 'Momentum & Trend Following', short: 'MOMENTUM', family: 'Momentum', description: 'Measure return persistence after scaling by realized variation.', method: 'Log return, rate of change, volatility adjusted score, and fast/slow trend filter.' },
  { id: 'volatility_breakout', number: '14', name: 'Volatility Breakout', short: 'BREAKOUT', family: 'Volatility', needsHighLow: true, description: 'Compare the close with a prior rolling range scaled by recent true range.', method: 'Prior-window high/low range and average true range from the supplied OHLC series.' },
  { id: 'monte_carlo', number: '15', name: 'Monte Carlo Simulation', short: 'MONTE CARLO', family: 'Simulation', description: 'Project a distribution of price paths from historical return estimates.', method: 'Seeded geometric Brownian motion using caller supplied historical log returns; outcomes are scenarios, not forecasts.', backtestable: true },
  { id: 'black_scholes', number: '16', name: 'Black–Scholes', short: 'BLACK–SCHOLES', family: 'Derivatives', description: 'Calculate a European option theoretical baseline and analytical Greeks from entered assumptions.', method: 'Black–Scholes call and put prices, delta, gamma, vega and theta from spot, strike, expiry, rate and volatility.', needsOptions: true, backtestable: false },
  { id: 'gradient_boosting', number: '17', name: 'Gradient Boosting', short: 'BOOSTING', family: 'Machine learning', description: 'Evaluate boosted decision stumps on lagged returns with a chronological holdout.', method: 'Deterministic squared-error gradient boosting, five return lags and reported out-of-sample error.', backtestable: false },
];

export const researchWorkspaces = [
  { id: 'stochastic', title: 'Stochastic Volatility Models', description: 'Heston paths and GARCH volatility forecasting.', available: ['heston', 'garch'] },
  { id: 'sabr', title: 'SABR Model', description: 'Strike-based implied volatility smile scenarios.', available: ['sabr'] },
  { id: 'hmm', title: 'Hidden Markov Models', description: 'Historical market states and transition probabilities.', available: ['market_regime'] },
  { id: 'ml_nlp', title: 'Advanced Machine Learning & NLP', description: 'Time-series ML and document analysis.', available: ['gradient_boosting'], unavailable: ['XGBoost', 'Random Forest', 'LSTM', 'Transformer-based Time-Series Models', 'Ensemble Models', 'FinBERT', 'Sentiment Analysis', 'Named Entity Recognition', 'Topic Detection'] },
] as const;
