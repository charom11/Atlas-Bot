import React from 'react';
import { ShieldAlert, DollarSign, X } from 'lucide-react';
import type { BinancePosition } from '../types';

interface PositionsTableProps {
  positions: BinancePosition[];
  onClosePosition: (symbol: string) => void;
  onEmergencyCloseAll: () => void;
}

export const PositionsTable: React.FC<PositionsTableProps> = ({
  positions,
  onClosePosition,
  onEmergencyCloseAll,
}) => {
  const totalUnrealized = positions.reduce((acc, p) => acc + p.unrealizedProfit, 0);

  return (
    <section className="panel full-width-panel">
      <div className="panel-header">
        <h2>
          <DollarSign size={18} />
          Active Binance Futures Positions & Live PnL ({positions.length} Slots)
          {positions.length > 0 && (
            <span
              style={{
                marginLeft: '10px',
                fontSize: '0.85rem',
                color: totalUnrealized >= 0 ? 'var(--color-bull)' : 'var(--color-bear)',
              }}
            >
              (Total PnL: {totalUnrealized >= 0 ? `+$${totalUnrealized.toFixed(2)}` : `-$${Math.abs(totalUnrealized).toFixed(2)}`} USDT)
            </span>
          )}
        </h2>
        <div className="header-actions">
          <button className="btn btn-danger btn-sm" onClick={onEmergencyCloseAll}>
            <ShieldAlert size={14} /> 🚨 Emergency Close All
          </button>
        </div>
      </div>

      <div className="table-wrapper">
        <table className="ledger-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Side</th>
              <th>Leverage</th>
              <th>Position Size</th>
              <th>Entry Price</th>
              <th>Mark Price</th>
              <th>Liquidation Price</th>
              <th>Unrealized PnL (USDT)</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 ? (
              <tr>
                <td colSpan={9} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '1.2rem' }}>
                  No active Binance Futures open positions.
                </td>
              </tr>
            ) : (
              positions.map((p) => {
                const isProfitable = p.unrealizedProfit >= 0;
                const liqBuffer =
                  p.markPrice > 0 && p.liquidationPrice > 0
                    ? ((Math.abs(p.markPrice - p.liquidationPrice) / p.markPrice) * 100).toFixed(1)
                    : 'Safe';

                return (
                  <tr key={p.symbol}>
                    <td style={{ fontWeight: 800, color: 'var(--color-accent)' }}>
                      #{p.symbol}
                    </td>
                    <td>
                      <span className={`change-tag ${p.side === 'LONG' ? 'pos' : 'neg'}`}>
                        {p.side}
                      </span>
                    </td>
                    <td>{p.leverage}x</td>
                    <td>{Math.abs(p.positionAmt)}</td>
                    <td>${p.entryPrice.toFixed(4)}</td>
                    <td>${p.markPrice.toFixed(4)}</td>
                    <td style={{ color: 'var(--text-muted)' }}>
                      ${p.liquidationPrice > 0 ? p.liquidationPrice.toFixed(4) : '0.0000'} ({liqBuffer}%)
                    </td>
                    <td style={{ fontWeight: 800, color: isProfitable ? 'var(--color-bull)' : 'var(--color-bear)' }}>
                      {isProfitable ? `+$${p.unrealizedProfit.toFixed(4)}` : `-$${Math.abs(p.unrealizedProfit).toFixed(4)}`}
                    </td>
                    <td>
                      <button
                        className="btn btn-secondary btn-sm"
                        style={{ padding: '2px 8px', fontSize: '0.7rem' }}
                        onClick={() => onClosePosition(p.symbol)}
                      >
                        <X size={12} /> Close
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
};
