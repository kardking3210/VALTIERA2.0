import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

vi.mock('./ChartPanel', () => ({ default: () => <div>Chart preview</div> }));

describe('quantitative terminal navigation', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const candles = Array.from({ length: 60 }, (_, index) => ({ time: 1_790_000_000 + index * 3600, open: 100 + index, high: 102 + index, low: 99 + index, close: 101 + index, volume: 10 + index, close_time: 1_790_003_599_000 + index * 3600_000 }));
      const payload = url.includes('/market-data/history')
        ? { symbol: 'BTCUSDT', timeframe: '1d', source: 'Public Spot', provider_status: 'AVAILABLE', fetched_at: new Date().toISOString(), observations: candles.length, candles, sample_volatility_pct: 0.7, annualized_volatility_pct: 13.4 }
        : { status: 'DEVELOPMENT', database: 'OPERATIONAL', worker: 'OFFLINE', engines: {} };
      return new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }));
    vi.stubGlobal('scrollTo', vi.fn());
  });

  it('renders the public landing page with a terminal entry point', () => {
    render(<App />);
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Launch terminal/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Explore the terminal/i })).toBeInTheDocument();
  });

  it('opens the market terminal from the primary entry point', () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: /Launch terminal/i }));
    expect(screen.getByRole('heading', { name: 'Market terminal' })).toBeInTheDocument();
    expect(screen.getByText('Chart preview')).toBeInTheDocument();
  });

  it('does not expose the removed overview page', () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: /Launch terminal/i }));
    expect(screen.getByRole('navigation')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Markets/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Overview/i })).not.toBeInTheDocument();
  });

  it('prefills backtest history from completed public candles', async () => {
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: /Launch terminal/i }));
    fireEvent.click(screen.getByRole('button', { name: /Backtesting/i }));
    expect(await screen.findByText(/60 completed candles/)).toBeInTheDocument();
    expect((screen.getByLabelText('Historical close prices') as HTMLTextAreaElement).value.split(', ')).toHaveLength(60);
  });
});
