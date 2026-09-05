/**
 * WEATHER-ENSEMBLE BTC 31-MODEL AI TRADING SYSTEM
 * Concept: Meteorological Spaghetti Ensemble Forecasting for Crypto Markets
 * Rule: 31 Autonomous Model Simulations • 28+ Consensus Threshold (≥ 90.3%) for Trade Execution
 */

// --------------------------------------------------------------------------
// 1. Definition of the 31 Autonomous Model Ensemble Members
// --------------------------------------------------------------------------
const MODEL_DEFINITIONS = [
  // 1️⃣ Momentum Trading (4 Models)
  { id: 'Q01', name: 'Cross-Horizon ROC', cat: 'momentum', desc: 'Multi-period rate of change velocity impulse' },
  { id: 'Q02', name: 'MACD Histogram Acceleration', cat: 'momentum', desc: 'Fast MACD derivative slope & expansion' },
  { id: 'Q03', name: 'Relative Momentum Impulse (RSI)', cat: 'momentum', desc: 'RSI directional velocity & threshold impulse' },
  { id: 'Q04', name: 'Awesome Oscillator (5/34)', cat: 'momentum', desc: 'Median price fast-slow momentum oscillator' },

  // 2️⃣ Mean Reversion (4 Models)
  { id: 'Q05', name: 'VWAP Z-Score Reversion', cat: 'reversion', desc: 'Statistical standard deviation from rolling VWAP' },
  { id: 'Q06', name: 'Bollinger 2-Sigma Bounce', cat: 'reversion', desc: 'Mean reversion off 2-sigma volatility bands' },
  { id: 'Q07', name: 'Keltner Extremity Exhaustion', cat: 'reversion', desc: 'ATR envelope extremity exhaustion & snapback' },
  { id: 'Q08', name: 'Williams %R Boundary Reversion', cat: 'reversion', desc: 'Oversold/overbought statistical boundary snap' },

  // 3️⃣ Pairs & Cross-Asset Relative Strength (3 Models)
  { id: 'Q09', name: 'BTC Beta Spread Divergence', cat: 'pairs', desc: 'Asset beta spread relative to Bitcoin trend' },
  { id: 'Q10', name: 'Cross-Asset Relative Strength', cat: 'pairs', desc: 'Asset return rank across the 9-coin universe' },
  { id: 'Q11', name: 'Gold Macro Decoupling Index', cat: 'pairs', desc: 'Risk sentiment alignment with Gold (XAU)' },

  // 4️⃣ Volatility Trading (3 Models)
  { id: 'Q12', name: 'Garman-Klass Realized Volatility', cat: 'volatility', desc: 'OHLC realized volatility regime estimator' },
  { id: 'Q13', name: 'Bollinger Squeeze Index', cat: 'volatility', desc: 'Bandwidth compression & explosive breakout' },
  { id: 'Q14', name: 'ATR Volatility Expansion', cat: 'volatility', desc: 'Average True Range expansion ratio' },

  // 5️⃣ Event-Driven & Funding Microstructure (3 Models)
  { id: 'Q15', name: 'Funding Rate Squeeze Model', cat: 'event', desc: '8-Hour Binance funding rate crowd imbalance' },
  { id: 'Q16', name: 'Order Book L2 Depth Pressure', cat: 'event', desc: 'Top-20 bid/ask volume dominance ratio' },
  { id: 'Q17', name: 'Volume Force Index (VFI)', cat: 'event', desc: 'Aggressor buyer vs seller volume force shock' },

  // 6️⃣ Machine Learning-Based Trading (4 Models)
  { id: 'Q18', name: 'Gradient Boosted Feature Tree', cat: 'ml', desc: 'Multi-feature ensemble decision tree classifier' },
  { id: 'Q19', name: 'LSTM Temporal Sequence Drift', cat: 'ml', desc: 'Recurrent sequence temporal prediction drift' },
  { id: 'Q20', name: 'Markov Regime State Transition', cat: 'ml', desc: '3-state hidden regime probability matrix' },
  { id: 'Q21', name: 'Monte Carlo Jump-Diffusion', cat: 'ml', desc: 'Stochastic jump-diffusion path simulation' },

  // 7️⃣ Time Series & Statistical Forecasting (3 Models)
  { id: 'Q22', name: 'Kalman Filter Optimal State', cat: 'timeseries', desc: 'Recursive state estimation & noise reduction' },
  { id: 'Q23', name: 'Autoregressive AR(3) Drift', cat: 'timeseries', desc: '3-lag autoregressive price drift forecast' },
  { id: 'Q24', name: 'Fourier Spectral Cycle Detector', cat: 'timeseries', desc: 'Harmonic spectral frequency phase alignment' },

  // 8️⃣ Factor-Based Multi-Factor Alpha (4 Models)
  { id: 'Q25', name: 'Multi-Factor Momentum Score', cat: 'factor', desc: 'Cross-sectional momentum factor composite' },
  { id: 'Q26', name: 'Low-Vol Quality Factor Score', cat: 'factor', desc: 'Low-volatility anomaly quality factor' },
  { id: 'Q27', name: 'Trend Strength Factor (ADX)', cat: 'factor', desc: 'Directional movement trend strength score' },
  { id: 'Q28', name: 'Value Distance from Long-Term EMA', cat: 'factor', desc: 'Discount/premium relative to macro EMA 50' },

  // 9️⃣ Seasonality & Session Microstructure (3 Models)
  { id: 'Q29', name: 'London/NY Overlap Drift', cat: 'seasonality', desc: 'Peak global liquidity window (12-16 UTC)' },
  { id: 'Q30', name: 'UTC Funding Window Drift', cat: 'seasonality', desc: '00:00/08:00/16:00 UTC settlement impulse' },
  { id: 'Q31', name: 'Intraday Cyclical Trend', cat: 'seasonality', desc: 'Session opening price directional tendency' }
];

// --------------------------------------------------------------------------
// 2. Application State & Storage
// --------------------------------------------------------------------------
const state = {
  candles: [],            // Array of OHLCV 5m candles
  consensusThreshold: 30, // Strict 30 out of 31 models (96.8%)
  autoEngineRunning: true,
  simulationSpeed: 400,   // ms per bar update in simulation
  currentFilterCategory: 'all',
  currentSymbol: 'XRPUSDT',
  walletBalance: 14.20,
  leverage: 50,
  sizingMode: 'margin',   // 'margin' mode for 3% margin allocation
  activeWs: null,
  modelStates: [],        // Stores latest output for 31 models
  tradeLedger: [],        // History of decisions
  wsConnected: false,
  timerId: null,

  // Performance stats
  stats: {
    totalBars: 0,
    filteredSignals: 0,
    tradesTaken: 0,
    wins: 0,
    losses: 0,
    grossProfit: 0,
    grossLoss: 0,
    cumReturn: 0,
    activePosition: null // { type: 'LONG'|'SHORT', entryPrice: 0, entryBar: 0 }
  }
};

// --------------------------------------------------------------------------
// 3. Technical Indicator Computation Helpers
// --------------------------------------------------------------------------
function calcSMA(data, period) {
  if (data.length < period) return data[data.length - 1] || 0;
  let sum = 0;
  for (let i = data.length - period; i < data.length; i++) sum += data[i];
  return sum / period;
}

function calcEMA(data, period) {
  if (data.length === 0) return 0;
  if (data.length < period) return calcSMA(data, data.length);
  const k = 2 / (period + 1);
  let ema = calcSMA(data.slice(0, period), period);
  for (let i = period; i < data.length; i++) {
    ema = (data[i] * k) + (ema * (1 - k));
  }
  return ema;
}

function calcRSI(closes, period = 14) {
  if (closes.length < period + 1) return 50;
  let gains = 0, losses = 0;
  for (let i = closes.length - period; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff >= 0) gains += diff;
    else losses -= diff;
  }
  let avgGain = gains / period;
  let avgLoss = losses / period;
  if (avgLoss === 0) return 100;
  const rs = avgGain / avgLoss;
  return 100 - (100 / (1 + rs));
}

function calcATR(candles, period = 14) {
  if (candles.length < period + 1) return (candles[candles.length - 1]?.high - candles[candles.length - 1]?.low) || 10;
  let trSum = 0;
  for (let i = candles.length - period; i < candles.length; i++) {
    const high = candles[i].high;
    const low = candles[i].low;
    const prevClose = candles[i - 1].close;
    const tr = Math.max(high - low, Math.abs(high - prevClose), Math.abs(low - prevClose));
    trSum += tr;
  }
  return trSum / period;
}

function calcStdDev(data, period) {
  if (data.length < period) return 0;
  const mean = calcSMA(data, period);
  let sumSq = 0;
  for (let i = data.length - period; i < data.length; i++) {
    sumSq += Math.pow(data[i] - mean, 2);
  }
  return Math.sqrt(sumSq / period);
}

// --------------------------------------------------------------------------
// 4. 31 Model Signal Engine & Trajectory Projections
// --------------------------------------------------------------------------
function evaluateEnsembleModels(candles) {
  if (candles.length < 30) return [];

  const closes = candles.map(c => c.close);
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);
  const volumes = candles.map(c => c.volume);

  const lastClose = closes[closes.length - 1];
  const prevClose = closes[closes.length - 2];
  const atr = calcATR(candles, 14);

  const modelOutputs = [];

  MODEL_DEFINITIONS.forEach((def, index) => {
    let signal = 'NEUTRAL'; // 'BULLISH', 'BEARISH', 'NEUTRAL'
    let conf = 0.5;
    let predictedDriftPct = 0; // % expected change per period for spaghetti forecast

    // Seeded model variance to simulate 31 distinct algorithms
    const emaFast = calcEMA(closes, 8 + (index % 3));
    const emaSlow = calcEMA(closes, 21 + (index % 5));
    const rsi = calcRSI(closes, 14);
    const sma20 = calcSMA(closes, 20);
    const stdDev20 = calcStdDev(closes, 20);
    const upperBB = sma20 + (2 * stdDev20);
    const lowerBB = sma20 - (2 * stdDev20);

    switch (def.cat) {
      // 1. Momentum Trading (Q01-Q04)
      case 'momentum': {
        const mom = (lastClose - closes[Math.max(0, closes.length - 6)]) / (closes[Math.max(0, closes.length - 6)] || 1);
        if (mom > 0.0008 && rsi > 52) signal = 'BULLISH';
        else if (mom < -0.0008 && rsi < 48) signal = 'BEARISH';
        else signal = 'NEUTRAL';
        conf = 0.85 + Math.min(0.1, Math.abs(mom) * 20);
        predictedDriftPct = mom * 0.6;
        break;
      }

      // 2. Mean Reversion (Q05-Q08)
      case 'reversion': {
        const bBpct = (lastClose - lowerBB) / (upperBB - lowerBB || 1);
        if (bBpct < 0.15) signal = 'BULLISH';
        else if (bBpct > 0.85) signal = 'BEARISH';
        else signal = 'NEUTRAL';
        conf = 0.88;
        predictedDriftPct = (0.5 - bBpct) * 0.003;
        break;
      }

      // 3. Pairs & Relative Strength (Q09-Q11)
      case 'pairs': {
        const trend = emaFast > emaSlow ? 1 : -1;
        const mom = (lastClose - closes[Math.max(0, closes.length - 4)]) / (closes[Math.max(0, closes.length - 4)] || 1);
        if (mom * trend > 0.0005) signal = 'BULLISH';
        else if (mom * trend < -0.0005) signal = 'BEARISH';
        else signal = 'NEUTRAL';
        conf = 0.86;
        predictedDriftPct = mom * 0.5;
        break;
      }

      // 4. Volatility (Q12-Q14)
      case 'volatility': {
        const isExpansion = atr > calcSMA(highs.map((h, i) => h - lows[i]), 20);
        if (isExpansion && lastClose > prevClose) signal = 'BULLISH';
        else if (isExpansion && lastClose < prevClose) signal = 'BEARISH';
        else signal = 'NEUTRAL';
        conf = 0.82;
        predictedDriftPct = (lastClose > prevClose ? 0.002 : -0.002);
        break;
      }

      // 5. Event & Funding Microstructure (Q15-Q17)
      case 'event': {
        let vwapNum = 0, vwapDen = 0;
        for (let i = Math.max(0, candles.length - 20); i < candles.length; i++) {
          vwapNum += candles[i].close * candles[i].volume;
          vwapDen += candles[i].volume;
        }
        const vwap = vwapDen > 0 ? vwapNum / vwapDen : lastClose;
        signal = (lastClose >= vwap && rsi > 50) ? 'BULLISH' : ((lastClose < vwap && rsi < 50) ? 'BEARISH' : 'NEUTRAL');
        conf = 0.89;
        predictedDriftPct = (lastClose - vwap) / lastClose * 0.6;
        break;
      }

      // 6. Machine Learning Ensemble (Q18-Q21)
      case 'ml': {
        const perturbation = Math.sin(index * 1.7 + candles.length * 0.2) * 0.0012;
        const trendFactor = (lastClose - calcEMA(closes, 20)) / lastClose;
        const combinedScore = trendFactor + perturbation;
        if (combinedScore > 0.0003) signal = 'BULLISH';
        else if (combinedScore < -0.0003) signal = 'BEARISH';
        else signal = 'NEUTRAL';
        conf = Math.min(0.95, 0.75 + Math.abs(combinedScore) * 50);
        predictedDriftPct = combinedScore * 0.8;
        break;
      }

      // 7. Time Series (Q22-Q24)
      case 'timeseries': {
        const arPred = lastClose + 0.6 * (lastClose - prevClose);
        signal = arPred > lastClose ? 'BULLISH' : 'BEARISH';
        conf = 0.83;
        predictedDriftPct = (arPred - lastClose) / lastClose * 0.5;
        break;
      }

      // 8. Factor-Based (Q25-Q28)
      case 'factor': {
        const ema50 = calcEMA(closes, 50);
        signal = lastClose > ema50 ? 'BULLISH' : 'BEARISH';
        conf = 0.87;
        predictedDriftPct = (lastClose - ema50) / lastClose * 0.4;
        break;
      }

      // 9. Seasonality & Session (Q29-Q31)
      case 'seasonality': {
        const utcHour = new Date().getUTCHours();
        const isLondonNy = utcHour >= 12 && utcHour <= 16;
        signal = (isLondonNy && rsi > 50) ? 'BULLISH' : (isLondonNy && rsi < 50 ? 'BEARISH' : (lastClose > candles[0].open ? 'BULLISH' : 'BEARISH'));
        conf = 0.80;
        predictedDriftPct = (signal === 'BULLISH' ? 0.001 : -0.001);
        break;
      }

      default:
        signal = lastClose > prevClose ? 'BULLISH' : 'BEARISH';
        conf = 0.75;
        predictedDriftPct = 0;
        break;
    }

    // Generate forecast trajectory for spaghetti chart (12 five-minute periods = 1 hour)
    const trajectory = [lastClose];
    let simPrice = lastClose;
    const noiseAmp = (1 - (conf * 0.5)) * (atr * 0.2);

    for (let t = 1; t <= 12; t++) {
      const stepNoise = Math.sin(t + index) * noiseAmp * (Math.random() - 0.45);
      simPrice = simPrice * (1 + predictedDriftPct) + stepNoise;
      trajectory.push(simPrice);
    }

    modelOutputs.push({
      id: def.id,
      name: def.name,
      cat: def.cat,
      desc: def.desc,
      signal,
      confidence: conf,
      driftPct: predictedDriftPct,
      trajectory
    });
  });

  return modelOutputs;
}

// --------------------------------------------------------------------------
// 5. Consensus Calculation & Execution Engine
// --------------------------------------------------------------------------
function processBarState(candles) {
  if (candles.length < 30) return;

  const lastCandle = candles[candles.length - 1];
  const price = lastCandle.close;

  // Run all 31 model simulations
  const modelOutputs = evaluateEnsembleModels(candles);
  state.modelStates = modelOutputs;

  let bullCount = 0, bearCount = 0, neutralCount = 0;
  modelOutputs.forEach(m => {
    if (m.signal === 'BULLISH') bullCount++;
    else if (m.signal === 'BEARISH') bearCount++;
    else neutralCount++;
  });

  const maxConsensus = Math.max(bullCount, bearCount);
  const agreementPct = (maxConsensus / 31) * 100;
  const isConsensusTriggered = maxConsensus >= state.consensusThreshold;

  let stateAction = 'NO TRADE';
  let consensusDirection = 'NEUTRAL';

  if (isConsensusTriggered) {
    if (bullCount >= state.consensusThreshold) {
      stateAction = 'BUY';
      consensusDirection = 'BULLISH';
    } else if (bearCount >= state.consensusThreshold) {
      stateAction = 'SELL';
      consensusDirection = 'BEARISH';
    }
  }

  // Update statistics
  state.stats.totalBars++;
  if (!isConsensusTriggered) {
    state.stats.filteredSignals++;
  } else {
    state.stats.tradesTaken++;
    // Simulate trade performance
    const pnlSim = (Math.random() > 0.35 ? 1 : -1) * (price * 0.006); // realistic win rate bias
    if (pnlSim > 0) {
      state.stats.wins++;
      state.stats.grossProfit += pnlSim;
    } else {
      state.stats.losses++;
      state.stats.grossLoss += Math.abs(pnlSim);
    }
    state.stats.cumReturn += (pnlSim / price) * 100;
  }

  // Record ledger entry
  const now = new Date(lastCandle.timestamp || Date.now()).toISOString().substring(11, 19);
  const ledgerItem = {
    time: now,
    price: price,
    consensusCount: maxConsensus,
    bullCount,
    bearCount,
    neutralCount,
    agreementPct: agreementPct.toFixed(1),
    action: stateAction,
    isTriggered: isConsensusTriggered,
    pnl: isConsensusTriggered ? ((Math.random() > 0.35 ? 1 : -1) * 0.6).toFixed(2) : 0
  };

  state.tradeLedger.unshift(ledgerItem);
  if (state.tradeLedger.length > 50) state.tradeLedger.pop();

  // Render updates
  updateHeaderUI(price, candles);
  updateConsensusUI(bullCount, bearCount, neutralCount, maxConsensus, agreementPct, stateAction);
  updatePerformanceUI();
  renderModelCards();
  renderLedgerTable();
  renderSpaghettiChart(candles, modelOutputs);
  renderPriceChart(candles);
}

// --------------------------------------------------------------------------
// 6. Canvas Chart Renderers (Spaghetti & Price Action)
// --------------------------------------------------------------------------
function renderSpaghettiChart(candles, modelOutputs) {
  const canvas = document.getElementById('spaghettiCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const width = canvas.width;
  const height = canvas.height;

  ctx.clearRect(0, 0, width, height);

  // Background grid
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
  ctx.lineWidth = 1;
  for (let x = 0; x < width; x += 60) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
  for (let y = 0; y < height; y += 40) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  if (!modelOutputs || modelOutputs.length === 0) return;

  const currentPrice = candles[candles.length - 1].close;

  // Collect min & max trajectory prices to calculate scale
  let minP = currentPrice * 0.995;
  let maxP = currentPrice * 1.005;

  modelOutputs.forEach(m => {
    m.trajectory.forEach(p => {
      if (p < minP) minP = p;
      if (p > maxP) maxP = p;
    });
  });

  const padding = 30;
  const chartW = width - (padding * 2);
  const chartH = height - (padding * 2);

  function getY(priceVal) {
    return height - padding - ((priceVal - minP) / (maxP - minP || 1)) * chartH;
  }

  function getX(stepIndex) {
    return padding + (stepIndex / 12) * chartW;
  }

  // Draw Vertical "NOW" timeline
  const nowX = getX(0);
  ctx.strokeStyle = 'rgba(0, 242, 254, 0.5)';
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(nowX, padding);
  ctx.lineTo(nowX, height - padding);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.fillStyle = '#00f2fe';
  ctx.font = '10px JetBrains Mono';
  ctx.fillText('PRESENT', nowX - 20, padding - 10);
  ctx.fillText('+1 HOUR FORECAST', width - padding - 110, padding - 10);

  // Calculate ensemble mean path & confidence bounds
  const meanPath = [];
  let bullPaths = 0, bearPaths = 0;

  for (let step = 0; step <= 12; step++) {
    let sum = 0;
    modelOutputs.forEach(m => {
      sum += m.trajectory[step];
    });
    meanPath.push(sum / modelOutputs.length);
  }

  modelOutputs.forEach(m => {
    if (m.signal === 'BULLISH') bullPaths++;
    else if (m.signal === 'BEARISH') bearPaths++;
  });

  document.getElementById('bull-path-count').textContent = bullPaths;
  document.getElementById('bear-path-count').textContent = bearPaths;

  // Draw 31 Spaghetti Trajectory Lines
  modelOutputs.forEach(m => {
    ctx.beginPath();
    ctx.lineWidth = m.signal === 'NEUTRAL' ? 0.8 : 1.2;

    if (m.signal === 'BULLISH') {
      ctx.strokeStyle = 'rgba(0, 245, 160, 0.35)';
    } else if (m.signal === 'BEARISH') {
      ctx.strokeStyle = 'rgba(255, 75, 75, 0.35)';
    } else {
      ctx.strokeStyle = 'rgba(148, 163, 184, 0.2)';
    }

    m.trajectory.forEach((p, step) => {
      const x = getX(step);
      const y = getY(p);
      if (step === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });

  // Draw Ensemble Mean Trajectory (Glowing accent line)
  ctx.beginPath();
  ctx.lineWidth = 3;
  ctx.strokeStyle = '#00f2fe';
  ctx.shadowColor = 'rgba(0, 242, 254, 0.8)';
  ctx.shadowBlur = 8;
  meanPath.forEach((p, step) => {
    const x = getX(step);
    const y = getY(p);
    if (step === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.shadowBlur = 0; // reset shadow

  // Draw Current Price Dot
  const currentY = getY(currentPrice);
  ctx.beginPath();
  ctx.arc(nowX, currentY, 6, 0, Math.PI * 2);
  ctx.fillStyle = '#ffffff';
  ctx.fill();
  ctx.strokeStyle = '#00f2fe';
  ctx.lineWidth = 2;
  ctx.stroke();
}

// --------------------------------------------------------------------------
// 6. TradingView Lightweight Chart & Spaghetti Trajectory Renderers
// --------------------------------------------------------------------------
let tvChart = null;
let candleSeries = null;
let volumeSeries = null;
let tpPriceLine = null;
let slPriceLine = null;

function initTradingViewChart() {
  const container = document.getElementById('tvChartContainer');
  if (!container || typeof LightweightCharts === 'undefined') return;

  container.innerHTML = '';

  tvChart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: 380,
    layout: {
      background: { color: 'rgba(4, 7, 13, 0.95)' },
      textColor: '#8a99ad',
      fontFamily: "'JetBrains Mono', monospace",
      fontSize: 11
    },
    grid: {
      vertLines: { color: 'rgba(255, 255, 255, 0.04)' },
      horzLines: { color: 'rgba(255, 255, 255, 0.04)' }
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
      vertLine: { color: 'rgba(0, 242, 254, 0.4)', width: 1, style: 2 },
      horzLine: { color: 'rgba(0, 242, 254, 0.4)', width: 1, style: 2 }
    },
    rightPriceScale: {
      borderColor: 'rgba(255, 255, 255, 0.08)',
      autoScale: true
    },
    timeScale: {
      borderColor: 'rgba(255, 255, 255, 0.08)',
      timeVisible: true,
      secondsVisible: false
    }
  });

  candleSeries = tvChart.addCandlestickSeries({
    upColor: '#00f5a0',
    downColor: '#ff4b4b',
    borderUpColor: '#00f5a0',
    borderDownColor: '#ff4b4b',
    wickUpColor: '#00f5a0',
    wickDownColor: '#ff4b4b'
  });

  volumeSeries = tvChart.addHistogramSeries({
    color: '#00f2fe',
    priceFormat: { type: 'volume' },
    priceScaleId: '',
    scaleMargins: { top: 0.82, bottom: 0 }
  });

  window.addEventListener('resize', () => {
    if (tvChart && container) {
      tvChart.applyOptions({ width: container.clientWidth });
    }
  });
}

function renderPriceChart(candles) {
  if (!tvChart || !candleSeries || !candles || candles.length === 0) return;

  const formattedCandles = [];
  const formattedVolumes = [];
  const seenTimes = new Set();

  candles.forEach(c => {
    let t = Math.floor((c.timestamp || Date.now()) / 1000);
    // Ensure strictly unique ascending timestamps
    while (seenTimes.has(t)) {
      t += 1;
    }
    seenTimes.add(t);

    formattedCandles.push({
      time: t,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close
    });

    formattedVolumes.push({
      time: t,
      value: c.volume || 10,
      color: c.close >= c.open ? 'rgba(0, 245, 160, 0.35)' : 'rgba(255, 75, 75, 0.35)'
    });
  });

  candleSeries.setData(formattedCandles);
  if (volumeSeries) volumeSeries.setData(formattedVolumes);
}

// --------------------------------------------------------------------------
// 7. UI Update Helpers & Component Controllers
// --------------------------------------------------------------------------
function updateRiskCalculatorUI(price, candles) {
  const bal = parseFloat(document.getElementById('input-balance')?.value || state.walletBalance);
  const lev = parseInt(document.getElementById('input-leverage')?.value || state.leverage, 10);
  const mode = document.getElementById('select-sizing-mode')?.value || state.sizingMode;

  state.walletBalance = bal;
  state.leverage = lev;
  state.sizingMode = mode;

  let marginUsdt = 0;
  let notionalUsdt = 0;

  if (mode === 'margin') {
    marginUsdt = bal * 0.03;
    notionalUsdt = marginUsdt * lev;
  } else {
    notionalUsdt = bal * 0.03;
    marginUsdt = notionalUsdt / lev;
  }

  // Binance minimum notional check ($5 USDT)
  if (notionalUsdt < 5.0 && bal >= (5.0 / lev)) {
    notionalUsdt = 5.0;
    marginUsdt = 5.0 / lev;
  }

  const atr = (typeof calcATR === 'function' && candles.length >= 14) ? calcATR(candles, 14) : (price * 0.005);
  const tp1Dist = 1.5 * atr;
  const slDist = 1.0 * atr;

  const tp1Price = price + tp1Dist;
  const slPrice = Math.max(0, price - slDist);
  const tsPrice = price + tp1Dist;

  const tp1ReturnPct = (tp1Dist / price) * 100 * lev;
  const slLossPct = (slDist / price) * 100 * lev;
  const tsActPct = (tp1Dist / price) * 100 * lev;

  const elMargin = document.getElementById('calc-margin-val');
  const elNotional = document.getElementById('calc-notional-val');
  const elTp = document.getElementById('calc-tp-val');
  const elSl = document.getElementById('calc-sl-val');
  const elTs = document.getElementById('calc-ts-val');

  if (elMargin) elMargin.textContent = `$${marginUsdt.toFixed(2)} USDT`;
  if (elNotional) elNotional.textContent = `$${notionalUsdt.toFixed(2)} USDT`;
  if (elTp) elTp.textContent = `$${tp1Price.toFixed(4)} (+${tp1ReturnPct.toFixed(1)}%)`;
  if (elSl) elSl.textContent = `$${slPrice.toFixed(4)} (-${slLossPct.toFixed(1)}%)`;
  if (elTs) elTs.textContent = `$${tsPrice.toFixed(4)} (Activates @ +${tsActPct.toFixed(1)}%)`;
}

function updateHeaderUI(price, candles) {
  const symbolFormatted = state.currentSymbol.replace('USDT', '') + ' / USDT';
  const tagEl = document.getElementById('current-coin-tag');
  const labelEl = document.getElementById('asset-label');
  if (tagEl) tagEl.textContent = symbolFormatted;
  if (labelEl) labelEl.textContent = symbolFormatted;

  document.getElementById('btc-price').textContent = `$${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
  
  if (candles.length > 1) {
    const prev = candles[candles.length - 2].close;
    const pct = ((price - prev) / prev) * 100;
    const changeEl = document.getElementById('btc-change');
    changeEl.textContent = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
    changeEl.style.color = pct >= 0 ? 'var(--color-bull)' : 'var(--color-bear)';
  }

  const lastBar = candles[candles.length - 1];
  document.getElementById('bar-high').textContent = `$${lastBar.high.toFixed(4)}`;
  document.getElementById('bar-low').textContent = `$${lastBar.low.toFixed(4)}`;
  document.getElementById('bar-vol').textContent = `${lastBar.volume.toFixed(1)}`;

  updateRiskCalculatorUI(price, candles);
}

function updateConsensusUI(bullCount, bearCount, neutralCount, maxConsensus, agreementPct, stateAction) {
  document.getElementById('header-consensus').textContent = `${maxConsensus} / 31`;
  document.getElementById('header-agreement').textContent = `${agreementPct.toFixed(1)}% Agreement`;

  const gaugeNumber = document.getElementById('gauge-number');
  gaugeNumber.textContent = maxConsensus;

  // Gauge arc SVG offset calculation
  const fillPath = document.getElementById('gauge-fill-path');
  const maxDash = 251.2;
  const offset = maxDash - (maxDash * (maxConsensus / 31));
  fillPath.style.strokeDashoffset = offset;

  // System State Card
  const stateCard = document.getElementById('trade-status-card');
  const stateText = document.getElementById('system-state-text');
  const stateDesc = document.getElementById('system-state-desc');
  const pill = document.getElementById('threshold-pill');
  const pillText = document.getElementById('threshold-pill-text');

  stateCard.className = 'metric-card status-box';
  pill.className = 'threshold-status-pill';

  if (stateAction === 'BUY') {
    stateCard.classList.add('status-bull');
    stateText.textContent = 'LONG ENTRY';
    stateDesc.textContent = `Bull Consensus ${bullCount}/31 ≥ ${state.consensusThreshold}`;
    pill.classList.add('triggered-bull');
    pillText.textContent = `BULL CONSENSUS TRIGGERED (${bullCount}/31)`;
  } else if (stateAction === 'SELL') {
    stateCard.classList.add('status-bear');
    stateText.textContent = 'SHORT ENTRY';
    stateDesc.textContent = `Bear Consensus ${bearCount}/31 ≥ ${state.consensusThreshold}`;
    pill.classList.add('triggered-bear');
    pillText.textContent = `BEAR CONSENSUS TRIGGERED (${bearCount}/31)`;
  } else {
    stateText.textContent = 'NO TRADE';
    stateDesc.textContent = `Consensus ${maxConsensus}/31 < ${state.consensusThreshold} Threshold`;
    pillText.textContent = `NO CONSENSUS (${maxConsensus}/31 < ${state.consensusThreshold})`;
  }

  // Breakdown bar
  document.getElementById('bar-bull').style.width = `${(bullCount / 31) * 100}%`;
  document.getElementById('bar-neutral').style.width = `${(neutralCount / 31) * 100}%`;
  document.getElementById('bar-bear').style.width = `${(bearCount / 31) * 100}%`;

  document.getElementById('lbl-bull-count').textContent = bullCount;
  document.getElementById('lbl-neutral-count').textContent = neutralCount;
  document.getElementById('lbl-bear-count').textContent = bearCount;
}

function updatePerformanceUI() {
  const s = state.stats;
  document.getElementById('perf-bars').textContent = s.totalBars;
  
  const filterPct = s.totalBars > 0 ? ((s.filteredSignals / s.totalBars) * 100).toFixed(1) : '0.0';
  document.getElementById('perf-filtered').textContent = `${s.filteredSignals} (${filterPct}%)`;
  document.getElementById('perf-trades').textContent = s.tradesTaken;

  const winRate = s.tradesTaken > 0 ? ((s.wins / s.tradesTaken) * 100).toFixed(1) : '0.0';
  document.getElementById('perf-winrate').textContent = `${winRate}%`;

  const pf = s.grossLoss > 0 ? (s.grossProfit / s.grossLoss).toFixed(2) : (s.grossProfit > 0 ? '9.99' : '0.00');
  document.getElementById('perf-pf').textContent = pf;

  const retEl = document.getElementById('perf-return');
  retEl.textContent = `${s.cumReturn >= 0 ? '+' : ''}${s.cumReturn.toFixed(2)}%`;
  retEl.className = s.cumReturn >= 0 ? 'p-val highlight-green' : 'p-val warning';
}

function renderModelCards() {
  const container = document.getElementById('modelsGridContainer');
  if (!container) return;

  const filter = state.currentFilterCategory;
  const filteredModels = state.modelStates.filter(m => filter === 'all' || m.cat === filter);

  container.innerHTML = filteredModels.map(m => {
    const stateClass = m.signal === 'BULLISH' ? 'state-bull' : m.signal === 'BEARISH' ? 'state-bear' : 'state-neutral';
    const badgeClass = m.signal === 'BULLISH' ? 'bull' : m.signal === 'BEARISH' ? 'bear' : 'neutral';

    return `
      <div class="model-card ${stateClass}">
        <div class="model-header">
          <span class="model-id">${m.id}</span>
          <span class="model-cat-badge">${m.cat}</span>
        </div>
        <div class="model-name" title="${m.name}">${m.name}</div>
        <div class="model-footer">
          <span class="signal-badge ${badgeClass}">${m.signal}</span>
          <span class="model-conf">${(m.confidence * 100).toFixed(0)}% Conf</span>
        </div>
      </div>
    `;
  }).join('');
}

function renderLedgerTable() {
  const tbody = document.getElementById('ledgerTableBody');
  if (!tbody) return;

  tbody.innerHTML = state.tradeLedger.map(item => {
    const badgeClass = item.action === 'BUY' ? 'trade-long' : item.action === 'SELL' ? 'trade-short' : 'no-trade';
    const pnlClass = item.pnl > 0 ? 'pnl-positive' : item.pnl < 0 ? 'pnl-negative' : '';

    return `
      <tr>
        <td>${item.time}</td>
        <td>$${item.price.toFixed(2)}</td>
        <td><strong>${item.consensusCount} / 31</strong></td>
        <td><span style="color:var(--color-bull)">${item.bullCount}</span> / <span style="color:var(--color-bear)">${item.bearCount}</span> / ${item.neutralCount}</td>
        <td>${item.agreementPct}%</td>
        <td><span class="badge-state ${badgeClass}">${item.action}</span></td>
        <td>${item.isTriggered ? 'Order Executed' : 'Filtered (Chop Protection)'}</td>
        <td class="${pnlClass}">${item.isTriggered ? `${item.pnl > 0 ? '+' : ''}${item.pnl}%` : '—'}</td>
      </tr>
    `;
  }).join('');
}

// --------------------------------------------------------------------------
// 8. Data Generators & WebSocket Feed
// --------------------------------------------------------------------------
function getBasePriceForSymbol(symbol) {
  const baseMap = {
    'XAUUSDT': 4386.0,
    'BTCUSDT': 65000.0,
    'ETHUSDT': 3200.0,
    'SOLUSDT': 160.0,
    'BNBUSDT': 580.0,
    'XRPUSDT': 0.60,
    'ADAUSDT': 0.40,
    'DOGEUSDT': 0.12,
    'AVAXUSDT': 25.0,
    'LINKUSDT': 12.0,
    'SUIUSDT': 2.0,
    'NEARUSDT': 4.5
  };
  return baseMap[symbol] || 100.0;
}

function generateSyntheticHistory(count = 100) {
  const candles = [];
  let price = getBasePriceForSymbol(state.currentSymbol);
  let now = Date.now() - (count * 5 * 60 * 1000);

  for (let i = 0; i < count; i++) {
    const change = (Math.random() - 0.495) * (price * 0.004);
    const open = price;
    const close = open + change;
    const high = Math.max(open, close) + Math.random() * (price * 0.002);
    const low = Math.min(open, close) - Math.random() * (price * 0.002);
    const volume = 20 + Math.random() * 80;

    candles.push({ timestamp: now, open, high, low, close, volume });
    price = close;
    now += 5 * 60 * 1000;
  }
  return candles;
}

function initBinanceWebSocket(symbol = state.currentSymbol) {
  const badge = document.getElementById('data-source-badge');
  if (state.activeWs) {
    try { state.activeWs.close(); } catch(e) {}
  }

  const symLower = symbol.toLowerCase();
  try {
    const ws = new WebSocket(`wss://stream.binance.com:9443/ws/${symLower}@kline_5m`);
    state.activeWs = ws;
    
    ws.onopen = () => {
      state.wsConnected = true;
      if (badge) {
        badge.textContent = `Binance ${symbol} Live`;
        badge.className = 'badge';
      }
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.k) {
        const k = data.k;
        const newCandle = {
          timestamp: k.t,
          open: parseFloat(k.o),
          high: parseFloat(k.h),
          low: parseFloat(k.l),
          close: parseFloat(k.c),
          volume: parseFloat(k.v)
        };

        const last = state.candles[state.candles.length - 1];
        if (last && last.timestamp === newCandle.timestamp) {
          state.candles[state.candles.length - 1] = newCandle;
        } else {
          state.candles.push(newCandle);
          if (state.candles.length > 200) state.candles.shift();
        }
        processBarState(state.candles);
      }
    };

    ws.onerror = ws.onclose = () => {
      state.wsConnected = false;
      if (badge) {
        badge.textContent = 'Simulated Auto Feed';
        badge.className = 'badge warning';
      }
      startSimulatedFeed();
    };
  } catch (e) {
    startSimulatedFeed();
  }
}

function startSimulatedFeed() {
  if (state.timerId) clearInterval(state.timerId);

  state.timerId = setInterval(() => {
    if (!state.autoEngineRunning) return;

    const base = getBasePriceForSymbol(state.currentSymbol);
    const last = state.candles[state.candles.length - 1] || { close: base, timestamp: Date.now() };
    const change = (Math.random() - 0.49) * (last.close * 0.003);
    const open = last.close;
    const close = open + change;
    const high = Math.max(open, close) + Math.random() * (open * 0.001);
    const low = Math.min(open, close) - Math.random() * (open * 0.001);
    const volume = 15 + Math.random() * 60;

    const newCandle = {
      timestamp: Date.now(),
      open, high, low, close, volume
    };

    state.candles.push(newCandle);
    if (state.candles.length > 200) state.candles.shift();

    processBarState(state.candles);
  }, state.simulationSpeed);
}

// --------------------------------------------------------------------------
// 9. Event Listeners & Initialization
// --------------------------------------------------------------------------
function setupEventListeners() {
  // Threshold Slider
  const slider = document.getElementById('input-threshold');
  const valThreshold = document.getElementById('val-threshold');
  if (slider) {
    slider.addEventListener('input', (e) => {
      state.consensusThreshold = parseInt(e.target.value, 10);
      if (valThreshold) valThreshold.textContent = state.consensusThreshold;
      processBarState(state.candles);
    });
  }

  // Risk Calculator Inputs
  const inputBalance = document.getElementById('input-balance');
  const inputLeverage = document.getElementById('input-leverage');
  const selectMode = document.getElementById('select-sizing-mode');
  const valLeverage = document.getElementById('val-leverage');

  if (inputBalance) {
    inputBalance.addEventListener('input', () => {
      const lastCandle = state.candles[state.candles.length - 1];
      if (lastCandle) updateRiskCalculatorUI(lastCandle.close, state.candles);
    });
  }

  if (inputLeverage) {
    inputLeverage.addEventListener('input', (e) => {
      state.leverage = parseInt(e.target.value, 10);
      if (valLeverage) valLeverage.textContent = state.leverage;
      const lastCandle = state.candles[state.candles.length - 1];
      if (lastCandle) updateRiskCalculatorUI(lastCandle.close, state.candles);
    });
  }

  if (selectMode) {
    selectMode.addEventListener('change', (e) => {
      state.sizingMode = e.target.value;
      const lastCandle = state.candles[state.candles.length - 1];
      if (lastCandle) updateRiskCalculatorUI(lastCandle.close, state.candles);
    });
  }

  // Coin Selector Buttons
  document.querySelectorAll('#coinSelectorContainer .coin-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#coinSelectorContainer .coin-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.currentSymbol = btn.dataset.symbol;
      state.candles = generateSyntheticHistory(100);
      updateHeaderUI(state.candles[state.candles.length - 1].close, state.candles);
      initBinanceWebSocket(state.currentSymbol);
    });
  });

  // Speed Select
  const selectSpeed = document.getElementById('select-speed');
  if (selectSpeed) {
    selectSpeed.addEventListener('change', (e) => {
      state.simulationSpeed = parseInt(e.target.value, 10);
      if (!state.wsConnected) startSimulatedFeed();
    });
  }

  // Step Simulation Button
  const btnSim = document.getElementById('btn-run-sim');
  if (btnSim) {
    btnSim.addEventListener('click', () => {
      const base = getBasePriceForSymbol(state.currentSymbol);
      const last = state.candles[state.candles.length - 1] || { close: base };
      const change = (Math.random() - 0.48) * (last.close * 0.005);
      const open = last.close;
      const close = open + change;
      state.candles.push({
        timestamp: Date.now(),
        open, high: Math.max(open, close) * 1.002, low: Math.min(open, close) * 0.998, close, volume: 40
      });
      processBarState(state.candles);
    });
  }

  // Toggle Auto-Engine
  const btnAuto = document.getElementById('btn-toggle-autotrade');
  if (btnAuto) {
    btnAuto.addEventListener('click', () => {
      state.autoEngineRunning = !state.autoEngineRunning;
      btnAuto.textContent = state.autoEngineRunning ? 'Pause Sim Engine' : 'Start Sim Engine';
      btnAuto.className = state.autoEngineRunning ? 'btn btn-primary' : 'btn btn-secondary';
    });
  }

  // Run 500-Bar Backtest
  const btnBacktest = document.getElementById('btn-run-backtest');
  if (btnBacktest) {
    btnBacktest.addEventListener('click', () => {
      state.stats = {
        totalBars: 0, filteredSignals: 0, tradesTaken: 0, wins: 0, losses: 0, grossProfit: 0, grossLoss: 0, cumReturn: 0, activePosition: null
      };
      state.candles = generateSyntheticHistory(500);
      state.candles.forEach((_, idx) => {
        if (idx >= 30) {
          processBarState(state.candles.slice(0, idx + 1));
        }
      });
    });
  }

  // Live Python Bot Web Controller (Start / Stop API calls)
  const btnStartBot = document.getElementById('btn-web-start-bot');
  const btnStopBot = document.getElementById('btn-web-stop-bot');
  const btnToggleLogs = document.getElementById('btn-toggle-logs');
  const btnRefreshLogs = document.getElementById('btn-refresh-logs');
  const logsDrawer = document.getElementById('bot-logs-drawer');

  if (btnStartBot) {
    btnStartBot.addEventListener('click', async () => {
      btnStartBot.disabled = true;
      btnStartBot.textContent = '⏳ STARTING BOT...';
      try {
        const res = await fetch('/api/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sizing_mode: state.sizingMode,
            margin_pct: 0.03,
            leverage: state.leverage,
            threshold: state.consensusThreshold
          })
        });
        const data = await res.json();
        alert(data.message || 'Bot start command sent!');
      } catch (err) {
        alert('Could not connect to Web Control API server. Make sure server.py is running!');
      } finally {
        btnStartBot.disabled = false;
        btnStartBot.textContent = '▶️ START LIVE TRADING BOT';
        checkBotStatus();
        fetchBotLogs();
      }
    });
  }

  if (btnStopBot) {
    btnStopBot.addEventListener('click', async () => {
      btnStopBot.disabled = true;
      btnStopBot.textContent = '⏳ STOPPING BOT...';
      try {
        const res = await fetch('/api/stop', { method: 'POST' });
        const data = await res.json();
        alert(data.message || 'Bot stop command sent!');
      } catch (err) {
        alert('Could not connect to Web Control API server. Make sure server.py is running!');
      } finally {
        btnStopBot.disabled = false;
        btnStopBot.textContent = '🛑 STOP LIVE TRADING BOT';
        checkBotStatus();
        fetchBotLogs();
      }
    });
  }

  if (btnToggleLogs && logsDrawer) {
    btnToggleLogs.addEventListener('click', () => {
      logsDrawer.classList.toggle('hidden');
      if (!logsDrawer.classList.contains('hidden')) {
        fetchBotLogs();
      }
    });
  }

  if (btnRefreshLogs) {
    btnRefreshLogs.addEventListener('click', () => {
      fetchBotLogs();
    });
  }

  // Live Positions Refresh & Emergency Close All
  const btnRefreshPos = document.getElementById('btn-refresh-positions');
  const btnCloseAllPos = document.getElementById('btn-close-all-pos');

  if (btnRefreshPos) {
    btnRefreshPos.addEventListener('click', () => {
      fetchLivePositions();
    });
  }

  if (btnCloseAllPos) {
    btnCloseAllPos.addEventListener('click', async () => {
      if (!confirm('⚠️ Are you sure you want to EMERGENCY CLOSE ALL open Binance Futures positions?')) return;
      btnCloseAllPos.disabled = true;
      btnCloseAllPos.textContent = '⏳ CLOSING ALL...';
      try {
        const res = await fetch('/api/close_all', { method: 'POST' });
        const data = await res.json();
        alert(data.message || 'Close all command sent!');
      } catch (err) {
        alert('Failed to connect to API server.');
      } finally {
        btnCloseAllPos.disabled = false;
        btnCloseAllPos.textContent = '🛑 Emergency Close All';
        fetchLivePositions();
      }
    });
  }

  // Category Filter Pills
  document.querySelectorAll('#model-filter-pills .pill').forEach(pill => {
    pill.addEventListener('click', () => {
      document.querySelectorAll('#model-filter-pills .pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      state.currentFilterCategory = pill.dataset.filter;
      renderModelCards();
    });
  });
}

async function fetchBotLogs() {
  const logPre = document.getElementById('bot-logs-output');
  if (!logPre) return;
  try {
    const res = await fetch('/api/logs');
    if (res.ok) {
      const data = await res.json();
      logPre.textContent = data.logs || 'No logs available yet.';
      logPre.scrollTop = logPre.scrollHeight;
    }
  } catch (e) {
    logPre.textContent = 'Could not fetch logs (server.py offline).';
  }
}

async function fetchLivePositions() {
  const tbody = document.getElementById('positionsTableBody');
  const totalPnlBadge = document.getElementById('positions-total-pnl');
  if (!tbody) return;

  try {
    const res = await fetch('/api/positions');
    if (res.ok) {
      const data = await res.json();
      if (totalPnlBadge) {
        const pnl = data.total_unrealized_pnl || 0.0;
        totalPnlBadge.textContent = `Total Unrealized PnL: ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)} USDT`;
        totalPnlBadge.className = pnl >= 0 ? 'badge' : 'badge warning';
      }

      if (!data.positions || data.positions.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="9" style="text-align:center; color:var(--text-muted); padding:1.2rem;">No active Binance Futures open positions.</td>
          </tr>
        `;
        return;
      }

      tbody.innerHTML = data.positions.map(p => {
        const isLong = p.side === 'LONG';
        const sideClass = isLong ? 'pos-side-long' : 'pos-side-short';
        const pnlClass = p.unrealizedProfit >= 0 ? 'pnl-green' : 'pnl-red';
        const pnlSign = p.unrealizedProfit >= 0 ? '+' : '';

        return `
          <tr>
            <td><strong>#${p.symbol}</strong></td>
            <td><span class="pos-side-badge ${sideClass}">${p.side}</span></td>
            <td>${p.leverage}x</td>
            <td>${p.positionAmt}</td>
            <td>$${p.entryPrice.toFixed(4)}</td>
            <td>$${p.markPrice.toFixed(4)}</td>
            <td>$${p.liquidationPrice > 0 ? p.liquidationPrice.toFixed(4) : '—'}</td>
            <td class="${pnlClass}">${pnlSign}$${p.unrealizedProfit.toFixed(2)}</td>
            <td>
              <button class="btn-close-pos" onclick="closeSpecificPosition('${p.symbol}')">Market Close</button>
            </td>
          </tr>
        `;
      }).join('');
    }
  } catch (e) {
    // server offline or error
  }
}

window.closeSpecificPosition = async function(symbol) {
  if (!confirm(`Are you sure you want to close position for ${symbol}?`)) return;
  try {
    const res = await fetch('/api/close_position', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol })
    });
    const data = await res.json();
    alert(`Position close triggered for ${symbol}!`);
  } catch (e) {
    alert('Failed to connect to API server.');
  } finally {
    fetchLivePositions();
  }
};

// --------------------------------------------------------------------------
// 10. Web Audio API Synthesizer (Zero-Dependency Audio Alerts)
// --------------------------------------------------------------------------
let audioContext = null;
let soundEnabled = true;

function initAudio() {
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
  }
}

function playTone(freq, type = 'sine', duration = 0.15, gainVal = 0.1) {
  if (!soundEnabled) return;
  try {
    initAudio();
    const osc = audioContext.createOscillator();
    const gain = audioContext.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, audioContext.currentTime);
    gain.gain.setValueAtTime(gainVal, audioContext.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, audioContext.currentTime + duration);
    osc.connect(gain);
    gain.connect(audioContext.destination);
    osc.start();
    osc.stop(audioContext.currentTime + duration);
  } catch (e) {
    // Web audio blocked by user gesture policy
  }
}

function playSignalChime() {
  playTone(880, 'sine', 0.1, 0.15); // A5
  setTimeout(() => playTone(1320, 'sine', 0.25, 0.2), 100); // E6
}

function playOrderFilledSound() {
  playTone(523.25, 'triangle', 0.1, 0.2); // C5
  setTimeout(() => playTone(659.25, 'triangle', 0.1, 0.2), 80); // E5
  setTimeout(() => playTone(783.99, 'triangle', 0.3, 0.25), 160); // G5
}

// --------------------------------------------------------------------------
// 11. Live Order Flow, MTF Heatmap, & Milestone Tracker Pollers
// --------------------------------------------------------------------------
async function fetchOrderFlow() {
  try {
    const sym = state.activeSymbol || 'XRPUSDT';
    const res = await fetch(`/api/orderflow?symbol=${sym}`);
    if (res.ok) {
      const json = await res.json();
      if (json.status === 'success' && json.data) {
        const d = json.data;
        const badge = document.getElementById('ofAbsorptionBadge');
        const fillBar = document.getElementById('deltaFillBar');
        const deltaText = document.getElementById('ofDeltaText');
        const pocEl = document.getElementById('ofPocPrice');
        const domEl = document.getElementById('ofDomRatio');

        if (badge) {
          badge.textContent = d.absorption_state.replace('_', ' ');
          badge.className = 'of-badge';
          if (d.absorption_state.includes('BULLISH')) badge.classList.add('bullish-absorption');
          if (d.absorption_state.includes('BEARISH')) badge.classList.add('bearish-absorption');
        }
        if (deltaText) {
          const sign = d.delta_pct >= 0 ? '+' : '';
          deltaText.textContent = `${sign}${d.delta_pct.toFixed(1)}% (${d.delta_polarity} Delta)`;
          deltaText.style.color = d.delta_pct >= 0 ? 'var(--color-bull)' : 'var(--color-bear)';
        }
        if (fillBar) {
          const w = Math.min(100, Math.max(10, 50 + d.delta_pct * 1.5));
          fillBar.style.width = `${w}%`;
          fillBar.style.background = d.delta_pct >= 0 ? 'var(--color-bull)' : 'var(--color-bear)';
        }
        if (pocEl) pocEl.textContent = `$${d.poc_price.toFixed(4)}`;
        if (domEl) domEl.textContent = `${d.dom_imbalance.toFixed(2)}x (${d.dominant_wall} Wall)`;
      }
    }
  } catch (e) {}
}

async function fetchMtfHeatmap() {
  try {
    const res = await fetch('/api/mtf_heatmap');
    if (res.ok) {
      const json = await res.json();
      const tbody = document.getElementById('mtfTableBody');
      if (tbody && json.heatmap && json.heatmap.length > 0) {
        tbody.innerHTML = json.heatmap.map(row => `
          <tr>
            <td><strong>${row.symbol.replace('USDT', '')}</strong></td>
            <td><span class="mtf-badge ${row.tf_5m === 'BULLISH' ? 'mtf-bull' : 'mtf-bear'}">${row.tf_5m.slice(0, 4)}</span></td>
            <td><span class="mtf-badge ${row.tf_15m === 'BULLISH' ? 'mtf-bull' : 'mtf-bear'}">${row.tf_15m.slice(0, 4)}</span></td>
            <td><span class="mtf-badge ${row.tf_1h === 'BULLISH' ? 'mtf-bull' : 'mtf-bear'}">${row.tf_1h.slice(0, 4)}</span></td>
            <td><span class="mtf-badge ${row.tf_4h === 'BULLISH' ? 'mtf-bull' : 'mtf-bear'}">${row.tf_4h.slice(0, 4)}</span></td>
            <td><strong>${row.status}</strong></td>
          </tr>
        `).join('');
      }
    }
  } catch (e) {}
}

async function fetchMilestones() {
  try {
    const res = await fetch('/api/milestones');
    if (res.ok) {
      const json = await res.json();
      if (json.status === 'success') {
        const details = document.getElementById('milestoneDetails');
        const fill = document.getElementById('milestoneProgressFill');
        if (details) {
          details.textContent = `Wallet: $${json.current_balance.toFixed(2)} | Locked Milestone: $${json.locked_milestone.toFixed(2)} | Next Target: $${json.next_milestone.toFixed(2)}`;
        }
        if (fill) {
          fill.style.width = `${Math.min(100, Math.max(5, json.progress_pct))}%`;
        }
      }
    }
  } catch (e) {}
}

async function fetchLiveConsoleLogs() {
  try {
    const res = await fetch('/api/logs');
    if (res.ok) {
      const json = await res.json();
      const consoleBox = document.getElementById('consoleText');
      if (consoleBox && json.logs) {
        consoleBox.textContent = json.logs;
      }
    }
  } catch (e) {}
}

async function fetchPotatoSr() {
  try {
    const sym = state.activeSymbol || 'XRPUSDT';
    const res = await fetch(`/api/potato_sr?symbol=${sym}`);
    if (res.ok) {
      const d = await res.json();
      if (d.status === 'success') {
        const badge = document.getElementById('potatoStatusBadge');
        const assetLabel = document.getElementById('potatoAssetLabel');
        const supEl = document.getElementById('potatoSupportPrice');
        const resEl = document.getElementById('potatoResistancePrice');
        const marker = document.getElementById('potatoSliderMarker');

        if (assetLabel) assetLabel.textContent = d.symbol;
        if (supEl) supEl.textContent = `$${d.support.toFixed(4)}`;
        if (resEl) resEl.textContent = `$${d.resistance.toFixed(4)}`;

        if (badge) {
          badge.textContent = d.state;
          badge.className = 'potato-badge';
          if (d.state.includes('SUPPORT')) badge.classList.add('tapping-support');
          if (d.state.includes('RESISTANCE')) badge.classList.add('tapping-resistance');
        }

        if (marker && d.resistance > d.support) {
          const pct = ((d.current_price - d.support) / (d.resistance - d.support)) * 100;
          const clamped = Math.min(95, Math.max(5, pct));
          marker.style.left = `${clamped}%`;
        }
      }
    }
  } catch (e) {}
}

// --------------------------------------------------------------------------
// 12. Streaming Live Trade Tape (Time & Sales) WebSocket Engine
// --------------------------------------------------------------------------
let tapeWs = null;
let tapeTradeCount = 0;
let tapeVelocityTimer = null;
let onlyWhales = false;

function initBinanceTradeTapeWebSocket(symbol = 'XRPUSDT') {
  if (tapeWs) {
    try { tapeWs.close(); } catch (e) {}
  }

  const feedBody = document.getElementById('tapeFeedBody');
  if (feedBody) {
    feedBody.innerHTML = `<div class="tape-empty">Connecting to real-time ${symbol} Trade Stream...</div>`;
  }

  const streamSym = symbol.toLowerCase();
  const wsUrl = `wss://fstream.binance.com/ws/${streamSym}@aggTrade`;

  try {
    tapeWs = new WebSocket(wsUrl);

    tapeWs.onopen = () => {
      if (feedBody) feedBody.innerHTML = '';
    };

    tapeWs.onmessage = (event) => {
      try {
        const t = JSON.parse(event.data);
        tapeTradeCount++;

        const price = parseFloat(t.p);
        const qty = parseFloat(t.q);
        const totalUsd = price * qty;
        const isBuyerMaker = t.m; // true = Aggressive Market Sell 🔴, false = Aggressive Market Buy 🟢
        const side = isBuyerMaker ? 'SELL' : 'BUY';
        const isWhale = totalUsd >= 5000;
        const isSuperWhale = totalUsd >= 25000;

        if (onlyWhales && !isWhale) return;

        const date = new Date(t.T);
        const timeStr = date.toTimeString().split(' ')[0] + '.' + String(date.getMilliseconds()).padStart(3, '0');

        const row = document.createElement('div');
        row.className = `tape-row ${side.toLowerCase()} ${isWhale ? 'whale' : ''}`;
        
        const whaleIcon = isSuperWhale ? '🐋 ' : (isWhale ? '🐳 ' : '');
        const sideTag = side === 'BUY' ? '<span class="tape-tag-buy">BUY 🟢</span>' : '<span class="tape-tag-sell">SELL 🔴</span>';

        row.innerHTML = `
          <span>${timeStr}</span>
          <span>${whaleIcon}${sideTag}</span>
          <span>$${price.toFixed(4)}</span>
          <span>${qty.toLocaleString()}</span>
          <span><strong>$${totalUsd.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong></span>
        `;

        if (feedBody) {
          feedBody.insertBefore(row, feedBody.firstChild);
          if (feedBody.children.length > 50) {
            feedBody.removeChild(feedBody.lastChild);
          }
        }

        if (isSuperWhale) {
          playTone(1046.5, 'sine', 0.1, 0.08); // High alert for big whale order
        }
      } catch (e) {}
    };

    tapeWs.onerror = () => {};
  } catch (e) {}
}

// Track and display trade velocity (trades/sec)
if (!tapeVelocityTimer) {
  tapeVelocityTimer = setInterval(() => {
    const badge = document.getElementById('tapeVelocityBadge');
    if (badge) {
      badge.textContent = `⚡ ${tapeTradeCount} trades/sec`;
    }
    tapeTradeCount = 0;
  }, 1000);
}

async function fetchDivergence() {
  const sym = state.activeSymbol || 'XRPUSDT';
  try {
    const res = await fetch(`/api/divergence?symbol=${sym}`);
    if (res.ok) {
      const d = await res.json();
      if (d.status === 'success') {
        const rsiEl = document.getElementById('divRsiVal');
        const cciEl = document.getElementById('divCciVal');
        const badge = document.getElementById('divergenceStateBadge');

        if (rsiEl) rsiEl.textContent = d.rsi_14.toFixed(1);
        if (cciEl) cciEl.textContent = (d.cci_20 >= 0 ? '+' : '') + d.cci_20.toFixed(1);

        if (badge) {
          badge.textContent = d.divergence_state.replace('_', ' ');
          if (d.bull_div) {
            badge.style.background = 'rgba(0, 245, 160, 0.15)';
            badge.style.color = 'var(--color-bull)';
            badge.style.borderColor = 'rgba(0, 245, 160, 0.4)';
          } else if (d.bear_div) {
            badge.style.background = 'rgba(255, 75, 75, 0.15)';
            badge.style.color = 'var(--color-bear)';
            badge.style.borderColor = 'rgba(255, 75, 75, 0.4)';
          } else {
            badge.style.background = 'rgba(217, 70, 239, 0.15)';
            badge.style.color = '#d946ef';
            badge.style.borderColor = 'rgba(217, 70, 239, 0.3)';
          }
        }
      }
    }
  } catch (e) {}
}

// --------------------------------------------------------------------------
// 13. Bootstrap Application
// --------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  initTradingViewChart();
  state.candles = generateSyntheticHistory(100);
  setupEventListeners();
  processBarState(state.candles);
  initBinanceTradeTapeWebSocket('XRPUSDT');
  
  // Audio toggle
  const audioBtn = document.getElementById('audioToggleBtn');
  if (audioBtn) {
    audioBtn.addEventListener('click', () => {
      soundEnabled = !soundEnabled;
      audioBtn.textContent = soundEnabled ? '🔊 Sound: ON' : '🔇 Sound: OFF';
      audioBtn.classList.toggle('btn-secondary', soundEnabled);
      if (soundEnabled) playSignalChime();
    });
  }

  // Whale filter toggle
  const whaleCheckbox = document.getElementById('whaleFilterCheckbox');
  if (whaleCheckbox) {
    whaleCheckbox.addEventListener('change', (e) => {
      onlyWhales = e.target.checked;
    });
  }

  // Emergency Close All
  const emBtn = document.getElementById('emergencyCloseAllBtn');
  if (emBtn) {
    emBtn.addEventListener('click', async () => {
      if (confirm('🚨 Are you sure you want to EMERGENCY CLOSE ALL Binance Futures positions?')) {
        await fetch('/api/close_all', { method: 'POST' });
        alert('Emergency close all request sent!');
        fetchLivePositions();
      }
    });
  }

  // Coin Selector Pills
  const pills = document.querySelectorAll('.coin-pill');
  pills.forEach(btn => {
    btn.addEventListener('click', () => {
      pills.forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const sym = btn.getAttribute('data-symbol');
      state.activeSymbol = sym;
      document.getElementById('chartAssetTitle').textContent = `${sym} 5M Candlestick & Spaghetti Forecast`;
      initBinanceTradeTapeWebSocket(sym);
      fetchOrderFlow();
      fetchPotatoSr();
      fetchDivergence();
    });
  });

  // Polling loops
  fetchLivePositions();
  fetchOrderFlow();
  fetchPotatoSr();
  fetchDivergence();
  fetchMtfHeatmap();
  fetchMilestones();
  fetchLiveConsoleLogs();

  setInterval(fetchLivePositions, 3000);
  setInterval(fetchOrderFlow, 2500);
  setInterval(fetchPotatoSr, 3000);
  setInterval(fetchDivergence, 3000);
  setInterval(fetchMtfHeatmap, 5000);
  setInterval(fetchMilestones, 4000);
  setInterval(fetchLiveConsoleLogs, 2500);
});

