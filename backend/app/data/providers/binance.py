"""Read-only public Spot candle adapter for research form prefill and summaries."""
from datetime import datetime, timezone
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from .http import fetch_json

BASE_URL = "https://data-api.binance.vision/api/v3/klines"
INTERVALS = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"}
_cache: dict[tuple[str, str, int], tuple[float, dict]] = {}


def fetch_candles(symbol: str, timeframe: str = "1d", limit: int = 500) -> dict:
    normalized = symbol.upper().strip()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", normalized):
        raise ValueError("Use a crypto Spot symbol such as BTCUSDT")
    if timeframe not in INTERVALS:
        raise ValueError("Unsupported Spot candle interval")
    if not 30 <= limit <= 1000:
        raise ValueError("Candle limit must be from 30 to 1000")
    key = (normalized, timeframe, limit)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < 20:
        result = dict(cached[1])
        result["cache"] = "HIT"
        return result
    # Binance includes the currently forming kline in the response. Fetch one
    # extra row so filtering that bar still leaves the requested closed sample.
    query = urlencode({"symbol": normalized, "interval": timeframe, "limit": min(limit + 1, 1000)})
    request = Request(f"{BASE_URL}?{query}", headers={"User-Agent": "VALTIERA-Research/1.0", "Accept": "application/json"})
    try:
        rows = fetch_json(request, timeout=8)
    except HTTPError as exc:
        raise RuntimeError(f"Public candle request failed ({exc.code})") from None
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        raise RuntimeError("Public candle history is temporarily unavailable") from None
    if not isinstance(rows, list) or len(rows) < 30:
        raise RuntimeError("Provider returned fewer than 30 candles")
    candles = []
    for row in rows:
        try:
            candle = {"time": int(row[0]) // 1000, "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4]), "volume": float(row[5]), "close_time": int(row[6])}
        except (IndexError, TypeError, ValueError):
            raise RuntimeError("Provider returned malformed candle data") from None
        if not all(value > 0 for value in (candle["open"], candle["high"], candle["low"], candle["close"])) or candle["volume"] < 0 or candle["high"] < max(candle["open"], candle["close"]) or candle["low"] > min(candle["open"], candle["close"]):
            raise RuntimeError("Provider returned invalid OHLCV values")
        candles.append(candle)
    # Discard the currently forming interval so model inputs use closed observations.
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    candles = [candle for candle in candles if candle["close_time"] < now_ms]
    if len(candles) < 30:
        raise RuntimeError("Fewer than 30 completed candles are available")
    result = {"symbol": normalized, "timeframe": timeframe, "source": "Binance Spot public market data", "provider_status": "AVAILABLE", "fetched_at": datetime.now(timezone.utc).isoformat(), "candles": candles}
    _cache[key] = (time.monotonic(), result)
    response = dict(result)
    response["cache"] = "MISS"
    return response


def latest_quote(symbol: str) -> dict:
    normalized = symbol.upper().strip()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", normalized):
        raise ValueError("Use a crypto Spot symbol such as BTCUSDT")
    request = Request(f"https://data-api.binance.vision/api/v3/ticker/price?{urlencode({'symbol': normalized})}", headers={"User-Agent": "VALTIERA-Research/1.0", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=6) as response:
            payload = json.loads(response.read())
        return {"symbol": normalized, "price": float(payload["price"]), "timestamp": datetime.now(timezone.utc).isoformat(), "source": "Binance public Spot ticker"}
    except HTTPError as exc:
        raise RuntimeError(f"Public quote request failed ({exc.code})") from None
    except (URLError, TimeoutError, OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise RuntimeError("Public quote is temporarily unavailable") from None


def top_of_book(symbol: str, side: str, levels: int = 10) -> dict:
    """Return visible public book levels for conservative paper fills only."""
    normalized=symbol.upper().strip()
    if not re.fullmatch(r"[A-Z0-9]{5,20}",normalized) or side not in {"BUY","SELL"}:
        raise ValueError("Invalid symbol or paper order side")
    request=Request(f"https://data-api.binance.vision/api/v3/depth?{urlencode({'symbol':normalized,'limit':min(max(levels,1),20)})}",headers={"User-Agent":"VALTIERA-Research/1.0","Accept":"application/json"})
    try:
        with urlopen(request,timeout=6) as response: payload=json.loads(response.read())
        rows=payload.get("asks" if side=="BUY" else "bids",[])
        parsed=[(float(row[0]),float(row[1])) for row in rows]
        if not parsed or any(price<=0 or size<0 for price,size in parsed): raise ValueError()
        return {"symbol":normalized,"levels":parsed,"source":"Binance public order book","timestamp":datetime.now(timezone.utc).isoformat()}
    except HTTPError as exc: raise RuntimeError(f"Public order book request failed ({exc.code})") from None
    except (URLError,TimeoutError,OSError,json.JSONDecodeError,KeyError,TypeError,ValueError,IndexError): raise RuntimeError("Public order book is temporarily unavailable") from None
