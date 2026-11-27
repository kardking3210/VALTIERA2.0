# VALTIERA 2.0 — Local Implementation Status

This repository stays local. Do not push or deploy unless the user later asks. No live broker orders may be sent. EVM native transfers can only be submitted after an explicit in-app review and wallet-extension approval.

## Implemented in this workspace

- React/Vite landing page and quantitative terminal with the dark, full-width chart, summary action, chart guide and model laboratory.
- Binance public crypto historical candles and a live kline WebSocket. Model fields prefill automatically and closed bars append to the active sample; peer-series models still require refreshed aligned history after a new bar.
- Optional Alpaca IEX historical and live US equity feed. It requires backend-only `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`; IEX is not consolidated US market coverage. Equity model streaming is limited to 1-minute bars in the UI.
- Optional FMP historical inputs for forex, commodity and futures symbols. Set backend-only `FMP_API_KEY`; the model lab and backtest workbench load daily or weekly completed candles and calculate annualized volatility. Symbol access depends on the FMP plan. These feeds are history only; exchange-direct futures and live streams remain unconfigured.
- User-scoped paper account, simulated balance, market/limit/stop paper order ticket, quote snapshot fills, fees, positions, order processing and cancellation. Open conditional orders are checked by a local background monitor against provider top-of-book snapshots and can be partially filled up to visible size. No live broker orders are sent.
- Injected EVM wallet connection, gas estimation, explicit transfer review, wallet-approved native transfer submission and RPC receipt polling. Solana and Base remain unsupported.
- Backtest walk-forward parameter selection on chronological folds for supported directional models, out-of-sample folds, and configurable fee, slippage, spread, impact, funding and annualization assumptions. These remain assumptions; they do not validate real execution costs or correct provider data issues.
- Local-only backend/API configuration; Docker Compose now requires explicit local database and signing secrets instead of insecure defaults.

## Still pending

- Broker-routed live orders (intentionally absent). Alpaca US-equity paper account connection and orders are supported when separate paper-only credentials are configured; futures, FX and crypto broker routes are absent.
- Solana/Base wallet and transaction support. EVM native transfer requires two explicit user confirmations: a browser review prompt and the wallet extension approval.
- Equity data credentials and entitlements, licensed real-time futures/FX/commodity feeds, market-depth data, and reliable provider-specific order-book/slippage models.
- Broker paper credentials are not configured here. Partial-fill simulation uses current visible top-of-book depth and is not a fill-quality guarantee. Borrow/shorting, funding feeds, corporate actions, exchange calendars, survivorship/delisting treatment, timestamp-gap checks and broader walk-forward robustness checks remain.
- Production backend hosting and Vercel deployment verification. Per prior instruction, nothing is deployed or pushed.

## Current validation performed

- `npm run build` succeeded after the latest frontend changes.
- `python -m compileall -q backend\app backend\alembic` succeeded.
- Automated backend suite and live provider integrations were not run in this turn. Credentials are not available in the project configuration for Alpaca.
