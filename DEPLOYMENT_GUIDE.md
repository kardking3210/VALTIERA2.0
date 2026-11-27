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

## Vercel + Supabase (two Vercel projects)

Deploy the frontend and API as separate projects from the same GitHub repository:

1. Frontend project: repository `kardking3210/VALTIERA2.0`, branch `main`, root directory `/`, framework Vite, build command `npm run build`, output directory `dist`.
2. API project: import the same repository again, select root directory `backend`, and use the FastAPI/Python preset. `backend/main.py` exports the FastAPI app and `backend/requirements.txt` lists its dependencies. `backend/vercel.json` sets the function duration for computations and reconnectable WebSocket sessions.
3. Create a Supabase project. In its Connect dialog, copy the Transaction Pooler URL for serverless functions. Add it to the API Vercel project as `DATABASE_URL`.
4. In the API Vercel project, add `VALTIERA_SECRET` (long random value) and `CORS_ORIGINS` (the exact frontend production URL). Add provider credentials such as `FMP_API_KEY` only if needed; keep them server-side.
5. Deploy the API, copy its Vercel URL, then set `VITE_MARKET_DATA_API_URL` in the frontend Vercel project to that URL. Redeploy the frontend.
6. Check `<api-url>/health` for database status. Research jobs calculate inline in the serverless request. The persistent paper-order monitor does not run on Vercel; users can manually process open conditional orders.

The frontend uses a same-origin localhost default only in development. Production API calls report a configuration error until `VITE_MARKET_DATA_API_URL` is set. Vercel Python Functions and FastAPI WebSockets have function duration limits, so clients must reconnect. Supabase transaction pooling is configured with one SQLAlchemy connection per warm function instance and disables prepared statements.

## Backend hosting and readiness

Production hosting still requires creating both Vercel projects and entering the Supabase URL and secrets in their dashboards. Configure database backups, migrations, CORS allowlist, rate limiting, logs and health checks before public use. Market charts load directly from the external chart embed; the backend does not relay market data. Exchange real-time access depends on its entitlements.

VALTIERA paper orders use a local depth-capped simulator. Optional Alpaca equity paper orders require separate `ALPACA_PAPER_*` credentials, `ALPACA_PAPER_TRADING_ENABLED=true`, and an owner email allowlist; the adapter is fixed to Alpaca’s paper API host. Do not provide live Alpaca keys. EVM native transfers are submitted from the browser only after the user confirms both the in-app review and the wallet extension prompt; no private key is sent to the backend. Solana and Base are not supported.
