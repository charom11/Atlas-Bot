import React from 'react';
import type { MTFHeatmapItem } from '../types';

interface MTFHeatmapTableProps {
  heatmap: MTFHeatmapItem[];
  onSelectSymbol?: (symbol: string) => void;
}

const DEFAULT_MTF_ITEMS: MTFHeatmapItem[] = [
  { symbol: 'BTCUSDT', price: 78599.9, tf_5m: 'BULLISH', tf_15m: 'BULLISH', tf_1h: 'BULLISH', tf_4h: 'BULLISH', confluence: '4/4', status: 'STRONG BUY 🟢' },
  { symbol: 'ETHUSDT', price: 2532.4, tf_5m: 'BULLISH', tf_15m: 'BULLISH', tf_1h: 'BULLISH', tf_4h: 'BULLISH', confluence: '4/4', status: 'STRONG BUY 🟢' },
  { symbol: 'SOLUSDT', price: 178.5, tf_5m: 'BULLISH', tf_15m: 'BULLISH', tf_1h: 'BULLISH', tf_4h: 'BULLISH', confluence: '4/4', status: 'STRONG BUY 🟢' },
  { symbol: 'XRPUSDT', price: 1.4306, tf_5m: 'BULLISH', tf_15m: 'BULLISH', tf_1h: 'BULLISH', tf_4h: 'BULLISH', confluence: '4/4', status: 'STRONG BUY 🟢' },
  { symbol: 'LINKUSDT', price: 12.256, tf_5m: 'BULLISH', tf_15m: 'BULLISH', tf_1h: 'BULLISH', tf_4h: 'BULLISH', confluence: '4/4', status: 'STRONG BUY 🟢' },
  { symbol: 'AVAXUSDT', price: 7.827, tf_5m: 'BULLISH', tf_15m: 'BULLISH', tf_1h: 'BULLISH', tf_4h: 'BULLISH', confluence: '4/4', status: 'STRONG BUY 🟢' },
  { symbol: 'SUIUSDT', price: 0.812, tf_5m: 'BULLISH', tf_15m: 'BULLISH', tf_1h: 'BULLISH', tf_4h: 'BULLISH', confluence: '4/4', status: 'STRONG BUY 🟢' },
  { symbol: 'DOGEUSDT', price: 0.085, tf_5m: 'BULLISH', tf_15m: 'BULLISH', tf_1h: 'BULLISH', tf_4h: 'BULLISH', confluence: '4/4', status: 'STRONG BUY 🟢' },
  { symbol: 'ADAUSDT', price: 0.218, tf_5m: 'BULLISH', tf_15m: 'BULLISH', tf_1h: 'BULLISH', tf_4h: 'BULLISH', confluence: '4/4', status: 'STRONG BUY 🟢' },
];

export const MTFHeatmapTable: React.FC<MTFHeatmapTableProps> = ({ heatmap, onSelectSymbol }) => {
  const displayItems = heatmap && heatmap.length > 0 ? heatmap : DEFAULT_MTF_ITEMS;

  const getBadgeClass = (trend: string) => {
    return trend === 'BULLISH' ? 'pos' : 'neg';
  };

  return (
    <div className="mtf-heatmap-section" style={{ marginTop: '0.8rem' }}>
      <div className="section-title-sm" style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--text-muted)', marginBottom: '0.4rem' }}>
        📊 MULTI-TIMEFRAME CONFLUENCE HEATMAP
      </div>
      <div className="table-wrapper">
        <table className="ledger-table">
          <thead>
            <tr>
              <th>Coin</th>
              <th>5m</th>
              <th>15m</th>
              <th>1h</th>
              <th>4h</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {displayItems.map((item) => (
              <tr
                key={item.symbol}
                style={{ cursor: onSelectSymbol ? 'pointer' : 'default' }}
                onClick={() => onSelectSymbol && onSelectSymbol(item.symbol)}
              >
                <td style={{ fontWeight: 700, color: 'var(--color-accent)' }}>
                  {item.symbol.replace('USDT', '')}
                </td>
                <td>
                  <span className={`change-tag ${getBadgeClass(item.tf_5m)}`}>{item.tf_5m}</span>
                </td>
                <td>
                  <span className={`change-tag ${getBadgeClass(item.tf_15m)}`}>{item.tf_15m}</span>
                </td>
                <td>
                  <span className={`change-tag ${getBadgeClass(item.tf_1h)}`}>{item.tf_1h}</span>
                </td>
                <td>
                  <span className={`change-tag ${getBadgeClass(item.tf_4h)}`}>{item.tf_4h}</span>
                </td>
                <td style={{ fontWeight: 800 }}>{item.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
