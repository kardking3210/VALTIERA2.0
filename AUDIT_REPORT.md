# VALTIERA 2.0 — Local Review

## Current product state

- The React/Vite frontend, dark interactive chart, market summary, quantitative model forms, historical backtest and risk workspace run locally.
- Binance public crypto historical data and a public kline WebSocket provide input prefills and closed-bar updates. Alpaca IEX is optional for US equity candles/stream and needs server-side credentials. Futures, FX and commodity raw model feeds are not configured. The chart embed has independent exchange permissions.
- Local paper trading stores user-scoped balances and orders, checks the public top of book every 10 seconds and caps simulated fills to visible size. It is not a venue fill guarantee.
- Alpaca US-equity paper account orders are supported only with separate paper API credentials, an explicit enable flag and a matching owner email. The integration uses a hard-coded paper host. No live broker order route exists.
- EVM browser extensions can estimate and submit native-token transfers only after a page review confirmation and the wallet's own approval. The backend never receives a private key. Solana and Base are unsupported.
- Backtests report chronological holdout and walk-forward refits for supported strategies, with entered cost assumptions. Timestamp gaps, corporate actions, survivorship, liquidity and venue-specific cost calibration remain limitations.

## Local verification

- `npm run build` succeeded after the UI and wallet changes.
- `python -m compileall -q backend\app backend\alembic` succeeded.
- The local API health check reports an operational database; a 30-candle Binance history request succeeded. The frontend returned HTTP 200 and the crypto WebSocket previously accepted a client and sent a candle.
- The automated suite, Alpaca broker credentials, browser wallet extension connection, and any blockchain transaction were not verified.

## Deployment boundary

The user requested local-only work. No code was pushed to GitHub and no Vercel or backend deployment was made.
