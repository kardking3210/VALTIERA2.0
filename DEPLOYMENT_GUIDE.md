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
- In Vercel Project Settings → Environment Variables, set `VITE_MARKET_DATA_API_URL` to the deployed API origin (for example `https://valtiera-api.onrender.com`) for Production and Preview, then redeploy. Vite embeds this value at build time.
- The production client no longer falls back to `127.0.0.1`; API-backed features show a configuration error if the API URL is missing.
- Never set private API keys as `VITE_*` variables.

## FastAPI API and worker on Render

The root `render.yaml` defines a Docker web service for FastAPI and a background worker for research jobs. In Render, create a Blueprint from this repository and fill in the prompted environment values:

1. Create a Supabase project. Copy its Session Pooler connection string for the persistent Render services. Use `postgresql://` or `postgres://`; the backend converts it to the installed psycopg 3 driver URL.
2. Set `DATABASE_URL` for both Render services. Set `CORS_ORIGINS` on the API service to the exact Vercel production origin, such as `https://your-project.vercel.app`.
3. Keep the generated `VALTIERA_SECRET`. Add optional provider keys in the Render dashboard only if those feeds are enabled.
4. In the Render API service shell, run `alembic upgrade head` from the service's `/srv/valtiera` working directory when applying database migrations.
5. Copy the API service HTTPS URL into Vercel as `VITE_MARKET_DATA_API_URL`, then redeploy the Vercel frontend.

The API and worker need a persistent host for the existing job poller and Python market WebSocket. This repository does not include a Supabase database password, Render account, or Vercel environment values, so those must be entered in their respective dashboards.

## Backend hosting and readiness

The FastAPI API, worker, database and optional Redis require a separately configured host. No production backend is currently deployed or verified. Configure HTTPS, database backups, migrations, CORS allowlist, rate limiting, logs and health checks before public use. Market charts load directly from the external chart embed; the backend does not relay market data. Exchange real-time access depends on its entitlements.

VALTIERA paper orders use a local depth-capped simulator. Optional Alpaca equity paper orders require separate `ALPACA_PAPER_*` credentials, `ALPACA_PAPER_TRADING_ENABLED=true`, and an owner email allowlist; the adapter is fixed to Alpaca’s paper API host. Do not provide live Alpaca keys. EVM native transfers are submitted from the browser only after the user confirms both the in-app review and the wallet extension prompt; no private key is sent to the backend. Solana and Base are not supported.
