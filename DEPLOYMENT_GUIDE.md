# Deployment Guide

## Local frontend

1. Install Node.js and run `npm install`.
2. Run `npm run dev` from the repository root.
3. Set `VITE_MARKET_DATA_API_URL` only to a non-secret API base URL. Vite variables are public to browsers.

## Local API

1. Create and activate a Python virtual environment under `backend`.
2. Install `backend/requirements.txt`.
3. Configure `DATABASE_URL`, `CORS_ORIGINS`, and a strong `VALTIERA_SECRET` outside source control.
4. Start from `backend` using `uvicorn app.main:app --reload --port 8000`.
5. Use SQLite for local development. Apply versioned Alembic migrations after migration setup is consolidated.

## Vercel frontend

- Framework: Vite; build command `npm run build`; output directory `dist`.
- Configure `VITE_MARKET_DATA_API_URL` to the separately hosted API origin.
- Never set private API keys as `VITE_*` variables.

## Backend hosting and readiness

The FastAPI API, worker, database and optional Redis require a separately configured host. No production backend is currently deployed or verified. Configure HTTPS, database backups, migrations, CORS allowlist, rate limiting, logs and health checks before public use. Market charts load directly from the external chart embed; the backend does not relay market data. Exchange real-time access depends on its entitlements.

VALTIERA paper orders use a local depth-capped simulator. Optional Alpaca equity paper orders require separate `ALPACA_PAPER_*` credentials, `ALPACA_PAPER_TRADING_ENABLED=true`, and an owner email allowlist; the adapter is fixed to Alpaca’s paper API host. Do not provide live Alpaca keys. EVM native transfers are submitted from the browser only after the user confirms both the in-app review and the wallet extension prompt; no private key is sent to the backend. Solana and Base are not supported.
