import React, { useEffect, useRef, useState } from 'react';
import { createChart, CandlestickSeries } from 'lightweight-charts';
import type { IChartApi, ISeriesApi, CandlestickData } from 'lightweight-charts';
import { binanceWsManager } from '../services/binanceWs';
import type { LiveTrade } from '../types';

interface TradingChartProps {
  symbol: string;
  timeframe: string;
  onTradeTick?: (trade: LiveTrade) => void;
}

export const TradingChart: React.FC<TradingChartProps> = ({
  symbol,
  timeframe,
  onTradeTick,
}) => {
  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  const [currentPrice, setCurrentPrice] = useState<number>(0);
  const [priceChangePct, setPriceChangePct] = useState<number>(0);

  // 1. Fetch initial Kline history from Binance REST API
  useEffect(() => {
    let isMounted = true;

    const fetchHistoricalKlines = async () => {
      try {
        const url = `https://fapi.binance.com/fapi/v1/klines?symbol=${symbol}&interval=${timeframe}&limit=120`;
        const res = await fetch(url);
        const data = await res.json();

        if (Array.isArray(data) && isMounted) {
          const formatted: CandlestickData[] = data.map((k: any) => ({
            time: Math.floor(k[0] / 1000) as any,
            open: parseFloat(k[1]),
            high: parseFloat(k[2]),
            low: parseFloat(k[3]),
            close: parseFloat(k[4]),
          }));

          if (candleSeriesRef.current) {
            candleSeriesRef.current.setData(formatted);
          }

          if (formatted.length > 0) {
            const last = formatted[formatted.length - 1];
            const first = formatted[0];
            setCurrentPrice(last.close);
            const chg = ((last.close - first.open) / first.open) * 100;
            setPriceChangePct(chg);
          }
        }
      } catch (err) {
        console.error('Failed to load klines', err);
      }
    };

    fetchHistoricalKlines();

    return () => {
      isMounted = false;
    };
  }, [symbol, timeframe]);

  // 2. Initialize Lightweight Chart container
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: 380,
      layout: {
        background: { color: '#090d14' },
        textColor: '#8b949e',
        fontSize: 11,
        fontFamily: 'JetBrains Mono, monospace',
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.04)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.04)' },
      },
      crosshair: {
        mode: 1,
      },
      timeScale: {
        borderColor: 'rgba(255, 255, 255, 0.08)',
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.08)',
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#00f090',
      downColor: '#ff3366',
      borderVisible: false,
      wickUpColor: '#00f090',
      wickDownColor: '#ff3366',
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries as any;

    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, []);

  // 3. Connect real-time WebSocket for live candle & trade updates
  useEffect(() => {
    binanceWsManager.subscribe(
      symbol,
      timeframe,
      (trade: LiveTrade) => {
        setCurrentPrice(trade.price);
        if (onTradeTick) {
          onTradeTick(trade);
        }
      },
      (bar: any) => {
        if (candleSeriesRef.current) {
          candleSeriesRef.current.update({
            time: bar.time as any,
            open: bar.open,
            high: bar.high,
            low: bar.low,
            close: bar.close,
          });
        }
        setCurrentPrice(bar.close);
      }
    );

    return () => {
      binanceWsManager.unsubscribe();
    };
  }, [symbol, timeframe, onTradeTick]);

  return (
    <section className="panel chart-panel">
      <div className="panel-header">
        <div className="chart-title-group">
          <h2>{symbol} {timeframe.toUpperCase()} Candlestick & Spaghetti Forecast</h2>
          <div className="live-price-tag">
            <span>${currentPrice > 0 ? currentPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 }) : '---'}</span>
            <span className={`change-tag ${priceChangePct >= 0 ? 'pos' : 'neg'}`}>
              {priceChangePct >= 0 ? `+${priceChangePct.toFixed(2)}%` : `${priceChangePct.toFixed(2)}%`}
            </span>
          </div>
        </div>
        <div className="chart-controls">
          <span className="badge badge-outline">TradingView Engine</span>
        </div>
      </div>

      <div className="chart-wrapper">
        <div ref={chartContainerRef} style={{ width: '100%', height: '380px' }} />
      </div>
    </section>
  );
};
