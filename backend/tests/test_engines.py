import os
os.environ["DATABASE_URL"] = "sqlite:///./test_valtiera.db"

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.auth import current_user, hash_password, issue_token, verify_password
from app.db import Base, SessionLocal, engine
from app.engines.core import ENGINES, calculate
from app.main import (app, initialize_storage, health, demo_users, run, RunRequest,
                      RiskRequest, update_risk, risk_view, PositionRequest, ExposureCheckRequest, check_proposed_exposure, add_position,
                      portfolio, delete_position, BacktestRequest, backtest, backtest_history,
                      posts, comment, CommentRequest, vote, VoteRequest, create_post, PostRequest,
                      candles, JobRequest, enqueue_research, research_job)
from app.models import User, EngineRun, Backtest as BacktestRow, AuditLog
from app.worker import process_one


@pytest.fixture(scope="module")
def db():
    Base.metadata.drop_all(bind=engine)
    initialize_storage()
    session=SessionLocal()
    yield session
    session.close()

@pytest.fixture
def user(db): return db.query(User).filter_by(email="maya@valtiera.demo").one()

@pytest.fixture
def prices():
    t=np.arange(120,dtype=float)
    return (100*np.exp(.001*t+.02*np.sin(t/6))).tolist()


@pytest.mark.parametrize("engine_name",ENGINES)
def test_six_engines_return_structured_results(engine_name,prices):
    peer=np.array(prices)*np.exp(.01*np.sin(np.arange(len(prices))/9))
    result=calculate(engine_name,{"prices":prices,"peer_prices":peer.tolist(),"source":"test fixture","status":"historical"})
    assert result["engine"]==engine_name and result["observations"]==120 and result["metrics"]
    assert result["data_status"]=="historical"

def test_options_engine_has_bsm_baseline(prices):
    result=calculate("volatility_options",{"prices":prices,"spot":100,"strike":100,"days_to_expiry":30,"implied_volatility":.25})
    assert result["metrics"]["black_scholes_call_baseline"]>0
    assert 0<result["metrics"]["call_delta"]<1

def test_engine_input_validation(prices):
    for series in ([1]*29,[1]*29+[0],[1]*30):
        with pytest.raises(ValueError): calculate("momentum",{"prices":series})
    with pytest.raises(ValueError,match="align"):
        calculate("statistical_arbitrage",{"prices":prices,"peer_prices":prices[:-1]})

def test_auth_password_and_signed_session(db,user):
    hashed=hash_password("A-strong-test-password")
    assert verify_password("A-strong-test-password",hashed)
    assert not verify_password("wrong-password",hashed)
    token=issue_token(user)
    assert current_user(HTTPAuthorizationCredentials(scheme="Bearer",credentials=token),db).id==user.id
    broken=token[:-2]+"xx"
    with pytest.raises(HTTPException): current_user(HTTPAuthorizationCredentials(scheme="Bearer",credentials=broken),db)

def test_health_demo_profiles_and_provider_transparency(db):
    assert health(db)["database"]=="OPERATIONAL"
    assert health(db)["market_data"]=="DATA UNAVAILABLE"
    demo=demo_users(db)
    assert len(demo["users"])==6 and all(x["is_demo"] for x in demo["users"])
    with pytest.raises(HTTPException) as error: candles("DEMO")
    assert error.value.status_code==503

def test_engine_execution_is_persisted(db,user,prices):
    result=run("momentum",RunRequest(data={"prices":prices,"status":"historical"}),user,db)
    assert result["execution_id"]
    assert db.query(EngineRun).filter_by(user_id=user.id,engine="momentum").count()==1
    with pytest.raises(HTTPException) as error: run("momentum",RunRequest(data={"prices":[1,2]}),user,db)
    assert error.value.status_code==422

def test_durable_worker_job_lifecycle(db,user,prices):
    queued=enqueue_research(JobRequest(engine="momentum",data={"prices":prices,"status":"historical"},parameters={}),user,db)
    assert queued["status"]=="PENDING"
    assert process_one(db) is True
    job=research_job(queued["job_id"],user,db)
    assert job["status"]=="COMPLETED" and job["result"]["metrics"]["direction"] in ("up","down","flat")

def test_risk_limits_and_portfolio_are_enforced_and_persisted(db,user):
    req=RiskRequest(max_position_pct=10,max_drawdown_pct=15,daily_loss_limit_pct=2,max_gross_exposure_pct=90,portfolio_nav=10000)
    assert update_risk(req,user,db)["portfolio_nav"]==10000
    result=add_position(PositionRequest(symbol="TEST",asset_class="equity",quantity=20,average_cost=100,current_price=110),user,db)
    assert result["summary"]["unrealized_pnl"]==200
    assert result["summary"]["exposure_pct"]==22
    assert len(result["risk_warnings"])==1
    review=check_proposed_exposure(ExposureCheckRequest(market_value=2000),user,db)
    assert review["eligible_for_review"] is False and review["action"].startswith("REVIEW ONLY")
    pid=result["positions"][0]["id"]
    assert delete_position(pid,user,db)["summary"]["position_count"]==0
    assert portfolio(user,db)["positions"]==[]

def test_backtest_is_lagged_and_saved(db,user,prices):
    req=BacktestRequest(engine="momentum",prices=prices,initial_capital=10000,fee_bps=5)
    result=backtest(req,user,db)
    assert result["data_status"]=="historical_simulation"
    assert result["exposure"][:20]==[0]*20
    assert "Not live performance" in result["disclosure"]
    assert "out_of_sample" in result and "risk_check" in result
    assert len(backtest_history(user,db))==1
    assert db.query(BacktestRow).filter_by(user_id=user.id).count()==1
    with pytest.raises(HTTPException): backtest(BacktestRequest(engine="statistical_arbitrage",prices=prices),user,db)
    with pytest.raises(HTTPException): backtest(BacktestRequest(engine="momentum",prices=[100]*31),user,db)

def test_community_posts_comments_and_votes_persist(db,user):
    feed=posts(None,db); assert len(feed)>=4
    item=next(x for x in feed if "poll" in x)
    poll=item["poll"]
    result=vote(poll["id"],VoteRequest(option_index=1),user,db)
    assert result["my_vote"]==1
    c=comment(item["id"],CommentRequest(body="Consider rolling stability diagnostics too."),user,db)
    assert c["body"].startswith("Consider")
    created=create_post(PostRequest(title="Validation protocol question",body="How do you set embargo windows around overlapping labels?",topic="Methods"),user,db)
    assert created["author"]["id"]==user.id
    assert db.query(AuditLog).filter_by(user_id=user.id).count()>=1

def test_required_api_routes_are_registered():
    paths={route.path for route in app.routes}
    assert {"/auth/register","/auth/login","/health","/engines/{engine_name}/run","/jobs","/backtests","/risk/settings","/risk/position-check","/portfolio","/community/posts","/audit","/events"}.issubset(paths)
