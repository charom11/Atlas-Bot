import React from 'react';

interface ConsensusHeroProps {
  consensusCount: number;
  totalModels: number;
  action: 'BUY' | 'SELL' | 'HOLD';
  score: number;
  smcBias: string;
  orderFlowConfirmed: boolean;
}

export const ConsensusHero: React.FC<ConsensusHeroProps> = ({
  consensusCount,
  totalModels = 31,
  action,
  score,
  smcBias,
  orderFlowConfirmed,
}) => {
  const isBuy = action === 'BUY';
  const isSell = action === 'SELL';

  const badgeClass = isBuy ? 'buy' : isSell ? 'sell' : 'hold';
  const badgeText = isBuy ? 'STRONG BUY 🟢' : isSell ? 'STRONG SELL 🔴' : 'HOLD / NEUTRAL ⚪';

  return (
    <div className="consensus-hero">
      <div className="gauge-container">
        <div
          className="gauge-circle"
          style={{
            borderColor: isBuy ? 'var(--color-bull)' : isSell ? 'var(--color-bear)' : 'var(--text-muted)',
            boxShadow: isBuy ? 'var(--glow-bull)' : isSell ? 'var(--glow-bear)' : 'none',
          }}
        >
          <span
            className="gauge-value"
            style={{
              color: isBuy ? 'var(--color-bull)' : isSell ? 'var(--color-bear)' : 'var(--text-muted)',
            }}
          >
            {consensusCount}
          </span>
          <span className="gauge-total">/ {totalModels}</span>
        </div>
      </div>
      <div className="consensus-details">
        <div className={`signal-badge-large ${badgeClass}`}>{badgeText}</div>
        <div className="consensus-stat">
          <span>Weighted Score:</span>
          <strong>{score.toFixed(1)} pts</strong>
        </div>
        <div className="consensus-stat">
          <span>SMC 4H Bias:</span>
          <strong style={{ color: isBuy ? 'var(--color-bull)' : isSell ? 'var(--color-bear)' : 'var(--text-main)' }}>
            {smcBias || 'BUYS ONLY 🏛️'}
          </strong>
        </div>
        <div className="consensus-stat">
          <span>Order Flow:</span>
          <strong style={{ color: orderFlowConfirmed ? 'var(--color-bull)' : 'var(--text-muted)' }}>
            {orderFlowConfirmed ? 'Confirmed 🌊' : 'Waiting Confluence'}
          </strong>
        </div>
      </div>
    </div>
  );
};
