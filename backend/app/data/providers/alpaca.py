"""Alpaca IEX read-only data adapter. Requires user-configured market-data credentials."""
from datetime import datetime, timedelta, timezone
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REST = "https://data.alpaca.markets/v2"
INTERVALS = {"1m": ("1Min", 60), "5m": ("5Min", 300), "15m": ("15Min", 900), "1h": ("1Hour", 3600), "4h": ("1Hour", 3600), "1d": ("1Day", 86400), "1w": ("1Day", 86400)}


def credentials() -> tuple[str,str] | None:
    key=os.getenv("ALPACA_API_KEY","").strip(); secret=os.getenv("ALPACA_SECRET_KEY","").strip()
    if key and secret: return key,secret
    if os.getenv("ALPACA_PAPER_TRADING_ENABLED","").lower()=="true":
        key=os.getenv("ALPACA_PAPER_API_KEY","").strip(); secret=os.getenv("ALPACA_PAPER_SECRET_KEY","").strip()
        if key and secret: return key,secret
    return None

def configured() -> bool:
    return credentials() is not None


def _get(path: str, params: dict) -> dict:
    if not configured():
        raise RuntimeError("Equity data needs ALPACA_API_KEY and ALPACA_SECRET_KEY configured on the backend")
    url = f"{REST}{path}?{urlencode(params)}"
    key,secret=credentials() or ("","")
    request = Request(url, headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        if exc.code in (401, 403): raise RuntimeError("Equity data credentials are invalid or the selected feed is not entitled") from None
        raise RuntimeError(f"Equity data request failed ({exc.code})") from None
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        raise RuntimeError("Equity data is temporarily unavailable") from None


def fetch_bars(symbol: str, timeframe: str = "1d", limit: int = 500) -> dict:
    symbol = symbol.upper().strip()
    if not symbol.isalnum() or not 1 <= len(symbol) <= 16:
        raise ValueError("Use a valid US equity symbol such as AAPL")
    if timeframe not in INTERVALS:
        raise ValueError("Alpaca IEX supports 1m, 5m, 15m, 1h, 4h, 1d and 1w bars")
    if not 30 <= limit <= 1000:
        raise ValueError("Candle limit must be from 30 to 1000")
    interval, seconds = INTERVALS[timeframe]
    end = datetime.now(timezone.utc)
    # Request enough calendar days to include 500 daily bars or the matching intraday history.
    days = min(3650, max(2, int(limit * seconds / 86400 * 5)))
    data = _get(f"/stocks/{symbol}/bars", {"timeframe": interval, "start": (end - timedelta(days=days)).isoformat(), "end": end.isoformat(), "limit": limit, "feed": "iex", "adjustment": "all", "sort": "asc"})
    rows = data.get("bars", [])
    candles = []
    for row in rows:
        try:
            timestamp = datetime.fromisoformat(row["t"].replace("Z", "+00:00"))
            candle = {"time": int(timestamp.timestamp()), "open": float(row["o"]), "high": float(row["h"]), "low": float(row["l"]), "close": float(row["c"]), "volume": float(row["v"]), "close_time": int(timestamp.timestamp() + seconds)}
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("Equity provider returned malformed candle data") from None
        if candle["high"] < max(candle["open"], candle["close"]) or candle["low"] > min(candle["open"], candle["close"]) or candle["volume"] < 0:
            raise RuntimeError("Equity provider returned invalid OHLCV values")
        candles.append(candle)
    if timeframe in ("1w", "4h"):
        # Collapse hourly bars into 4-hour windows and daily bars into exchange weeks.
        grouped = {}
        for candle in candles:
            date = datetime.fromtimestamp(candle["time"], timezone.utc)
            key = date.isocalendar()[:2] if timeframe == "1w" else (date.date().isoformat(), date.hour // 4)
            group = grouped.setdefault(key, {**candle, "high": candle["high"], "low": candle["low"], "volume": 0})
            group["high"] = max(group["high"], candle["high"]); group["low"] = min(group["low"], candle["low"]); group["close"] = candle["close"]; group["volume"] += candle["volume"]; group["close_time"] = candle["close_time"]
        candles = list(grouped.values())
    now = int(datetime.now(timezone.utc).timestamp())
    candles = [c for c in candles if c["close_time"] <= now]
    if len(candles) < 30:
        raise RuntimeError("Fewer than 30 completed IEX candles are available for this symbol and interval")
    return {"symbol": symbol, "timeframe": timeframe, "source": "Alpaca IEX (US equities)", "provider_status": "AVAILABLE", "fetched_at": datetime.now(timezone.utc).isoformat(), "candles": candles[-limit:]}


def latest_trade(symbol: str) -> dict:
    symbol = symbol.upper().strip()
    data = _get(f"/stocks/{symbol}/trades/latest", {"feed": "iex"})
    trade = data.get("trade", {})
    try:
        return {"symbol": symbol, "price": float(trade["p"]), "size": int(trade["s"]), "timestamp": trade["t"], "source": "Alpaca IEX"}
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("No current IEX trade is available for this symbol") from None


def top_of_book(symbol: str, side: str) -> dict:
    symbol=symbol.upper().strip()
    if not symbol.isalnum() or side not in {"BUY","SELL"}: raise ValueError("Invalid symbol or paper order side")
    data=_get(f"/stocks/{symbol}/quotes/latest",{"feed":"iex"}); quote=data.get("quote",{})
    try:
        price=float(quote["ap"] if side=="BUY" else quote["bp"])
        size=float(quote["as"] if side=="BUY" else quote["bs"])
        if price<=0 or size<0: raise ValueError()
        return {"symbol":symbol,"levels":[(price,size)],"source":"Alpaca IEX top quote","timestamp":quote["t"]}
    except (KeyError,TypeError,ValueError): raise RuntimeError("No usable IEX top-of-book quote is available") from None
