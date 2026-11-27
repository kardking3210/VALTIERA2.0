import os
os.environ["DATABASE_URL"] = "sqlite:///./test_valtiera.db"

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request
from sqlalchemy.orm import Session
from app.auth import current_user, hash_password, issue_token, verify_password
from app.db import Base, SessionLocal, engine
from app.engines.core import ENGINES, calculate
from app.main import (app, initialize_storage, health, run, RunRequest,
                      RiskRequest, update_risk, risk_view, PositionRequest, ExposureCheckRequest, check_proposed_exposure, add_position,
                      portfolio, delete_position, BacktestRequest, backtest, backtest_history,
                      JobRequest, enqueue_research, research_job,
                      change_password, PasswordChangeRequest, intelligence_consensus, IntelligenceRequest, logout)
from app.models import User, EngineRun, Backtest as BacktestRow, AuditLog, RiskSettings
from app.worker import process_one


@pytest.fixture(scope="module")
def db():
    Base.metadata.drop_all(bind=engine)
    initialize_storage()
    session=SessionLocal()
    yield session
    session.close()

@pytest.fixture
def user(db):
    account=db.query(User).filter_by(email="researcher@test.local").first()
    if account is None:
        account=User(email="researcher@test.local",name="Test Researcher",password_hash=hash_password("A-strong-test-password"))
        db.add(account); db.flush(); db.add(RiskSettings(user_id=account.id)); db.commit(); db.refresh(account)
    return account

@pytest.fixture
def prices():
    t=np.arange(120,dtype=float)
    return (100*np.exp(.001*t+.02*np.sin(t/6))).tolist()


@pytest.mark.parametrize("engine_name",ENGINES)
def test_six_engines_return_structured_results(engine_name,prices):
    peer=np.array(prices)*np.exp(.01*np.sin(np.arange(len(prices))/9))
    data={"prices":prices,"peer_prices":peer.tolist(),"source":"test fixture","status":"historical"}
    if engine_name=="vwap": data["volumes"]=[100.]*len(prices)
    if engine_name=="volatility_breakout": data.update(highs=(np.asarray(prices)*1.01).tolist(),lows=(np.asarray(prices)*.99).tolist())
    if engine_name=="black_scholes": data.update(spot=100,strike=100,days_to_expiry=30,implied_volatility=.25)
    result=calculate(engine_name,data)
    assert result["engine"]==engine_name and result["observations"]==120 and result["metrics"]
    assert result["data_status"]=="historical"

def test_options_engine_has_bsm_baseline(prices):
    result=calculate("volatility_options",{"prices":prices,"spot":100,"strike":100,"days_to_expiry":30,"implied_volatility":.25})
    assert result["metrics"]["black_scholes_call_baseline"]>0
    assert 0<result["metrics"]["call_delta"]<1

def test_options_engine_inverts_market_price_and_returns_full_greeks(prices):
    source={"prices":prices,"spot":100,"strike":100,"days_to_expiry":45,"market_call_price":4.5}
    result=calculate("volatility_options",source)["metrics"]
    assert .01<result["implied_volatility"]<2
    assert result["implied_volatility_method"]=="Black-Scholes call price inversion"
    assert 0<result["gamma"] and result["vega_per_1pct"]>0
    assert len(result["scenario_call_prices"])==3

def test_momentum_mean_reversion_and_hmm_metrics_are_real(prices):
    momentum=calculate("momentum",{"prices":prices})["metrics"]
    rng=np.random.default_rng(7); mr=[100.]
    for _ in range(119): mr.append(mr[-1]+.15*(105-mr[-1])+rng.normal(0,.25))
    mean=calculate("mean_reversion",{"prices":mr})["metrics"]
    regime=calculate("market_regime",{"prices":prices})["metrics"]
    assert momentum["fast_moving_average"]>0 and 0<=momentum["trend_persistence"]<=1
    assert len(mean["bands"])==4
    assert mean["estimated_half_life_observations"] is not None
    assert regime["method"]=="two_state_gaussian_hmm_on_returns"
    assert abs(sum(regime["state_posterior"].values())-1)<1e-6

def test_kalman_pairs_and_cross_asset_factor_metrics(prices):
    x=np.asarray(prices); peer=(80*np.exp(.7*np.log(x/100)+.01*np.sin(np.arange(len(x))/4))).tolist()
    pair=calculate("statistical_arbitrage",{"prices":prices,"peer_prices":peer})["metrics"]
    relative=calculate("cross_asset",{"prices":prices,"peer_prices":peer,"yield_a":.04,"yield_b":.035})["metrics"]
    assert np.isfinite(pair["kalman_hedge_ratio"])
    assert relative["factor_beta"] is not None
    assert relative["yield_spread_bps"]==pytest.approx(50)

def test_engine_input_validation(prices):
    for series in ([1]*29,[1]*29+[0],[1]*30):
        with pytest.raises(ValueError): calculate("momentum",{"prices":series})
    with pytest.raises(ValueError,match="align"):
        calculate("statistical_arbitrage",{"prices":prices,"peer_prices":prices[:-1]})

def test_user_data_cannot_claim_live_provenance(prices):
    result=calculate("momentum",{"prices":prices,"source":"licensed exchange feed","status":"live"})
    assert result["input_source"]=="caller_supplied" and result["data_status"]=="historical"

def test_auth_password_and_signed_session(db,user):
    hashed=hash_password("A-strong-test-password")
    assert verify_password("A-strong-test-password",hashed)
    assert not verify_password("wrong-password",hashed)
    token=issue_token(user)
    assert current_user(HTTPAuthorizationCredentials(scheme="Bearer",credentials=token),db).id==user.id
    broken=token[:-2]+"xx"
    with pytest.raises(HTTPException): current_user(HTTPAuthorizationCredentials(scheme="Bearer",credentials=broken),db)
    logout(user,HTTPAuthorizationCredentials(scheme="Bearer",credentials=token),db)
    with pytest.raises(HTTPException): current_user(HTTPAuthorizationCredentials(scheme="Bearer",credentials=token),db)

def test_health_and_market_feed_is_not_configured(db):
    assert health(db)["database"]=="OPERATIONAL"
    assert "market_data" not in health(db)

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

def test_personalized_risk_limits_include_asset_allocation_and_leverage(db,user):
    req=RiskRequest(max_position_pct=50,max_drawdown_pct=20,daily_loss_limit_pct=3,max_gross_exposure_pct=200,portfolio_nav=10000,risk_profile="conservative",max_leverage_pct=80,asset_class_limits={"equity":40},volatility_tolerance="low",liquidity_floor_usd=100000,investment_horizon_months=36)
    saved=update_risk(req,user,db)
    assert saved["risk_profile"]=="conservative" and saved["max_leverage_pct"]==80
    add_position(PositionRequest(symbol="ALPHA",asset_class="equity",quantity=10,average_cost=100,current_price=100),user,db)
    assessment=risk_view(db.query(RiskSettings).filter_by(user_id=user.id).one())
    assert assessment["asset_class_limits"]["equity"]==40
    check=check_proposed_exposure(ExposureCheckRequest(market_value=5000,asset_class="equity"),user,db)
    assert check["eligible_for_review"] is False
    assert any("asset-class" in w for w in check["warnings"])

def test_backtest_is_lagged_and_saved(db,user,prices):
    req=BacktestRequest(engine="momentum",prices=prices,benchmark_prices=prices,initial_capital=10000,fee_bps=5,slippage_bps=2,position_size=.5)
    result=backtest(req,user,db)
    assert result["data_status"]=="historical_simulation"
    assert result["input_provenance"]["source"]=="CALLER_SUPPLIED"
    assert len(result["input_provenance"]["series_sha256"])==64
    assert result["exposure"][:20]==[0]*20
    assert "Not live performance" in result["disclosure"]
    assert "out_of_sample" in result and "risk_check" in result
    assert result["benchmark"]["relative_return_pct"] is not None
    assert result["walk_forward"]["folds"] and result["sortino_ratio"] is not None
    assert result["cost_assumptions_bps"]["slippage"]==2 and result["position_size_fraction"]==.5
    assert len(backtest_history(user,db))==1
    assert db.query(BacktestRow).filter_by(user_id=user.id).count()==1
    with pytest.raises(HTTPException): backtest(BacktestRequest(engine="statistical_arbitrage",prices=prices),user,db)
    with pytest.raises(HTTPException): backtest(BacktestRequest(engine="momentum",prices=[100]*31),user,db)

def test_backtest_saves_caller_supplied_input_fingerprint(db,user,prices):
    result=backtest(BacktestRequest(engine="momentum",prices=prices),user,db)
    saved=next(row for row in backtest_history(user,db) if row["id"]==result["id"])["result"]["input_provenance"]
    assert saved["source"]=="CALLER_SUPPLIED"
    assert saved["observations"]==len(prices) and len(saved["series_sha256"])==64

def test_password_change_is_audited(db,user):
    changed=change_password(PasswordChangeRequest(current_password="A-strong-test-password",new_password="Another-strong-password-2026"),user,db)
    assert changed["changed"] is True
    assert verify_password("Another-strong-password-2026",user.password_hash)
    assert db.query(AuditLog).filter_by(user_id=user.id).count()>=1

def test_central_intelligence_persists_independent_outputs(db,user,prices):
    peer=(np.asarray(prices)*np.exp(.01*np.sin(np.arange(len(prices))/9))).tolist()
    result=intelligence_consensus(IntelligenceRequest(data={"prices":prices,"peer_prices":peer,"volumes":[100.]*len(prices),"highs":(np.asarray(prices)*1.01).tolist(),"lows":(np.asarray(prices)*.99).tolist(),"spot":100,"strike":100,"days_to_expiry":30,"implied_volatility":.25,"status":"historical"}),user,db)
    assert len(result["models"])==len(ENGINES)
    assert all(x.get("execution_id") for x in result["models"])
    assert "not a probability" in result["summary"]["interpretation"].lower()

def test_required_api_routes_are_registered():
    paths={route.path for route in app.routes}
    assert {"/auth/register","/auth/login","/auth/password","/health","/engines/{engine_name}/run","/intelligence/consensus","/jobs","/backtests","/risk/settings","/risk/position-check","/portfolio","/audit","/events"}.issubset(paths)
