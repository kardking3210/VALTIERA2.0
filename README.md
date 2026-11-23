# VALTIERA 2.0

VALTIERA is a quantitative research workspace for studying market relationships, testing simple research rules on user-supplied historical prices, reviewing manual portfolios and discussing methodology. It does not execute trades, hold assets, supply licensed market data, or claim investment returns.

## Run the full local stack

Requirements: Node.js 20.19+ (or 22.12+), Python 3.11+, and optionally Docker Desktop.

### Option A: local Python with SQLite

Open three terminals from this repository:

```powershell
# Terminal 1: API and persistent local SQLite database
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000

# Terminal 2: durable background research-job worker
cd backend
.\.venv\Scripts\python.exe -m app.worker

# Terminal 3: frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. API health and interactive docs are at `http://127.0.0.1:8000/health` and `http://127.0.0.1:8000/docs`. The default SQLite file is `backend/valtiera.db`. The frontend connects to the local API for product features. Chart display data remains visibly marked local simulation until a market data adapter is configured.

Six fictional local profiles are seeded on first API startup. Use `maya@valtiera.demo` with password `Research-Demo-2026`, or any other profile listed at `/demo-users`. Change `DEMO_PASSWORD` before sharing a development environment. New accounts can also register from the sign-in form.

### Option B: PostgreSQL, Redis, API, and worker with Docker

```powershell
docker compose up --build
npm run dev
```

The compose stack serves the API on port 8000 and PostgreSQL/Redis on their local ports. Set `POSTGRES_PASSWORD` and `VALTIERA_SECRET` in a root `.env` file before using it beyond a local machine. The database volume persists between container restarts. The worker stores and processes durable engine jobs in PostgreSQL. Redis connectivity is monitored but is not currently used as the job queue.

## Product areas

- **Overview:** product explanation, six engine statuses, service health, market data and execution disclosures.
- **Quant lab:** six independent input-driven calculations, interactive candlestick display, run history, and durable queued jobs.
- **Backtesting:** chronological 70/30 holdout reporting, lagged signals, explicit fees, equity curve, volatility, Sharpe ratio and drawdown. Results are labeled historical simulations.
- **Portfolio:** private manual position entry, cost basis, entered-price valuation, P&L, concentration and exposure checks.
- **Risk intelligence:** persistent user limits for position size, drawdown, daily loss, gross exposure and portfolio NAV.
- **Markets and data:** current API/database/Redis/worker/provider condition. A missing market provider returns HTTP 503 rather than a fake quote.
- **Research network:** fictional demo participants, persistent posts and comments, optional polls and one saved vote per profile.
- **Audit log:** selected account, model, risk, position, backtest and community operations.

## Six research engines

1. **Statistical arbitrage:** Pearson and Spearman association, Engle–Granger test, fitted log-price residual spread, rolling Z-score and hedge ratio.
2. **Momentum:** time-series log return and volatility-adjusted score.
3. **Mean reversion:** rolling deviation, simple OLS reversion slope and estimated half-life.
4. **Volatility and options:** realized volatility, optional IV/RV spread, Black–Scholes call baseline, delta, gamma and vega when required inputs are provided.
5. **Cross-asset relative value:** aligned return correlation, relative return and basis.
6. **Market regime:** volatility-threshold description.

These are transparent research calculations with simplified assumptions. They do not include a complete Kalman pairs model, volatility surface, full Greeks, factor model, portfolio optimizer or production-grade regime classifier. Inputs are supplied by the user; the chart series never feed model calculations or backtests.

Backtests enforce a one-observation signal lag and report a chronological holdout, but they are not a substitute for independent quantitative validation. They do not include survivorship-bias controls, corporate actions, borrow, funding, slippage models, realistic market calendars or parameter-selection embargoes. Never treat a simulation as verified performance.

## API and persistence

- `POST /auth/register`, `POST /auth/login`, `GET /auth/me`
- `GET /engines`, `POST /engines/{engine_name}/run`, `GET /engines/history`
- `POST /jobs`, `GET /jobs/{job_id}` (requires the background worker to process queued jobs)
- `POST /backtests`, `GET /backtests`
- `GET/PUT /risk/settings`, `GET /risk/assessment`
- `GET/POST /portfolio/positions`, `DELETE /portfolio/positions/{id}`
- `GET/POST /community/posts`, comments and poll vote routes
- `GET /audit`, `GET /events` (server-sent system status)
- `GET /health`, `GET /market-data/candles` (503 until an authorized provider adapter exists)

SQLAlchemy persists account records, settings, positions, research executions, backtests, jobs, community content and activity. Local startup creates the SQLite schema. Alembic is configured for explicit environment migrations:

```powershell
cd backend
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe revision --autogenerate -m "describe schema change"
```

Authentication uses salted PBKDF2 password hashes and signed, expiring bearer tokens. Set a strong random `VALTIERA_SECRET`, `DATABASE_URL`, `CORS_ORIGINS`, and `ALLOW_DEMO_SEED=false` in production. Login rate limits are process-local and must be replaced by a shared limiter for a multi-instance production deployment. Database transport encryption, managed backups, secret rotation, formal role administration, and external audit immutability still need deployment-level work.

## Tests and build

```powershell
# Python engine, storage, auth, backtest, risk, worker and community checks
cd backend
.\.venv\Scripts\python.exe -m pytest -q

# Frontend type-check and production build
cd ..
npm run build
```

## Vercel deployment

Use two Vercel projects connected to this repository:

1. **Frontend project:** Root Directory is the repository root. `vercel.json` configures the Vite build (`npm run build`, output `dist`). Set `VITE_MARKET_DATA_API_URL` to the deployed API origin and redeploy.
2. **API project:** Root Directory is `backend`. `backend/main.py` exports the FastAPI app; the Python runtime reads `backend/requirements.txt`. Set `DATABASE_URL` to managed PostgreSQL, a unique `VALTIERA_SECRET`, `CORS_ORIGINS` to the frontend production domain (and any preview domains), and `ALLOW_DEMO_SEED=false`. Never use SQLite for persistent production data.

Vercel can host the static frontend and FastAPI application. The continuous worker should run as a separate worker service sharing the managed database; Vercel Functions are request-driven and do not provide a continuously running worker process. Configure licensed data provider credentials only on a server-side adapter once the company has an appropriate data agreement. The current candle route remains unavailable until that integration is built and validated.

The supplied design brief references video/poster files but the pasted attachment contained no actual media URLs or files. The Overview therefore uses an original CSS orbital illustration; replace it with the approved VALTIERA media assets when they are available.

## Risk and product disclosures

All investments involve risk. Historical and simulated results do not predict future performance. Model outputs depend on input quality, assumptions and implementation limits. VALTIERA is a research product in development, not an investment adviser, licensed fund, broker, custodian or trading system.
