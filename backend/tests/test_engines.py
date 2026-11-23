import numpy as np
import pytest
from fastapi import HTTPException

from app.engines.core import ENGINES, calculate
from app.main import candles, health, run, RunRequest


@pytest.fixture
def prices():
    t = np.arange(120, dtype=float)
    return (100 * np.exp(0.001 * t + 0.02 * np.sin(t / 6))).tolist()


@pytest.mark.parametrize("engine", ENGINES)
def test_each_engine_returns_structured_historical_result(engine, prices):
    peer = np.array(prices) * np.exp(.01 * np.sin(np.arange(len(prices)) / 9))
    data = {"prices": prices, "peer_prices": peer.tolist(), "source": "test fixture", "status": "historical"}
    result = calculate(engine, data)
    assert result["engine"] == engine
    assert result["observations"] == 120
    assert result["data_status"] == "historical"
    assert result["metrics"]


def test_options_engine_computes_bsm_baseline(prices):
    result = calculate("volatility_options", {"prices": prices, "spot": 100, "strike": 100, "days_to_expiry": 30, "implied_volatility": .25})
    assert result["metrics"]["black_scholes_call_baseline"] > 0
    assert 0 < result["metrics"]["call_delta"] < 1


def test_stat_arb_requires_aligned_peer(prices):
    with pytest.raises(ValueError, match="align"):
        calculate("statistical_arbitrage", {"prices": prices, "peer_prices": prices[:-1]})


def test_rejects_short_and_nonpositive_prices():
    with pytest.raises(ValueError):
        calculate("momentum", {"prices": [10] * 29})
    with pytest.raises(ValueError):
        calculate("momentum", {"prices": [10] * 29 + [0]})


def test_api_reports_development_and_unavailable_provider():
    assert health()["database"] == "OFFLINE"
    with pytest.raises(HTTPException) as error:
        candles("DEMO")
    assert error.value.status_code == 503


def test_engine_api_validates_input(prices):
    response = run("momentum", RunRequest(data={"prices": prices}))
    assert response["engine"] == "momentum"
    with pytest.raises(HTTPException) as error:
        run("momentum", RunRequest(data={"prices": [1, 2]}))
    assert error.value.status_code == 422
