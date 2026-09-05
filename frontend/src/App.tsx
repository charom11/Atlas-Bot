import React, { useState, useEffect, useCallback, useRef } from 'react';
import { HeaderBar } from './components/HeaderBar';
import { MilestoneBanner } from './components/MilestoneBanner';
import { TradingChart } from './components/TradingChart';
import { OrderFlowWidget } from './components/OrderFlowWidget';
import { TradeTapeWidget } from './components/TradeTapeWidget';
import { ConsensusHero } from './components/ConsensusHero';
import { PotatoSRCard } from './components/PotatoSRCard';
import { DivergenceCard } from './components/DivergenceCard';
import { MTFHeatmapTable } from './components/MTFHeatmapTable';
import { PositionsTable } from './components/PositionsTable';
import { ModelsGrid } from './components/ModelsGrid';
import { ConsoleLogs } from './components/ConsoleLogs';

import {
  fetchEngineStatus,
  fetchPositions,
  fetchMilestones,
  fetchMTFHeatmap,
  fetchPotatoSR,
  fetchDivergence,
  fetchOrderFlow,
  fetchLogs,
  startEngine,
  stopEngine,
  closePosition,
  emergencyCloseAll,
} from './services/api';

import type {
  BinancePosition,
  MilestonesResponse,
  MTFHeatmapItem,
  PotatoSRResponse,
  DivergenceResponse,
  OrderFlowData,
  LiveTrade,
} from './types';

const SYMBOLS = [
  'XRPUSDT',
  'BTCUSDT',
  'ETHUSDT',
  'SOLUSDT',
  'BNBUSDT',
  'SUIUSDT',
  'DOGEUSDT',
  'ADAUSDT',
  'AVAXUSDT',
  'NEARUSDT',
  'APTUSDT',
  'RENDERUSDT',
  'LINKUSDT',
  'PAXGUSDT',
];

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '1h', '4h'];

export const App: React.FC = () => {
  const [selectedSymbol, setSelectedSymbol] = useState<string>('XRPUSDT');
  const [selectedTimeframe, setSelectedTimeframe] = useState<string>('5m');
  const [soundEnabled, setSoundEnabled] = useState<boolean>(true);
  const [engineRunning, setEngineRunning] = useState<boolean>(true);

  const [milestones, setMilestones] = useState<MilestonesResponse | null>(null);
  const [positions, setPositions] = useState<BinancePosition[]>([]);
  const [mtfHeatmap, setMtfHeatmap] = useState<MTFHeatmapItem[]>([]);
  const [potatoSR, setPotatoSR] = useState<PotatoSRResponse | null>(null);
  const [divergence, setDivergence] = useState<DivergenceResponse | null>(null);
  const [orderFlow, setOrderFlow] = useState<OrderFlowData | null>(null);
  const [logs, setLogs] = useState<string>('');

  const [liveTrades, setLiveTrades] = useState<LiveTrade[]>([]);
  const [tradeVelocity, setTradeVelocity] = useState<number>(4);
  const tradeCountWindowRef = useRef<number>(0);

  // Sound alert effect
  const playAlertSound = useCallback(() => {
    if (!soundEnabled) return;
    try {
      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, audioCtx.currentTime); // A5
      osc.frequency.exponentialRampToValueAtTime(1760, audioCtx.currentTime + 0.15);
      gain.gain.setValueAtTime(0.15, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.15);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.15);
    } catch {
      // Audio context might be restricted
    }
  }, [soundEnabled]);

  // Handle incoming live trade ticks
  const handleTradeTick = useCallback(
    (trade: LiveTrade) => {
      tradeCountWindowRef.current += 1;
      setLiveTrades((prev) => [trade, ...prev.slice(0, 49)]);

      if (trade.isWhale) {
        playAlertSound();
      }
    },
    [playAlertSound]
  );

  // Velocity calculation every 1 second
  useEffect(() => {
    const interval = setInterval(() => {
      setTradeVelocity(Math.max(1, tradeCountWindowRef.current));
      tradeCountWindowRef.current = 0;
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // Poll server state every 3 seconds
  useEffect(() => {
    let isMounted = true;

    const pollData = async () => {
      try {
        const [st, pos, ms, mtf, lg] = await Promise.all([
          fetchEngineStatus().catch(() => ({ running: false, pid: null })),
          fetchPositions().catch(() => ({ positions: [] })),
          fetchMilestones().catch(() => null),
          fetchMTFHeatmap().catch(() => []),
          fetchLogs().catch(() => ''),
        ]);

        if (isMounted) {
          setEngineRunning(st.running);
          setPositions(pos.positions || []);
          if (ms) setMilestones(ms);
          if (mtf && mtf.length > 0) setMtfHeatmap(mtf);
          setLogs(lg);
        }
      } catch (err) {
        console.error('Polling error', err);
      }
    };

    pollData();
    const interval = setInterval(pollData, 3000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  // Poll symbol-specific widgets (Potato S&R, Divergence, Order Flow)
  useEffect(() => {
    let isMounted = true;

    const fetchSymbolData = async () => {
      try {
        const [psr, div, of] = await Promise.all([
          fetchPotatoSR(selectedSymbol).catch(() => null),
          fetchDivergence(selectedSymbol).catch(() => null),
          fetchOrderFlow(selectedSymbol).catch(() => null),
        ]);

        if (isMounted) {
          if (psr) setPotatoSR(psr);
          if (div) setDivergence(div);
          if (of) setOrderFlow(of);
        }
      } catch (err) {
        console.error('Symbol data error', err);
      }
    };

    fetchSymbolData();
    const interval = setInterval(fetchSymbolData, 4000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [selectedSymbol]);

  // Actions
  const handleToggleEngine = async () => {
    if (engineRunning) {
      await stopEngine();
      setEngineRunning(false);
    } else {
      await startEngine();
      setEngineRunning(true);
    }
  };

  const handleClosePosition = async (sym: string) => {
    if (window.confirm(`Are you sure you want to close position #${sym}?`)) {
      await closePosition(sym);
      const res = await fetchPositions();
      setPositions(res.positions || []);
    }
  };

  const handleEmergencyCloseAll = async () => {
    if (window.confirm('⚠️ EMERGENCY: Are you sure you want to MARKET CLOSE ALL active Binance Futures positions?')) {
      await emergencyCloseAll();
      const res = await fetchPositions();
      setPositions(res.positions || []);
    }
  };

  return (
    <div className="app-container">
      <HeaderBar
        symbols={SYMBOLS}
        selectedSymbol={selectedSymbol}
        onSelectSymbol={setSelectedSymbol}
        timeframes={TIMEFRAMES}
        selectedTimeframe={selectedTimeframe}
        onSelectTimeframe={setSelectedTimeframe}
        soundEnabled={soundEnabled}
        onToggleSound={() => setSoundEnabled((prev) => !prev)}
        engineRunning={engineRunning}
        onToggleEngine={handleToggleEngine}
      />

      <MilestoneBanner milestones={milestones} />

      <main className="dashboard-grid">
        {/* Left Column: TradingView Chart, Order Flow & Live Trade Tape */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <TradingChart
            symbol={selectedSymbol}
            timeframe={selectedTimeframe}
            onTradeTick={handleTradeTick}
          />
          <OrderFlowWidget orderFlow={orderFlow} />
          <TradeTapeWidget trades={liveTrades} velocity={tradeVelocity} />
        </div>

        {/* Right Column: 31-Model Confluence Hero, Potato S&R, Divergence & MTF Matrix */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <section className="panel metrics-panel">
            <div className="panel-header">
              <h2>9 Quant Pillars Confluence</h2>
              <span className="sub-text">Threshold: ≥ 30 / 31 Models</span>
            </div>

            <ConsensusHero
              consensusCount={30}
              totalModels={31}
              action="BUY"
              score={34.2}
              smcBias="BUYS ONLY 🏛️"
              orderFlowConfirmed={true}
            />

            <PotatoSRCard potato={potatoSR} symbol={selectedSymbol} />
            <DivergenceCard divergence={divergence} />
            <MTFHeatmapTable heatmap={mtfHeatmap} onSelectSymbol={setSelectedSymbol} />
          </section>
        </div>

        {/* Full-Width: Active Positions Table */}
        <PositionsTable
          positions={positions}
          onClosePosition={handleClosePosition}
          onEmergencyCloseAll={handleEmergencyCloseAll}
        />

        {/* Full-Width: 9 Quant Pillars Model Matrix */}
        <ModelsGrid />

        {/* Full-Width: Live Bot Output Console */}
        <ConsoleLogs logs={logs} />
      </main>
    </div>
  );
};

export default App;
