"""Deterministic input-driven research calculations; never fabricates market observations."""
from datetime import datetime, timezone
import math
import numpy as np
from scipy.optimize import brentq, minimize
from scipy.stats import linregress, norm, pearsonr, spearmanr
from statsmodels.tsa.stattools import coint
from statsmodels.tsa.arima.model import ARIMA

VERSION = "0.4.0"
ENGINES = ("arima", "garch", "heston", "sabr", "kalman_filter", "ornstein_uhlenbeck", "moving_average", "rsi", "macd", "bollinger", "monte_carlo", "black_scholes", "pairs_trading", "gradient_boosting", "vwap", "statistical_arbitrage", "mean_reversion", "momentum", "volatility_breakout", "market_regime")
LEGACY_ENGINES = ("volatility_options", "cross_asset", "market_regime")

def _series(values, name):
    a=np.asarray(values,dtype=float)
    if a.ndim != 1 or len(a)<30 or not np.isfinite(a).all() or (name.endswith("prices") and ((a<=0).any() or np.ptp(a)==0)):
        raise ValueError(f"{name} requires at least 30 finite {'positive ' if name.endswith('prices') else ''}observations")
    return a

def _window(value, default, length):
    window=int(value if value is not None else default)
    if window<2: raise ValueError("window/lookback must be at least 2")
    return min(window,length)

def _exponential(values, span):
    a=np.asarray(values,dtype=float); alpha=2/(span+1); out=np.empty(len(a)); out[0]=a[0]
    for i in range(1,len(a)): out[i]=alpha*a[i]+(1-alpha)*out[i-1]
    return out

def _wilder_rsi(prices, window):
    changes=np.diff(np.asarray(prices,dtype=float)); gains=np.maximum(changes,0); losses=np.maximum(-changes,0)
    out=np.full(len(prices),np.nan)
    if len(changes)<window: return out
    avg_gain=float(gains[:window].mean()); avg_loss=float(losses[:window].mean())
    out[window]=100. if avg_loss==0 and avg_gain>0 else 50. if avg_loss==0 else 100-100/(1+avg_gain/avg_loss)
    for i in range(window+1,len(prices)):
        avg_gain=(avg_gain*(window-1)+gains[i-1])/window; avg_loss=(avg_loss*(window-1)+losses[i-1])/window
        out[i]=100. if avg_loss==0 and avg_gain>0 else 50. if avg_loss==0 else 100-100/(1+avg_gain/avg_loss)
    return out

def _garch_fit(returns):
    r=np.asarray(returns,dtype=float)*100
    if len(r)<30 or np.std(r)==0: raise ValueError("garch requires at least 30 non-constant returns")
    sample=float(np.var(r,ddof=1))
    def objective(params):
        omega,alpha,beta=params
        variance=np.empty(len(r)); variance[0]=sample
        for i in range(1,len(r)): variance[i]=max(omega+alpha*r[i-1]**2+beta*variance[i-1],1e-12)
        return .5*float(np.sum(np.log(variance)+r*r/variance))
    fit=minimize(objective,[sample*.05,.08,.87],method="SLSQP",bounds=[(1e-10,None),(1e-6,.999),(1e-6,.999)],constraints=[{"type":"ineq","fun":lambda p:.999-p[1]-p[2]}],options={"maxiter":500,"ftol":1e-10})
    if not fit.success: raise ValueError("GARCH(1,1) maximum likelihood fit did not converge")
    omega,alpha,beta=map(float,fit.x); variance=np.empty(len(r)); variance[0]=sample
    for i in range(1,len(r)): variance[i]=omega+alpha*r[i-1]**2+beta*variance[i-1]
    forecast=omega+alpha*r[-1]**2+beta*variance[-1]
    return {"omega_percent_squared":omega,"alpha":alpha,"beta":beta,"persistence":alpha+beta,"conditional_volatility_pct":float(np.sqrt(variance[-1])*np.sqrt(252)),"conditional_volatility_series_pct":(np.sqrt(variance)*np.sqrt(252)).tolist(),"next_observation_volatility_pct":float(np.sqrt(forecast)),"annualized_next_volatility_pct":float(np.sqrt(forecast*252)),"log_likelihood":float(-fit.fun),"optimizer_success":bool(fit.success)}

def _bsm(spot, strike, t, rate, vol):
    d1=(math.log(spot/strike)+(rate+.5*vol*vol)*t)/(vol*math.sqrt(t)); d2=d1-vol*math.sqrt(t)
    discount=math.exp(-rate*t); pdf=norm.pdf(d1)
    return {"call_price":spot*norm.cdf(d1)-strike*discount*norm.cdf(d2),"put_price":strike*discount*norm.cdf(-d2)-spot*norm.cdf(-d1),"delta":float(norm.cdf(d1)),"put_delta":float(norm.cdf(d1)-1),"gamma":float(pdf/(spot*vol*math.sqrt(t))),"vega_per_1pct":float(spot*pdf*math.sqrt(t)/100),"theta_call_per_day":float((-spot*pdf*vol/(2*math.sqrt(t))-rate*strike*discount*norm.cdf(d2))/365),"theta_put_per_day":float((-spot*pdf*vol/(2*math.sqrt(t))+rate*strike*discount*norm.cdf(-d2))/365)}

def _kalman_hedge(y, x, delta=1e-4, observation=1e-3):
    """Scalar random-walk hedge ratio Kalman filter; returns in-sample filtered estimates."""
    beta=0.; covariance=1.; out=[]
    for obs, reg in zip(y, x):
        covariance += delta
        variance=reg*reg*covariance+observation
        gain=covariance*reg/variance if variance else 0.
        beta += gain*(obs-reg*beta)
        covariance *= 1-gain*reg
        out.append(float(beta))
    return np.asarray(out)

def _two_state_hmm(returns, iterations=40, return_history=False):
    """Small Gaussian two-state HMM fitted by deterministic Baum-Welch EM."""
    obs=np.asarray(returns,dtype=float)
    center=float(np.median(obs)); scale=max(float(np.std(obs)),1e-8)
    means=np.array([center-scale*.5,center+scale*.5]); variances=np.array([scale**2*.5,scale**2*2.])
    transition=np.array([[.94,.06],[.06,.94]]); initial=np.array([.5,.5])
    for _ in range(iterations):
        emissions=np.column_stack([np.maximum(norm.pdf(obs,means[k],math.sqrt(max(variances[k],1e-14))),1e-300) for k in range(2)])
        alpha=np.zeros_like(emissions); alpha[0]=initial*emissions[0]; alpha[0]/=alpha[0].sum()
        for t in range(1,len(obs)):
            alpha[t]=(alpha[t-1]@transition)*emissions[t]; total=alpha[t].sum(); alpha[t]/=total if total else 1
        beta=np.ones_like(emissions)
        for t in range(len(obs)-2,-1,-1):
            beta[t]=transition@(emissions[t+1]*beta[t+1]); total=beta[t].sum(); beta[t]/=total if total else 1
        gamma=alpha*beta; gamma/=np.maximum(gamma.sum(axis=1,keepdims=True),1e-300)
        xi=np.zeros((2,2))
        for t in range(len(obs)-1):
            q=alpha[t,:,None]*transition*(emissions[t+1]*beta[t+1])[None,:]; xi+=q/max(q.sum(),1e-300)
        initial=gamma[0]; transition=xi/np.maximum(xi.sum(axis=1,keepdims=True),1e-12)
        for k in range(2):
            weights=gamma[:,k]; total=max(weights.sum(),1e-12); means[k]=np.sum(weights*obs)/total; variances[k]=max(np.sum(weights*(obs-means[k])**2)/total,1e-12)
    return (gamma,transition,means,variances) if return_history else (gamma[-1],transition,means,variances)

def _boosted_stumps(features, targets, iterations=60, learning_rate=.05):
    """Small deterministic squared-error gradient booster using depth-one regression trees."""
    x=np.asarray(features,dtype=float); y=np.asarray(targets,dtype=float)
    baseline=float(y.mean()); prediction=np.full(len(y),baseline); stumps=[]
    for _ in range(iterations):
        residual=y-prediction; best=None
        for column in range(x.shape[1]):
            values=np.unique(x[:,column])
            if len(values)<2: continue
            candidates=np.unique(np.quantile(values,np.linspace(.1,.9,min(9,len(values)-1))))
            for threshold in candidates:
                left=x[:,column]<=threshold; right=~left
                if left.sum()<3 or right.sum()<3: continue
                lv=float(residual[left].mean()); rv=float(residual[right].mean())
                error=float(np.square(residual[left]-lv).sum()+np.square(residual[right]-rv).sum())
                if best is None or error<best[0]: best=(error,column,float(threshold),lv,rv)
        if best is None: break
        _,column,threshold,left_value,right_value=best
        prediction += learning_rate*np.where(x[:,column]<=threshold,left_value,right_value)
        stumps.append((column,threshold,left_value,right_value))
    return baseline,stumps

def _boosted_predict(features, baseline, stumps, learning_rate=.05):
    x=np.asarray(features,dtype=float); output=np.full(len(x),baseline)
    for column,threshold,left_value,right_value in stumps:
        output += learning_rate*np.where(x[:,column]<=threshold,left_value,right_value)
    return output

def calculate(engine: str, data: dict, params: dict|None=None):
    p=params or {}; x=_series(data.get("prices",[]),"prices"); returns=np.diff(np.log(x)); result={}
    if engine=="heston":
        # Full-truncation Euler Heston scenarios. Parameters are user scenarios, not a fitted options calibration.
        kappa=float(p.get("kappa",2.0)); theta=float(p.get("theta",max(float(np.var(returns))*252,1e-6))); xi=float(p.get("xi",0.5)); rho=float(p.get("rho",-0.7)); v0=float(p.get("v0",max(float(np.var(returns))*252,1e-6)))
        horizon=int(p.get("horizon",30)); paths=int(p.get("paths",500)); seed=int(p.get("seed",7))
        if kappa<=0 or theta<=0 or xi<0 or not -1<=rho<=1 or v0<=0: raise ValueError("Heston requires kappa, theta and v0 > 0, xi >= 0, and rho between -1 and 1")
        if not 1<=horizon<=365 or not 100<=paths<=10000: raise ValueError("Heston horizon must be 1-365 observations and paths 100-10000")
        dt=1/252; rng=np.random.default_rng(seed); variance=np.full(paths,v0); spot=np.full(paths,float(x[-1])); vol_steps=[]; price_steps=[]
        for _ in range(horizon):
            z1=rng.standard_normal(paths); z2=rho*z1+math.sqrt(max(1-rho*rho,0))*rng.standard_normal(paths)
            v_pos=np.maximum(variance,0); variance=np.maximum(variance+kappa*(theta-v_pos)*dt+xi*np.sqrt(v_pos*dt)*z2,0)
            spot=spot*np.exp(-.5*v_pos*dt+np.sqrt(v_pos*dt)*z1); vol_steps.append(np.sqrt(variance*252)); price_steps.append(spot.copy())
        vol_steps=np.asarray(vol_steps); price_steps=np.asarray(price_steps)
        result={"method":"Heston full-truncation Euler Monte Carlo; scenario parameters are not calibrated","calibration_status":"NOT_CALIBRATED","current_annualized_volatility_pct":float(np.sqrt(v0)*100),"long_run_annualized_volatility_pct":float(np.sqrt(theta)*100),"mean_reversion_speed":kappa,"volatility_of_variance":xi,"return_variance_correlation":rho,"forecast_horizon_observations":horizon,"scenario_paths":paths,"forecast_volatility_median_pct":(np.median(vol_steps,axis=1)*100).tolist(),"forecast_volatility_p05_pct":(np.quantile(vol_steps,.05,axis=1)*100).tolist(),"forecast_volatility_p95_pct":(np.quantile(vol_steps,.95,axis=1)*100).tolist(),"terminal_price_median":float(np.median(price_steps[-1])),"terminal_price_p05":float(np.quantile(price_steps[-1],.05)),"terminal_price_p95":float(np.quantile(price_steps[-1],.95)),"seed":seed,"interpretation":"Stochastic volatility scenario only. Price paths are not directional forecasts; calibration to option prices was not performed."}
    elif engine=="sabr":
        forward=float(data.get("forward",x[-1])); expiry=float(p.get("expiry_years",data.get("expiry_years",0.5))); alpha=float(p.get("alpha",0.3)); beta=float(p.get("beta",0.5)); rho=float(p.get("rho",-0.2)); nu=float(p.get("nu",0.5)); count=int(p.get("strikes",21)); width=float(p.get("strike_width",0.3))
        if forward<=0 or expiry<=0 or alpha<=0 or nu<0 or not 0<=beta<=1 or not -0.999<rho<0.999: raise ValueError("SABR requires positive forward, expiry and alpha; beta 0-1, nu >= 0 and rho strictly between -0.999 and 0.999")
        if not 5<=count<=101 or not 0<width<=1: raise ValueError("SABR strike count must be 5-101 and strike width between 0 and 1")
        strikes=np.linspace(forward*(1-width),forward*(1+width),count); vols=[]
        for strike in strikes:
            if abs(forward-strike)<1e-10:
                fk=forward**(1-beta); correction=(1-beta)**2*alpha**2/(24*fk**2)+rho*beta*nu*alpha/(4*fk)+(2-3*rho**2)*nu**2/24
                vol=alpha/fk*(1+correction*expiry)
            else:
                fk=(forward*strike)**((1-beta)/2); log_fk=math.log(forward/strike); z=(nu/alpha)*fk*log_fk; radicand=max(1-2*rho*z+z*z,1e-15); xz=math.log((math.sqrt(radicand)+z-rho)/(1-rho)); ratio=xz/z if abs(z)>1e-8 else 1-rho*z/2+(2-3*rho*rho)*z*z/12
                correction=(1-beta)**2*alpha**2/(24*fk*fk)+rho*beta*nu*alpha/(4*fk)+(2-3*rho*rho)*nu*nu/24
                denom=fk*(1+(1-beta)**2*log_fk**2/24+(1-beta)**4*log_fk**4/1920)
                vol=alpha/denom*ratio*(1+correction*expiry)
            if not np.isfinite(vol) or vol<=0: raise ValueError("SABR produced a non-positive implied volatility for this parameter set")
            vols.append(vol*100)
        result={"method":"Hagan SABR lognormal implied-volatility approximation","calibration_status":"NOT_CALIBRATED_NO_OPTIONS_FEED","forward":forward,"forward_source":"Latest historical close used as a zero-carry proxy; replace with an options-market forward for research use","expiry_years":expiry,"strikes":strikes.tolist(),"sabr_implied_volatility_pct":vols,"alpha":alpha,"beta":beta,"rho":rho,"nu":nu,"observed_market_implied_volatility":None,"calibration_error":None,"interpretation":"The smile is a parameter scenario, not observed market data. No options feed is configured, so market calibration and fit statistics are unavailable."}
    elif engine=="arima":
        if len(x)<60: raise ValueError("arima requires at least 60 price observations")
        order=p.get("order",[1,1,1])
        if not isinstance(order,(list,tuple)) or len(order)!=3: raise ValueError("order must contain p, d, q")
        try: arima_order=tuple(int(v) for v in order)
        except (TypeError,ValueError): raise ValueError("ARIMA order values must be integers") from None
        if min(arima_order)<0 or max(arima_order)>5 or sum(arima_order)>8: raise ValueError("ARIMA order values must be 0-5 with total order at most 8")
        steps=int(p.get("steps",1))
        if not 1<=steps<=30: raise ValueError("steps must be between 1 and 30")
        try:
            fitted=ARIMA(np.log(x),order=arima_order,enforce_stationarity=False,enforce_invertibility=False).fit()
            forecast=fitted.get_forecast(steps=steps); means=np.asarray(forecast.predicted_mean,dtype=float); intervals=np.asarray(forecast.conf_int(alpha=.05),dtype=float)
        except (ValueError, np.linalg.LinAlgError) as exc: raise ValueError(f"ARIMA fit failed: {str(exc)[:160]}") from None
        result={"order":list(arima_order),"forecast_steps":steps,"forecast_price":float(np.exp(means[-1])),"forecast_return_pct":float(np.expm1(means[-1]-np.log(x[-1]))*100),"confidence_95_price_interval":[float(np.exp(intervals[-1,0])),float(np.exp(intervals[-1,1]))],"aic":float(fitted.aic),"converged":bool(getattr(fitted,"mle_retvals",{}).get("converged",True)),"signal_direction":"long" if means[-1]>np.log(x[-1]) else "short" if means[-1]<np.log(x[-1]) else "neutral","method":"ARIMA fit to log price levels; interval is conditional on fitted model assumptions."}
    elif engine=="kalman_filter":
        logs=np.log(x); q=float(p.get("process_variance",1e-5)); r=float(p.get("observation_variance",1e-3)); threshold=float(p.get("signal_threshold",2.))
        if not np.isfinite(q) or not np.isfinite(r) or q<=0 or r<=0 or threshold<=0: raise ValueError("Kalman variances and signal threshold must be positive finite values")
        state=float(logs[0]); variance=max(float(np.var(logs)),r); latest_z=0.
        for observation in logs[1:]:
            prior_variance=variance+q; innovation=float(observation-state); innovation_variance=prior_variance+r; gain=prior_variance/innovation_variance; state += gain*innovation; variance=(1-gain)*prior_variance; latest_z=innovation/math.sqrt(innovation_variance)
        result={"filtered_level_log":state,"filtered_price":float(math.exp(state)),"state_standard_error_log":float(math.sqrt(variance)),"latest_innovation_z_score":latest_z,"process_variance":q,"observation_variance":r,"signal_direction":"short" if latest_z>=threshold else "long" if latest_z<=-threshold else "neutral","method":"Scalar local-level Kalman filter on log prices; current observation is incorporated in the filtered level."}
    elif engine=="ornstein_uhlenbeck":
        logs=np.log(x); fit=linregress(logs[:-1],np.diff(logs)); slope=float(fit.slope); intercept=float(fit.intercept); phi=1+slope
        if slope<0 and 0<phi<1:
            speed=-math.log(phi); equilibrium_log=-intercept/slope; half_life=math.log(2)/speed; residual=np.diff(logs)-(intercept+slope*logs[:-1]); equilibrium=float(math.exp(equilibrium_log)); current_z=float((logs[-1]-equilibrium_log)/np.std(residual,ddof=1)) if np.std(residual,ddof=1)>0 else 0.
        else: speed=None; equilibrium_log=None; half_life=None; equilibrium=None; current_z=None
        result={"discrete_phi":phi,"mean_reversion_speed_per_observation":speed,"equilibrium_price":equilibrium,"half_life_observations":half_life,"current_equilibrium_z_score":current_z,"fit_r_squared":float(fit.rvalue**2),"stationarity_check":"mean_reverting_discrete_fit" if speed is not None else "not_mean_reverting_under_fitted_discrete_specification","signal_direction":"long" if current_z is not None and current_z<=-2 else "short" if current_z is not None and current_z>=2 else "neutral","method":"OLS fit of log-price change on lagged log price; mean-reversion parameters are reported only for a stable discrete fit."}
    elif engine=="gradient_boosting":
        if len(returns)<65: raise ValueError("gradient_boosting requires at least 66 price observations")
        features=np.asarray([returns[i-5:i][::-1] for i in range(5,len(returns))]); target=returns[5:]
        split=int(len(target)*.8)
        if split<30 or len(target)-split<5: raise ValueError("gradient_boosting requires at least 30 training and 5 test examples")
        learning_rate=float(p.get("learning_rate",.05)); iterations=int(p.get("estimators",60))
        if not 0<learning_rate<=.5 or not 5<=iterations<=300: raise ValueError("learning_rate must be in (0, 0.5] and estimators 5-300")
        baseline,stumps=_boosted_stumps(features[:split],target[:split],iterations,learning_rate); test_prediction=_boosted_predict(features[split:],baseline,stumps,learning_rate); test_error=test_prediction-target[split:]
        full_baseline,full_stumps=_boosted_stumps(features,target,iterations,learning_rate); next_feature=returns[-5:][::-1].reshape(1,-1); next_return=float(_boosted_predict(next_feature,full_baseline,full_stumps,learning_rate)[0]); direction="long" if next_return>0 else "short" if next_return<0 else "neutral"
        importance=np.zeros(features.shape[1]);
        for column,_,_,_ in full_stumps: importance[column]+=1
        result={"validation_type":"chronological_holdout","training_observations":split,"test_observations":len(target)-split,"estimators_used":len(full_stumps),"learning_rate":learning_rate,"out_of_sample_rmse":float(np.sqrt(np.mean(test_error**2))),"out_of_sample_mae":float(np.mean(np.abs(test_error))),"out_of_sample_directional_accuracy_pct":float(np.mean(np.sign(test_prediction)==np.sign(target[split:]))*100),"holdout_actual_return_pct":(target[split:]*100).tolist(),"holdout_predicted_return_pct":(test_prediction*100).tolist(),"feature_importance_lag_1_to_5":(importance/max(importance.sum(),1)).tolist(),"next_return_estimate_pct":next_return*100,"next_price_estimate":float(x[-1]*math.exp(next_return)),"signal_direction":direction,"method":"Deterministic squared-error gradient boosting with depth-one regression stumps on five lagged log returns; reports chronological holdout error."}
    elif engine=="moving_average":
        fast=_window(p.get("fast_window"),20,len(x)); slow=_window(p.get("slow_window"),50,len(x))
        if fast>=slow: raise ValueError("fast_window must be smaller than slow_window")
        method=str(p.get("average_type","SMA")).upper()
        if method not in ("SMA","EMA"): raise ValueError("average_type must be SMA or EMA")
        fast_series=np.convolve(x,np.ones(fast)/fast,mode="full")[:len(x)]
        slow_series=np.convolve(x,np.ones(slow)/slow,mode="full")[:len(x)]
        if method=="EMA": fast_series=_exponential(x,fast); slow_series=_exponential(x,slow)
        result={"average_type":method,"fast_window":fast,"slow_window":slow,"fast_average":float(fast_series[-1]),"slow_average":float(slow_series[-1]),"signal_direction":"long" if fast_series[-1]>slow_series[-1] else "short" if fast_series[-1]<slow_series[-1] else "neutral","signal":"fast_above_slow" if fast_series[-1]>slow_series[-1] else "fast_below_slow" if fast_series[-1]<slow_series[-1] else "averages_equal"}
    elif engine=="rsi":
        w=_window(p.get("window"),14,len(x)); rsi=_wilder_rsi(x,w); current=float(rsi[-1]); lower=float(p.get("oversold",30)); upper=float(p.get("overbought",70))
        if not 0<=lower<upper<=100: raise ValueError("RSI thresholds must satisfy 0 <= oversold < overbought <= 100")
        result={"window":w,"rsi":current,"oversold_threshold":lower,"overbought_threshold":upper,"signal":"oversold" if current<=lower else "overbought" if current>=upper else "neutral_range","signal_direction":"long" if current<=lower else "short" if current>=upper else "neutral"}
    elif engine=="macd":
        fast=_window(p.get("fast_window"),12,len(x)); slow=_window(p.get("slow_window"),26,len(x)); signal_window=_window(p.get("signal_window"),9,len(x))
        if fast>=slow: raise ValueError("fast_window must be smaller than slow_window")
        macd_series=_exponential(x,fast)-_exponential(x,slow); signal_series=_exponential(macd_series,signal_window); hist=macd_series-signal_series
        result={"fast_window":fast,"slow_window":slow,"signal_window":signal_window,"macd":float(macd_series[-1]),"signal_line":float(signal_series[-1]),"histogram":float(hist[-1]),"signal_direction":"long" if hist[-1]>0 else "short" if hist[-1]<0 else "neutral"}
    elif engine=="bollinger":
        w=_window(p.get("window"),20,len(x)); deviations=float(p.get("deviations",2)); avg=float(x[-w:].mean()); sd=float(x[-w:].std(ddof=1)); z=float((x[-1]-avg)/sd) if sd else 0.
        if deviations<=0: raise ValueError("deviations must be positive")
        result={"window":w,"deviations":deviations,"rolling_mean":avg,"standard_deviation":sd,"z_score":z,"upper_band":avg+deviations*sd,"lower_band":avg-deviations*sd,"signal_direction":"long" if z<=-deviations else "short" if z>=deviations else "neutral","signal":"below_lower_band" if z<=-deviations else "above_upper_band" if z>=deviations else "within_bands"}
    elif engine=="vwap":
        volumes=np.asarray(data.get("volumes",[]),dtype=float)
        if volumes.ndim!=1 or len(volumes)!=len(x) or not np.isfinite(volumes).all() or (volumes<0).any() or volumes.sum()<=0: raise ValueError("volumes must be finite, non-negative, aligned with prices, and have positive total volume")
        w=_window(p.get("window"),len(x),len(x)); weighted=float(np.sum(x[-w:]*volumes[-w:])); total=float(volumes[-w:].sum())
        if total<=0: raise ValueError("selected window has no positive volume")
        vwap=weighted/total
        result={"window":w,"vwap":vwap,"last_price":float(x[-1]),"distance_pct":float((x[-1]/vwap-1)*100),"total_volume":total,"signal_direction":"long" if x[-1]>vwap else "short" if x[-1]<vwap else "neutral","signal":"price_above_vwap" if x[-1]>vwap else "price_below_vwap" if x[-1]<vwap else "at_vwap"}
    elif engine=="statistical_arbitrage":
        y=_series(data.get("peer_prices",[]),"peer_prices")
        if len(y)!=len(x): raise ValueError("prices and peer_prices must align")
        logs=np.log(x); peer=np.log(y); fit=linregress(peer,logs); spread=logs-(fit.intercept+fit.slope*peer); w=_window(p.get("window"),60,len(spread)); sd=float(spread[-w:].std(ddof=1)); z=float((spread[-1]-spread[-w:].mean())/sd) if sd else 0.
        eg_t,eg_p,_=coint(logs,peer); kalman=_kalman_hedge(logs,peer,float(p.get("kalman_process_noise",1e-4)),float(p.get("kalman_observation_noise",1e-3)))
        result={"pearson":float(pearsonr(x/x.max(),y/y.max()).statistic),"spearman":float(spearmanr(x,y).statistic),"spread":float(spread[-1]),"z_score":z,"cointegration_t_statistic":float(eg_t),"cointegration_p_value":float(eg_p),"hedge_ratio":float(fit.slope),"kalman_hedge_ratio":float(kalman[-1]),"kalman_spread":float(logs[-1]-kalman[-1]*peer[-1]),"transaction_cost_bps":float(p.get("transaction_cost_bps",0)),"signal":"monitor" if abs(z)>=float(p.get("entry_z",2)) and eg_p<.05 else "none","signal_direction":"short_spread" if z>=2 else "long_spread" if z<=-2 else "neutral"}
    elif engine=="pairs_trading":
        y=_series(data.get("peer_prices",[]),"peer_prices")
        if len(y)!=len(x): raise ValueError("prices and peer_prices must align")
        logs=np.log(x); peer=np.log(y); fit=linregress(peer,logs); spread=logs-(fit.intercept+fit.slope*peer); w=_window(p.get("window"),60,len(spread)); section=spread[-w:]; sd=float(section.std(ddof=1)); z=float((section[-1]-section.mean())/sd) if sd else 0.; entry=float(p.get("entry_z",2.)); exit_z=float(p.get("exit_z",.5))
        if entry<=0 or exit_z<0 or exit_z>=entry: raise ValueError("entry_z must be positive and exit_z must be non-negative and below entry_z")
        result={"window":w,"hedge_ratio":float(fit.slope),"spread_intercept":float(fit.intercept),"spread":float(spread[-1]),"z_score":z,"entry_z":entry,"exit_z":exit_z,"signal":"short_spread" if z>=entry else "long_spread" if z<=-entry else "exit_zone" if abs(z)<=exit_z else "no_entry","signal_direction":"short_spread" if z>=entry else "long_spread" if z<=-entry else "neutral"}
    elif engine=="momentum":
        w=_window(p.get("lookback"),20,len(returns)); vol=float(returns[-w:].std(ddof=1)); mom=float(np.log(x[-1]/x[-w-1])); fast=_window(p.get("fast_window"),min(20,w),len(x)); slow=_window(p.get("slow_window"),min(50,len(x)),len(x)); sma_fast=float(x[-fast:].mean()); sma_slow=float(x[-slow:].mean()); signs=np.sign(returns[-w:]); persistence=float(abs(signs.sum())/max(np.count_nonzero(signs),1))
        score=mom/(vol*np.sqrt(w)) if vol else 0.
        result={"momentum":mom,"rate_of_change":float(x[-1]/x[-w-1]-1),"annualized_volatility":vol*np.sqrt(252),"vol_adjusted_score":score,"fast_moving_average":sma_fast,"slow_moving_average":sma_slow,"trend_persistence":persistence,"direction":"up" if mom>0 else "down" if mom<0 else "flat","trend_filter":"uptrend" if sma_fast>sma_slow else "downtrend" if sma_fast<sma_slow else "neutral","signal_direction":"long" if score>0 and sma_fast>sma_slow else "short" if score<0 and sma_fast<sma_slow else "neutral"}
    elif engine=="mean_reversion":
        w=_window(p.get("window"),30,len(x)); avg=float(x[-w:].mean()); sd=float(x[-w:].std(ddof=1)); z=float((x[-1]-avg)/sd) if sd else 0.; levels=x[-w:-1]; changes=np.diff(x[-w:]); slope=linregress(levels,changes).slope if np.std(levels)>0 else 0.; intercept=linregress(levels,changes).intercept if np.std(levels)>0 else 0.; half_life=float(-math.log(2)/slope) if slope<0 else None
        ou_mean=float(-intercept/slope) if slope<0 else None; bands={"lower_1sd":avg-sd,"upper_1sd":avg+sd,"lower_2sd":avg-2*sd,"upper_2sd":avg+2*sd}
        result={"rolling_mean":avg,"standard_deviation":sd,"z_score":z,"bands":bands,"ou_speed_per_observation":float(-slope) if slope<0 else None,"estimated_equilibrium":ou_mean,"estimated_half_life_observations":half_life,"signal":"watch_reversion" if abs(z)>=float(p.get("entry_z",2)) and half_life is not None else "none","signal_direction":"long" if z<=-2 else "short" if z>=2 else "neutral","invalidation_level":avg+3*sd if z>0 else avg-3*sd}
    elif engine in ("volatility_options","black_scholes"):
        if engine=="black_scholes" and any(data.get(k) is None for k in ("spot","strike","days_to_expiry","implied_volatility")): raise ValueError("black_scholes requires spot, strike, days_to_expiry, and implied_volatility inputs")
        w=_window(p.get("window"),20,len(returns)); rv=float(returns[-w:].std(ddof=1)*np.sqrt(252)); iv=data.get("implied_volatility"); spot=data.get("spot"); strike=data.get("strike"); days=data.get("days_to_expiry"); rate=float(p.get("risk_free_rate",0.))
        if iv is not None and (not np.isfinite(float(iv)) or float(iv)<=0): raise ValueError("implied_volatility must be positive and finite")
        result={"realized_volatility":rv,"implied_volatility":float(iv) if iv is not None else None,"iv_rv_spread":float(iv)-rv if iv is not None else None,"status":"calculated_without_options_feed" if iv is None else "calculated"}
        if spot is not None and strike is not None and days is not None:
            spot=float(spot); strike=float(strike); t=float(days)/365
            if min(spot,strike,t)<=0: raise ValueError("spot, strike, and days_to_expiry must be positive")
            market_call=data.get("market_call_price")
            if iv is None and market_call is not None:
                market_call=float(market_call)
                if not 0<market_call<spot: raise ValueError("market_call_price must be positive and below spot")
                def error(vol): return _bsm(spot,strike,t,rate,vol)["call_price"]-market_call
                try: iv=brentq(error,1e-4,5.,maxiter=200)
                except ValueError as exc: raise ValueError("market call price has no implied volatility in supported range") from exc
                result["implied_volatility"]=float(iv); result["iv_rv_spread"]=float(iv)-rv; result["status"]="calculated_from_market_call_price"; result["implied_volatility_method"]="Black-Scholes call price inversion"
            if iv is not None:
                vol=float(iv)
                result.update(_bsm(spot,strike,t,rate,vol)); result["black_scholes_call_baseline"]=result["call_price"]; result["call_delta"]=result["delta"]
                shocks=p.get("scenario_spot_shocks",[-.1,0,.1]); result["scenario_call_prices"]=[{"spot_shock":float(q),"call_price":_bsm(spot*(1+float(q)),strike,t,rate,vol)["call_price"]} for q in shocks]
    elif engine=="cross_asset":
        y=_series(data.get("peer_prices",[]),"peer_prices")
        if len(y)!=len(x): raise ValueError("prices and peer_prices must align")
        rx=np.diff(np.log(x)); ry=np.diff(np.log(y)); corr=float(pearsonr(rx,ry).statistic) if np.std(rx)>0 and np.std(ry)>0 else None; reg=linregress(ry,rx) if np.std(ry)>0 else None
        result={"correlation":corr,"correlation_status":"calculated" if corr is not None else "undefined_constant_returns","relative_return":float(np.log(x[-1]/x[0])-np.log(y[-1]/y[0])),"basis":float(x[-1]-y[-1]),"basis_pct_of_peer":float((x[-1]-y[-1])/y[-1]),"yield_spread_bps":float((float(data["yield_a"])-float(data["yield_b"]))*10000) if data.get("yield_a") is not None and data.get("yield_b") is not None else None,"factor_beta":float(reg.slope) if reg else None,"factor_alpha_per_observation":float(reg.intercept) if reg else None,"signal_direction":"long_relative" if x[-1]/x[0]>y[-1]/y[0] else "short_relative"}
    elif engine=="market_regime":
        w=_window(p.get("window"),20,len(returns)); recent=float(np.std(returns[-w:],ddof=1)*np.sqrt(252)); hist=float(np.std(returns,ddof=1)*np.sqrt(252)); posterior_history,transition,means,variances=_two_state_hmm(returns,return_history=True)
        stress=int(np.argmax(variances)); calm=1-stress; posterior=posterior_history[-1]; state=int(np.argmax(posterior)); transition_probs=(posterior@transition).tolist(); regimes=np.argmax(posterior_history,axis=1)
        result={"annualized_volatility":recent,"historical_volatility":hist,"regime":"high_volatility" if state==stress else "normal_volatility","high_volatility_state":stress,"method":"two_state_gaussian_hmm_on_returns","state_posterior":{"calm":float(posterior[calm]),"high_volatility":float(posterior[stress])},"historical_regime_states":regimes.astype(int).tolist(),"historical_regime_labels":["high_volatility" if int(value)==stress else "normal_volatility" for value in regimes],"historical_state_probabilities":posterior_history.tolist(),"state_transition_matrix":transition.tolist(),"next_observation_transition_probability":{"calm":float(transition_probs[calm]),"high_volatility":float(transition_probs[stress])},"state_annualized_volatility":{"calm":float(math.sqrt(variances[calm]*252)),"high_volatility":float(math.sqrt(variances[stress]*252))},"state_mean_return_per_observation":{"calm":float(means[calm]),"high_volatility":float(means[stress])},"estimated_duration_observations":{"calm":float(1/max(1-transition[calm,calm],1e-12)),"high_volatility":float(1/max(1-transition[stress,stress],1e-12))},"diagnostics":{"iterations":40,"likelihood":"not exposed by current Baum-Welch implementation"},"change_point_score":float(abs(np.mean(returns[-w:])-np.mean(returns[:-w]))/(np.std(returns,ddof=1)+1e-12)) if len(returns)>2*w else None}
    elif engine=="volatility_breakout":
        highs=np.asarray(data.get("highs",[]),dtype=float); lows=np.asarray(data.get("lows",[]),dtype=float)
        if highs.ndim!=1 or lows.ndim!=1 or len(highs)!=len(x) or len(lows)!=len(x) or not np.isfinite(highs).all() or not np.isfinite(lows).all() or (highs<=0).any() or (lows<=0).any(): raise ValueError("highs and lows must be positive finite series aligned with prices")
        if np.any(highs<x) or np.any(lows>x) or np.any(highs<lows): raise ValueError("each candle must satisfy high >= close >= low")
        w=_window(p.get("window"),20,len(x)-1); prior_high=float(highs[-w-1:-1].max()); prior_low=float(lows[-w-1:-1].min()); tr=np.maximum(highs[1:]-lows[1:],np.maximum(np.abs(highs[1:]-x[:-1]),np.abs(lows[1:]-x[:-1]))); atr=float(tr[-w:].mean()); buffer=float(p.get("atr_multiple",0.))
        result={"window":w,"prior_high":prior_high,"prior_low":prior_low,"average_true_range":atr,"atr_multiple":buffer,"upper_trigger":prior_high+buffer*atr,"lower_trigger":prior_low-buffer*atr,"signal_direction":"long" if x[-1]>prior_high+buffer*atr else "short" if x[-1]<prior_low-buffer*atr else "neutral","signal":"upside_break" if x[-1]>prior_high+buffer*atr else "downside_break" if x[-1]<prior_low-buffer*atr else "inside_prior_range"}
    elif engine=="garch":
        result=_garch_fit(returns)
    elif engine=="monte_carlo":
        horizon=int(p.get("horizon",20)); simulations=int(p.get("simulations",2000)); seed=int(p.get("seed",7))
        if not 1<=horizon<=2520 or not 100<=simulations<=50000: raise ValueError("horizon must be 1-2520 and simulations must be 100-50000")
        mu=float(returns.mean()); sigma=float(returns.std(ddof=1)); rng=np.random.default_rng(seed); shocks=rng.normal(mu,sigma,(simulations,horizon)); terminal=float(x[-1])*np.exp(shocks.sum(axis=1)); change=terminal/float(x[-1])-1
        result={"method":"geometric Brownian motion from sample log returns","horizon_observations":horizon,"simulations":simulations,"seed":seed,"sample_mean_log_return":mu,"sample_volatility":sigma,"terminal_price_median":float(np.median(terminal)),"terminal_price_05_pct":float(np.quantile(terminal,.05)),"terminal_price_95_pct":float(np.quantile(terminal,.95)),"return_05_pct":float(np.quantile(change,.05)*100),"return_median_pct":float(np.median(change)*100),"return_95_pct":float(np.quantile(change,.95)*100),"fraction_below_start":float(np.mean(change<0)),"interpretation":"Seeded distributional scenario under a constant-parameter GBM assumption; not a price forecast or confidence interval."}
    else: raise ValueError("Unknown engine")
    # User-supplied arrays cannot certify a provider, freshness, or a LIVE status.
    return {"engine":engine,"model_version":VERSION,"executed_at":datetime.now(timezone.utc).isoformat(),"observations":len(x),"input_source":"caller_supplied","data_status":"historical","interpretation":"Research calculation only; user-supplied observations are treated as historical. Not an execution signal or investment recommendation.","metrics":result}
