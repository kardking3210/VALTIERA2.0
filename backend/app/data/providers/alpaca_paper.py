"""Broker paper-trading adapter. The host is fixed to Alpaca's paper API."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE="https://paper-api.alpaca.markets/v2"

def configured():
    return os.getenv("ALPACA_PAPER_TRADING_ENABLED","").lower()=="true" and bool(os.getenv("ALPACA_PAPER_API_KEY","").strip() and os.getenv("ALPACA_PAPER_SECRET_KEY","").strip())

def _request(path:str,method="GET",payload=None,query=None):
    if os.getenv("ALPACA_PAPER_TRADING_ENABLED","").lower()!="true": raise RuntimeError("Alpaca paper broker is disabled. Set ALPACA_PAPER_TRADING_ENABLED=true to enable its isolated paper endpoint")
    if not configured(): raise RuntimeError("Configure ALPACA_PAPER_API_KEY and ALPACA_PAPER_SECRET_KEY on the backend")
    url=f"{BASE}{path}"+(f"?{urlencode(query)}" if query else "")
    body=json.dumps(payload).encode() if payload is not None else None
    request=Request(url,data=body,method=method,headers={"APCA-API-KEY-ID":os.environ["ALPACA_PAPER_API_KEY"],"APCA-API-SECRET-KEY":os.environ["ALPACA_PAPER_SECRET_KEY"],"Accept":"application/json","Content-Type":"application/json"})
    try:
        with urlopen(request,timeout=10) as response: return json.loads(response.read()) if response.status!=204 else {}
    except HTTPError as exc:
        if exc.code in (401,403): raise RuntimeError("Alpaca paper credentials were rejected or paper trading is unavailable") from None
        try: detail=json.loads(exc.read()).get("message")
        except Exception: detail=None
        raise RuntimeError(f"Alpaca paper request failed ({exc.code})"+(f": {detail}" if detail else "")) from None
    except (URLError,TimeoutError,OSError,json.JSONDecodeError): raise RuntimeError("Alpaca paper service is temporarily unavailable") from None

def account():
    row=_request("/account")
    return {"provider":"Alpaca Paper","mode":"PAPER_ONLY","status":row.get("status"),"currency":row.get("currency"),"cash":float(row.get("cash",0)),"equity":float(row.get("equity",0)),"buying_power":float(row.get("buying_power",0)),"trading_blocked":bool(row.get("trading_blocked",False)),"account_id_masked":"…"+str(row.get("id",""))[-6:]}

def orders():
    rows=_request("/orders",query={"status":"all","limit":50,"direction":"desc"})
    return [{"id":row.get("id"),"symbol":row.get("symbol"),"side":row.get("side"),"type":row.get("type"),"quantity":float(row.get("qty") or 0),"filled_quantity":float(row.get("filled_qty") or 0),"average_fill_price":float(row["filled_avg_price"]) if row.get("filled_avg_price") else None,"status":row.get("status"),"created_at":row.get("created_at")} for row in rows]

def place_order(symbol:str,side:str,order_type:str,quantity:float,limit_price:float|None):
    payload={"symbol":symbol.upper(),"qty":str(quantity),"side":side.lower(),"type":order_type.lower(),"time_in_force":"gtc" if order_type=="LIMIT" else "day"}
    if order_type=="LIMIT": payload["limit_price"]=str(limit_price)
    if order_type=="STOP": payload["stop_price"]=str(limit_price)
    row=_request("/orders","POST",payload)
    return {"id":row.get("id"),"symbol":row.get("symbol"),"side":row.get("side"),"type":row.get("type"),"quantity":float(row.get("qty") or 0),"filled_quantity":float(row.get("filled_qty") or 0),"average_fill_price":float(row["filled_avg_price"]) if row.get("filled_avg_price") else None,"status":row.get("status"),"created_at":row.get("created_at")}

def cancel_order(order_id:str):
    if not order_id.isalnum() and not all(part.isalnum() or part=="-" for part in order_id): raise ValueError("Invalid paper order identifier")
    _request(f"/orders/{order_id}","DELETE")
    return {"id":order_id,"status":"CANCEL_REQUESTED","mode":"PAPER_ONLY"}
