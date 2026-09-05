import React from 'react';
import { Volume2, VolumeX, Play, Pause } from 'lucide-react';

interface HeaderBarProps {
  symbols: string[];
  selectedSymbol: string;
  onSelectSymbol: (symbol: string) => void;
  timeframes: string[];
  selectedTimeframe: string;
  onSelectTimeframe: (tf: string) => void;
  soundEnabled: boolean;
  onToggleSound: () => void;
  engineRunning: boolean;
  onToggleEngine: () => void;
}

export const HeaderBar: React.FC<HeaderBarProps> = ({
  symbols,
  selectedSymbol,
  onSelectSymbol,
  timeframes,
  selectedTimeframe,
  onSelectTimeframe,
  soundEnabled,
  onToggleSound,
  engineRunning,
  onToggleEngine,
}) => {
  return (
    <header className="top-bar">
      <div className="brand-section">
        <div className="radar-pulse"></div>
        <div className="brand-text">
          <h1>WEATHER-ENSEMBLE AI</h1>
          <span className="badge badge-quant">INSTITUTIONAL QUANT C2</span>
        </div>
      </div>

      <div className="coin-selector-bar">
        <span className="selector-label">ASSET:</span>
        <div className="coin-pills">
          {symbols.map((sym) => (
            <button
              key={sym}
              className={`coin-pill ${selectedSymbol === sym ? 'active' : ''}`}
              onClick={() => onSelectSymbol(sym)}
            >
              {sym.replace('USDT', '')}
            </button>
          ))}
        </div>

        <span className="selector-label" style={{ marginLeft: 12 }}>
          TF:
        </span>
        <div className="coin-pills">
          {timeframes.map((tf) => (
            <button
              key={tf}
              className={`coin-pill ${selectedTimeframe === tf ? 'active' : ''}`}
              onClick={() => onSelectTimeframe(tf)}
            >
              {tf.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      <div className="header-controls">
        <button
          className="btn btn-secondary btn-sm"
          onClick={onToggleSound}
          title="Toggle Audio Alerts"
        >
          {soundEnabled ? <Volume2 size={14} /> : <VolumeX size={14} />}
          <span>{soundEnabled ? 'Sound ON' : 'Sound OFF'}</span>
        </button>

        <div className={`status-indicator ${engineRunning ? 'live' : 'paused'}`}>
          <span className="dot"></span>
          <span>{engineRunning ? 'ENGINE LIVE' : 'PAUSED'}</span>
        </div>

        <button
          className={`btn btn-sm ${engineRunning ? 'btn-secondary' : 'btn-primary'}`}
          onClick={onToggleEngine}
        >
          {engineRunning ? (
            <>
              <Pause size={14} /> Pause
            </>
          ) : (
            <>
              <Play size={14} /> Resume
            </>
          )}
        </button>
      </div>
    </header>
  );
};
