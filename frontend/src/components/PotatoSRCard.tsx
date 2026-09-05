import React from 'react';
import type { PotatoSRResponse } from '../types';

interface PotatoSRCardProps {
  potato: PotatoSRResponse | null;
  symbol: string;
}

export const PotatoSRCard: React.FC<PotatoSRCardProps> = ({ potato, symbol }) => {
  const current = potato?.current_price || 0;
  const support = potato?.support || 0;
  const resistance = potato?.resistance || 0;
  const state = potato?.state || 'IN RANGE 🥔';

  let markerPct = 50;
  if (resistance > support && current > 0) {
    const rawPct = ((current - support) / (resistance - support)) * 100;
    markerPct = Math.min(100, Math.max(0, rawPct));
  }

  return (
    <div className="potato-sr-section">
      <div className="section-title-sm" style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--text-muted)', marginBottom: '0.4rem' }}>
        🥔 POTATO S&R RADAR (FLOOR & CEILING)
      </div>
      <div className="potato-card">
        <div className="potato-header">
          <span className="potato-badge">{state}</span>
          <span className="potato-asset">{symbol}</span>
        </div>
        <div className="potato-levels-grid">
          <div className="potato-level-box support">
            <span className="p-lvl-tag">FLOOR (SUPPORT 🛡️)</span>
            <strong className="p-lvl-price">
              ${support > 0 ? support.toFixed(4) : '---'}
            </strong>
          </div>
          <div className="potato-level-box resistance">
            <span className="p-lvl-tag">CEILING (RESISTANCE 🧱)</span>
            <strong className="p-lvl-price">
              ${resistance > 0 ? resistance.toFixed(4) : '---'}
            </strong>
          </div>
        </div>
        <div className="potato-slider-wrapper">
          <div className="potato-slider-track">
            <div className="potato-slider-marker" style={{ left: `${markerPct}%` }}>
              🥔
            </div>
          </div>
          <div className="potato-slider-labels">
            <span>Floor (Buy Zone)</span>
            <span>Ceiling (Sell Zone)</span>
          </div>
        </div>
      </div>
    </div>
  );
};
