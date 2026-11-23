import { useEffect, useRef, useState } from 'react';
import { CandlestickSeries, ColorType, createChart, createSeriesMarkers, HistogramSeries, LineSeries, type IChartApi, type UTCTimestamp } from 'lightweight-charts';
import { marketData, type Candle, type DataStatus } from '../data/marketData';
import type { Model } from '../data/models';

const times=['1m','5m','15m','1h','4h','1D','1W'];
const symbols=[['SPY','S&P 500 ETF'],['NVDA','NVIDIA'],['AAPL','Apple'],['MSFT','Microsoft'],['ES1!','Equity index future'],['BTC-USD','Bitcoin'],['TLT','Long Treasury ETF']];
function average(rows:Candle[],n:number){return rows.map((_,i)=>{const part=rows.slice(Math.max(0,i-n+1),i+1);return {time:rows[i].time,value:part.reduce((s,x)=>s+x.close,0)/part.length};});}

export default function ChartPanel({model}:{model:Model}){
 const priceEl=useRef<HTMLDivElement>(null), indicatorEl=useRef<HTMLDivElement>(null), priceChart=useRef<IChartApi|null>(null), indicatorChart=useRef<IChartApi|null>(null);
 const [symbol,setSymbol]=useState('SPY'),[tf,setTf]=useState('1D'),[candles,setCandles]=useState<Candle[]>([]),[status,setStatus]=useState<DataStatus>('simulation'),[source,setSource]=useState(''),[error,setError]=useState(''),[query,setQuery]=useState(''),[searchOpen,setSearchOpen]=useState(false);
 useEffect(()=>{let active=true; setError(''); marketData.candles(symbol,tf).then(result=>{if(active){setCandles(result.candles);setStatus(result.status);setSource(result.source);}}).catch(e=>active&&setError(e instanceof Error?e.message:'Unable to load market data')); return()=>{active=false};},[symbol,tf]);
 useEffect(()=>{
  if(!priceEl.current||!indicatorEl.current||!candles.length)return;
  const common={layout:{background:{type:ColorType.Solid,color:'#111114'},textColor:'#85858d',fontFamily:'Inter, system-ui',fontSize:11},grid:{vertLines:{color:'#202024'},horzLines:{color:'#202024'}},rightPriceScale:{borderColor:'#303036'},timeScale:{borderColor:'#303036',timeVisible:tf!=='1D'&&tf!=='1W',secondsVisible:false},crosshair:{vertLine:{color:'#ff8a73',labelBackgroundColor:'#f0605a'},horzLine:{color:'#ff8a73',labelBackgroundColor:'#f0605a'}},handleScroll:true,handleScale:true};
  const chart=createChart(priceEl.current,{...common,width:priceEl.current.clientWidth,height:300}); priceChart.current=chart;
  const cs=chart.addSeries(CandlestickSeries,{upColor:'#56b889',downColor:'#e16767',borderUpColor:'#56b889',borderDownColor:'#e16767',wickUpColor:'#56b889',wickDownColor:'#e16767',priceLineVisible:true}); cs.setData(candles);
  const vol=chart.addSeries(HistogramSeries,{priceScaleId:'volume',priceFormat:{type:'volume'},lastValueVisible:false,priceLineVisible:false}); vol.priceScale().applyOptions({scaleMargins:{top:.82,bottom:0}}); vol.setData(candles.map(c=>({time:c.time,value:c.volume,color:c.close>=c.open?'rgba(86,184,137,.35)':'rgba(225,103,103,.35)'})));
  const ma=chart.addSeries(LineSeries,{color:'#ff8a73',lineWidth:2,priceLineVisible:false,lastValueVisible:false}); ma.setData(average(candles,20));
  if(['stat-arb','mean-reversion'].includes(model.id)){const m=average(candles,20); const std=candles.map((c,i)=>{const p=candles.slice(Math.max(0,i-19),i+1);const avg=m[i].value;return Math.sqrt(p.reduce((s,x)=>s+(x.close-avg)**2,0)/p.length)}); for(const mult of [-2,2]){const band=chart.addSeries(LineSeries,{color:'rgba(255,138,115,.32)',lineWidth:1,lineStyle:2,priceLineVisible:false,lastValueVisible:false});band.setData(m.map((x,i)=>({time:x.time,value:x.value+mult*std[i]})));}}
  if(model.id==='stat-arb') createSeriesMarkers(cs,candles.filter((_,i)=>i%47===8).map(c=>({time:c.time,position:'belowBar',color:'#ff8a73',shape:'arrowUp',text:'Entry'})));
  const ind=createChart(indicatorEl.current,{...common,width:indicatorEl.current.clientWidth,height:104,rightPriceScale:{borderColor:'#303036',scaleMargins:{top:.15,bottom:.15}},timeScale:{visible:false,borderColor:'#303036'}}); indicatorChart.current=ind;
  const line=ind.addSeries(LineSeries,{color:model.id==='volatility'?'#e9a35b':'#ff8a73',lineWidth:2,priceLineVisible:false,lastValueVisible:true});
  const values=candles.map((c,i)=>{const base=average(candles,model.id==='momentum'?12:20)[i].value; const v=model.id==='momentum'?(c.close/base-1)*100:model.id==='volatility'?Math.abs(c.close-c.open)/c.open*100:(c.close-base)/Math.max(base*.005,.01);return {time:c.time,value:v};}); line.setData(values);
  if(model.id==='stat-arb'||model.id==='mean-reversion') {const zero=ind.addSeries(LineSeries,{color:'#55555d',lineWidth:1,lineStyle:2,priceLineVisible:false,lastValueVisible:false});zero.setData(values.map(x=>({time:x.time,value:0})));}
  chart.timeScale().fitContent(); ind.timeScale().fitContent();
  const ro=new ResizeObserver(()=>{if(priceEl.current&&indicatorEl.current){chart.applyOptions({width:priceEl.current.clientWidth});ind.applyOptions({width:indicatorEl.current.clientWidth});}});ro.observe(priceEl.current);ro.observe(indicatorEl.current);
  return()=>{ro.disconnect();chart.remove();ind.remove();priceChart.current=null;indicatorChart.current=null};
 },[candles,tf,model]);
 const filtered=symbols.filter(([s,n])=>`${s} ${n}`.toLowerCase().includes(query.toLowerCase()));
 const live=status==='live',badge=status==='simulation'?'SIMULATION':status.toUpperCase();
 return <section className="chartbox" aria-label={`${model.name} chart`}>
  <div className="chart-toolbar"><div className="instrument-wrap"><button className="instrument" onClick={()=>setSearchOpen(!searchOpen)} aria-expanded={searchOpen}><span className="ticker">{symbol}</span><span className="instrument-name">{symbols.find(s=>s[0]===symbol)?.[1]}</span><span>⌄</span></button>{searchOpen&&<div className="search-pop"><input autoFocus placeholder="Search instruments" value={query} onChange={e=>setQuery(e.target.value)}/>{filtered.map(([s,n])=><button key={s} onClick={()=>{setSymbol(s);setSearchOpen(false);setQuery('')}}><b>{s}</b><span>{n}</span></button>)}</div>}</div>
   <div className="timeframes">{times.map(t=><button className={tf===t?'selected':''} key={t} onClick={()=>setTf(t)}>{t}</button>)}</div><div className={`feed-status ${live?'live':''}`}><i/>{badge}</div>
  </div>
  <div className="chart-caption"><span>PRICE & VOLUME</span><span>{tf} · {candles.length?`${candles.length} bars`:''}</span></div>
  {error?<div className="chart-error">{error}<button onClick={()=>setTf(x=>x)}>Retry</button></div>:<><div ref={priceEl} className="price-chart"/><div className="indicator-head"><span>{model.id==='momentum'?'MOMENTUM':model.id==='volatility'?'INTRABAR VOLATILITY':model.id==='stat-arb'?'NORMALIZED SPREAD PROXY':model.id==='mean-reversion'?'DEVIATION FROM ROLLING MEAN':'MODEL INDICATOR'}</span><span>DISPLAY ONLY</span></div><div ref={indicatorEl} className="indicator-chart"/></>}
  <div className="chart-foot"><span>{status==='simulation'?'DEMONSTRATION SERIES · NOT FOR MODEL INPUT':`${status.toUpperCase()} DATA · ${source}`}</span><span>Chart display is isolated from VALTIERA model calculations.</span></div>
  <div className="attribution">Charts powered by <a href="https://tradingview.github.io/lightweight-charts/" target="_blank" rel="noreferrer">Lightweight Charts</a></div>
 </section>
}
