#!/usr/bin/env python3
"""
WEATHER-ENSEMBLE AI: NATIVE PYTHON DESKTOP GUI TERMINAL (TKINTER)
=================================================================
100% Native Python Desktop GUI (Zero HTML / Zero Browser Required)
Built with Python Tkinter:
- Dark Cyberpunk GUI Window
- Real-Time WebSocket Streaming Trade Tape (Time & Sales)
- 🐳 Institutional Whale Order Alerts ($5,000+ & $25,000+)
- 🥔 Potato Support & Resistance Floor & Ceiling Radar
- 1-Click Interactive Trading Action Pad (Buy, Sell, Close All)
- Live Binance Futures Positions & Account Equity Tracker
"""

import os
import sys
import time
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timezone
import requests
import websocket

try:
    import winsound
except ImportError:
    winsound = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main import (
    get_binance_futures_positions,
    get_binance_futures_usdt_balance,
    close_binance_futures_position,
    close_all_binance_futures_positions,
    check_potato_sr_levels,
    place_binance_futures_market_order,
    OPTIMIZED_SYMBOLS
)
from order_flow_engine import OrderFlowEngine

class DesktopQuantTerminal(tk.Tk):
    def __init__(self):
        super().__init__()
        
        self.title("⚡ Weather-Ensemble AI Quant Futures Terminal (Native Desktop)")
        self.geometry("1100x750")
        self.minsize(950, 650)
        self.configure(bg="#0c0e14")
        
        self.active_symbol = "XRPUSDT"
        self.tape_ws = None
        self.recent_trades = []
        self.trade_count = 0
        self.only_whales = False
        self.sound_enabled = True
        
        self.init_styles()
        self.build_ui()
        self.start_websocket_trade_tape()
        self.start_background_pollers()
        
    def init_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Dark theme treeview
        self.style.configure("Treeview",
            background="#121620",
            foreground="#e6edf3",
            rowheight=24,
            fieldbackground="#121620",
            bordercolor="#212638",
            font=("Consolas", 9)
        )
        self.style.configure("Treeview.Heading",
            background="#1a2030",
            foreground="#00f2fe",
            font=("Segoe UI", 9, "bold"),
            relief="flat"
        )
        self.style.map("Treeview", background=[('selected', '#253350')])

    def build_ui(self):
        # 1. Top Header Bar
        header_frame = tk.Frame(self, bg="#161b26", height=50, padx=15, pady=8)
        header_frame.pack(fill="x", side="top")
        
        title_label = tk.Label(header_frame, text="⚡ WEATHER-ENSEMBLE AI", font=("Segoe UI", 13, "bold"), fg="#00f2fe", bg="#161b26")
        title_label.pack(side="left")
        
        self.wallet_label = tk.Label(header_frame, text="💰 Wallet: $14.20 USDT | Floor: $30.00", font=("Segoe UI", 10, "bold"), fg="#ffb800", bg="#161b26")
        self.wallet_label.pack(side="left", padx=25)
        
        self.sound_btn = tk.Button(header_frame, text="🔊 Sound: ON", font=("Segoe UI", 9, "bold"), bg="#212638", fg="#00f2fe", relief="flat", padx=10, command=self.toggle_sound)
        self.sound_btn.pack(side="right", padx=5)
        
        self.panic_btn = tk.Button(header_frame, text="🚨 PANIC CLOSE ALL", font=("Segoe UI", 9, "bold"), bg="#dc2626", fg="#ffffff", relief="flat", padx=12, command=self.panic_close_all)
        self.panic_btn.pack(side="right", padx=5)

        # 2. Asset Selector Pills Frame
        selector_frame = tk.Frame(self, bg="#0c0e14", padx=15, pady=6)
        selector_frame.pack(fill="x")
        
        tk.Label(selector_frame, text="ASSET:", font=("Segoe UI", 9, "bold"), fg="#8b949e", bg="#0c0e14").pack(side="left", padx=(0, 8))
        
        self.asset_buttons = {}
        for sym in OPTIMIZED_SYMBOLS:
            btn = tk.Button(
                selector_frame,
                text=sym.replace("USDT", ""),
                font=("Segoe UI", 9, "bold"),
                bg="#00f2fe" if sym == self.active_symbol else "#161b26",
                fg="#000000" if sym == self.active_symbol else "#8b949e",
                relief="flat",
                padx=8, pady=2,
                command=lambda s=sym: self.switch_asset(s)
            )
            btn.pack(side="left", padx=3)
            self.asset_buttons[sym] = btn

        # 3. Main Split Content Area
        main_split = tk.Frame(self, bg="#0c0e14", padx=15, pady=5)
        main_split.pack(fill="both", expand=True)

        # Left Column: Streaming Trade Tape (Time & Sales)
        left_col = tk.Frame(main_split, bg="#121620", bd=1, relief="solid", padx=10, pady=8)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 8))

        tape_header_frame = tk.Frame(left_col, bg="#121620")
        tape_header_frame.pack(fill="x", pady=(0, 6))
        
        tk.Label(tape_header_frame, text="⚡ STREAMING LIVE TRADE TAPE (TIME & SALES)", font=("Segoe UI", 10, "bold"), fg="#00f2fe", bg="#121620").pack(side="left")
        self.velocity_label = tk.Label(tape_header_frame, text="⚡ 0 trades/s", font=("Consolas", 9, "bold"), fg="#ffb800", bg="#121620")
        self.velocity_label.pack(side="right")
        
        self.whale_var = tk.BooleanVar(value=False)
        self.whale_check = tk.Checkbutton(tape_header_frame, text="🐳 Whales Only (≥$5k)", variable=self.whale_var, font=("Segoe UI", 8), fg="#8b949e", bg="#121620", selectcolor="#161b26", activebackground="#121620", command=self.toggle_whale_filter)
        self.whale_check.pack(side="right", padx=10)

        # Treeview for Trade Tape
        cols = ("Time", "Side", "Price", "Quantity", "Total ($)")
        self.tape_tree = ttk.Treeview(left_col, columns=cols, show="headings", height=14)
        for col in cols:
            self.tape_tree.heading(col, text=col)
        self.tape_tree.column("Time", width=95, anchor="center")
        self.tape_tree.column("Side", width=75, anchor="center")
        self.tape_tree.column("Price", width=95, anchor="e")
        self.tape_tree.column("Quantity", width=90, anchor="e")
        self.tape_tree.column("Total ($)", width=110, anchor="e")
        self.tape_tree.pack(fill="both", expand=True)

        # Tags for colored rows
        self.tape_tree.tag_configure("buy", foreground="#00f5a0")
        self.tape_tree.tag_configure("sell", foreground="#ff4b4b")
        self.tape_tree.tag_configure("whale", background="#2a2510", foreground="#ffb800")

        # Right Column: Potato S&R, Order Flow & 1-Click Action Pad
        right_col = tk.Frame(main_split, bg="#121620", bd=1, relief="solid", padx=12, pady=8, width=380)
        right_col.pack(side="right", fill="both")

        # Potato S&R Radar
        tk.Label(right_col, text="🥔 POTATO S&R (FLOOR & CEILING)", font=("Segoe UI", 10, "bold"), fg="#ffb800", bg="#121620").pack(anchor="w")
        self.potato_status_lbl = tk.Label(right_col, text="IN RANGE 🥔", font=("Segoe UI", 9, "bold"), fg="#ffb800", bg="#1a2030", padx=8, pady=3)
        self.potato_status_lbl.pack(fill="x", pady=4)
        
        sr_frame = tk.Frame(right_col, bg="#121620")
        sr_frame.pack(fill="x", pady=4)
        self.sup_lbl = tk.Label(sr_frame, text="Floor: $0.0000", font=("Consolas", 10, "bold"), fg="#00f5a0", bg="#121620")
        self.sup_lbl.pack(side="left")
        self.res_lbl = tk.Label(sr_frame, text="Ceiling: $0.0000", font=("Consolas", 10, "bold"), fg="#ff4b4b", bg="#121620")
        self.res_lbl.pack(side="right")

        ttk.Separator(right_col, orient="horizontal").pack(fill="x", pady=8)

        # Order Flow Metrics
        tk.Label(right_col, text="🌊 ORDER FLOW & ABSORPTION", font=("Segoe UI", 10, "bold"), fg="#00f2fe", bg="#121620").pack(anchor="w")
        self.of_delta_lbl = tk.Label(right_col, text="• Net Delta: +0.0% (NEUTRAL)", font=("Consolas", 9), fg="#00f5a0", bg="#121620")
        self.of_delta_lbl.pack(anchor="w", pady=1)
        self.of_abs_lbl = tk.Label(right_col, text="• State: NORMAL FLOW", font=("Consolas", 9, "bold"), fg="#00f2fe", bg="#121620")
        self.of_abs_lbl.pack(anchor="w", pady=1)
        self.of_poc_lbl = tk.Label(right_col, text="• Volume POC: $0.0000", font=("Consolas", 9), fg="#ffb800", bg="#121620")
        self.of_poc_lbl.pack(anchor="w", pady=1)

        ttk.Separator(right_col, orient="horizontal").pack(fill="x", pady=8)

        # 1-Click Fast Action Pad
        tk.Label(right_col, text="⚡ 1-CLICK FAST ACTION PAD (50x)", font=("Segoe UI", 10, "bold"), fg="#e6edf3", bg="#121620").pack(anchor="w", pady=(0, 6))
        
        act_frame = tk.Frame(right_col, bg="#121620")
        act_frame.pack(fill="x")
        
        self.buy_btn = tk.Button(act_frame, text="🟢 BUY MARKET (3%)", font=("Segoe UI", 9, "bold"), bg="#059669", fg="#ffffff", relief="flat", pady=6, command=lambda: self.execute_trade("BUY"))
        self.buy_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        
        self.sell_btn = tk.Button(act_frame, text="🔴 SELL MARKET (3%)", font=("Segoe UI", 9, "bold"), bg="#dc2626", fg="#ffffff", relief="flat", pady=6, command=lambda: self.execute_trade("SELL"))
        self.sell_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

        # 4. Bottom Open Positions Table Panel
        bot_frame = tk.Frame(self, bg="#121620", bd=1, relief="solid", padx=10, pady=6, height=130)
        bot_frame.pack(fill="x", side="bottom", padx=15, pady=(0, 10))

        tk.Label(bot_frame, text="📈 ACTIVE BINANCE FUTURES POSITIONS", font=("Segoe UI", 9, "bold"), fg="#00f2fe", bg="#121620").pack(anchor="w", pady=(0, 4))

        pos_cols = ("Symbol", "Side", "Leverage", "Size", "Entry ($)", "Mark ($)", "PnL ($)")
        self.pos_tree = ttk.Treeview(bot_frame, columns=pos_cols, show="headings", height=3)
        for col in pos_cols:
            self.pos_tree.heading(col, text=col)
        self.pos_tree.column("Symbol", width=120, anchor="center")
        self.pos_tree.column("Side", width=80, anchor="center")
        self.pos_tree.column("Leverage", width=90, anchor="center")
        self.pos_tree.column("Size", width=110, anchor="e")
        self.pos_tree.column("Entry ($)", width=110, anchor="e")
        self.pos_tree.column("Mark ($)", width=110, anchor="e")
        self.pos_tree.column("PnL ($)", width=140, anchor="e")
        self.pos_tree.pack(fill="x")

        self.pos_tree.tag_configure("pos_green", foreground="#00f5a0")
        self.pos_tree.tag_configure("pos_red", foreground="#ff4b4b")

    def toggle_sound(self):
        self.sound_enabled = not self.sound_enabled
        self.sound_btn.config(text="🔊 Sound: ON" if self.sound_enabled else "🔇 Sound: OFF")

    def toggle_whale_filter(self):
        self.only_whales = self.whale_var.get()

    def switch_asset(self, sym):
        for s, btn in self.asset_buttons.items():
            btn.config(bg="#00f2fe" if s == sym else "#161b26", fg="#000000" if s == sym else "#8b949e")
        self.active_symbol = sym
        self.start_websocket_trade_tape()

    def start_websocket_trade_tape(self):
        if self.tape_ws:
            try:
                self.tape_ws.close()
            except Exception:
                pass

        for row in self.tape_tree.get_children():
            self.tape_tree.delete(row)

        stream_sym = self.active_symbol.lower()
        ws_url = f"wss://fstream.binance.com/ws/{stream_sym}@aggTrade"

        def on_message(ws, msg):
            try:
                t = json.loads(msg)
                self.trade_count += 1
                price = float(t['p'])
                qty = float(t['q'])
                total_usd = price * qty
                is_buyer_maker = t['m']
                side = "SELL" if is_buyer_maker else "BUY"
                is_whale = total_usd >= 5000.0

                if self.only_whales and not is_whale:
                    return

                date = datetime.fromtimestamp(t['T'] / 1000.0, timezone.utc)
                time_str = date.strftime("%H:%M:%S") + f".{int(date.microsecond/1000):03d}"

                side_tag = "whale" if is_whale else ("buy" if side == "BUY" else "sell")
                side_text = "🐳 BUY" if (is_whale and side == "BUY") else ("🐋 SELL" if (is_whale and side == "SELL") else side)

                # Insert in UI thread
                self.after(0, self.insert_trade_row, time_str, side_text, price, qty, total_usd, side_tag, is_whale)
            except Exception:
                pass

        def run():
            self.tape_ws = websocket.WebSocketApp(ws_url, on_message=on_message)
            self.tape_ws.run_forever()

        threading.Thread(target=run, daemon=True).start()

    def insert_trade_row(self, time_str, side_text, price, qty, total_usd, side_tag, is_whale):
        self.tape_tree.insert("", 0, values=(
            time_str,
            side_text,
            f"${price:.4f}",
            f"{qty:,.1f}",
            f"${total_usd:,.2f}"
        ), tags=(side_tag,))
        
        children = self.tape_tree.get_children()
        if len(children) > 40:
            self.tape_tree.delete(children[-1])

        if is_whale and self.sound_enabled and winsound:
            try:
                winsound.Beep(1200, 80)
            except Exception:
                pass

    def start_background_pollers(self):
        def poll_loop():
            while True:
                try:
                    bal = get_binance_futures_usdt_balance()
                    pos = get_binance_futures_positions()
                    pot = check_potato_sr_levels(self.active_symbol)
                    of_eng = OrderFlowEngine(self.active_symbol)
                    of = of_eng.analyze_order_flow()
                    
                    self.after(0, self.update_dashboard_data, bal, pos, pot, of)
                except Exception:
                    pass
                time.sleep(2.5)

        def vel_loop():
            while True:
                c = self.trade_count
                self.trade_count = 0
                self.after(0, lambda: self.velocity_label.config(text=f"⚡ {c} trades/s"))
                time.sleep(1.0)

        threading.Thread(target=poll_loop, daemon=True).start()
        threading.Thread(target=vel_loop, daemon=True).start()

    def update_dashboard_data(self, bal, pos, pot, of):
        # Update wallet
        self.wallet_label.config(text=f"💰 Wallet: ${bal:,.2f} USDT | Floor: $30.00")
        
        # Update Potato S&R
        if pot and pot.get('status') == 'success':
            self.potato_status_lbl.config(text=pot['state'])
            self.sup_lbl.config(text=f"Floor: ${pot['support']:.4f}")
            self.res_lbl.config(text=f"Ceiling: ${pot['resistance']:.4f}")

        # Update Order Flow
        if of:
            delta_pct = of.get('delta_pct', 0.0)
            self.of_delta_lbl.config(text=f"• Net Delta: {delta_pct:+.1f}% ({of.get('delta_polarity', 'NEUTRAL')})", fg="#00f5a0" if delta_pct >= 0 else "#ff4b4b")
            self.of_abs_lbl.config(text=f"• State: {of.get('absorption_state', 'NORMAL_FLOW')}")
            self.of_poc_lbl.config(text=f"• Volume POC: ${of.get('poc_price', 0.0):.4f}")

        # Update Positions
        for row in self.pos_tree.get_children():
            self.pos_tree.delete(row)
        if not pos:
            self.pos_tree.insert("", "end", values=("—", "NO OPEN POSITIONS", "—", "—", "—", "—", "$0.00"))
        else:
            for p in pos:
                pnl = p['unrealizedProfit']
                tag = "pos_green" if pnl >= 0 else "pos_red"
                self.pos_tree.insert("", "end", values=(
                    f"#{p['symbol']}",
                    p['side'],
                    f"{p['leverage']}x",
                    f"{p['positionAmt']}",
                    f"${p['entryPrice']:.4f}",
                    f"${p['markPrice']:.4f}",
                    f"{pnl:+.2f} USDT"
                ), tags=(tag,))

    def execute_trade(self, side):
        if not messagebox.askyesno("Confirm Order", f"Execute {side} Market Order for #{self.active_symbol} at 50x leverage?"):
            return
        res = place_binance_futures_market_order(symbol=self.active_symbol, side=side, margin_pct=0.03, leverage=50)
        if res and res.get('error'):
            messagebox.showerror("Execution Error", f"Failed to execute order: {res['error']}")
        else:
            messagebox.showinfo("Order Sent", f"Successfully sent {side} order for #{self.active_symbol}!")

    def panic_close_all(self):
        if not messagebox.askyesno("🚨 PANIC CLOSE ALL", "Are you 100% sure you want to close ALL active Binance Futures positions?"):
            return
        results = close_all_binance_futures_positions()
        messagebox.showinfo("Closed All", f"Emergency close executed for {len(results)} positions.")

if __name__ == '__main__':
    app = DesktopQuantTerminal()
    app.mainloop()
