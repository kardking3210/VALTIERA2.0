import { useEffect, useRef, useState } from 'react';
import { BookOpen, LoaderCircle, LineChart } from 'lucide-react';
import { post } from '../data/api';

const DEFAULT_SYMBOL = 'COINBASE:BTCUSD';
const DEFAULT_INTERVAL = '5';

export default function ChartPanel() {
  const mount = useRef<HTMLDivElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [summarySymbol, setSummarySymbol] = useState('BTCUSDT');
  const [summaryTimeframe, setSummaryTimeframe] = useState('1h');
  const [summary, setSummary] = useState<{ summary: string; verdict: string; metrics: { latest_close: number; change_pct_window: number; rsi14: number; sample_volatility_pct_per_bar: number }; model: string; llm_status: string; data_timestamp: string } | null>(null);
  const [summaryError, setSummaryError] = useState('');
  const [summaryBusy, setSummaryBusy] = useState(false);

  useEffect(() => {
    const node = mount.current;
    if (!node) return;
    setLoaded(false);
    node.replaceChildren();
    const widget = document.createElement('div');
    widget.className = 'tradingview-widget-container__widget';
    const attribution = document.createElement('div');
    attribution.className = 'tradingview-widget-copyright';
    const link = document.createElement('a');
    link.href = `https://www.tradingview.com/symbols/${encodeURIComponent(DEFAULT_SYMBOL.replace(':', '-'))}/`;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = `${DEFAULT_SYMBOL} chart`;
    attribution.append(link);
    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.async = true;
    script.type = 'text/javascript';
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: DEFAULT_SYMBOL,
      interval: DEFAULT_INTERVAL,
      timezone: 'Asia/Kolkata',
      theme: 'dark',
      style: '1',
      locale: 'en',
      allow_symbol_change: true,
      calendar: false,
      details: true,
      hotlist: false,
      hide_side_toolbar: false,
      withdateranges: true,
      save_image: false,
      studies: ['Volume@tv-basicstudies'],
      support_host: 'https://www.tradingview.com',
    });
    node.append(widget, attribution, script);
    const observer = new MutationObserver(() => {
      const frame = node.querySelector('iframe');
      if (frame) {
        frame.addEventListener('load', () => setLoaded(true), { once: true });
        observer.disconnect();
      }
    });
    observer.observe(node, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  const summarize = async () => {
    setSummaryBusy(true); setSummaryError(''); setSummary(null);
    try {
      setSummary(await post('/market-data/summary', { symbol: summarySymbol, timeframe: summaryTimeframe }));
    } catch (error) {
      setSummaryError(error instanceof Error ? error.message : 'Could not summarize market data.');
    } finally { setSummaryBusy(false); }
  };

  return <section className="chart-panel chart-panel-large">
    <div className="chart-frame-large" aria-label="Interactive market chart">
      {!loaded && <div className="chart-loading" role="status">Loading interactive chart…</div>}
      <div ref={mount} className="tradingview-widget-container chart-embed-large" />
    </div>
    <div className="chart-chart-note">Candlesticks show open, high, low and close for the selected interval. Volume bars show traded activity. Use the chart controls to change intervals, indicators and drawing tools. Prices may be delayed by the exchange.</div>
    <section className="chart-guide chart-guide-large" aria-labelledby="chart-guide-title"><div className="chart-guide-title"><BookOpen size={17}/><div><span className="eyebrow">HOW TO READ THIS CHART</span><h3 id="chart-guide-title">A quick guide</h3></div></div><div className="chart-guide-grid"><p><b>Each candle</b> shows open, high, low and close for the selected interval. Green closes are above the open; red closes are below.</p><p><b>Timeframe</b> changes the duration represented by each candle. Use the chart toolbar to change the interval.</p><p><b>Volume</b> bars show activity for each interval. This chart is for research and does not submit orders.</p></div>
      <div className="chart-summary-action"><div><span className="eyebrow">QUANTITATIVE MARKET SUMMARY</span><p>Fetch closed candles for an asset and interval, calculate technical and volatility metrics, then produce a concise verdict. This data summary is separate from the chart display.</p><div className="chart-summary-controls"><label>Summary asset<select aria-label="Summary asset" value={summarySymbol} onChange={event => setSummarySymbol(event.target.value)}><option value="BTCUSDT">BTC / USDT</option><option value="ETHUSDT">ETH / USDT</option></select></label><label>Summary interval<select aria-label="Summary interval" value={summaryTimeframe} onChange={event => setSummaryTimeframe(event.target.value)}>{['15m','1h','4h','1d'].map(value => <option key={value}>{value}</option>)}</select></label></div></div><button className="research-action-button" type="button" onClick={summarize} disabled={summaryBusy}>{summaryBusy ? <LoaderCircle size={15} className="spin"/> : <LineChart size={15}/>} {summaryBusy ? 'Analyzing market' : 'Summarize market'}</button></div>
      {summaryError && <div className="chart-summary-message" role="status">{summaryError}</div>}
      {summary && <div className="chart-verdict" aria-live="polite"><div className="verdict-top"><span className="eyebrow">FINAL VERDICT / {summary.model}</span><span className={`verdict-chip ${summary.verdict.toLowerCase() === 'bullish' ? 'up' : summary.verdict.toLowerCase() === 'bearish' ? 'down' : 'neutral'}`}>{summary.verdict}</span></div><p className="rule-summary-text">{summary.summary}</p><div className="verdict-metrics"><div><span>LATEST CLOSE</span><b>{summary.metrics.latest_close.toLocaleString(undefined, { maximumFractionDigits: 5 })}</b></div><div><span>CHANGE / WINDOW</span><b className={summary.metrics.change_pct_window >= 0 ? 'positive' : 'negative'}>{summary.metrics.change_pct_window >= 0 ? '+' : ''}{summary.metrics.change_pct_window.toFixed(2)}%</b></div><div><span>RSI (14)</span><b>{summary.metrics.rsi14.toFixed(1)}</b></div><div><span>VOLATILITY / BAR</span><b>{summary.metrics.sample_volatility_pct_per_bar.toFixed(3)}%</b></div></div><small>{summarySymbol} · {summaryTimeframe} · {summary.llm_status === 'AVAILABLE' ? 'AI assisted with computed market metrics' : 'Deterministic rules fallback'} · sampled {new Date(summary.data_timestamp).toLocaleString()}. Not a forecast or trade instruction.</small></div>}
    </section>
  </section>;
}
