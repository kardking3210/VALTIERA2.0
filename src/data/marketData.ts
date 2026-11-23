import type { UTCTimestamp } from 'lightweight-charts';
export type Candle={time:UTCTimestamp;open:number;high:number;low:number;close:number;volume:number};
export type DataStatus='simulation'|'historical'|'delayed'|'live';
export interface MarketDataAdapter { candles(symbol:string, timeframe:string, limit?:number):Promise<{candles:Candle[];status:DataStatus;source:string}> }

// Demo data is generated locally for chart interaction only. It never feeds model calculations.
const simulated:MarketDataAdapter={async candles(symbol,timeframe,limit=220){
 const interval:Record<string,number>={'1m':60,'5m':300,'15m':900,'1h':3600,'4h':14400,'1D':86400,'1W':604800};
 const step=interval[timeframe]??86400, now=Math.floor(Date.now()/1000/step)*step, seed=[...symbol].reduce((n,c)=>n+c.charCodeAt(0),17);
 let price=100+seed*1.13; const out:Candle[]=[];
 for(let i=limit-1;i>=0;i--){const k=limit-i; const wave=Math.sin(k*.17+seed)*.52+Math.cos(k*.061)*.39+Math.sin(k*.009)*.71; const drift=.018+Math.sin(k*.025)*.025; const open=price; price=Math.max(5,price*(1+(wave*.002+drift*.001))); const close=price; const spread=Math.max(open,close)*(.0012+Math.abs(wave)*.0015); out.push({time:(now-i*step) as UTCTimestamp,open,close,high:Math.max(open,close)+spread,low:Math.min(open,close)-spread,volume:Math.round(45000+Math.abs(wave)*180000+Math.abs(Math.sin(k*.39))*80000)}); }
 return {candles:out,status:'simulation',source:'Local deterministic demonstration series'};
}};

// The VALTIERA backend returns { candles, status, source }; chart display data is not passed to models.
const backend:MarketDataAdapter={async candles(symbol,timeframe,limit=220){
 const base=import.meta.env.VITE_MARKET_DATA_API_URL;
 if(!base) return simulated.candles(symbol,timeframe,limit);
 const response=await fetch(`${base.replace(/\/$/,'')}/market-data/candles?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}&limit=${limit}`);
 if(!response.ok) throw new Error(`Market data request failed (${response.status})`);
 const payload=await response.json();
 if(!Array.isArray(payload.candles)||!['live','delayed','historical','simulation'].includes(payload.status)) throw new Error('Backend returned an invalid market data contract');
 return payload;
}};
export const marketData=backend;
