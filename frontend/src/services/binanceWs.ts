import type { LiveTrade } from '../types';

export class BinanceFuturesWebSocket {
  private wsTrade: WebSocket | null = null;
  private wsKline: WebSocket | null = null;
  private currentSymbol: string = '';
  private currentTimeframe: string = '5m';
  private tradeCallback: ((trade: LiveTrade) => void) | null = null;
  private klineCallback: ((kline: any) => void) | null = null;

  public subscribe(
    symbol: string,
    timeframe: string,
    onTrade: (trade: LiveTrade) => void,
    onKline: (kline: any) => void
  ) {
    this.unsubscribe();
    this.currentSymbol = symbol.toLowerCase();
    this.currentTimeframe = timeframe;
    this.tradeCallback = onTrade;
    this.klineCallback = onKline;

    this.connectTradeStream();
    this.connectKlineStream();
  }

  private connectTradeStream() {
    const url = `wss://fstream.binance.com/ws/${this.currentSymbol}@aggTrade`;
    try {
      this.wsTrade = new WebSocket(url);
      this.wsTrade.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data && data.e === 'aggTrade') {
            const price = parseFloat(data.p);
            const qty = parseFloat(data.q);
            const totalUsdt = price * qty;
            const isBuyerMaker = data.m;
            const side: 'BUY' | 'SELL' = isBuyerMaker ? 'SELL' : 'BUY';
            const trade: LiveTrade = {
              id: data.a || Date.now(),
              time: new Date(data.E || Date.now()).toLocaleTimeString(),
              side,
              price,
              qty,
              totalUsdt,
              isWhale: totalUsdt >= 5000,
            };
            if (this.tradeCallback) {
              this.tradeCallback(trade);
            }
          }
        } catch {
          // ignore parsing error
        }
      };

      this.wsTrade.onerror = () => {
        // will handle on close
      };

      this.wsTrade.onclose = () => {
        // attempt reconnect if symbol matches
      };
    } catch {
      // ws not available
    }
  }

  private connectKlineStream() {
    const url = `wss://fstream.binance.com/ws/${this.currentSymbol}@kline_${this.currentTimeframe}`;
    try {
      this.wsKline = new WebSocket(url);
      this.wsKline.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data && data.e === 'kline') {
            const k = data.k;
            const bar = {
              time: Math.floor(k.t / 1000),
              open: parseFloat(k.o),
              high: parseFloat(k.h),
              low: parseFloat(k.l),
              close: parseFloat(k.c),
              volume: parseFloat(k.v),
            };
            if (this.klineCallback) {
              this.klineCallback(bar);
            }
          }
        } catch {
          // ignore
        }
      };
    } catch {
      // ws not available
    }
  }

  public unsubscribe() {
    if (this.wsTrade) {
      this.wsTrade.onmessage = null;
      this.wsTrade.close();
      this.wsTrade = null;
    }
    if (this.wsKline) {
      this.wsKline.onmessage = null;
      this.wsKline.close();
      this.wsKline = null;
    }
    this.tradeCallback = null;
    this.klineCallback = null;
  }
}

export const binanceWsManager = new BinanceFuturesWebSocket();
