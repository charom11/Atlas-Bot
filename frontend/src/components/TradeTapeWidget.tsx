import React, { useState } from 'react';
import type { LiveTrade } from '../types';

interface TradeTapeWidgetProps {
  trades: LiveTrade[];
  velocity: number;
}

export const TradeTapeWidget: React.FC<TradeTapeWidgetProps> = ({ trades, velocity }) => {
  const [whaleOnly, setWhaleOnly] = useState<boolean>(false);

  const filtered = whaleOnly ? trades.filter((t) => t.isWhale) : trades;

  return (
    <div className="trade-tape-widget">
      <div className="tape-header">
        <div className="tape-title-group">
          <h3>⚡ STREAMING LIVE TRADE TAPE (TIME & SALES)</h3>
          <span className="tape-velocity-badge">⚡ {velocity} trades/sec</span>
        </div>
        <div className="tape-controls">
          <label className="tape-filter-label">
            <input
              type="checkbox"
              checked={whaleOnly}
              onChange={(e) => setWhaleOnly(e.target.checked)}
            />
            <span>🐳 Whales Only (≥ $5k)</span>
          </label>
        </div>
      </div>
      <div className="tape-feed-wrapper">
        <div className="tape-feed-header">
          <span>Time</span>
          <span>Side</span>
          <span>Price</span>
          <span>Size</span>
          <span>Total ($)</span>
        </div>
        <div className="tape-feed-body">
          {filtered.length === 0 ? (
            <div style={{ padding: '8px', color: 'var(--text-muted)', textAlign: 'center' }}>
              Streaming Binance live orders...
            </div>
          ) : (
            filtered.slice(0, 30).map((t) => (
              <div
                key={t.id}
                className={`tape-row ${t.side.toLowerCase()} ${t.isWhale ? 'whale' : ''}`}
              >
                <span>{t.time}</span>
                <span>{t.side}</span>
                <span>${t.price.toFixed(4)}</span>
                <span>{t.qty.toFixed(2)}</span>
                <span>${t.totalUsdt.toLocaleString(undefined, { maximumFractionDigits: 1 })}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
