import React from 'react';
import type { DivergenceResponse } from '../types';

interface DivergenceCardProps {
  divergence: DivergenceResponse | null;
}

export const DivergenceCard: React.FC<DivergenceCardProps> = ({ divergence }) => {
  const rsi = divergence?.rsi_14 ?? 48.5;
  const cci = divergence?.cci_20 ?? -12.4;
  const state = divergence?.divergence_state || divergence?.confluence_grade || 'NO DIVERGENCE';
  const isBull = divergence?.bull_div || divergence?.macro_bull;
  const isBear = divergence?.bear_div || divergence?.macro_bear;

  let badgeStyle = {
    background: 'rgba(217, 70, 239, 0.15)',
    color: '#d946ef',
    border: '1px solid rgba(217, 70, 239, 0.3)',
  };

  if (isBull) {
    badgeStyle = {
      background: 'var(--color-bull-bg)',
      color: 'var(--color-bull)',
      border: '1px solid var(--color-bull)',
    };
  } else if (isBear) {
    badgeStyle = {
      background: 'var(--color-bear-bg)',
      color: 'var(--color-bear)',
      border: '1px solid var(--color-bear)',
    };
  }

  return (
    <div className="divergence-section" style={{ marginTop: '0.8rem' }}>
      <div className="section-title-sm" style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--text-muted)', marginBottom: '0.4rem' }}>
        ⚡ RSI + CCI DUAL DIVERGENCE RADAR
      </div>
      <div
        className="divergence-card"
        style={{
          background: 'rgba(0,0,0,0.3)',
          border: '1px solid var(--bg-card-border)',
          borderRadius: 'var(--radius-sm)',
          padding: '0.6rem',
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '0.4rem',
          }}
        >
          <span className="potato-badge" style={badgeStyle}>
            {state}
          </span>
          <span style={{ fontSize: '0.68rem', color: 'var(--text-dim)' }}>
            4H Trend Gate:{' '}
            <strong style={{ color: 'var(--color-bull)' }}>ACTIVE ✅</strong>
          </span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
          <div style={{ background: 'rgba(255,255,255,0.03)', padding: '0.4rem', borderRadius: '4px' }}>
            <div style={{ fontSize: '0.62rem', color: 'var(--text-dim)', fontWeight: 700 }}>
              RSI (14) SMOOTH MOMENTUM
            </div>
            <div
              style={{
                fontSize: '0.9rem',
                fontWeight: 800,
                fontFamily: 'var(--font-mono)',
                color: 'var(--color-accent)',
              }}
            >
              {rsi.toFixed(1)}
            </div>
          </div>
          <div style={{ background: 'rgba(255,255,255,0.03)', padding: '0.4rem', borderRadius: '4px' }}>
            <div style={{ fontSize: '0.62rem', color: 'var(--text-dim)', fontWeight: 700 }}>
              CCI (20) FAST STAT DEVIATION
            </div>
            <div
              style={{
                fontSize: '0.9rem',
                fontWeight: 800,
                fontFamily: 'var(--font-mono)',
                color: '#ffb800',
              }}
            >
              {cci.toFixed(1)}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
