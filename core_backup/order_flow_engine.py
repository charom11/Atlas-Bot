#!/usr/bin/env python3
"""
INSTITUTIONAL ORDER FLOW & FOOTPRINT DELTA ABSORPTION ENGINE
============================================================
Real-Time Market Microstructure Analysis for Binance Futures:
1. Aggressive Market vs Passive Limit Orders (AggTrades Stream)
2. Cumulative Volume Delta (CVD) & Bar Delta Imbalance
3. Passive Limit Order Absorption Detector (High Vol at extreme with zero price expansion)
4. Volume Profile Point of Control (POC) & Value Area (VAH/VAL)
5. Delta Divergence (Price New High/Low vs Delta Exhaustion)
"""

import sys
import time
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

class OrderFlowEngine:
    def __init__(self, symbol="XRPUSDT"):
        self.symbol = symbol
        self.absorption_threshold = 2.0  # 2x average volume cluster with < 0.05% price displacement
        
    def fetch_recent_agg_trades(self, limit=1000):
        """
        Fetches the latest aggressive market buyer and seller trades from Binance Futures.
        isBuyerMaker = True  -> Buyer was resting LIMIT order, Seller was AGGRESSIVE MARKET SELL.
        isBuyerMaker = False -> Seller was resting LIMIT order, Buyer was AGGRESSIVE MARKET BUY.
        """
        url = "https://fapi.binance.com/fapi/v1/aggTrades"
        params = {"symbol": self.symbol, "limit": limit}
        try:
            r = requests.get(url, params=params, timeout=4)
            if r.status_code == 200:
                raw = r.json()
                trades = []
                for t in raw:
                    trades.append({
                        'id': t['a'],
                        'price': float(t['p']),
                        'qty': float(t['q']),
                        'timestamp': t['T'],
                        'is_aggressive_sell': t['m'], # isBuyerMaker = True means aggressive sell hit the bid
                        'is_aggressive_buy': not t['m'] # isBuyerMaker = False means aggressive buy lifted the ask
                    })
                return pd.DataFrame(trades)
        except Exception:
            pass
        return None

    def fetch_order_book_dom(self, limit=50):
        """
        Fetches resting passive limit orders in the Depth of Market (DOM).
        """
        url = "https://fapi.binance.com/fapi/v1/depth"
        params = {"symbol": self.symbol, "limit": limit}
        try:
            r = requests.get(url, params=params, timeout=4)
            if r.status_code == 200:
                data = r.json()
                bids = [{'price': float(b[0]), 'qty': float(b[1]), 'type': 'BID_LIMIT'} for b in data.get('bids', [])]
                asks = [{'price': float(a[0]), 'qty': float(a[1]), 'type': 'ASK_LIMIT'} for a in data.get('asks', [])]
                return bids, asks
        except Exception:
            pass
        return [], []

    def analyze_order_flow(self):
        """
        Calculates CVD, Delta Imbalances, Absorption, and POC.
        """
        df_trades = self.fetch_recent_agg_trades(limit=1000)
        bids, asks = self.fetch_order_book_dom(limit=50)
        
        if df_trades is None or len(df_trades) < 50:
            return None

        # 1. Volume Delta Metrics
        buy_trades = df_trades[df_trades['is_aggressive_buy']]
        sell_trades = df_trades[df_trades['is_aggressive_sell']]
        
        agg_buy_vol = buy_trades['qty'].sum()
        agg_sell_vol = sell_trades['qty'].sum()
        total_vol = agg_buy_vol + agg_sell_vol
        net_delta = agg_buy_vol - agg_sell_vol
        delta_pct = (net_delta / total_vol) * 100 if total_vol > 0 else 0.0
        
        # 2. Cumulative Volume Delta (CVD) Series
        df_trades['signed_qty'] = np.where(df_trades['is_aggressive_buy'], df_trades['qty'], -df_trades['qty'])
        df_trades['cvd'] = df_trades['signed_qty'].cumsum()
        cvd_slope = df_trades['cvd'].iloc[-1] - df_trades['cvd'].iloc[-50]
        
        # 3. Absorption Detection
        # Check if heavy volume was traded at high or low of the window without price progression
        prices = df_trades['price'].values
        max_p = np.max(prices)
        min_p = np.min(prices)
        current_p = prices[-1]
        
        # Upper absorption (Aggressive buyers trapped into passive limit sellers)
        top_cluster = df_trades[df_trades['price'] >= max_p * 0.9995]
        top_buy_vol = top_cluster[top_cluster['is_aggressive_buy']]['qty'].sum()
        
        # Lower absorption (Aggressive sellers trapped into passive limit buyers)
        bottom_cluster = df_trades[df_trades['price'] <= min_p * 1.0005]
        bottom_sell_vol = bottom_cluster[bottom_cluster['is_aggressive_sell']]['qty'].sum()
        
        avg_cluster_vol = total_vol / 10.0
        
        absorption_state = "NONE"
        absorption_desc = "Normal order flow dynamics"
        
        if bottom_sell_vol > avg_cluster_vol * self.absorption_threshold and current_p > min_p:
            absorption_state = "BULLISH_ABSORPTION"
            absorption_desc = f"Institutional Limit Buyers absorbed {bottom_sell_vol:,.1f} aggressive market sell orders at low (${min_p:,.4f}) 🛡️"
        elif top_buy_vol > avg_cluster_vol * self.absorption_threshold and current_p < max_p:
            absorption_state = "BEARISH_ABSORPTION"
            absorption_desc = f"Institutional Limit Sellers absorbed {top_buy_vol:,.1f} aggressive market buy orders at high (${max_p:,.4f}) 🛑"

        # 4. Volume Profile Point of Control (POC)
        bins = np.linspace(min_p, max_p, 25)
        hist, bin_edges = np.histogram(prices, bins=bins, weights=df_trades['qty'])
        poc_idx = np.argmax(hist)
        poc_price = (bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2.0
        
        # 5. Order Book Passive Walls (DOM)
        total_bid_wall = sum(b['qty'] for b in bids)
        total_ask_wall = sum(a['qty'] for a in asks)
        dom_ratio = total_bid_wall / (total_ask_wall + 1e-9)
        
        # 6. Overall Order Flow Signal
        of_signal = "NEUTRAL"
        if (net_delta > 0 and cvd_slope > 0 and dom_ratio > 1.05) or absorption_state == "BULLISH_ABSORPTION":
            of_signal = "BULLISH"
        elif (net_delta < 0 and cvd_slope < 0 and dom_ratio < 0.95) or absorption_state == "BEARISH_ABSORPTION":
            of_signal = "BEARISH"
            
        return {
            'symbol': self.symbol,
            'current_price': current_p,
            'net_delta': net_delta,
            'delta_pct': delta_pct,
            'agg_buy_vol': agg_buy_vol,
            'agg_sell_vol': agg_sell_vol,
            'total_vol': total_vol,
            'cvd_slope': cvd_slope,
            'absorption_state': absorption_state,
            'absorption_desc': absorption_desc,
            'poc_price': poc_price,
            'dom_ratio': dom_ratio,
            'order_flow_signal': of_signal,
            'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        }

if __name__ == '__main__':
    print("=" * 80)
    print(" 🌊 REAL-TIME ORDER FLOW & FOOTPRINT DELTA ABSORPTION SCANNER")
    print("=" * 80)
    
    symbols = ["XAUUSDT", "XRPUSDT", "SUIUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "NEARUSDT", "SOLUSDT", "AVAXUSDT"]
    for sym in symbols:
        engine = OrderFlowEngine(symbol=sym)
        res = engine.analyze_order_flow()
        if res:
            delta_emoji = "🟢 BUY DELTA" if res['net_delta'] > 0 else "🔴 SELL DELTA"
            print(f"\n📌 ASSET: #{sym} | Price: ${res['current_price']:,.4f}")
            print(f"   • Net Aggressive Delta:    {delta_emoji} ({res['net_delta']:+,.1f} | {res['delta_pct']:+.1f}%)")
            print(f"   • Volume Profile POC:      ${res['poc_price']:,.4f}")
            print(f"   • DOM Limit Wall Ratio:    {res['dom_ratio']:.2f}x {'(Buyer Wall)' if res['dom_ratio'] > 1 else '(Seller Wall)'}")
            print(f"   • Absorption Status:       {res['absorption_state']} -> {res['absorption_desc']}")
            print(f"   • Order Flow Signal:       {res['order_flow_signal']}")
            
    print("\n" + "=" * 80)
