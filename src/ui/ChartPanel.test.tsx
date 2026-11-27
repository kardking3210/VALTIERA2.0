import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ChartPanel from './ChartPanel';

describe('large interactive market chart', () => {
  it('removes the duplicate heading and selectors above the chart', () => {
    render(<ChartPanel/>);
    expect(screen.getByLabelText('Interactive market chart')).toBeInTheDocument();
    expect(screen.queryByText('MARKET TERMINAL / INTERACTIVE CHART')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Chart instrument')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Chart interval')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Summarize market' })).toBeInTheDocument();
    expect(screen.getByLabelText('Summary asset')).toHaveValue('BTCUSDT');
    expect(screen.getByLabelText('Summary interval')).toHaveValue('1h');
    expect(document.querySelector('.tradingview-widget-container script')?.textContent).toContain('"theme":"dark"');
  });
});