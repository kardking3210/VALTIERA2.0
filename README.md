# VALTIERA Research Workspace

A development research interface with six input-driven quantitative calculations. It is not a trading system, does not provide investment advice, and does not claim verified results.

## Run locally

- Frontend: `npm install`, then `npm run dev`.
- Backend: from `backend`, install `requirements.txt`, then run `uvicorn app.main:app --reload --port 8000`.
- Set `VITE_MARKET_DATA_API_URL=http://localhost:8000` in `.env.local` to connect the UI. Without it, the chart clearly identifies its local series as simulated.
- Engine endpoint: `POST /engines/{engine}/run` with `{"data":{"prices":[...],"peer_prices":[...]},"parameters":{}}`. All price series require 30 or more finite positive observations.
- Tests: from `backend`, run `pytest`.

## Deploy the frontend to Vercel

Import this repository in Vercel with the Vite preset. `vercel.json` sets `npm run build` and `dist`. Define `VITE_MARKET_DATA_API_URL` as the public origin of a separately hosted FastAPI service, then redeploy. Add the Vercel production and preview origins to that service's `CORS_ORIGINS`. Vite embeds `VITE_` values into the browser build; never place credentials there.

Only the static React frontend is configured for Vercel. The API, database, workers, authentication, persistence, and licensed market data are not production configured. The current API reports database and market-data availability honestly; candles return HTTP 503 until a licensed provider adapter exists. The compose file supplies local PostgreSQL and Redis for future service work only.

## Data and calculations

The API accepts caller-supplied series. Implemented calculations include pair correlation and Engle-Granger cointegration statistics, rolling spread Z-scores, volatility-adjusted momentum, rolling deviation and mean-reversion half-life estimate, realized volatility and a Black-Scholes call baseline when option inputs are supplied, cross-asset correlation/basis, and a volatility-threshold regime descriptor. These are research calculations with simplified assumptions; they do not include transaction costs, portfolio construction, verified backtests, or execution.

Chart display series remain isolated from model calculations. A missing market-data provider never gets represented as live data.
