import React, { useState } from 'react';
import { Layers } from 'lucide-react';
import type { QuantModel } from '../types';

export const ALL_MODELS_DATA: QuantModel[] = [
  // 1. Momentum (4)
  { id: 'm1', name: 'EMA Cross (8/21)', pillar: 'Momentum', pillarNum: 1, weight: 1.2, score: 1.0, signal: 'BUY', description: 'Fast Exponential Moving Average breakout confirmation' },
  { id: 'm2', name: 'MACD Histogram Surge', pillar: 'Momentum', pillarNum: 1, weight: 1.1, score: 1.0, signal: 'BUY', description: 'Zero-line acceleration & volume expansion' },
  { id: 'm3', name: 'Supertrend Dynamic', pillar: 'Momentum', pillarNum: 1, weight: 1.3, score: 1.0, signal: 'BUY', description: 'ATR-based trailing volatility channel' },
  { id: 'm4', name: 'ADX Power (>25)', pillar: 'Momentum', pillarNum: 1, weight: 1.0, score: 1.0, signal: 'BUY', description: 'Directional index trend conviction filter' },

  // 2. Mean Reversion (4)
  { id: 'm5', name: 'Bollinger %B Bounce', pillar: 'Mean Reversion', pillarNum: 2, weight: 1.0, score: 1.0, signal: 'BUY', description: '2.0-sigma lower envelope expansion reclaim' },
  { id: 'm6', name: 'Keltner Channel Rev', pillar: 'Mean Reversion', pillarNum: 2, weight: 1.1, score: 1.0, signal: 'BUY', description: 'ATR-smoothed EMA envelope mean reversion' },
  { id: 'm7', name: 'Donchian 20 Bounce', pillar: 'Mean Reversion', pillarNum: 2, weight: 1.0, score: 1.0, signal: 'BUY', description: 'Rolling 20-bar extreme liquidity floor touch' },
  { id: 'm8', name: 'Hull MA Reversion', pillar: 'Mean Reversion', pillarNum: 2, weight: 1.2, score: 1.0, signal: 'BUY', description: 'Zero-lag weighted moving average direction shift' },

  // 3. Relative Strength (3)
  { id: 'm9', name: 'RSI(14) Momentum', pillar: 'Relative Strength', pillarNum: 3, weight: 1.2, score: 1.0, signal: 'BUY', description: 'Wilder smooth momentum index oscillator' },
  { id: 'm10', name: 'Stochastic Slow', pillar: 'Relative Strength', pillarNum: 3, weight: 1.0, score: 1.0, signal: 'BUY', description: '%K / %D oversold crossover in macro uptrend' },
  { id: 'm11', name: 'Williams %R Hook', pillar: 'Relative Strength', pillarNum: 3, weight: 0.9, score: 1.0, signal: 'BUY', description: 'Fast range momentum recovery trigger' },

  // 4. Volatility (3)
  { id: 'm12', name: 'ATR Expansion Ratio', pillar: 'Volatility', pillarNum: 4, weight: 1.3, score: 1.0, signal: 'BUY', description: 'Volatility breakout above 14-period SMA' },
  { id: 'm13', name: 'Historical Vol Cone', pillar: 'Volatility', pillarNum: 4, weight: 1.0, score: 1.0, signal: 'BUY', description: 'Realized variance cone expansion trigger' },
  { id: 'm14', name: 'Chaikin Volatility', pillar: 'Volatility', pillarNum: 4, weight: 1.0, score: 1.0, signal: 'BUY', description: 'High-low spread acceleration detector' },

  // 5. Event & Funding (3)
  { id: 'm15', name: '8H Funding Squeeze', pillar: 'Event & Funding', pillarNum: 5, weight: 1.4, score: 1.0, signal: 'BUY', description: 'Perpetual swap funding arbitrage squeeze' },
  { id: 'm16', name: 'Cumulative Delta', pillar: 'Event & Funding', pillarNum: 5, weight: 1.2, score: 1.0, signal: 'BUY', description: 'Aggressive taker buying volume dominance' },
  { id: 'm17', name: 'Long/Short Pressure', pillar: 'Event & Funding', pillarNum: 5, weight: 1.1, score: 1.0, signal: 'BUY', description: 'Top trader account positioning skew' },

  // 6. Machine Learning (4)
  { id: 'm18', name: 'Logistic Classifier', pillar: 'Machine Learning', pillarNum: 6, weight: 1.2, score: 1.0, signal: 'BUY', description: 'Multi-factor logistic probability > 0.65' },
  { id: 'm19', name: 'Random Forest Regime', pillar: 'Machine Learning', pillarNum: 6, weight: 1.3, score: 1.0, signal: 'BUY', description: '100-tree non-linear decision ensemble' },
  { id: 'm20', name: 'Bayesian Probability', pillar: 'Machine Learning', pillarNum: 6, weight: 1.1, score: 1.0, signal: 'BUY', description: 'Prior probability belief updating matrix' },
  { id: 'm21', name: 'LightGBM Predictor', pillar: 'Machine Learning', pillarNum: 6, weight: 1.4, score: 1.0, signal: 'BUY', description: 'Gradient boosted 15m directional forecaster' },

  // 7. Time Series (3)
  { id: 'm22', name: 'ARIMA Return Forecaster', pillar: 'Time Series', pillarNum: 7, weight: 1.1, score: 1.0, signal: 'BUY', description: 'Autoregressive integrated moving average projection' },
  { id: 'm23', name: 'Fractal Dimension (FDI)', pillar: 'Time Series', pillarNum: 7, weight: 1.2, score: 1.0, signal: 'BUY', description: 'Mandelbrot chaos vs trend persistence gate' },
  { id: 'm24', name: 'Hurst Exponent (H>0.55)', pillar: 'Time Series', pillarNum: 7, weight: 1.3, score: 1.0, signal: 'BUY', description: 'Long-memory persistent trend filter' },

  // 8. Factor Alpha (4)
  { id: 'm25', name: 'Volume Profile POC', pillar: 'Factor Alpha', pillarNum: 8, weight: 1.3, score: 1.0, signal: 'BUY', description: 'Point of Control institutional liquidity anchor' },
  { id: 'm26', name: 'VWAP Deviation Bands', pillar: 'Factor Alpha', pillarNum: 8, weight: 1.2, score: 1.0, signal: 'BUY', description: 'Volume-weighted institutional anchor deviation' },
  { id: 'm27', name: 'LinReg Slope Velocity', pillar: 'Factor Alpha', pillarNum: 8, weight: 1.0, score: 1.0, signal: 'BUY', description: '20-bar price curve angle acceleration' },
  { id: 'm28', name: 'Composite Alpha Score', pillar: 'Factor Alpha', pillarNum: 8, weight: 1.4, score: 1.0, signal: 'BUY', description: 'Cross-pillar institutional factor confluence' },

  // 9. Seasonality & Microstructure (3)
  { id: 'm29', name: 'L2 Book Imbalance', pillar: 'Microstructure', pillarNum: 9, weight: 1.4, score: 1.0, signal: 'BUY', description: 'Top-20 bid vs ask limit depth dominance' },
  { id: 'm30', name: 'Spread Velocity', pillar: 'Microstructure', pillarNum: 9, weight: 1.0, score: 1.0, signal: 'BUY', description: 'Tightening bid-ask execution friction check' },
  { id: 'm31', name: 'Micro Flow Delta', pillar: 'Microstructure', pillarNum: 9, weight: 1.2, score: 1.0, signal: 'BUY', description: 'Sub-second passive limit order absorption' },
];

export const ModelsGrid: React.FC = () => {
  const [selectedPillar, setSelectedPillar] = useState<string>('all');

  const pillars = [
    { id: 'all', label: 'All 31 Quant Models' },
    { id: 'Momentum', label: '1. Momentum (4)' },
    { id: 'Mean Reversion', label: '2. Mean Rev (4)' },
    { id: 'Relative Strength', label: '3. Rel Strength (3)' },
    { id: 'Volatility', label: '4. Volatility (3)' },
    { id: 'Event & Funding', label: '5. Event/Funding (3)' },
    { id: 'Machine Learning', label: '6. ML Cluster (4)' },
    { id: 'Time Series', label: '7. Time Series (3)' },
    { id: 'Factor Alpha', label: '8. Factor Alpha (4)' },
    { id: 'Microstructure', label: '9. Structure (3)' },
  ];

  const filteredModels =
    selectedPillar === 'all'
      ? ALL_MODELS_DATA
      : ALL_MODELS_DATA.filter((m) => m.pillar === selectedPillar);

  return (
    <section className="panel full-width-panel">
      <div className="panel-header">
        <h2>
          <Layers size={18} />
          9 Quant Pillars Ensemble Matrix & Model States
        </h2>
        <div className="filter-pills">
          {pillars.map((p) => (
            <button
              key={p.id}
              className={`pill ${selectedPillar === p.id ? 'active' : ''}`}
              onClick={() => setSelectedPillar(p.id)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <div className="models-grid">
        {filteredModels.map((m) => (
          <div key={m.id} className="model-card">
            <div className="model-card-header">
              <span className="model-name">{m.name}</span>
              <span className={`model-badge ${m.signal.toLowerCase()}`}>
                {m.signal} 🟢
              </span>
            </div>
            <span className="model-pillar">
              Pillar {m.pillarNum}: {m.pillar} (w: {m.weight.toFixed(1)}x)
            </span>
            <p style={{ fontSize: '0.65rem', color: 'var(--text-muted)', lineHeight: '1.3' }}>
              {m.description}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
};
