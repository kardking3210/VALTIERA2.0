import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

vi.mock('./ChartPanel', () => ({ default: () => <div>Chart preview</div> }));

const demoUser={id:1,name:'Maya Chen',email:'maya@valtiera.demo',role:'researcher',is_demo:true};
const discussions=[{id:1,author:demoUser,title:'Testing spread stability',body:'How should we review stability?',topic:'Methods',created_at:new Date().toISOString(),comments:[],poll:{id:1,question:'First diagnostic?',options:['Residual ADF','Half-life stability'],counts:[2,1],my_vote:null}}];

class EventSourceMock { onmessage:((e:MessageEvent)=>void)|null=null; close(){} }

describe('VALTIERA workspace',()=>{
 beforeEach(()=>{
   vi.stubGlobal('EventSource',EventSourceMock);
   vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
     const url=new URL(String(input),'http://127.0.0.1:8000'); const path=url.pathname; let data:any={}; let status=200;
     if(path==='/health')data={status:'DEVELOPMENT',database:'OPERATIONAL',market_data:'DATA UNAVAILABLE',redis:'NOT CONFIGURED',worker:'OFFLINE'};
     else if(path==='/demo-users')data={enabled:true,password:'Research-Demo-2026',users:[demoUser]};
     else if(path==='/engines')data={engines:[]};
     else if(path==='/community/posts')data=discussions;
     else if(path==='/auth/login')data={token:'test-session',user:demoUser};
     else if(path==='/auth/me')data=demoUser;
     else if(path==='/portfolio')data={positions:[],summary:{position_count:0,gross_market_value:0,unrealized_pnl:0,return_pct:0,largest_position_pct:0,exposure_pct:0},risk_warnings:[],valuation_status:'User-entered prices'};
     else if(path==='/risk/settings')data={max_position_pct:10,max_drawdown_pct:15,daily_loss_limit_pct:2,max_gross_exposure_pct:100,portfolio_nav:100000,updated_at:new Date().toISOString()};
     else if(path==='/risk/assessment')data={portfolio:{position_count:0,gross_market_value:0},limits:{},warnings:[],checks:{concentration:'PASS',valuation:'USER ENTERED',drawdown:'NO HISTORICAL EQUITY CURVE'}};
     else if(path==='/backtests'||path==='/engines/history')data=[];
     else if(path==='/audit')data=[];
     else {status=404;data={detail:'Not found'}}
     return new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
   }));
 });

 it('explains the product and presents all six research engines',async()=>{
   render(<App/>);
   expect(await screen.findByText(/Markets move on inefficiencies/)).toBeInTheDocument();
   expect(screen.getAllByText(/Statistical Arbitrage/).length).toBeGreaterThan(0);
   expect(screen.getByText(/Mean Reversion/)).toBeInTheDocument();
   expect(screen.getByText(/Volatility & Options/)).toBeInTheDocument();
   expect(screen.getByText(/Cross-Asset Relative Value/)).toBeInTheDocument();
   expect(screen.getByText(/Momentum & Trend/)).toBeInTheDocument();
   expect(screen.getByText(/Market Regime/)).toBeInTheDocument();
   expect(screen.getByText(/MARKET DATA UNAVAILABLE/)).toBeInTheDocument();
 });

 it('opens the community feed with demo transparency',async()=>{
   render(<App/>);
   fireEvent.click(screen.getAllByRole('button',{name:/Research network/})[0]);
   expect(await screen.findByText('Testing spread stability')).toBeInTheDocument();
   expect(screen.getByText(/Fictional demo profile/)).toBeInTheDocument();
   expect(screen.getByText('First diagnostic?')).toBeInTheDocument();
 });

 it('authenticates a demo profile and unlocks private portfolio data',async()=>{
   render(<App/>);
   fireEvent.click(document.querySelector('.sign-in-top')!);
   expect(await screen.findByRole('heading',{name:'Sign in'})).toBeInTheDocument();
   fireEvent.submit(document.querySelector('.auth-modal')!);
   await waitFor(()=>expect(screen.getAllByText(/Maya Chen/).length).toBeGreaterThan(0));
   fireEvent.click(screen.getAllByRole('button',{name:/Portfolio/})[0]);
   expect(await screen.findByText('Portfolio intelligence')).toBeInTheDocument();
   expect(screen.getByText('No positions yet. Add a holding to calculate exposure and cost basis.')).toBeInTheDocument();
   expect(localStorage.getItem('valtiera_token')).toBe('test-session');
 });

 it('loads persistent risk controls and explicit review status',async()=>{
   render(<App/>);
   fireEvent.click(document.querySelector('.sign-in-top')!);
   fireEvent.submit(document.querySelector('.auth-modal')!);
   await waitFor(()=>expect(screen.getAllByText(/Maya Chen/).length).toBeGreaterThan(0));
   fireEvent.click(screen.getAllByRole('button',{name:/Risk intelligence/})[0]);
   expect(await screen.findByText('Workspace limits')).toBeInTheDocument();
   expect(screen.getByText(/NO HISTORICAL EQUITY CURVE/)).toBeInTheDocument();
   expect(screen.getByDisplayValue('100000')).toBeInTheDocument();
 });

 it('shows provider and worker gaps without labeling them operational',async()=>{
   render(<App/>);
   fireEvent.click(screen.getAllByRole('button',{name:/Markets & data/})[0]);
   expect(await screen.findByText('Data with provenance.')).toBeInTheDocument();
   expect(screen.getByText('No licensed provider adapter or API credentials configured.')).toBeInTheDocument();
   expect(screen.getByText('OFFLINE')).toBeInTheDocument();
 });
});
