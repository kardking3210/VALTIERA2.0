import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .engines.core import calculate, ENGINES

app=FastAPI(title="VALTIERA Research API",version="0.1.0",description="Input-driven quantitative research calculations. No market data or investment execution is provided.")
origins=[x.strip() for x in os.getenv("CORS_ORIGINS","http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=["GET","POST"],allow_headers=["Content-Type","Authorization"])
class RunRequest(BaseModel):
    data: dict
    parameters: dict=Field(default_factory=dict)
@app.get("/health")
def health(): return {"status":"DEVELOPMENT","database":"OFFLINE","market_data":"DATA UNAVAILABLE","engines":{e:"TESTING" for e in ENGINES}}
@app.get("/market-data/candles")
def candles(symbol:str=Query(min_length=1,max_length=32),timeframe:str="1D",limit:int=Query(default=220,ge=30,le=1000)):
    raise HTTPException(503,"No licensed market-data provider is configured; chart data unavailable.")
@app.post("/engines/{engine}/run")
def run(engine:str,request:RunRequest):
    try: return calculate(engine,request.data,request.parameters)
    except ValueError as e: raise HTTPException(422,str(e))
@app.get("/engines")
def engines(): return {"engines":list(ENGINES),"status":"TESTING","note":"Calculation endpoints require caller-supplied validated data."}
