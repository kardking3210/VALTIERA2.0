"""VALTIERA quantitative research API; market charts are provided by the external chart embed."""
import asyncio, hashlib, json, logging, os, time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request as URLRequest, urlopen
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv
import websockets
from sqlalchemy import func, text, inspect
from sqlalchemy.orm import Session
from .auth import bearer, current_user, hash_password, issue_token, verify_password
from .db import Base, DATABASE_URL, SessionLocal, engine, get_db
from .engines.core import calculate, ENGINES, _exponential, _garch_fit, _wilder_rsi
from .data.providers.binance import fetch_candles, latest_quote, top_of_book as binance_book
from .data.providers import alpaca as alpaca_provider
from .data.providers import fmp as fmp_provider
from .data.providers import alpaca_paper as broker_paper
from .models import AuditLog, Backtest, EngineRun, PaperAccount, PaperOrder, Position, ResearchJob, RevokedSession, RiskSettings, ServiceHeartbeat, User

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
logger=logging.getLogger("valtiera.api")

def initialize_storage():
    if not DATABASE_URL.startswith("sqlite") and not os.getenv("VALTIERA_SECRET"):
        raise RuntimeError("VALTIERA_SECRET must be configured for non-development deployments")
    Base.metadata.create_all(bind=engine)
    columns={c["name"] for c in inspect(engine).get_columns("risk_settings")}
    additions={"portfolio_nav":"FLOAT NOT NULL DEFAULT 100000","risk_profile":"VARCHAR(20) NOT NULL DEFAULT 'moderate'","max_leverage_pct":"FLOAT NOT NULL DEFAULT 100","asset_class_limits":"JSON NOT NULL DEFAULT '{}'","volatility_tolerance":"VARCHAR(20) NOT NULL DEFAULT 'moderate'","liquidity_floor_usd":"FLOAT NOT NULL DEFAULT 0","investment_horizon_months":"INTEGER NOT NULL DEFAULT 12"}
    with engine.begin() as connection:
        for column,ddl in additions.items():
            if column not in columns: connection.execute(text(f"ALTER TABLE risk_settings ADD COLUMN {column} {ddl}"))
    order_columns={c["name"] for c in inspect(engine).get_columns("paper_orders")} if "paper_orders" in inspect(engine).get_table_names() else set()
    with engine.begin() as connection:
        if order_columns and "filled_quantity" not in order_columns: connection.execute(text("ALTER TABLE paper_orders ADD COLUMN filled_quantity FLOAT NOT NULL DEFAULT 0"))
        if order_columns and "average_fill_price" not in order_columns: connection.execute(text("ALTER TABLE paper_orders ADD COLUMN average_fill_price FLOAT"))
@asynccontextmanager
async def lifespan(_app):
    initialize_storage()
    monitor=asyncio.create_task(paper_order_monitor())
    try: yield
    finally:
        monitor.cancel()
        try: await monitor
        except asyncio.CancelledError: pass

app=FastAPI(title="VALTIERA Research API",version="1.0.0",description="Persistent quantitative research workspace. No investment execution is provided.",lifespan=lifespan)
origins=[x.strip() for x in os.getenv("CORS_ORIGINS","http://localhost:5173,http://127.0.0.1:5173,http://localhost:5176,http://127.0.0.1:5176").split(",") if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=["GET","POST","PUT","DELETE"],allow_headers=["Content-Type","Authorization"])
STARTED=datetime.now(timezone.utc); login_attempts={}; market_summary_attempts={}

class RunRequest(BaseModel):
    data: dict
    parameters: dict=Field(default_factory=dict)
class JobRequest(BaseModel):
    engine: str
    data: dict
    parameters: dict=Field(default_factory=dict)
class IntelligenceRequest(BaseModel):
    data: dict
    parameters: dict=Field(default_factory=dict)
class MarketHistoryRequest(BaseModel):
    symbol: str=Field(default="BTCUSDT",min_length=5,max_length=20,pattern=r"^[A-Za-z0-9]+$")
    timeframe: str="1d"
    limit: int=Field(default=500,ge=30,le=1000)
    peer_symbol: str|None=Field(default=None,min_length=5,max_length=20,pattern=r"^[A-Za-z0-9]+$")
    provider: Literal["crypto","equity","forex","futures","commodities"]="crypto"
class MarketSummaryRequest(BaseModel):
    symbol: str=Field(default="BTCUSDT",min_length=5,max_length=20,pattern=r"^[A-Za-z0-9]+$")
    timeframe: str="1h"
    provider: Literal["crypto"]="crypto"
class Credentials(BaseModel):
    email: str=Field(min_length=3,max_length=255)
    password: str=Field(min_length=8,max_length=128)
class RegisterRequest(Credentials):
    name: str=Field(min_length=2,max_length=100)
class PasswordChangeRequest(BaseModel):
    current_password: str=Field(min_length=8,max_length=128)
    new_password: str=Field(min_length=12,max_length=128)
class PositionRequest(BaseModel):
    symbol: str=Field(min_length=1,max_length=32)
    asset_class: Literal["equity","future","option","bond","crypto","other"]="equity"
    quantity: float=Field(gt=0,le=1e12)
    average_cost: float=Field(gt=0,le=1e12)
    current_price: float=Field(gt=0,le=1e12)
class ExposureCheckRequest(BaseModel):
    market_value: float=Field(gt=0,le=1e12)
    asset_class: Literal["equity","future","option","bond","crypto","other"]="other"
class RiskRequest(BaseModel):
    max_position_pct: float=Field(gt=0,le=100)
    max_drawdown_pct: float=Field(gt=0,le=100)
    daily_loss_limit_pct: float=Field(gt=0,le=100)
    max_gross_exposure_pct: float=Field(gt=0,le=300)
    portfolio_nav: float=Field(gt=0,le=1e12)
    risk_profile: Literal["conservative","moderate","growth","aggressive","custom"]="moderate"
    max_leverage_pct: float=Field(default=100,gt=0,le=500)
    asset_class_limits: dict[str,float]=Field(default_factory=dict)
    volatility_tolerance: Literal["low","moderate","high"]="moderate"
    liquidity_floor_usd: float=Field(default=0,ge=0,le=1e12)
    investment_horizon_months: int=Field(default=12,ge=1,le=1200)
    @field_validator("asset_class_limits")
    @classmethod
    def validate_asset_limits(cls, value):
        allowed={"equity","future","option","bond","crypto","other"}
        if any(k not in allowed or not np.isfinite(v) or v<=0 or v>100 for k,v in value.items()): raise ValueError("Asset-class limits must use supported classes and values from 0 to 100 percent")
        return value
class BacktestRequest(BaseModel):
    engine: str
    prices: list[float]=Field(min_length=31,max_length=10000)
    peer_prices: list[float]|None=None
    volumes: list[float]|None=None
    highs: list[float]|None=None
    lows: list[float]|None=None
    initial_capital: float=Field(default=100000,gt=0,le=1e12)
    fee_bps: float=Field(default=5,ge=0,le=1000)
    slippage_bps: float=Field(default=0,ge=0,le=1000)
    spread_cost_bps: float=Field(default=0,ge=0,le=1000)
    market_impact_bps: float=Field(default=0,ge=0,le=1000)
    funding_bps_per_period: float=Field(default=0,ge=0,le=1000)
    periods_per_year: int=Field(default=252,ge=1,le=525600)
    position_size: float=Field(default=1,gt=0,le=1)
    benchmark_prices: list[float]|None=None
    parameters: dict=Field(default_factory=dict)
class PaperOrderRequest(BaseModel):
    symbol: str=Field(min_length=1,max_length=20,pattern=r"^[A-Za-z0-9]+$")
    asset_class: Literal["crypto","equity"]="crypto"
    side: Literal["BUY","SELL"]
    order_type: Literal["MARKET","LIMIT","STOP"]="MARKET"
    quantity: float=Field(gt=0,le=1e9)
    limit_price: float|None=Field(default=None,gt=0,le=1e12)
    fee_bps: float=Field(default=10,ge=0,le=1000)
def public_user(user,include_email=False):
    result={"id":user.id,"name":user.name,"role":user.role}
    if include_email: result["email"]=user.email
    return result
def audit(db,user_id,action,entity_type="workspace",entity_id=None,details=None):
    db.add(AuditLog(user_id=user_id,action=action,entity_type=entity_type,entity_id=str(entity_id) if entity_id is not None else None,details=details or {}))
@app.get("/health")
def health(db: Session=Depends(get_db)):
    try: db.execute(text("SELECT 1")); database="OPERATIONAL"
    except Exception: database="OFFLINE"
    redis_state="NOT CONFIGURED"
    redis_url=os.getenv("REDIS_URL")
    if redis_url:
        try:
            import redis
            redis.Redis.from_url(redis_url,socket_connect_timeout=.3,socket_timeout=.3).ping(); redis_state="OPERATIONAL"
        except Exception: redis_state="OFFLINE"
    heartbeat=db.get(ServiceHeartbeat,"research-worker") if database=="OPERATIONAL" else None
    worker_state="OFFLINE"
    if heartbeat and heartbeat.checked_at:
        checked=heartbeat.checked_at if heartbeat.checked_at.tzinfo else heartbeat.checked_at.replace(tzinfo=timezone.utc)
        worker_state="OPERATIONAL" if (datetime.now(timezone.utc)-checked).total_seconds()<90 else "OFFLINE"
    latest={}
    latest_error=None
    if database=="OPERATIONAL":
        for name in ENGINES:
            row=db.query(EngineRun).filter_by(engine=name).order_by(EngineRun.created_at.desc()).first()
            latest[name]={"status":"CALCULATION AVAILABLE","last_successful_execution":row.created_at.isoformat() if row else None,"observations":row.result.get("observations") if row else None}
        failed=db.query(ResearchJob).filter_by(status="FAILED").order_by(ResearchJob.updated_at.desc()).first()
        latest_error={"message":failed.error,"at":failed.updated_at.isoformat()} if failed else None
    return {"status":"DEVELOPMENT","database":database,"redis":redis_state,"worker":worker_state,"engines":latest or {e:{"status":"UNKNOWN"} for e in ENGINES},"started_at":STARTED.isoformat(),"latest_error":latest_error}

@app.post("/auth/register",status_code=201)
def register(request:RegisterRequest,db:Session=Depends(get_db)):
    email=request.email.strip().lower()
    if db.query(User).filter(func.lower(User.email)==email).first(): raise HTTPException(409,"An account with this email already exists")
    user=User(email=email,name=request.name.strip(),password_hash=hash_password(request.password)); db.add(user); db.flush(); db.add(RiskSettings(user_id=user.id)); audit(db,user.id,"account_registered"); db.commit(); db.refresh(user)
    return {"token":issue_token(user),"user":public_user(user,include_email=True)}

@app.post("/auth/login")
def login(request:Credentials,req:Request,db:Session=Depends(get_db)):
    key=req.client.host if req.client else "unknown"; now=time.time(); times=[t for t in login_attempts.get(key,[]) if now-t<300]
    if len(times)>=12: raise HTTPException(429,"Too many login attempts; try again in five minutes")
    user=db.query(User).filter(func.lower(User.email)==request.email.strip().lower()).first()
    if not user or not verify_password(request.password,user.password_hash):
        times.append(now); login_attempts[key]=times; raise HTTPException(401,"Email or password is incorrect")
    login_attempts.pop(key,None); audit(db,user.id,"login_succeeded"); db.commit(); return {"token":issue_token(user),"user":public_user(user,include_email=True)}

@app.get("/auth/me")
def me(user:User=Depends(current_user)): return public_user(user,include_email=True)
@app.put("/auth/password")
def change_password(req:PasswordChangeRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    if not verify_password(req.current_password,user.password_hash): raise HTTPException(403,"Current password is incorrect")
    user.password_hash=hash_password(req.new_password); audit(db,user.id,"password_changed","user",user.id); db.commit(); return {"changed":True,"session":"Existing session expires on its normal schedule."}
@app.post("/auth/logout")
def logout(user:User=Depends(current_user),credentials=Depends(bearer),db:Session=Depends(get_db)):
    if credentials:
        digest=hashlib.sha256(credentials.credentials.encode()).hexdigest()
        db.add(RevokedSession(token_hash=digest,user_id=user.id,expires_at=datetime.now(timezone.utc)+__import__("datetime").timedelta(hours=12)))
        db.query(RevokedSession).filter(RevokedSession.expires_at<datetime.now(timezone.utc)).delete(synchronize_session=False)
    audit(db,user.id,"logout_completed","session",None); db.commit()
    return {"ok":True,"note":"Session token revoked."}

@app.get("/market-data/candles")
def market_candles(symbol:str=Query(default="BTCUSDT",min_length=5,max_length=20),timeframe:str="1d",limit:int=Query(default=500,ge=30,le=1000)):
    try: return fetch_candles(symbol,timeframe,limit)
    except ValueError as exc: raise HTTPException(422,str(exc)) from None
    except RuntimeError as exc: raise HTTPException(502,str(exc)) from None

@app.get("/market-data/history")
def market_history(request:MarketHistoryRequest=Depends()):
    try:
        if request.provider=="crypto": primary=fetch_candles(request.symbol,request.timeframe,request.limit)
        elif request.provider=="equity": primary=alpaca_provider.fetch_bars(request.symbol,request.timeframe,request.limit)
        else: primary=fmp_provider.fetch_bars(request.provider,request.symbol,request.timeframe,request.limit)
        candles=primary["candles"]
        prices=np.asarray([candle["close"] for candle in candles],dtype=float)
        returns=np.diff(np.log(prices))
        interval=request.timeframe
        periods=({"1m":525600,"3m":175200,"5m":105120,"15m":35040,"30m":17520,"1h":8760,"2h":4380,"4h":2190,"6h":1460,"8h":1095,"12h":730,"1d":365,"3d":122,"1w":52,"1M":12}[interval] if request.provider=="crypto" else {"1m":98280,"5m":19656,"15m":6552,"1h":1638,"4h":504,"1d":252,"1w":52}[interval])
        sample_vol=float(np.std(returns,ddof=1)*100) if len(returns)>1 else 0.0
        annual_vol=sample_vol*float(np.sqrt(periods))
        peer_candles=[]
        if request.peer_symbol:
            if request.provider=="crypto": peer=fetch_candles(request.peer_symbol,request.timeframe,request.limit)
            elif request.provider=="equity": peer=alpaca_provider.fetch_bars(request.peer_symbol,request.timeframe,request.limit)
            else: peer=fmp_provider.fetch_bars(request.provider,request.peer_symbol,request.timeframe,request.limit)
            peer_by_time={candle["time"]:candle for candle in peer["candles"]}
            aligned=[candle for candle in candles if candle["time"] in peer_by_time]
            if len(aligned)<30: raise HTTPException(422,"Primary and peer markets have fewer than 30 aligned closed candles")
            candles=aligned
            peer_candles=[peer_by_time[candle["time"]] for candle in aligned]
        result={"symbol":request.symbol.upper(),"provider":request.provider,"timeframe":interval,"source":primary["source"],"provider_status":primary["provider_status"],"fetched_at":primary["fetched_at"],"observations":len(candles),"candles":candles,"sample_volatility_pct":sample_vol,"annualized_volatility_pct":annual_vol}
        if request.peer_symbol:
            result["peer_symbol"]=request.peer_symbol.upper(); result["peer_candles"]=peer_candles
        return result
    except ValueError as exc: raise HTTPException(422,str(exc)) from None
    except RuntimeError as exc: raise HTTPException(502,str(exc)) from None

@app.get("/market-data/coverage")
def market_coverage():
    return {"providers":[
        {"asset_class":"crypto","provider":"Binance Spot","status":"AVAILABLE_PUBLIC","capabilities":["history","live quotes","candles"]},
        {"asset_class":"us_equities","provider":"Alpaca IEX","status":"AVAILABLE_CONFIGURED" if alpaca_provider.configured() else "NEEDS_API_CREDENTIALS","capabilities":["history","live trades","bars"],"feed":"IEX only; not consolidated US market coverage"},
        {"asset_class":"futures","provider":"FMP","status":"AVAILABLE_HISTORY_ONLY" if fmp_provider.configured() else "NEEDS_API_CREDENTIALS","capabilities":["daily history","weekly history"],"note":"Symbol coverage depends on FMP plan; exchange-direct futures feed is not configured."},
        {"asset_class":"forex","provider":"FMP","status":"AVAILABLE_HISTORY_ONLY" if fmp_provider.configured() else "NEEDS_API_CREDENTIALS","capabilities":["daily history","weekly history"]},
        {"asset_class":"commodities","provider":"FMP","status":"AVAILABLE_HISTORY_ONLY" if fmp_provider.configured() else "NEEDS_API_CREDENTIALS","capabilities":["daily history","weekly history"]},
    ]}

@app.get("/market-data/quote")
def market_quote(symbol:str=Query(min_length=1,max_length=20),asset_class:Literal["crypto","equity"]="crypto"):
    try: return latest_quote(symbol) if asset_class=="crypto" else alpaca_provider.latest_trade(symbol)
    except ValueError as exc: raise HTTPException(422,str(exc)) from None
    except RuntimeError as exc: raise HTTPException(502,str(exc)) from None

def paper_account(db:Session,user_id:int):
    row=db.query(PaperAccount).filter_by(user_id=user_id).with_for_update().first()
    if not row:
        row=PaperAccount(user_id=user_id,cash=100000,positions={}); db.add(row); db.flush()
    return row

def market_price(symbol:str,asset_class:str):
    try: quote_data=latest_quote(symbol) if asset_class=="crypto" else alpaca_provider.latest_trade(symbol)
    except ValueError as exc: raise HTTPException(422,str(exc)) from None
    except RuntimeError as exc: raise HTTPException(502,str(exc)) from None
    value=quote_data.get("price") or quote_data.get("last")
    if value is None: raise HTTPException(502,"Provider did not return a usable price")
    return float(value),quote_data

def order_triggered(order:PaperOrder,price:float):
    if order.order_type=="MARKET": return True
    if order.order_type=="LIMIT": return price<=order.limit_price if order.side=="BUY" else price>=order.limit_price
    return price>=order.limit_price if order.side=="BUY" else price<=order.limit_price

def apply_paper_fill(order:PaperOrder,account:PaperAccount,price:float,quantity:float,fee_bps:float):
    remaining=max(0.,order.quantity-float(order.filled_quantity or 0)); quantity=min(quantity,remaining)
    if quantity<=0: return
    notional=quantity*price; fee=notional*fee_bps/10000
    positions=dict(account.positions or {}); key=f"{order.asset_class}:{order.symbol}"
    position=dict(positions.get(key,{})); held=float(position.get("quantity",0)); avg=float(position.get("average_price",0))
    if order.side=="BUY":
        affordable=account.cash/(price*(1+fee_bps/10000)); quantity=min(quantity,affordable)
        if quantity<=0: order.status="CANCELLED"; return
        notional=quantity*price; fee=notional*fee_bps/10000; total=notional+fee
        account.cash-=total; position={"quantity":held+quantity,"average_price":((held*avg)+notional)/(held+quantity)}
    else:
        quantity=min(quantity,held)
        if quantity<=0: order.status="CANCELLED"; return
        notional=quantity*price; fee=notional*fee_bps/10000
        account.cash+=notional-fee; position={"quantity":held-quantity,"average_price":avg}
    if position["quantity"]<=1e-12: positions.pop(key,None)
    else: positions[key]=position
    account.positions=positions
    prior_filled=float(order.filled_quantity or 0); new_filled=prior_filled+quantity
    order.average_fill_price=((float(order.average_fill_price or 0)*prior_filled)+(price*quantity))/new_filled
    order.fill_price=order.average_fill_price; order.filled_quantity=new_filled; order.fee=float(order.fee or 0)+fee
    order.status="FILLED" if new_filled>=order.quantity-1e-10 else "PARTIALLY_FILLED"
    if order.status=="FILLED": order.filled_at=datetime.now(timezone.utc)

def try_paper_fill(order:PaperOrder,account:PaperAccount):
    last_price,quote_data=market_price(order.symbol,order.asset_class)
    if not order_triggered(order,last_price): return quote_data
    book=binance_book(order.symbol,order.side) if order.asset_class=="crypto" else alpaca_provider.top_of_book(order.symbol,order.side)
    levels=book["levels"]
    if order.order_type=="LIMIT":
        levels=[(price,size) for price,size in levels if price<=order.limit_price] if order.side=="BUY" else [(price,size) for price,size in levels if price>=order.limit_price]
    remaining=max(0.,order.quantity-float(order.filled_quantity or 0)); notional=0.; filled=0.
    for price,size in levels:
        amount=min(remaining-filled,size)
        if amount>0: filled+=amount; notional+=amount*price
        if filled>=remaining: break
    if filled>0: apply_paper_fill(order,account,notional/filled,filled,order.fee_bps)
    return {**quote_data,"fill_book_source":book["source"],"available_quantity":sum(size for _,size in levels)}

async def paper_order_monitor():
    while True:
        await asyncio.sleep(float(os.getenv("PAPER_ORDER_POLL_SECONDS","10")))
        try:
            def process_batch():
                with SessionLocal() as db:
                    orders=db.query(PaperOrder).filter(PaperOrder.status.in_(["OPEN","PARTIALLY_FILLED"])).order_by(PaperOrder.created_at).limit(10).all()
                    for order in orders:
                        try:
                            user_id=order.user_id; account=paper_account(db,user_id); before=order.filled_quantity
                            try_paper_fill(order,account)
                            if order.filled_quantity>before: audit(db,user_id,"paper_order_auto_fill","paper_order",order.id,{"new_filled_quantity":order.filled_quantity,"status":order.status,"mode":"SIMULATED_ONLY"})
                            db.commit()
                        except Exception as exc:
                            db.rollback(); logger.warning("Paper monitor skipped order %s: %s",order.id,str(exc)[:160])
            await asyncio.to_thread(process_batch)
        except Exception: logger.exception("Paper order monitor cycle failed")

@app.get("/paper/account")
def get_paper_account(user:User=Depends(current_user),db:Session=Depends(get_db)):
    account=paper_account(db,user.id); orders=db.query(PaperOrder).filter_by(user_id=user.id).order_by(PaperOrder.created_at.desc()).limit(100).all(); db.commit()
    return {"mode":"SIMULATED_ONLY","starting_cash":100000,"cash":account.cash,"positions":account.positions or {},"orders":[paper_order_view(o) for o in orders]}

def paper_order_view(order:PaperOrder):
    return {"id":order.id,"symbol":order.symbol,"asset_class":order.asset_class,"side":order.side,"order_type":order.order_type,"quantity":order.quantity,"filled_quantity":order.filled_quantity,"average_fill_price":order.average_fill_price,"limit_price":order.limit_price,"status":order.status,"fill_price":order.fill_price,"fee":order.fee,"fee_bps":order.fee_bps,"created_at":order.created_at.isoformat(),"filled_at":order.filled_at.isoformat() if order.filled_at else None}

@app.post("/paper/orders",status_code=201)
def create_paper_order(req:PaperOrderRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    if req.order_type!="MARKET" and req.limit_price is None: raise HTTPException(422,"Limit and stop orders require a trigger price")
    account=paper_account(db,user.id); order=PaperOrder(user_id=user.id,symbol=req.symbol.upper(),asset_class=req.asset_class,side=req.side,order_type=req.order_type,quantity=req.quantity,limit_price=req.limit_price,fee_bps=req.fee_bps,status="OPEN")
    if req.side=="SELL":
        key=f"{req.asset_class}:{req.symbol.upper()}"; held=float((account.positions or {}).get(key,{}).get("quantity",0))
        reserved=sum(row.quantity-row.filled_quantity for row in db.query(PaperOrder).filter_by(user_id=user.id,symbol=req.symbol.upper(),asset_class=req.asset_class,side="SELL").filter(PaperOrder.status.in_(["OPEN","PARTIALLY_FILLED"])).all())
        if req.quantity>held-reserved: raise HTTPException(422,"Paper sell quantity exceeds unreserved long holdings")
    db.add(order); db.flush()
    try: quote_data=try_paper_fill(order,account)
    except (ValueError,RuntimeError) as exc: raise HTTPException(502,str(exc)) from None
    audit(db,user.id,"paper_order_created","paper_order",order.id,{"symbol":order.symbol,"side":order.side,"status":order.status,"quote_timestamp":quote_data.get("timestamp")})
    db.commit(); db.refresh(order)
    return {"mode":"SIMULATED_ONLY","order":paper_order_view(order),"quote":quote_data}

@app.post("/paper/orders/{order_id}/process")
def process_paper_order(order_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    order=db.query(PaperOrder).filter_by(id=order_id,user_id=user.id).with_for_update().first()
    if not order: raise HTTPException(404,"Paper order not found")
    if order.status not in {"OPEN","PARTIALLY_FILLED"}: raise HTTPException(409,"Only open paper orders can be processed")
    try: quote_data=try_paper_fill(order,paper_account(db,user.id))
    except (ValueError,RuntimeError) as exc: raise HTTPException(502,str(exc)) from None
    audit(db,user.id,"paper_order_processed","paper_order",order.id,{"status":order.status,"quote_timestamp":quote_data.get("timestamp")}); db.commit(); db.refresh(order)
    return {"mode":"SIMULATED_ONLY","order":paper_order_view(order),"quote":quote_data}

@app.delete("/paper/orders/{order_id}")
def cancel_paper_order(order_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    order=db.query(PaperOrder).filter_by(id=order_id,user_id=user.id).first()
    if not order: raise HTTPException(404,"Paper order not found")
    if order.status not in {"OPEN","PARTIALLY_FILLED"}: raise HTTPException(409,"Only open paper orders can be cancelled")
    order.status="CANCELLED"; audit(db,user.id,"paper_order_cancelled","paper_order",order.id); db.commit()
    return paper_order_view(order)

@app.get("/broker/alpaca-paper/account")
def alpaca_paper_account(user:User=Depends(current_user)):
    owner=os.getenv("ALPACA_PAPER_OWNER_EMAIL","").strip().lower()
    if not owner or user.email.lower()!=owner: raise HTTPException(403,"This local researcher is not authorized to access the configured Alpaca paper account")
    try: return {"account":broker_paper.account(),"orders":broker_paper.orders()}
    except RuntimeError as exc: raise HTTPException(503,str(exc)) from None

@app.post("/broker/alpaca-paper/orders",status_code=201)
def alpaca_paper_order(req:PaperOrderRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    owner=os.getenv("ALPACA_PAPER_OWNER_EMAIL","").strip().lower()
    if not owner or user.email.lower()!=owner: raise HTTPException(403,"This local researcher is not authorized to access the configured Alpaca paper account")
    if req.asset_class!="equity": raise HTTPException(422,"Alpaca paper broker orders are enabled for US equities only")
    if req.order_type!="MARKET" and req.limit_price is None: raise HTTPException(422,"Limit and stop orders require a trigger price")
    try:
        status=broker_paper.account()
        if status["trading_blocked"]: raise HTTPException(409,"The configured Alpaca paper account is blocked from trading")
        order=broker_paper.place_order(req.symbol,req.side,req.order_type,req.quantity,req.limit_price)
    except HTTPException: raise
    except RuntimeError as exc: raise HTTPException(503,str(exc)) from None
    audit(db,user.id,"alpaca_paper_order_submitted","broker_paper_order",order.get("id"),{"symbol":order.get("symbol"),"side":order.get("side"),"status":order.get("status"),"mode":"PAPER_ONLY"}); db.commit()
    return {"mode":"ALPACA_PAPER_ONLY","order":order}

@app.delete("/broker/alpaca-paper/orders/{order_id}")
def cancel_alpaca_paper_order(order_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    owner=os.getenv("ALPACA_PAPER_OWNER_EMAIL","").strip().lower()
    if not owner or user.email.lower()!=owner: raise HTTPException(403,"This local researcher is not authorized to access the configured Alpaca paper account")
    try: result=broker_paper.cancel_order(order_id)
    except ValueError as exc: raise HTTPException(422,str(exc)) from None
    except RuntimeError as exc: raise HTTPException(503,str(exc)) from None
    audit(db,user.id,"alpaca_paper_order_cancel_requested","broker_paper_order",order_id,{"mode":"PAPER_ONLY"}); db.commit()
    return result

@app.websocket("/ws/market/{asset_class}/{symbol}/{timeframe}")
async def market_stream(websocket:WebSocket,asset_class:str,symbol:str,timeframe:str):
    normalized=symbol.upper().strip()
    if asset_class not in {"crypto","equity"} or not normalized.isalnum() or not 1<=len(normalized)<=20:
        await websocket.close(code=1008,reason="Unsupported asset class or symbol"); return
    if asset_class=="crypto" and timeframe not in {"1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d","3d","1w","1M"}:
        await websocket.close(code=1008,reason="Unsupported candle interval"); return
    if asset_class=="equity" and not alpaca_provider.configured():
        await websocket.close(code=1013,reason="Alpaca IEX credentials are not configured"); return
    await websocket.accept()
    try:
        if asset_class=="crypto":
            url=f"wss://stream.binance.com:9443/ws/{normalized.lower()}@kline_{timeframe}"
            async with websockets.connect(url,ping_interval=20,ping_timeout=20,close_timeout=3) as stream:
                await websocket.send_json({"type":"status","status":"CONNECTED","source":"Binance Spot public stream"})
                async for message in stream:
                    packet=json.loads(message); row=packet.get("k",{})
                    candle={"symbol":normalized,"time":int(row["t"])//1000,"open":float(row["o"]),"high":float(row["h"]),"low":float(row["l"]),"close":float(row["c"]),"volume":float(row["v"]),"closed":bool(row["x"]),"timestamp":datetime.now(timezone.utc).isoformat()}
                    await websocket.send_json({"type":"candle","candle":candle,"source":"Binance Spot public stream"})
        else:
            url="wss://stream.data.alpaca.markets/v2/iex"
            async with websockets.connect(url,ping_interval=20,ping_timeout=20,close_timeout=3) as stream:
                await stream.recv()
                key,secret=alpaca_provider.credentials() or ("","")
                await stream.send(json.dumps({"action":"auth","key":key,"secret":secret}))
                auth=json.loads(await stream.recv())
                if not any(message.get("T")=="success" and message.get("msg")=="authenticated" for message in (auth if isinstance(auth,list) else [auth])):
                    await websocket.send_json({"type":"status","status":"AUTHENTICATION_FAILED","source":"Alpaca IEX"}); await websocket.close(code=1013); return
                await stream.send(json.dumps({"action":"subscribe","trades":[normalized],"bars":[normalized]}))
                await websocket.send_json({"type":"status","status":"CONNECTED","source":"Alpaca IEX"})
                async for message in stream:
                    packets=json.loads(message)
                    for packet in packets if isinstance(packets,list) else [packets]:
                        if packet.get("S")!=normalized: continue
                        if packet.get("T")=="t":
                            await websocket.send_json({"type":"quote","symbol":normalized,"price":float(packet["p"]),"timestamp":packet["t"],"source":"Alpaca IEX"})
                        elif packet.get("T")=="b":
                            candle={"symbol":normalized,"time":int(datetime.fromisoformat(packet["t"].replace("Z","+00:00")).timestamp()),"open":float(packet["o"]),"high":float(packet["h"]),"low":float(packet["l"]),"close":float(packet["c"]),"volume":float(packet["v"]),"closed":True,"timestamp":packet["t"]}
                            await websocket.send_json({"type":"candle","candle":candle,"source":"Alpaca IEX"})
    except WebSocketDisconnect: return
    except (websockets.exceptions.ConnectionClosed,OSError,TimeoutError,ValueError,KeyError,TypeError,json.JSONDecodeError):
        try: await websocket.send_json({"type":"status","status":"DISCONNECTED","retry_in_seconds":3})
        except WebSocketDisconnect: return

@app.post("/market-data/summary")
def market_summary(data:MarketSummaryRequest,request:Request):
    client=request.client.host if request.client else "unknown"; now=time.time()
    attempts=[t for t in market_summary_attempts.get(client,[]) if now-t<60]
    if len(attempts)>=6: raise HTTPException(429,"Market summaries are limited to 6 requests per minute")
    attempts.append(now); market_summary_attempts[client]=attempts
    try: market=fetch_candles(data.symbol,data.timeframe,220)
    except ValueError as exc: raise HTTPException(422,str(exc)) from None
    except RuntimeError as exc: raise HTTPException(502,str(exc)) from None
    candles=market["candles"]
    closes=np.asarray([candle["close"] for candle in candles],dtype=float)
    returns=np.diff(np.log(closes))
    latest=float(closes[-1]); sma20=float(np.mean(closes[-20:])); sma50=float(np.mean(closes[-50:]))
    rsi_series=_wilder_rsi(closes,14); rsi=float(rsi_series[-1]) if np.isfinite(rsi_series[-1]) else 50.0
    change=float((closes[-1]/closes[-min(50,len(closes))]-1)*100)
    sample_vol=float(np.std(returns[-50:],ddof=1)*100) if len(returns[-50:])>1 else 0.0
    direction=int(latest>sma20)+int(latest>sma50)+int(change>0)
    opposite=int(latest<sma20)+int(latest<sma50)+int(change<0)
    verdict="Bullish" if direction>=2 and direction>opposite else "Bearish" if opposite>=2 and opposite>direction else "Mixed"
    facts={"symbol":data.symbol.upper(),"timeframe":data.timeframe,"verdict":verdict,"latest_close":latest,"change_pct_window":change,"sma20":sma20,"sma50":sma50,"rsi14":rsi,"sample_volatility_pct_per_bar":sample_vol,"observations":len(candles),"data_timestamp":market["fetched_at"]}
    fallback=(f"FINAL VERDICT: {verdict}. {data.symbol.upper()} has changed {change:+.2f}% over the latest {min(50,len(closes))} bars. "
              f"The latest close is {'above' if latest>=sma20 else 'below'} its 20-bar average and {'above' if latest>=sma50 else 'below'} its 50-bar average. "
              f"RSI(14) is {rsi:.1f}; per-bar sample volatility is {sample_vol:.3f}%. This is a historical, rules-based snapshot, not a forecast or trade instruction.")
    summary=fallback; provider="deterministic rules"; llm_status="UNCONFIGURED"
    api_key=os.getenv("GEMINI_API_KEY","").strip()
    if api_key:
        prompt=("Summarize this quantitative market snapshot in 2-3 concise sentences. Use only supplied facts, "
                "preserve the given final verdict exactly, describe uncertainty, and do not predict prices or recommend trades.\n"
                +json.dumps(facts,separators=(",",":")))
        payload={"contents":[{"role":"user","parts":[{"text":prompt}]}],"generationConfig":{"temperature":0.2,"maxOutputTokens":180}}
        models=[os.getenv("GEMINI_MODEL","gemini-3.5-flash-lite").strip(),"gemini-3.5-flash-lite"]
        for model in dict.fromkeys(models):
            gemini_request=URLRequest(f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model,safe='')}:generateContent",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","x-goog-api-key":api_key},method="POST")
            try:
                with urlopen(gemini_request,timeout=18) as response: generated=json.loads(response.read())
                text_out=" ".join(part.get("text","").strip() for part in generated["candidates"][0]["content"]["parts"] if part.get("text"))
                if text_out:
                    summary=f"FINAL VERDICT: {verdict}. {text_out} This is a historical market summary, not a forecast or trade instruction."
                    provider=model; llm_status="AVAILABLE"; break
                llm_status="FALLBACK_EMPTY_RESPONSE"
            except HTTPError as exc:
                llm_status="FALLBACK_API_UNAVAILABLE"
                if exc.code in (429,500,502,503,504): continue
                break
            except (URLError,TimeoutError,OSError,ValueError,KeyError,IndexError,TypeError):
                llm_status="FALLBACK_API_UNAVAILABLE"; break
    return {"symbol":data.symbol.upper(),"timeframe":data.timeframe,"summary":summary,"verdict":verdict,"metrics":facts,"model":provider,"llm_status":llm_status,"data_source":market["source"],"data_timestamp":market["fetched_at"]}

@app.get("/engines")
def engines():
    descriptions={"arima":"ARIMA on log price levels with a conditional interval","garch":"Gaussian GARCH(1,1) maximum likelihood fit","kalman_filter":"Scalar local-level filter for log prices","ornstein_uhlenbeck":"Discrete log-price mean-reversion fit","moving_average":"SMA/EMA crossover","rsi":"Wilder RSI momentum","macd":"Exponential trend convergence/divergence","bollinger":"Rolling mean and standard-deviation bands","monte_carlo":"Seeded geometric Brownian motion scenarios","black_scholes":"European option theoretical baseline and analytical Greeks","gradient_boosting":"Deterministic boosted regression stumps with chronological holdout","vwap":"Volume weighted average price","statistical_arbitrage":"Cointegration and spread diagnostics","pairs_trading":"OLS hedge ratio and spread Z-score","mean_reversion":"Rolling Z-score and conditional half-life","momentum":"Volatility adjusted time-series momentum","volatility_breakout":"Prior range and true-range breakout"}
    return {"engines":[{"id":e,"status":"CALCULATION AVAILABLE","version":"0.3.0","description":descriptions[e]} for e in ENGINES],"note":"Calculation code is available for caller supplied observations. No licensed equity or commodity feed is configured."}

@app.post("/intelligence/consensus")
def intelligence_consensus(req:IntelligenceRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    """Run all compatible research engines over one validated caller-supplied dataset."""
    outputs=[]; directions=[]
    for engine_name in ENGINES:
        try:
            result=calculate(engine_name,req.data,req.parameters)
            row=EngineRun(user_id=user.id,engine=engine_name,model_version=result["model_version"],result=result); db.add(row); db.flush()
            outputs.append({"execution_id":row.id,**result})
            direction=result["metrics"].get("signal_direction")
            if direction and direction!="neutral": directions.append((engine_name,direction))
        except (ValueError,TypeError) as exc:
            outputs.append({"engine":engine_name,"status":"INPUT_REQUIRED_OR_INVALID","reason":str(exc)})
    active=[direction for _,direction in directions]
    agreement=(max(active.count(x) for x in set(active))/len(active)) if active else None
    conflict=len(set(active))>1
    summary={"status":"CONFLICTING_RESEARCH" if conflict else "RESEARCH_AGREEMENT" if active else "INSUFFICIENT_MODEL_OUTPUTS","direction":None if conflict or not active else active[0],"agreement_fraction":agreement,"interpretation":"Agreement is a count of directional research outputs, not a probability of profit."}
    audit(db,user.id,"intelligence_consensus_run","research",None,{"completed_models":sum("execution_id" in x for x in outputs),"status":summary["status"]}); db.commit()
    return {"data_status":req.data.get("status","historical"),"summary":summary,"models":outputs}

@app.post("/engines/{engine_name}/run")
def run(engine_name:str,request:RunRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    try: result=calculate(engine_name,request.data,request.parameters)
    except (ValueError,TypeError,OverflowError) as e: raise HTTPException(422,str(e))
    execution=EngineRun(user_id=user.id,engine=engine_name,model_version=result["model_version"],result=result); db.add(execution); audit(db,user.id,"engine_calculated","engine",engine_name,{"model_version":result["model_version"]}); db.commit(); result["execution_id"]=execution.id
    return result

@app.get("/engines/history")
def engine_history(limit:int=Query(default=30,ge=1,le=100),user:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.query(EngineRun).filter(EngineRun.user_id==user.id).order_by(EngineRun.created_at.desc()).limit(limit).all()
    return [{"id":r.id,"engine":r.engine,"model_version":r.model_version,"created_at":r.created_at.isoformat(),"result":r.result} for r in rows]

@app.post("/jobs",status_code=202)
def enqueue_research(request:JobRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    if request.engine not in ENGINES: raise HTTPException(422,"A valid engine name is required")
    job=ResearchJob(user_id=user.id,engine=request.engine,data=request.data,parameters=request.parameters)
    db.add(job); db.flush(); audit(db,user.id,"research_job_queued","job",job.id,{"engine":job.engine}); db.commit(); db.refresh(job)
    return {"job_id":job.id,"status":job.status,"created_at":job.created_at.isoformat(),"note":"A configured worker will process this durable job."}

@app.get("/jobs/{job_id}")
def research_job(job_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    job=db.query(ResearchJob).filter_by(id=job_id,user_id=user.id).first()
    if not job: raise HTTPException(404,"Research job not found")
    return {"job_id":job.id,"engine":job.engine,"status":job.status,"result":job.result,"error":job.error,"created_at":job.created_at.isoformat(),"updated_at":job.updated_at.isoformat()}

BACKTEST_ENGINES={"moving_average","rsi","macd","bollinger","vwap","statistical_arbitrage","pairs_trading","mean_reversion","momentum","volatility_breakout","garch","monte_carlo"}

def _walk_forward_candidates(engine:str,base:dict):
    candidates=[]
    if engine=="moving_average":
        candidates=[{**base,"fast_window":fast,"slow_window":slow} for fast in (5,10,20) for slow in (30,50) if fast<slow]
    elif engine=="rsi":
        candidates=[{**base,"window":window,"oversold":entry,"overbought":exit} for window in (7,14,21) for entry,exit in ((25,75),(30,70))]
    elif engine=="macd":
        candidates=[{**base,"fast_window":fast,"slow_window":slow,"signal_window":signal} for fast,slow,signal in ((8,21,6),(12,26,9),(10,30,9))]
    elif engine=="bollinger":
        candidates=[{**base,"window":window,"deviations":deviation} for window,deviation in ((10,1.5),(20,2),(30,2),(20,2.5))]
    elif engine=="vwap":
        candidates=[{**base,"window":window} for window in (20,60,100)]
    elif engine in ("statistical_arbitrage","pairs_trading"):
        candidates=[{**base,"window":window,"entry_z":entry} for window,entry in ((30,1.5),(30,2),(60,1.5),(60,2),(90,2))]
    elif engine=="mean_reversion":
        candidates=[{**base,"window":window} for window in (15,20,30,60)]
    elif engine=="momentum":
        candidates=[{**base,"lookback":window} for window in (10,20,40,60)]
    elif engine=="volatility_breakout":
        candidates=[{**base,"window":window} for window in (10,20,30,40)]
    return candidates[:8]

def _walk_forward_refit(req:BacktestRequest,include_walk_forward:bool):
    if not include_walk_forward or req.engine not in BACKTEST_ENGINES-{"garch","monte_carlo"}:
        return {"method":"Not available for this forecast validation engine","folds":[]}
    prices=np.asarray(req.prices,dtype=float); candidates=_walk_forward_candidates(req.engine,req.parameters or {})
    if len(prices)<180 or not candidates:
        return {"method":"Expanding-window parameter refit; not reported because the sample is too short for a stable initial calibration window","folds":[]}
    first_test=max(100,int(len(prices)*.55)); edges=np.linspace(first_test,len(prices)-1,4,dtype=int); folds=[]
    for fold_index in range(3):
        train_end=int(edges[fold_index]); test_end=int(edges[fold_index+1])
        if train_end<80 or test_end-train_end<10: continue
        train_update={"prices":req.prices[:train_end],"parameters":req.parameters}
        for name in ("peer_prices","volumes","highs","lows"):
            values=getattr(req,name)
            if values is not None: train_update[name]=values[:train_end]
        best=None
        for candidate in candidates:
            train_update["parameters"]=candidate
            try:
                train_req=req.model_copy(update=train_update)
                train_result=evaluate_backtest(train_req,include_walk_forward=False)
                score=float(train_result.get("sharpe_ratio") or 0)
                if best is None or score>best[0]: best=(score,candidate)
            except (ValueError,TypeError,OverflowError): continue
        if best is None: continue
        params=best[1]; full_update={"prices":req.prices[:test_end],"parameters":params}
        for name in ("peer_prices","volumes","highs","lows"):
            values=getattr(req,name)
            if values is not None: full_update[name]=values[:test_end]
        try: simulated=evaluate_backtest(req.model_copy(update=full_update),include_walk_forward=False)
        except (ValueError,TypeError,OverflowError): continue
        curve=simulated.get("equity_curve",[]); start_index=train_end-2; end_index=test_end-2
        before=float(curve[start_index]) if 0<=start_index<len(curve) else req.initial_capital
        after=float(curve[end_index]) if 0<=end_index<len(curve) else before
        fold_curve=np.asarray(curve[max(start_index,0):end_index+1],dtype=float)
        peak=np.maximum.accumulate(np.r_[before,fold_curve])
        draw=np.min(np.r_[0.,fold_curve/peak[1:]-1]) if len(fold_curve) else 0.
        folds.append({"fold":fold_index+1,"calibration_observations":train_end,"out_of_sample_observations":test_end-train_end,"selected_parameters":params,"calibration_sharpe":best[0],"out_of_sample_return_pct":(after/before-1)*100 if before else 0.,"out_of_sample_max_drawdown_pct":float(draw*100)})
    return {"method":"Expanding-window refit on prior observations; candidate parameters selected by in-sample Sharpe, then measured on the next chronological fold. The rule is re-run on past data with the chosen parameters; no fold uses future bars.","folds":folds}

def evaluate_backtest(req:BacktestRequest,include_walk_forward:bool=True):
    if req.engine not in BACKTEST_ENGINES: raise ValueError("This model currently supports research calculations but not strategy backtesting")
    prices=np.asarray(req.prices,dtype=float)
    if not np.isfinite(prices).all() or (prices<=0).any() or np.ptp(prices)==0: raise ValueError("prices must be finite, positive, and contain price movement")
    peer=np.asarray(req.peer_prices,dtype=float) if req.peer_prices is not None else None
    if req.engine in ("statistical_arbitrage","pairs_trading") and (peer is None or len(peer)!=len(prices) or not np.isfinite(peer).all() or (peer<=0).any()): raise ValueError("A valid aligned peer_prices series is required for this engine")
    log_returns=np.diff(np.log(prices))
    if not np.isfinite(log_returns).all() or np.max(np.abs(log_returns))>20: raise ValueError("single-observation price moves are outside the supported numeric range")
    if req.engine in ("garch","monte_carlo"):
        split=max(30,int(len(log_returns)*.7))
        if len(log_returns)-split<5: raise ValueError("forecast validation requires at least five out-of-sample returns")
        observed=log_returns[split:]
        if req.engine=="garch":
            fit=_garch_fit(log_returns[:split]); omega=fit["omega_percent_squared"]; alpha=fit["alpha"]; beta=fit["beta"]
            prior=log_returns[:split]*100; variance=(fit["conditional_volatility_pct"]/np.sqrt(252))**2; forecasts=[]; realized=[]; qlike=[]
            for r in observed:
                variance=max(omega+alpha*prior[-1]**2+beta*variance,1e-12); actual=float((r*100)**2); forecasts.append(variance); realized.append(actual); qlike.append(float(np.log(variance)+actual/variance)); prior=np.r_[prior,float(r*100)]
            return {"engine":req.engine,"validation_type":"volatility_forecast","data_status":"historical_validation","observations":len(prices),"calibration_observations":split,"forecast_observations":len(observed),"forecast_method":"Fixed Gaussian GARCH(1,1) parameters estimated on the chronological calibration sample; variance updated using prior observed returns.","mean_squared_variance_error":float(np.mean((np.asarray(forecasts)-realized)**2)),"mean_absolute_variance_error":float(np.mean(np.abs(np.asarray(forecasts)-realized))),"mean_qlike":float(np.mean(qlike)),"mean_forecast_volatility_pct":float(np.mean(np.sqrt(forecasts))),"mean_realized_volatility_pct":float(np.mean(np.sqrt(realized))),"parameters":{"omega_percent_squared":omega,"alpha":alpha,"beta":beta},"disclosure":"Chronological one-step forecast validation on caller supplied returns. Calibration parameters are held fixed in the test period. Results are sample dependent and are not live forecasts."}
        window=min(int(req.parameters.get("lookback",60)),split); simulations=int(req.parameters.get("simulations",2000)); seed=int(req.parameters.get("seed",7))
        if window<20 or simulations<100 or simulations>50000: raise ValueError("lookback must be at least 20; simulations must be 100-50000")
        rng=np.random.default_rng(seed); quantiles=[]; hit=[]
        for offset,r in enumerate(observed):
            hist=log_returns[split+offset-window:split+offset]; scenarios=rng.normal(float(hist.mean()),float(hist.std(ddof=1)),simulations); quantile=float(np.quantile(scenarios,.05)); quantiles.append(quantile); hit.append(bool(r<quantile))
        return {"engine":req.engine,"validation_type":"monte_carlo_var","data_status":"historical_validation","observations":len(prices),"calibration_observations":split,"forecast_observations":len(observed),"forecast_horizon_observations":1,"simulations_per_forecast":simulations,"seed":seed,"mean_simulated_var_95_pct":float(np.mean(quantiles)*100),"observed_breach_rate_pct":float(np.mean(hit)*100),"expected_breach_rate_pct":5.0,"breaches":int(np.sum(hit)),"disclosure":"Rolling one-step 5% return quantile from seeded Monte Carlo draws using the preceding historical window. Breach rates are noisy at small sample sizes and are not a guarantee of future loss bounds."}
    volumes=np.asarray(req.volumes,dtype=float) if req.volumes is not None else None
    if req.engine=="vwap" and (volumes is None or len(volumes)!=len(prices) or not np.isfinite(volumes).all() or (volumes<0).any() or volumes.sum()<=0): raise ValueError("A valid aligned volumes series is required for VWAP")
    highs=np.asarray(req.highs,dtype=float) if req.highs is not None else None; lows=np.asarray(req.lows,dtype=float) if req.lows is not None else None
    if req.engine=="volatility_breakout" and (highs is None or lows is None or len(highs)!=len(prices) or len(lows)!=len(prices) or not np.isfinite(highs).all() or not np.isfinite(lows).all() or np.any(highs<prices) or np.any(lows>prices) or np.any(highs<lows)): raise ValueError("Valid aligned highs and lows satisfying high >= close >= low are required for volatility breakout")
    ret=np.expm1(log_returns); w=min(int(req.parameters.get("lookback",20)),len(ret)); fee=(req.fee_bps+req.slippage_bps+req.spread_cost_bps+req.market_impact_bps)/10000
    if w<2: raise ValueError("lookback must be at least 2")
    weights=[]; params=req.parameters or {}; fast_window=int(params.get("fast_window",20)); slow_window=int(params.get("slow_window",50)); window=min(int(params.get("window",20)),len(prices))
    if req.engine in ("moving_average","macd") and (fast_window<2 or slow_window<=fast_window): raise ValueError("fast_window must be at least 2 and smaller than slow_window")
    for i in range(len(ret)):
        # The signal for return i uses prices only through i, never the ending price of that return.
        end=i; start=max(0,end-w); hist=ret[start:end]
        if end<max(20,w): weights.append(0.); continue
        weight=0.
        if req.engine=="moving_average":
            sample=prices[:end+1]; kind=str(params.get("average_type","SMA")).upper(); fast=float(np.mean(sample[-fast_window:])) if kind=="SMA" else float(_exponential(sample,fast_window)[-1]); slow=float(np.mean(sample[-slow_window:])) if kind=="SMA" else float(_exponential(sample,slow_window)[-1]); weight=float(np.sign(fast-slow))
        elif req.engine=="rsi":
            value=_wilder_rsi(prices[:end+1],int(params.get("window",14)))[-1]; weight=1. if np.isfinite(value) and value<=float(params.get("oversold",30)) else -1. if np.isfinite(value) and value>=float(params.get("overbought",70)) else 0.
        elif req.engine=="macd":
            sample=prices[:end+1]; line=_exponential(sample,fast_window)-_exponential(sample,slow_window); signal=_exponential(line,int(params.get("signal_window",9))); weight=float(np.sign(line[-1]-signal[-1]))
        elif req.engine=="bollinger":
            sample=prices[max(0,end-window):end]; sd=float(sample.std(ddof=1)) if len(sample)>1 else 0.; z=(prices[end]-sample.mean())/sd if sd>0 else 0.; weight=-float(np.clip(z/float(params.get("deviations",2)),-1,1))
        elif req.engine=="vwap":
            sample=prices[max(0,end-window):end]; sample_volume=volumes[max(0,end-window):end]; total=float(sample_volume.sum()); average=float(np.sum(sample*sample_volume)/total) if total>0 else prices[end]; weight=float(np.sign(prices[end]-average))
        elif req.engine in ("statistical_arbitrage","pairs_trading"):
            from scipy.stats import linregress
            low=max(0,end-window); sample=np.log(prices[low:end+1]); peer_sample=np.log(peer[low:end+1]); fit=linregress(peer_sample,sample); spread=sample-(fit.intercept+fit.slope*peer_sample); sd=float(spread.std(ddof=1)); z=(spread[-1]-spread.mean())/sd if sd>0 else 0.; weight=-float(np.clip(z/float(params.get("entry_z",2)),-1,1))
        elif req.engine=="mean_reversion":
            sample=prices[max(0,end-w):end]; std=float(sample.std(ddof=1)); z=(prices[end]-sample.mean())/std if std>0 else 0.; weight=-float(np.clip(z/2,-1,1))
        elif req.engine=="momentum": weight=float(np.sign(np.prod(1+hist)-1))
        elif req.engine=="volatility_breakout":
            prior_high=float(highs[max(0,end-window):end].max()); prior_low=float(lows[max(0,end-window):end].min()); weight=1. if prices[end]>prior_high else -1. if prices[end]<prior_low else 0.
        weights.append(weight)
    weights=np.asarray(weights)*req.position_size; turnover=np.abs(np.diff(np.r_[0,weights])); strat=weights*ret-turnover*fee-np.abs(weights)*(req.funding_bps_per_period/10000)
    if not np.isfinite(strat).all() or np.any(1+strat<=0): raise ValueError("Costs and input returns would produce a non-positive account value")
    equity=req.initial_capital*np.cumprod(1+strat)
    if not np.isfinite(equity).all(): raise ValueError("Computed equity overflowed the supported numeric range; shorten the sample")
    peak=np.maximum.accumulate(np.r_[req.initial_capital,equity])[1:]; draw=equity/peak-1
    total=float(equity[-1]/req.initial_capital-1); ann=float((equity[-1]/req.initial_capital)**(req.periods_per_year/max(1,len(strat)))-1) if equity[-1]>0 else -1.
    vol=float(strat.std(ddof=1)*np.sqrt(req.periods_per_year)) if len(strat)>1 else 0.; sharpe=float(strat.mean()*req.periods_per_year/vol) if vol>0 else 0.
    downside=float(np.sqrt(np.mean(np.minimum(strat,0)**2))*np.sqrt(req.periods_per_year)); sortino=float(strat.mean()*req.periods_per_year/downside) if downside>0 else None
    gains=float(strat[strat>0].sum()); losses=float(-strat[strat<0].sum()); profit_factor=gains/losses if losses>0 else None
    drawdown_abs=abs(float(draw.min())); calmar=ann/drawdown_abs if drawdown_abs>0 else None
    active_days=int(np.count_nonzero(weights)); trade_count=int(np.count_nonzero(np.diff(np.r_[0,weights]))); avg_holding=active_days/max(trade_count,1)
    benchmark=None
    if req.benchmark_prices is not None:
        benchmark_prices=np.asarray(req.benchmark_prices,dtype=float)
        if len(benchmark_prices)!=len(prices) or not np.isfinite(benchmark_prices).all() or (benchmark_prices<=0).any(): raise ValueError("benchmark_prices must be positive, finite, and align with prices")
        benchmark_returns=np.expm1(np.diff(np.log(benchmark_prices))); benchmark_total=float(np.prod(1+benchmark_returns)-1)
        benchmark={"total_return_pct":benchmark_total*100,"relative_return_pct":(total-benchmark_total)*100,"label":"User supplied benchmark; gross of strategy transaction costs"}
    split=max(1,int(len(strat)*.7)); holdout=strat[split:]; holdout_curve=np.cumprod(1+holdout) if len(holdout) else np.array([1.]); holdout_peak=np.maximum.accumulate(np.r_[1.,holdout_curve])[1:]; holdout_draw=holdout_curve/holdout_peak-1
    test_return=float(holdout_curve[-1]-1); test_vol=float(holdout.std(ddof=1)*np.sqrt(req.periods_per_year)) if len(holdout)>1 else 0.; test_sharpe=float(holdout.mean()*req.periods_per_year/test_vol) if test_vol>0 else 0.
    walk_forward=_walk_forward_refit(req,include_walk_forward)
    return {"engine":req.engine,"data_status":"historical_simulation","observations":len(prices),"initial_capital":req.initial_capital,"final_equity":float(equity[-1]),"total_return_pct":total*100,"annualized_return_pct":ann*100,"annualized_volatility_pct":vol*100,"sharpe_ratio":sharpe,"sortino_ratio":sortino,"calmar_ratio":calmar,"profit_factor":profit_factor,"win_rate_pct":float(np.mean(strat>0)*100),"trade_count":trade_count,"average_holding_period_observations":avg_holding,"turnover_units":float(turnover.sum()),"maximum_drawdown_pct":float(draw.min()*100),"max_drawdown_pct":float(draw.min()*100),"benchmark":benchmark,"out_of_sample":{"method":"chronological 70/30 holdout; signal is lagged by one observation","test_start_observation":split+1,"observations":len(holdout),"return_pct":test_return*100,"annualized_volatility_pct":test_vol*100,"sharpe_ratio":test_sharpe,"max_drawdown_pct":float(holdout_draw.min()*100)},"walk_forward":walk_forward,"cost_assumptions_bps":{"fees":req.fee_bps,"slippage":req.slippage_bps,"spread":req.spread_cost_bps,"market_impact":req.market_impact_bps,"funding_per_period":req.funding_bps_per_period},"periods_per_year":req.periods_per_year,"position_size_fraction":req.position_size,"equity_curve":equity.round(2).tolist(),"exposure":weights.round(4).tolist(),"disclosure":"Historical simulation from supplied observations. Walk-forward parameters are selected only from prior data; candidate-grid optimization remains vulnerable to data-snooping. Signals use a one-bar lag. Fees, spread, slippage, market impact and funding are entered assumptions, not estimates from venue depth. No corporate-action, borrow, liquidity, tax or delisting adjustments. Not live performance or investment advice."}

@app.post("/backtests",status_code=201)
def backtest(req:BacktestRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    try: result=evaluate_backtest(req)
    except (ValueError,TypeError) as e: raise HTTPException(422,str(e))
    series_payload={"prices":req.prices,"peer_prices":req.peer_prices,"volumes":req.volumes,"highs":req.highs,"lows":req.lows}
    for name,values in series_payload.items():
        if values is not None and not np.isfinite(np.asarray(values,dtype=float)).all(): raise HTTPException(422,f"{name} must contain only finite values")
    fingerprint=hashlib.sha256(json.dumps(series_payload,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()
    result["input_provenance"]={"source":"CALLER_SUPPLIED","observations":len(req.prices),"series_sha256":fingerprint}
    settings=db.query(RiskSettings).filter_by(user_id=user.id).first()
    if settings and "max_drawdown_pct" in result:
        limit=settings.max_drawdown_pct
        result["risk_check"]={"maximum_drawdown_limit_pct":limit,"observed_max_drawdown_pct":abs(result["max_drawdown_pct"]),"within_limit":abs(result["max_drawdown_pct"])<=limit,"action":"REVIEW ONLY · NO TRADING CONTROL"}
    record=Backtest(user_id=user.id,engine=req.engine,result=result); db.add(record); db.flush(); audit(db,user.id,"backtest_created","backtest",record.id,{"engine":req.engine}); db.commit(); result["id"]=record.id; return result

@app.get("/backtests")
def backtest_history(user:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.query(Backtest).filter(Backtest.user_id==user.id).order_by(Backtest.created_at.desc()).limit(50).all()
    return [{"id":r.id,"engine":r.engine,"created_at":r.created_at.isoformat(),"result":r.result} for r in rows]

def risk_view(row): return {"max_position_pct":row.max_position_pct,"max_drawdown_pct":row.max_drawdown_pct,"daily_loss_limit_pct":row.daily_loss_limit_pct,"max_gross_exposure_pct":row.max_gross_exposure_pct,"portfolio_nav":row.portfolio_nav,"risk_profile":row.risk_profile,"max_leverage_pct":row.max_leverage_pct,"asset_class_limits":row.asset_class_limits or {},"volatility_tolerance":row.volatility_tolerance,"liquidity_floor_usd":row.liquidity_floor_usd,"investment_horizon_months":row.investment_horizon_months,"updated_at":row.updated_at.isoformat()}
@app.get("/risk/settings")
def get_risk(user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=db.query(RiskSettings).filter_by(user_id=user.id).first()
    if not row: row=RiskSettings(user_id=user.id); db.add(row); db.commit(); db.refresh(row)
    return risk_view(row)
@app.put("/risk/settings")
def update_risk(req:RiskRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=db.query(RiskSettings).filter_by(user_id=user.id).first()
    if not row: row=RiskSettings(user_id=user.id); db.add(row)
    for k,v in req.model_dump().items(): setattr(row,k,v)
    audit(db,user.id,"risk_limits_updated","risk_settings",user.id)
    db.commit(); db.refresh(row); return risk_view(row)

def portfolio_view(user,db):
    rows=db.query(Position).filter_by(user_id=user.id).order_by(Position.id.desc()).all(); gross=sum(r.quantity*r.current_price for r in rows); cost=sum(r.quantity*r.average_cost for r in rows); pnl=gross-cost
    settings=db.query(RiskSettings).filter_by(user_id=user.id).first()
    pos=[{"id":r.id,"symbol":r.symbol,"asset_class":r.asset_class,"quantity":r.quantity,"average_cost":r.average_cost,"current_price":r.current_price,"market_value":r.quantity*r.current_price,"pnl":r.quantity*(r.current_price-r.average_cost),"weight_pct":(r.quantity*r.current_price/gross*100 if gross else 0)} for r in rows]
    nav=settings.portfolio_nav if settings else 100000; maxpos=max([x["market_value"]/nav*100 for x in pos],default=0); gross_limit=settings.max_gross_exposure_pct if settings else 100; pos_limit=settings.max_position_pct if settings else 10
    warnings=[]
    if maxpos>pos_limit: warnings.append("A position exceeds the configured concentration limit.")
    exposure=gross/nav*100
    if exposure>gross_limit: warnings.append("Portfolio gross exposure exceeds the configured limit.")
    classes={}
    for p in pos: classes[p["asset_class"]]=classes.get(p["asset_class"],0)+p["market_value"]
    allocations={k:{"market_value":v,"weight_pct":v/gross*100 if gross else 0} for k,v in classes.items()}
    if settings:
        for asset,limit in (settings.asset_class_limits or {}).items():
            if allocations.get(asset,{}).get("weight_pct",0)>limit: warnings.append(f"{asset.capitalize()} allocation exceeds its configured asset-class limit.")
    return {"positions":pos,"summary":{"position_count":len(pos),"gross_market_value":gross,"cost_basis":cost,"unrealized_pnl":pnl,"return_pct":pnl/cost*100 if cost else 0,"largest_position_pct":maxpos,"exposure_pct":exposure,"asset_allocations":allocations},"risk_warnings":warnings,"valuation_status":"User-entered prices; not a live valuation."}
@app.get("/portfolio")
def portfolio(user:User=Depends(current_user),db:Session=Depends(get_db)): return portfolio_view(user,db)
@app.post("/portfolio/positions",status_code=201)
def add_position(req:PositionRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=Position(user_id=user.id,**req.model_dump()); db.add(row); db.flush(); audit(db,user.id,"portfolio_position_added","position",row.id,{"symbol":row.symbol,"asset_class":row.asset_class}); db.commit(); db.refresh(row); return portfolio_view(user,db)
@app.delete("/portfolio/positions/{position_id}")
def delete_position(position_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=db.query(Position).filter_by(id=position_id,user_id=user.id).first()
    if not row: raise HTTPException(404,"Position not found")
    audit(db,user.id,"portfolio_position_removed","position",row.id,{"symbol":row.symbol}); db.delete(row); db.commit(); return portfolio_view(user,db)
@app.get("/risk/assessment")
def risk_assessment(user:User=Depends(current_user),db:Session=Depends(get_db)):
    data=portfolio_view(user,db); settings=db.query(RiskSettings).filter_by(user_id=user.id).first()
    return {"portfolio":data["summary"],"limits":risk_view(settings) if settings else None,"warnings":data["risk_warnings"],"checks":{"concentration":"PASS" if not data["risk_warnings"] else "REVIEW","valuation":"USER ENTERED","drawdown":"NO HISTORICAL EQUITY CURVE","volatility":"NOT ASSESSED · no position return history","liquidity":"NOT ASSESSED · no provider data","correlation":"NOT ASSESSED · no aligned return series"}}

@app.post("/risk/position-check")
def check_proposed_exposure(req:ExposureCheckRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    settings=db.query(RiskSettings).filter_by(user_id=user.id).first() or RiskSettings(user_id=user.id)
    portfolio_data=portfolio_view(user,db); summary=portfolio_data["summary"]; nav=settings.portfolio_nav
    position_pct=req.market_value/nav*100; projected_gross=summary["gross_market_value"]+req.market_value; gross_pct=projected_gross/nav*100; warnings=[]
    if position_pct>settings.max_position_pct: warnings.append("Proposed position exceeds the maximum position weight.")
    if gross_pct>settings.max_gross_exposure_pct: warnings.append("Proposed gross exposure exceeds the workspace limit.")
    if gross_pct>settings.max_leverage_pct: warnings.append("Proposed gross exposure exceeds the configured leverage limit.")
    asset_value=summary.get("asset_allocations",{}).get(req.asset_class,{}).get("market_value",0)+req.market_value
    asset_pct=asset_value/projected_gross*100 if projected_gross else 0; asset_limit=(settings.asset_class_limits or {}).get(req.asset_class)
    if asset_limit is not None and asset_pct>asset_limit: warnings.append("Proposed allocation exceeds the asset-class limit.")
    return {"eligible_for_review":not warnings,"proposed_position_pct":position_pct,"projected_gross_exposure_pct":gross_pct,"proposed_asset_class_weight_pct":asset_pct,"liquidity_check":"NOT ASSESSED · no market data","warnings":warnings,"action":"REVIEW ONLY · DOES NOT AUTHORIZE OR EXECUTE AN ORDER"}

@app.get("/audit")
def audit_history(limit:int=Query(default=100,ge=1,le=500),user:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.query(AuditLog).filter_by(user_id=user.id).order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [{"id":r.id,"action":r.action,"entity_type":r.entity_type,"entity_id":r.entity_id,"details":r.details,"created_at":r.created_at.isoformat()} for r in rows]

@app.get("/events")
async def events():
    async def stream():
        while True:
            try:
                with SessionLocal() as db: payload={"type":"status_snapshot","at":datetime.now(timezone.utc).isoformat(),**health(db)}
            except Exception as exc: payload={"type":"status_snapshot","at":datetime.now(timezone.utc).isoformat(),"status":"DEVELOPMENT","database":"OFFLINE","latest_error":{"message":str(exc)[:200]}}
            yield "data: "+__import__("json").dumps(payload)+"\n\n"
            await asyncio.sleep(15)
    return StreamingResponse(stream(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
