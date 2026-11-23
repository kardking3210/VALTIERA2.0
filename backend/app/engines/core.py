"""Deterministic, input-driven research calculations; no data is fabricated here."""
from datetime import datetime, timezone
import numpy as np
from scipy.stats import pearsonr, spearmanr
from scipy.stats import linregress, norm
from statsmodels.tsa.stattools import coint
import math

VERSION = "0.1.0"
ENGINES = ("statistical_arbitrage", "momentum", "mean_reversion", "volatility_options", "cross_asset", "market_regime")

def _series(values, name):
    a=np.asarray(values,dtype=float)
    if a.ndim != 1 or len(a)<30 or not np.isfinite(a).all() or (name.endswith("prices") and ((a<=0).any() or np.ptp(a)==0)):
        raise ValueError(f"{name} requires at least 30 finite {'positive ' if name.endswith('prices') else ''}observations")
    return a

def _window(value, default, length):
    window=int(value if value is not None else default)
    if window<2: raise ValueError("window/lookback must be at least 2")
    return min(window,length)

def calculate(engine: str, data: dict, params: dict|None=None):
    p=params or {}; x=_series(data.get("prices",[]),"prices"); returns=np.diff(np.log(x)); result={}
    if engine=="statistical_arbitrage":
        y=_series(data.get("peer_prices",[]),"peer_prices")
        if len(y)!=len(x): raise ValueError("prices and peer_prices must align")
        corr=float(pearsonr(x/x.max(),y/y.max()).statistic); rank=float(spearmanr(x,y).statistic); logs=np.log(x); peer=np.log(y); fit=linregress(peer,logs); spread=logs-(fit.intercept+fit.slope*peer); w=_window(p.get("window"),60,len(spread)); sd=float(spread[-w:].std(ddof=1)); z=float((spread[-1]-spread[-w:].mean())/sd) if sd else 0.
        eg_t,eg_p,_=coint(logs,peer); hedge=fit.slope
        result={"pearson":corr,"spearman":rank,"spread":float(spread[-1]),"z_score":z,"cointegration_t_statistic":float(eg_t),"cointegration_p_value":float(eg_p),"hedge_ratio":float(hedge),"signal":"monitor" if abs(z)>=2 and eg_p<.05 else "none"}
    elif engine=="momentum":
        w=_window(p.get("lookback"),20,len(returns)); vol=float(returns[-w:].std(ddof=1)); mom=float(np.log(x[-1]/x[-w-1])); result={"momentum":mom,"annualized_volatility":vol*np.sqrt(252),"vol_adjusted_score":mom/(vol*np.sqrt(w)) if vol else 0.,"direction":"up" if mom>0 else "down" if mom<0 else "flat"}
    elif engine=="mean_reversion":
        w=_window(p.get("window"),30,len(x)); avg=float(x[-w:].mean()); sd=float(x[-w:].std(ddof=1)); z=float((x[-1]-avg)/sd) if sd else 0.
        lag=np.diff(x[-w:]); level=x[-w:-1]; slope=linregress(level,lag).slope if np.std(level)>0 else 0.; half_life=float(-math.log(2)/slope) if slope<0 else None
        result={"rolling_mean":avg,"standard_deviation":sd,"z_score":z,"estimated_half_life_observations":half_life,"signal":"watch_reversion" if abs(z)>=2 and half_life is not None else "none"}
    elif engine=="volatility_options":
        w=_window(p.get("window"),20,len(returns)); rv=float(returns[-w:].std(ddof=1)*np.sqrt(252)); iv=data.get("implied_volatility")
        if iv is not None and (not np.isfinite(float(iv)) or float(iv)<=0): raise ValueError("implied_volatility must be positive and finite")
        result={"realized_volatility":rv,"implied_volatility":float(iv) if iv is not None else None,"iv_rv_spread":float(iv)-rv if iv is not None else None,"status":"calculated_without_options_feed" if iv is None else "calculated"}
        spot=data.get("spot"); strike=data.get("strike"); rate=float(p.get("risk_free_rate",0.)); days=data.get("days_to_expiry")
        if all(v is not None for v in (spot,strike,iv,days)):
            spot=float(spot); strike=float(strike); vol=float(iv); t=float(days)/365
            if min(spot,strike,vol,t)<=0: raise ValueError("spot, strike, implied_volatility, and days_to_expiry must be positive")
            d1=(math.log(spot/strike)+(rate+.5*vol*vol)*t)/(vol*math.sqrt(t)); d2=d1-vol*math.sqrt(t)
            call=spot*norm.cdf(d1)-strike*math.exp(-rate*t)*norm.cdf(d2)
            result["black_scholes_call_baseline"]=float(call)
            result["call_delta"]=float(norm.cdf(d1)); result["gamma"]=float(norm.pdf(d1)/(spot*vol*math.sqrt(t)))
            result["vega_per_1pct"]=float(spot*norm.pdf(d1)*math.sqrt(t)/100)
            result["theta_per_calendar_day"]=float((-spot*norm.pdf(d1)*vol/(2*math.sqrt(t))-rate*strike*math.exp(-rate*t)*norm.cdf(d2))/365)
    elif engine=="cross_asset":
        y=_series(data.get("peer_prices",[]),"peer_prices")
        if len(y)!=len(x): raise ValueError("prices and peer_prices must align")
        rx=np.diff(np.log(x)); ry=np.diff(np.log(y)); corr=float(pearsonr(rx,ry).statistic) if np.std(rx)>0 and np.std(ry)>0 else None
        result={"correlation":corr,"correlation_status":"calculated" if corr is not None else "undefined_constant_returns","relative_return":float(np.log(x[-1]/x[0])-np.log(y[-1]/y[0])),"basis":float(x[-1]-y[-1])}
    elif engine=="market_regime":
        w=_window(p.get("window"),20,len(returns)); recent=float(np.std(returns[-w:],ddof=1)*np.sqrt(252)); hist=float(np.std(returns,ddof=1)*np.sqrt(252)); result={"annualized_volatility":recent,"historical_volatility":hist,"regime":"high_volatility" if recent>hist*1.5 else "normal_volatility","method":"volatility_threshold"}
    else: raise ValueError("Unknown engine")
    return {"engine":engine,"model_version":VERSION,"executed_at":datetime.now(timezone.utc).isoformat(),"observations":len(x),"input_source":data.get("source","caller_supplied"),"data_status":data.get("status","historical"),"interpretation":"Research calculation only; not an execution signal or investment recommendation.","metrics":result}
