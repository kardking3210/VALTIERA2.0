# VALTIERA 2.0

VALTIERA is a quantitative research terminal for market analysis, model calculations, historical simulation, risk review and simulated paper orders. Broker submission is restricted to Alpaca’s separate paper API. EVM native-token transfers can be sent only from a connected browser wallet after an explicit confirmation here and an approval in the wallet. VALTIERA never receives private keys. See `DEPLOYMENT_GUIDE.md` for the Vercel + Supabase setup.

## Local development

Frontend: `npm install` then `npm run dev` from the repository root.

Backend: create a virtual environment in `backend`, install `backend/requirements.txt`, then run `uvicorn app.main:app --reload --port 8000` from `backend`. Set `VITE_MARKET_DATA_API_URL=http://127.0.0.1:8000` in root `.env.local` when using that port. Local SQLite is the default.

## Product areas

- **Markets:** large dark embedded interactive chart and a separate live crypto kline feed. The embedded chart has its own market-data permissions and may show delayed data depending on symbol/exchange.
- **Models:** automatically load historical crypto candles; the sample and parameters remain editable. Closed Binance stream bars append to the active sample. Optional US equity history is available from Alpaca IEX with server-side credentials; the UI equity stream is 1-minute and does not represent consolidated tape coverage. Peer strategies need the peer series refreshed to retain alignment.
- **Backtests:** lagged historical signals, chronological holdout and expanding-window parameter refit for supported directional models. User-entered fee, slippage, spread, impact and per-bar funding assumptions are applied. The engine has no venue depth model or licensed point-in-time data validation.
- **Paper trading:** a per-user simulated $100,000 ledger, market/limit/stop orders, fee deductions, positions, cancellation and a local monitor that checks top-of-book depth every 10 seconds. Orders may partially fill up to observed visible size; this remains a simulation. This is still a simulation and not venue execution.
- **Wallet architecture:** connect an injected EVM wallet and estimate native-token gas. Transfers can be submitted after a review step and the wallet extension’s confirmation prompt. Receipt status is polled from the wallet RPC. The app never has custody of keys. Solana/Base support is not implemented.
- **Risk:** historical, sample-dependent metrics and manually entered portfolio exposures.

## Data configuration

Binance public Spot history and WebSocket stream need no key. Alpaca equity history/stream requires backend-only `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` in the backend environment; its IEX feed is one exchange feed, not consolidated US equity coverage. Never put private provider keys in `VITE_*` variables.

The product identifies data source, timestamp and availability when the provider returns that metadata. It does not claim that an embedded chart is the same feed as model inputs. Market summary verdicts describe computed sample statistics and are not forecasts or trade instructions.

## Backtest limitations

The walk-forward report chooses a bounded parameter grid using only prior folds, then measures the next chronological fold. This reduces direct look-ahead but does not address data snooping, timestamp gaps, stale quotes, survivorship, delisted symbols, corporate actions, taxes, liquidity, market impact calibration or exchange-specific costs. Entered costs are assumptions, not measured fills. Results are not live performance.

## Deployment status

The repository supports separate Vercel frontend and FastAPI projects backed by Supabase Postgres. Each project, its secrets, and the database URL must be configured in the service dashboards. The Vercel serverless deployment calculates queued research requests inline and does not run the persistent paper-order monitor. `docker-compose.yml` requires explicit `POSTGRES_PASSWORD` and `VALTIERA_SECRET`. Alpaca paper orders require `ALPACA_PAPER_TRADING_ENABLED=true`, a paper-only key pair and the matching `ALPACA_PAPER_OWNER_EMAIL` on the backend.
