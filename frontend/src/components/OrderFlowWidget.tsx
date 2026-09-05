import React from 'react';
import type { OrderFlowData } from '../types';

interface OrderFlowWidgetProps {
  orderFlow: OrderFlowData | null;
}

export const OrderFlowWidget: React.FC<OrderFlowWidgetProps> = ({ orderFlow }) => {
  const d = orderFlow?.data;
  const deltaPct = d?.delta_pct || 0;
  const isBuyerDelta = deltaPct >= 0;
  const absDelta = Math.min(100, Math.max(10, Math.abs(deltaPct) * 2));

  return (
    <div className="order-flow-widget">
      <div className="of-header">
        <h3>🌊 REAL-TIME ORDER FLOW & FOOTPRINT TAPE</h3>
        <span className="of-badge">{d?.absorption || 'NORMAL FLOW'}</span>
      </div>
      <div className="of-metrics-grid">
        <div className="of-metric-box">
          <span className="of-label">Aggressive Buy/Sell Delta</span>
          <div className="delta-bar-wrapper">
            <div
              className="delta-fill-bar"
              style={{
                width: `${absDelta}%`,
                background: isBuyerDelta ? 'var(--color-bull)' : 'var(--color-bear)',
              }}
            />
          </div>
          <span
            className="of-val"
            style={{ color: isBuyerDelta ? 'var(--color-bull)' : 'var(--color-bear)' }}
          >
            {deltaPct >= 0 ? `+${deltaPct.toFixed(1)}% Net Buyer Delta` : `${deltaPct.toFixed(1)}% Net Seller Delta`}
          </span>
        </div>
        <div className="of-metric-box">
          <span className="of-label">Volume Profile POC</span>
          <span className="of-val-highlight">
            ${d?.poc_price ? d.poc_price.toFixed(4) : '---'}
          </span>
        </div>
        <div className="of-metric-box">
          <span className="of-label">DOM Limit Wall Ratio</span>
          <span className="of-val">
            {d?.dom_ratio ? `${d.dom_ratio.toFixed(2)}x (${isBuyerDelta ? 'Buyer Wall' : 'Seller Wall'})` : '1.15x (Balanced)'}
          </span>
        </div>
      </div>
    </div>
  );
};
