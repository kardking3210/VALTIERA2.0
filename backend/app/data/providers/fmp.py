"""FMP end-of-day history adapter for forex and commodity/futures symbols."""
from datetime import datetime, timedelta, timezone
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request
from .http import fetch_json

BASE = "https://financialmodelingprep.com/stable"
PROVIDERS = {
    "forex": ("FMP Forex (end-of-day)", "Forex"),
    "futures": ("FMP futures series (end-of-day)", "Futures"),
    "commodities": ("FMP commodities (end-of-day)", "Commodities"),
}


def configured() -> bool:
    return bool(os.getenv("FMP_API_KEY", "").strip())


def fetch_bars(asset_class: str, symbol: str, timeframe: str = "1d", limit: int = 500) -> dict:
    if asset_class not in PROVIDERS:
        raise ValueError("Select forex, futures, or commodities")
    symbol = symbol.upper().strip()
    if not symbol.isalnum() or not 3 <= len(symbol) <= 20:
        raise ValueError("Use the symbol format listed by FMP, for example EURUSD for forex")
    if timeframe not in {"1d", "1w"}:
        raise ValueError("FMP model history currently supports daily and weekly candles for these markets")
    if not 30 <= limit <= 1000:
        raise ValueError("Candle limit must be from 30 to 1000")
    key = os.getenv("FMP_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Other-market history requires FMP_API_KEY in backend/.env; the key stays on the backend")
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=int(limit * (7 if timeframe == "1w" else 2.2)))
    params = urlencode({"symbol": symbol, "from": start.isoformat(), "to": end.isoformat(), "apikey": key})
    request = Request(f"{BASE}/historical-price-eod/full?{params}", headers={"Accept": "application/json", "User-Agent": "VALTIERA-local-research/1.0"})
    try:
        rows = fetch_json(request, timeout=15)
    except HTTPError as exc:
        if exc.code in (401, 403):
            body=exc.read(2048).decode("utf-8",errors="replace")
            try:
                detail=json.loads(body)
                detail=detail.get("Error Message") or detail.get("message") or detail.get("error") or ""
            except (ValueError,AttributeError): detail=""
            detail=str(detail).replace(key,"[redacted]")[:240]
            reason=f": {detail}" if detail else ""
            raise RuntimeError(f"FMP denied this request ({exc.code}); check the API key, symbol format, endpoint and plan entitlement{reason}") from None
        raise RuntimeError(f"FMP history request failed ({exc.code})") from None
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        raise RuntimeError("FMP history is temporarily unavailable") from None
    if isinstance(rows, dict) and rows.get("Error Message"):
        raise RuntimeError("FMP could not return this symbol; check the symbol and your plan coverage")
    if not isinstance(rows, list):
        raise RuntimeError("FMP returned an unexpected historical-data response")
    candles = []
    for row in reversed(rows):
        try:
            timestamp = int(datetime.strptime(row["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
            close = float(row["close"])
            candle = {"time": timestamp, "open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]), "close": close, "volume": float(row.get("volume") or 0), "close_time": timestamp + 86400}
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("FMP returned malformed end-of-day candles") from None
        if min(candle["open"], candle["high"], candle["low"], close) <= 0 or candle["high"] < max(candle["open"], close) or candle["low"] > min(candle["open"], close):
            continue
        candles.append(candle)
    if timeframe == "1w":
        grouped = {}
        for candle in candles:
            date = datetime.fromtimestamp(candle["time"], timezone.utc).date()
            key = date.isocalendar()[:2]
            group = grouped.setdefault(key, {**candle, "volume": 0})
            group["high"] = max(group["high"], candle["high"])
            group["low"] = min(group["low"], candle["low"])
            group["close"] = candle["close"]
            group["volume"] += candle["volume"]
            group["close_time"] = candle["close_time"]
        candles = list(grouped.values())
    candles = candles[-limit:]
    if len(candles) < 30:
        raise RuntimeError("Fewer than 30 completed candles were returned; check symbol access and history coverage")
    source = PROVIDERS[asset_class][0]
    return {"symbol": symbol, "timeframe": timeframe, "source": source, "provider_status": "AVAILABLE_HISTORY_ONLY", "fetched_at": datetime.now(timezone.utc).isoformat(), "candles": candles}
