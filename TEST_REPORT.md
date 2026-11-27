# Test Report

Verification after replacing the market chart and removing the legacy market-data feeds:

- Frontend production build: passed (`npm run build`).
- Frontend tests: passed (5 tests).
- Backend tests: passed (34 tests). Six SciPy optimizer bound-clipping warnings occurred in GARCH-related tests.
- Local frontend: `http://127.0.0.1:5176/` returned HTTP 200.
- Local API: `http://127.0.0.1:8001/health` returned HTTP 200.

The chart is an external embedded widget. Its market availability and latency depend on exchange entitlements; the widget does not provide its raw candle series to VALTIERA for summaries or backtests.
