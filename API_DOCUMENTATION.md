# API Documentation — Local Research Prototype

Default local API URL: `http://127.0.0.1:8000`. Authenticated endpoints require `Authorization: Bearer <token>`.

| Method | Path | Auth | Behavior |
|---|---|---:|---|
| GET | `/health` | No | Database, worker, optional Redis and engine status |
| POST | `/auth/register`, `/auth/login`, `/auth/logout` | Mixed | Local researcher session lifecycle |
| GET | `/market-data/history` | No | Closed historical candles and computed volatility. `provider=crypto` uses Binance public Spot; `provider=equity` uses Alpaca IEX and requires backend credentials. Optional peer history is timestamp aligned. |
| GET | `/market-data/coverage` | No | Provider configuration and supported coverage status |
| GET | `/market-data/quote` | No | Latest public crypto ticker or Alpaca IEX trade snapshot |
| WS | `/ws/market/{crypto\|equity}/{symbol}/{timeframe}` | No | Binance public kline stream or authenticated Alpaca IEX trade/bar stream |
| POST | `/market-data/summary` | No | Computed historical metrics plus configured explanation/fallback |
| POST | `/engines/{engine_name}/run` | Yes | Run deterministic research calculation over submitted data |
| POST | `/backtests` | Yes | Persist historical simulation, cost assumptions, holdout metrics, walk-forward folds and input fingerprint |
| GET | `/backtests` | Yes | Read saved simulations |
| GET | `/paper/account` | Yes | Read the user's separate simulated cash, positions and order history |
| POST | `/paper/orders` | Yes | Create a quote-snapshot simulated market/limit/stop order; does not contact a broker order API |
| POST | `/paper/orders/{id}/process` | Yes | Recheck an open conditional paper order against the latest quote |
| DELETE | `/paper/orders/{id}` | Yes | Cancel the remaining quantity of an open/partially filled simulated order |
| GET | `/broker/alpaca-paper/account` | Yes | Read configured Alpaca paper-account status and recent orders. Requires a separately configured paper key pair, explicit enable flag and matching `ALPACA_PAPER_OWNER_EMAIL`. |
| POST | `/broker/alpaca-paper/orders` | Yes | Send a US-equity order to Alpaca paper API only; API host is hard-coded to paper-api. |
| DELETE | `/broker/alpaca-paper/orders/{id}` | Yes | Request cancellation from Alpaca paper API only |
| GET/PUT | `/risk/settings` | Yes | Read/update personal risk settings |
| GET | `/portfolio`, `/risk/assessment` | Yes | Read saved position exposure and historical risk |

## Constraints

- The browser chart embed has independent data permissions and is not a raw-data or execution API.
- Alpaca IEX is not consolidated US market coverage; credentials and entitlements are required.
- `GET /market-data/history?provider=forex|futures|commodities` loads FMP daily or weekly historical candles. Configure backend-only `FMP_API_KEY`; symbol coverage depends on the FMP plan. No live feed is provided by these routes, and futures symbols are the provider's listed series rather than exchange-direct contract market data.
- Local paper orders are monitored every 10 seconds by the API worker. Crypto uses public top-of-book levels; equity requires Alpaca IEX quotes. Simulated quantity is capped to visible book size and can partially fill. This is an approximation, not a venue fill guarantee. Alpaca broker-paper orders are sent only to the fixed paper endpoint when explicitly selected and submitted.
- The wallet page uses an injected EVM wallet, estimates a native-token transfer, displays a review confirmation, then asks the wallet extension for final approval. Transaction receipt state is checked via wallet RPC. No private key reaches the backend.
- Backtest cost values are user assumptions. The API cannot independently verify the source of submitted numeric arrays or detect missing timestamps when only arrays are provided.
- API modules and migrations require broader integration review before production use. Production hosting is not configured.
