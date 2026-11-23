"""VALTIERA quantitative research API; market execution and live data are intentionally absent."""
import asyncio, os, time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, text, inspect
from sqlalchemy.orm import Session
from .auth import current_user, hash_password, issue_token, verify_password
from .db import Base, DATABASE_URL, SessionLocal, engine, get_db
from .engines.core import calculate, ENGINES
from .models import AuditLog, Backtest, Comment, EngineRun, Poll, PollVote, Position, Post, ResearchJob, RiskSettings, ServiceHeartbeat, User

def initialize_storage():
    if not DATABASE_URL.startswith("sqlite") and not os.getenv("VALTIERA_SECRET"):
        raise RuntimeError("VALTIERA_SECRET must be configured for non-development deployments")
    Base.metadata.create_all(bind=engine)
    columns={c["name"] for c in inspect(engine).get_columns("risk_settings")}
    if "portfolio_nav" not in columns:
        with engine.begin() as connection: connection.execute(text("ALTER TABLE risk_settings ADD COLUMN portfolio_nav FLOAT NOT NULL DEFAULT 100000"))
    seed_allowed=os.getenv("ALLOW_DEMO_SEED","true" if DATABASE_URL.startswith("sqlite") else "false").lower()=="true"
    if not seed_allowed: return
    with SessionLocal() as db:
        if db.query(User).filter(User.is_demo.is_(True)).count(): return
        demo=[("Maya Chen","maya@valtiera.demo"),("Elias Morgan","elias@valtiera.demo"),("Sofia Patel","sofia@valtiera.demo"),("Noah Williams","noah@valtiera.demo"),("Amara Okafor","amara@valtiera.demo"),("Lucas Fischer","lucas@valtiera.demo")]
        users=[]
        for name,email in demo:
            user=User(name=name,email=email,password_hash=hash_password(password_secret()),role="researcher",is_demo=True); db.add(user); users.append(user)
        db.flush()
        for user in users: db.add(RiskSettings(user_id=user.id))
        topics=[
          ("Testing spread stability across regimes","We are comparing rolling Engle–Granger residuals across calm and high-volatility windows. What diagnostics do you require before treating a pair as research-worthy?","Methods"),
          ("Volatility forecast evaluation","Which loss function has been most useful for comparing realized-volatility forecasts in your recent research? Please include the sampling horizon and assumptions.","Volatility"),
          ("Out-of-sample protocol for momentum","We are reviewing expanding-window validation with a one-month embargo. Interested in how others account for overlapping labels and changing liquidity.","Backtesting"),
          ("Research question: risk budgets","How do you communicate concentration limits when assets share hidden factor exposure? Looking for reproducible approaches, not performance claims.","Risk")]
        for i,(title,body,topic) in enumerate(topics): db.add(Post(user_id=users[i].id,title=title,body=body,topic=topic))
        db.flush(); first=db.query(Post).order_by(Post.id).first()
        db.add(Poll(post_id=first.id,question="Which diagnostic is your first stationarity check?",options=["Residual ADF","Half-life stability","Regime robustness","I need more evidence"]))
        db.commit()

@asynccontextmanager
async def lifespan(_app):
    initialize_storage()
    yield

app=FastAPI(title="VALTIERA Research API",version="1.0.0",description="Persistent quantitative research workspace. No investment execution or live market feed is provided.",lifespan=lifespan)
origins=[x.strip() for x in os.getenv("CORS_ORIGINS","http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=["GET","POST","PUT","DELETE"],allow_headers=["Content-Type","Authorization"])
STARTED=datetime.now(timezone.utc); login_attempts={}

class RunRequest(BaseModel):
    data: dict
    parameters: dict=Field(default_factory=dict)
class JobRequest(BaseModel):
    engine: str
    data: dict
    parameters: dict=Field(default_factory=dict)
class Credentials(BaseModel):
    email: str=Field(min_length=3,max_length=255)
    password: str=Field(min_length=8,max_length=128)
class RegisterRequest(Credentials):
    name: str=Field(min_length=2,max_length=100)
class PositionRequest(BaseModel):
    symbol: str=Field(min_length=1,max_length=32)
    asset_class: Literal["equity","future","option","bond","crypto","other"]="equity"
    quantity: float=Field(gt=0,le=1e12)
    average_cost: float=Field(gt=0,le=1e12)
    current_price: float=Field(gt=0,le=1e12)
class ExposureCheckRequest(BaseModel): market_value: float=Field(gt=0,le=1e12)
class RiskRequest(BaseModel):
    max_position_pct: float=Field(gt=0,le=100)
    max_drawdown_pct: float=Field(gt=0,le=100)
    daily_loss_limit_pct: float=Field(gt=0,le=100)
    max_gross_exposure_pct: float=Field(gt=0,le=300)
    portfolio_nav: float=Field(gt=0,le=1e12)
class BacktestRequest(BaseModel):
    engine: str
    prices: list[float]=Field(min_length=31,max_length=10000)
    peer_prices: list[float]|None=None
    initial_capital: float=Field(default=100000,gt=0,le=1e12)
    fee_bps: float=Field(default=5,ge=0,le=1000)
    parameters: dict=Field(default_factory=dict)
class PostRequest(BaseModel):
    title: str=Field(min_length=5,max_length=180)
    body: str=Field(min_length=10,max_length=5000)
    topic: str=Field(default="Research",min_length=2,max_length=48)
class CommentRequest(BaseModel): body: str=Field(min_length=2,max_length=2000)
class PollRequest(BaseModel):
    question: str=Field(min_length=5,max_length=240)
    options: list[str]=Field(min_length=2,max_length=6)
    @field_validator("options")
    @classmethod
    def validate_options(cls, values):
        if any(not x.strip() or len(x)>100 for x in values): raise ValueError("Poll choices must contain 1 to 100 characters")
        return values
class VoteRequest(BaseModel): option_index: int=Field(ge=0)

def public_user(user): return {"id":user.id,"email":user.email,"name":user.name,"role":user.role,"is_demo":user.is_demo}
def audit(db,user_id,action,entity_type="workspace",entity_id=None,details=None):
    db.add(AuditLog(user_id=user_id,action=action,entity_type=entity_type,entity_id=str(entity_id) if entity_id is not None else None,details=details or {}))
def password_secret(): return os.getenv("DEMO_PASSWORD","Research-Demo-2026")

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
    return {"status":"DEVELOPMENT","database":database,"market_data":"DATA UNAVAILABLE","redis":redis_state,"worker":worker_state,"engines":{e:"READY" for e in ENGINES},"started_at":STARTED.isoformat(),"last_market_timestamp":None}

@app.get("/demo-users")
def demo_users(db: Session=Depends(get_db)):
    if db.query(User).filter(User.is_demo.is_(True)).count()==0: return {"enabled":False,"users":[]}
    users=db.query(User).filter(User.is_demo.is_(True)).order_by(User.id).all()
    return {"enabled":True,"label":"Fictional development profiles","password":password_secret(),"users":[public_user(u) for u in users]}

@app.post("/auth/register",status_code=201)
def register(request:RegisterRequest,db:Session=Depends(get_db)):
    email=request.email.strip().lower()
    if db.query(User).filter(func.lower(User.email)==email).first(): raise HTTPException(409,"An account with this email already exists")
    user=User(email=email,name=request.name.strip(),password_hash=hash_password(request.password)); db.add(user); db.flush(); db.add(RiskSettings(user_id=user.id)); audit(db,user.id,"account_registered"); db.commit(); db.refresh(user)
    return {"token":issue_token(user),"user":public_user(user)}

@app.post("/auth/login")
def login(request:Credentials,req:Request,db:Session=Depends(get_db)):
    key=req.client.host if req.client else "unknown"; now=time.time(); times=[t for t in login_attempts.get(key,[]) if now-t<300]
    if len(times)>=12: raise HTTPException(429,"Too many login attempts; try again in five minutes")
    user=db.query(User).filter(func.lower(User.email)==request.email.strip().lower()).first()
    if not user or not verify_password(request.password,user.password_hash):
        times.append(now); login_attempts[key]=times; raise HTTPException(401,"Email or password is incorrect")
    login_attempts.pop(key,None); audit(db,user.id,"login_succeeded"); db.commit(); return {"token":issue_token(user),"user":public_user(user)}

@app.get("/auth/me")
def me(user:User=Depends(current_user)): return public_user(user)
@app.post("/auth/logout")
def logout(user:User=Depends(current_user),db:Session=Depends(get_db)):
    audit(db,user.id,"logout_requested"); db.commit()
    return {"ok":True,"note":"Discard the bearer token in the client to end this session."}

@app.get("/market-data/candles")
def candles(symbol:str=Query(min_length=1,max_length=32),timeframe:str="1D",limit:int=Query(default=220,ge=30,le=1000)):
    raise HTTPException(503,"No licensed market-data provider is configured; chart data unavailable.")

@app.get("/engines")
def engines():
    descriptions={"statistical_arbitrage":"Pair association, Engle-Granger residual cointegration, spread deviation","momentum":"Volatility-adjusted time-series momentum","mean_reversion":"Rolling deviation and OLS half-life estimate","volatility_options":"Realized volatility and optional Black-Scholes baseline Greeks","cross_asset":"Aligned return correlation and relative basis","market_regime":"Realized-volatility threshold regime descriptor"}
    return {"engines":[{"id":e,"status":"READY","version":"0.1.0","description":descriptions[e]} for e in ENGINES],"note":"Caller supplies the data; no market-data provider is connected."}

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

def evaluate_backtest(req:BacktestRequest):
    if req.engine not in ENGINES: raise ValueError("Unknown research engine")
    prices=np.asarray(req.prices,dtype=float)
    if not np.isfinite(prices).all() or (prices<=0).any() or np.ptp(prices)==0: raise ValueError("prices must be finite, positive, and contain price movement")
    peer=np.asarray(req.peer_prices,dtype=float) if req.peer_prices is not None else None
    if req.engine in ("statistical_arbitrage","cross_asset") and (peer is None or len(peer)!=len(prices) or not np.isfinite(peer).all() or (peer<=0).any()): raise ValueError("A valid aligned peer_prices series is required for this engine")
    log_returns=np.diff(np.log(prices))
    if not np.isfinite(log_returns).all() or np.max(np.abs(log_returns))>20: raise ValueError("single-observation price moves are outside the supported numeric range")
    ret=np.expm1(log_returns); w=min(int(req.parameters.get("lookback",20)),len(ret)); fee=req.fee_bps/10000
    if w<2: raise ValueError("lookback must be at least 2")
    weights=[]
    for i in range(len(ret)):
        # The signal for return i uses prices only through i, never the ending price of that return.
        end=i; start=max(0,end-w); hist=ret[start:end]
        if end<max(20,w): weights.append(0.); continue
        weight=0.
        if req.engine=="momentum": weight=float(np.sign(np.prod(1+hist)-1))
        elif req.engine=="mean_reversion":
            sample=prices[max(0,end-w):end]; std=float(sample.std(ddof=1)); z=(prices[end]-sample.mean())/std if std>0 else 0.; weight=-float(np.clip(z/2,-1,1))
        elif req.engine=="statistical_arbitrage":
            spread=np.log(prices[:end+1])-np.log(peer[:end+1]); tail=spread[-w:]; std=float(tail.std(ddof=1)); z=(tail[-1]-tail.mean())/std if std>0 else 0.; weight=-float(np.clip(z/2,-1,1))
        elif req.engine=="cross_asset":
            rel=np.diff(np.log(prices[:end+1]))-np.diff(np.log(peer[:end+1])); tail=rel[-w:]; std=float(tail.std(ddof=1)); z=tail[-1]/std if std>0 else 0.; weight=-float(np.clip(z/2,-1,1))
        elif req.engine=="market_regime": weight=.5 if np.std(hist,ddof=1)<np.std(ret[:end],ddof=1)*1.5 else .25
        elif req.engine=="volatility_options": weight=.5 if np.std(hist,ddof=1)<.02 else .25
        weights.append(weight)
    weights=np.asarray(weights); turnover=np.abs(np.diff(np.r_[0,weights])); strat=weights*ret-turnover*fee
    if not np.isfinite(strat).all() or np.any(1+strat<=0): raise ValueError("Costs and input returns would produce a non-positive account value")
    equity=req.initial_capital*np.cumprod(1+strat)
    if not np.isfinite(equity).all(): raise ValueError("Computed equity overflowed the supported numeric range; shorten the sample")
    peak=np.maximum.accumulate(np.r_[req.initial_capital,equity])[1:]; draw=equity/peak-1
    total=float(equity[-1]/req.initial_capital-1); ann=float((equity[-1]/req.initial_capital)**(252/max(1,len(strat)))-1) if equity[-1]>0 else -1.
    vol=float(strat.std(ddof=1)*np.sqrt(252)) if len(strat)>1 else 0.; sharpe=float(strat.mean()*252/vol) if vol>0 else 0.
    split=max(1,int(len(strat)*.7)); holdout=strat[split:]; holdout_curve=np.cumprod(1+holdout) if len(holdout) else np.array([1.]); holdout_peak=np.maximum.accumulate(np.r_[1.,holdout_curve])[1:]; holdout_draw=holdout_curve/holdout_peak-1
    test_return=float(holdout_curve[-1]-1); test_vol=float(holdout.std(ddof=1)*np.sqrt(252)) if len(holdout)>1 else 0.; test_sharpe=float(holdout.mean()*252/test_vol) if test_vol>0 else 0.
    return {"engine":req.engine,"data_status":"historical_simulation","observations":len(prices),"initial_capital":req.initial_capital,"final_equity":float(equity[-1]),"total_return_pct":total*100,"annualized_return_pct":ann*100,"annualized_volatility_pct":vol*100,"sharpe_ratio":sharpe,"max_drawdown_pct":float(draw.min()*100),"out_of_sample":{"method":"chronological 70/30 holdout; signal is lagged by one observation","test_start_observation":split+1,"observations":len(holdout),"return_pct":test_return*100,"annualized_volatility_pct":test_vol*100,"sharpe_ratio":test_sharpe,"max_drawdown_pct":float(holdout_draw.min()*100)},"fees_bps":req.fee_bps,"equity_curve":equity.round(2).tolist(),"exposure":weights.round(4).tolist(),"disclosure":"Historical simulation from caller supplied prices; simplified signal rules, no survivorship or data-snooping controls. The chronological holdout does not eliminate data-snooping risk. Not live performance or investment advice."}

@app.post("/backtests",status_code=201)
def backtest(req:BacktestRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    try: result=evaluate_backtest(req)
    except (ValueError,TypeError) as e: raise HTTPException(422,str(e))
    settings=db.query(RiskSettings).filter_by(user_id=user.id).first()
    if settings:
        limit=settings.max_drawdown_pct
        result["risk_check"]={"maximum_drawdown_limit_pct":limit,"observed_max_drawdown_pct":abs(result["max_drawdown_pct"]),"within_limit":abs(result["max_drawdown_pct"])<=limit,"action":"REVIEW ONLY · NO TRADING CONTROL"}
    record=Backtest(user_id=user.id,engine=req.engine,result=result); db.add(record); db.flush(); audit(db,user.id,"backtest_created","backtest",record.id,{"engine":req.engine}); db.commit(); result["id"]=record.id; return result

@app.get("/backtests")
def backtest_history(user:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.query(Backtest).filter(Backtest.user_id==user.id).order_by(Backtest.created_at.desc()).limit(50).all()
    return [{"id":r.id,"engine":r.engine,"created_at":r.created_at.isoformat(),"result":r.result} for r in rows]

def risk_view(row): return {"max_position_pct":row.max_position_pct,"max_drawdown_pct":row.max_drawdown_pct,"daily_loss_limit_pct":row.daily_loss_limit_pct,"max_gross_exposure_pct":row.max_gross_exposure_pct,"portfolio_nav":row.portfolio_nav,"updated_at":row.updated_at.isoformat()}
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
    return {"positions":pos,"summary":{"position_count":len(pos),"gross_market_value":gross,"cost_basis":cost,"unrealized_pnl":pnl,"return_pct":pnl/cost*100 if cost else 0,"largest_position_pct":maxpos,"exposure_pct":exposure},"risk_warnings":warnings,"valuation_status":"User-entered prices; not a live valuation."}
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
    return {"portfolio":data["summary"],"limits":risk_view(settings) if settings else None,"warnings":data["risk_warnings"],"checks":{"concentration":"PASS" if not data["risk_warnings"] else "REVIEW","valuation":"USER ENTERED","drawdown":"NO HISTORICAL EQUITY CURVE"}}

@app.post("/risk/position-check")
def check_proposed_exposure(req:ExposureCheckRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    settings=db.query(RiskSettings).filter_by(user_id=user.id).first() or RiskSettings(user_id=user.id)
    portfolio_data=portfolio_view(user,db); summary=portfolio_data["summary"]; nav=settings.portfolio_nav
    position_pct=req.market_value/nav*100; gross_pct=(summary["gross_market_value"]+req.market_value)/nav*100; warnings=[]
    if position_pct>settings.max_position_pct: warnings.append("Proposed position exceeds the maximum position weight.")
    if gross_pct>settings.max_gross_exposure_pct: warnings.append("Proposed gross exposure exceeds the workspace limit.")
    return {"eligible_for_review":not warnings,"proposed_position_pct":position_pct,"projected_gross_exposure_pct":gross_pct,"warnings":warnings,"action":"REVIEW ONLY · DOES NOT AUTHORIZE OR EXECUTE AN ORDER"}

def comment_view(c,db): return {"id":c.id,"user":public_user(db.get(User,c.user_id)),"body":c.body,"created_at":c.created_at.isoformat()}
def post_view(p,db,user=None):
    comments=db.query(Comment).filter_by(post_id=p.id).order_by(Comment.created_at.asc()).all(); poll=db.query(Poll).filter_by(post_id=p.id).first(); data={"id":p.id,"author":public_user(db.get(User,p.user_id)),"title":p.title,"body":p.body,"topic":p.topic,"created_at":p.created_at.isoformat(),"comments":[comment_view(c,db) for c in comments]}
    if poll:
        counts=[db.query(PollVote).filter_by(poll_id=poll.id,option_index=i).count() for i in range(len(poll.options))]; vote=db.query(PollVote).filter_by(poll_id=poll.id,user_id=user.id).first() if user else None
        data["poll"]={"id":poll.id,"question":poll.question,"options":poll.options,"counts":counts,"my_vote":vote.option_index if vote else None}
    return data
@app.get("/community/posts")
def posts(topic:str|None=None,db:Session=Depends(get_db)):
    query=db.query(Post).order_by(Post.created_at.desc());
    if topic: query=query.filter_by(topic=topic)
    return [post_view(p,db) for p in query.limit(100).all()]
@app.post("/community/posts",status_code=201)
def create_post(req:PostRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    p=Post(user_id=user.id,**req.model_dump()); db.add(p); db.flush(); audit(db,user.id,"community_post_created","post",p.id,{"topic":p.topic}); db.commit(); db.refresh(p); return post_view(p,db,user)
@app.post("/community/posts/{post_id}/comments",status_code=201)
def comment(post_id:int,req:CommentRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    if not db.get(Post,post_id): raise HTTPException(404,"Research post not found")
    c=Comment(post_id=post_id,user_id=user.id,body=req.body.strip()); db.add(c); db.flush(); audit(db,user.id,"community_comment_created","comment",c.id,{"post_id":post_id}); db.commit(); db.refresh(c); return comment_view(c,db)
@app.post("/community/posts/{post_id}/polls",status_code=201)
def create_poll(post_id:int,req:PollRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    if not db.get(Post,post_id): raise HTTPException(404,"Research post not found")
    if db.query(Poll).filter_by(post_id=post_id).first(): raise HTTPException(409,"This post already has a poll")
    poll=Poll(post_id=post_id,question=req.question,options=[x.strip() for x in req.options]); db.add(poll); db.flush(); audit(db,user.id,"community_poll_created","poll",poll.id,{"post_id":post_id}); db.commit(); db.refresh(poll); return {"id":poll.id,"question":poll.question,"options":poll.options,"counts":[0]*len(poll.options),"my_vote":None}
@app.post("/community/polls/{poll_id}/votes")
def vote(poll_id:int,req:VoteRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    poll=db.get(Poll,poll_id)
    if not poll: raise HTTPException(404,"Poll not found")
    if req.option_index>=len(poll.options): raise HTTPException(422,"Choice index is outside the poll choices")
    row=db.query(PollVote).filter_by(poll_id=poll.id,user_id=user.id).first()
    if row: row.option_index=req.option_index
    else: db.add(PollVote(poll_id=poll.id,user_id=user.id,option_index=req.option_index))
    audit(db,user.id,"community_poll_voted","poll",poll.id,{"option_index":req.option_index}); db.commit(); counts=[db.query(PollVote).filter_by(poll_id=poll.id,option_index=i).count() for i in range(len(poll.options))]
    return {"id":poll.id,"question":poll.question,"options":poll.options,"counts":counts,"my_vote":req.option_index}

@app.get("/audit")
def audit_history(limit:int=Query(default=100,ge=1,le=500),user:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.query(AuditLog).filter_by(user_id=user.id).order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [{"id":r.id,"action":r.action,"entity_type":r.entity_type,"entity_id":r.entity_id,"details":r.details,"created_at":r.created_at.isoformat()} for r in rows]

@app.get("/events")
async def events():
    async def stream():
        while True:
            payload={"type":"system_status","at":datetime.now(timezone.utc).isoformat(),"market_data":"DATA UNAVAILABLE","engines":"READY"}
            yield "data: "+__import__("json").dumps(payload)+"\n\n"
            await asyncio.sleep(15)
    return StreamingResponse(stream(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
