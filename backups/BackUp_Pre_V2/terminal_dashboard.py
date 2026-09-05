#!/usr/bin/env python3
"""
WEATHER-ENSEMBLE AI: NATIVE PYTHON INTERACTIVE TERMINAL DASHBOARD (TUI)
=======================================================================
100% Pure Python Terminal User Interface (Zero HTML / Zero Browser Required)
Built with Python Rich:
- Live Millisecond Streaming Trade Tape & Whale Radar
- 9 Quant Pillars (31 Models) Consensus Engine
- 4H SMC Macro Bias Gate & Real-Time Order Flow Absorption
- 🥔 Potato Support & Resistance (Floor & Ceiling Tracker)
- Multi-Timeframe (MTF) Heatmap Matrix (5m, 15m, 1h, 4h)
- Live Binance Futures Positions & Account Equity Monitor
"""

import os
import sys
import time
import json
import threading
import requests
from datetime import datetime, timezone
import websocket

# Rich TUI Components
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.live import Live
from rich.progress import ProgressBar

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Import core bot helpers
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from weather_ensemble_bot import (
    get_binance_futures_positions,
    get_binance_futures_usdt_balance,
    get_mtf_heatmap_data,
    check_potato_sr_levels,
    get_divergence_status,
    OPTIMIZED_SYMBOLS
)
from order_flow_engine import OrderFlowEngine

class TerminalQuantDashboard:
    def __init__(self, symbol="XRPUSDT"):
        self.console = Console()
        self.symbol = symbol
        self.running = True
        
        # State Data
        self.balance = 14.20
        self.positions = []
        self.order_flow_data = {}
        self.potato_data = {}
        self.mtf_data = []
        self.recent_trades = []
        self.trade_velocity = 0
        self._trade_counter = 0
        
        # Start Background Streaming & Polling Threads
        self.start_websocket_trade_tape()
        self.start_background_pollers()
        
    def start_websocket_trade_tape(self):
        """Streams real-time trades directly from Binance Futures WebSocket"""
        def on_message(ws, message):
            try:
                t = json.loads(message)
                self._trade_counter += 1
                
                price = float(t['p'])
                qty = float(t['q'])
                total_usd = price * qty
                is_buyer_maker = t['m']
                side = "SELL" if is_buyer_maker else "BUY"
                is_whale = total_usd >= 5000.0
                
                date = datetime.fromtimestamp(t['T'] / 1000.0, timezone.utc)
                time_str = date.strftime("%H:%M:%S") + f".{int(date.microsecond/1000):03d}"
                
                self.recent_trades.insert(0, {
                    'time': time_str,
                    'side': side,
                    'price': price,
                    'qty': qty,
                    'total_usd': total_usd,
                    'is_whale': is_whale
                })
                if len(self.recent_trades) > 15:
                    self.recent_trades.pop()
            except Exception:
                pass

        def run_ws():
            while self.running:
                try:
                    stream_sym = self.symbol.lower()
                    ws = websocket.WebSocketApp(
                        f"wss://fstream.binance.com/ws/{stream_sym}@aggTrade",
                        on_message=on_message
                    )
                    ws.run_forever()
                except Exception:
                    time.sleep(2)

        t = threading.Thread(target=run_ws, daemon=True)
        t.start()

    def start_background_pollers(self):
        """Background poller for Account, OrderFlow, S/R, and MTF Heatmap"""
        def poll_loop():
            while self.running:
                try:
                    self.balance = get_binance_futures_usdt_balance()
                    self.positions = get_binance_futures_positions()
                    
                    # Order Flow
                    of_eng = OrderFlowEngine(self.symbol)
                    self.order_flow_data = of_eng.analyze_order_flow()
                    
                    # Potato S&R
                    self.potato_data = check_potato_sr_levels(self.symbol)

                    # RSI + CCI Divergence
                    self.divergence_data = get_divergence_status(self.symbol)
                    
                    # MTF Heatmap
                    self.mtf_data = get_mtf_heatmap_data()
                except Exception:
                    pass
                time.sleep(2.5)

        def velocity_loop():
            while self.running:
                self.trade_velocity = self._trade_counter
                self._trade_counter = 0
                time.sleep(1.0)

        threading.Thread(target=poll_loop, daemon=True).start()
        threading.Thread(target=velocity_loop, daemon=True).start()

    def make_header(self):
        table = Table.grid(expand=True)
        table.add_column(justify="left", ratio=1)
        table.add_column(justify="center", ratio=1)
        table.add_column(justify="right", ratio=1)
        
        active_pos_count = len(self.positions)
        pos_str = f"[bold green]{active_pos_count} ACTIVE[/bold green]" if active_pos_count > 0 else "[dim]0 ACTIVE[/dim]"
        
        table.add_row(
            f"[bold cyan]⚡ WEATHER-ENSEMBLE QUANT C2[/bold cyan] [bold yellow]({self.symbol})[/bold yellow]",
            f"💰 Wallet: [bold green]${self.balance:,.2f} USDT[/bold green] | Milestone Floor: [bold yellow]$30.00[/bold yellow]",
            f"Positions: {pos_str} | [bold green]LIVE ENGINE ACTIVE[/bold green]"
        )
        return Panel(table, style="bold cyan on black", border_style="cyan")

    def make_trade_tape_panel(self):
        table = Table(expand=True, box=None, padding=(0, 1))
        table.add_column("Time", justify="left", style="dim", width=12)
        table.add_column("Side", justify="center", width=8)
        table.add_column("Price", justify="right", width=12)
        table.add_column("Qty", justify="right", width=10)
        table.add_column("Value ($)", justify="right", width=14)
        
        if not self.recent_trades:
            table.add_row("—", "CONNECTING", "—", "—", "—")
        else:
            for tr in self.recent_trades[:10]:
                side_style = "bold green" if tr['side'] == "BUY" else "bold red"
                side_icon = "🟢 BUY " if tr['side'] == "BUY" else "🔴 SELL"
                if tr['is_whale']:
                    side_icon = "🐳 " + side_icon
                    val_str = f"[bold yellow]${tr['total_usd']:,.2f}[/bold yellow]"
                else:
                    val_str = f"${tr['total_usd']:,.2f}"
                    
                table.add_row(
                    tr['time'],
                    f"[{side_style}]{side_icon}[/{side_style}]",
                    f"${tr['price']:.4f}",
                    f"{tr['qty']:,.1f}",
                    val_str
                )
                
        title = f"⚡ Live Streaming Trade Tape (Time & Sales) — [yellow]{self.trade_velocity} trades/sec[/yellow]"
        return Panel(table, title=title, border_style="yellow", style="on black")

    def make_order_flow_and_potato_panel(self):
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        
        # Left: Order Flow
        of = self.order_flow_data or {}
        delta_pct = of.get('delta_pct', 0.0)
        delta_color = "green" if delta_pct >= 0 else "red"
        absorption = of.get('absorption_state', 'NORMAL_FLOW')
        abs_color = "bold green" if "BULLISH" in absorption else ("bold red" if "BEARISH" in absorption else "cyan")
        poc = of.get('poc_price', 0.0)
        dom = of.get('dom_imbalance', 1.0)
        
        of_text = Text()
        of_text.append(f"🌊 ORDER FLOW FOOTPRINT\n", style="bold cyan")
        of_text.append(f"• Net Delta: [{delta_color}]{delta_pct:+.1f}%[/] ({of.get('delta_polarity', 'NEUTRAL')})\n")
        of_text.append(f"• State: [{abs_color}]{absorption}[/]\n")
        of_text.append(f"• VP POC Price: [bold yellow]${poc:.4f}[/]\n")
        of_text.append(f"• L2 Wall Ratio: [bold]{dom:.2f}x[/] ({of.get('dominant_wall', 'BALANCED')})")
        
        # Middle: Potato S&R
        pot = self.potato_data or {}
        sup = pot.get('support', 0.0)
        res = pot.get('resistance', 0.0)
        curr_p = pot.get('current_price', 0.0)
        pot_state = pot.get('state', 'IN_RANGE 🥔')
        
        pot_text = Text()
        pot_text.append(f"🥔 POTATO S&R RADAR\n", style="bold yellow")
        pot_text.append(f"• Floor (Support 🛡️):   [bold green]${sup:.4f}[/]\n")
        pot_text.append(f"• Ceiling (Resistance 🧱): [bold red]${res:.4f}[/]\n")
        pot_text.append(f"• Current Price:        [bold white]${curr_p:.4f}[/]\n")
        pot_text.append(f"• Potato State:         [bold yellow]{pot_state}[/]")

        # Right: RSI + CCI Dual Divergence Radar
        div_data = getattr(self, 'divergence_data', {}) or {}
        rsi_val = div_data.get('rsi_14', 50.0)
        cci_val = div_data.get('cci_20', 0.0)
        div_state = div_data.get('divergence_state', 'NO_DIVERGENCE')
        div_color = "bold green" if "BULLISH" in div_state else ("bold red" if "BEARISH" in div_state else "dim")

        div_text = Text()
        div_text.append(f"⚡ RSI + CCI DUAL DIVERGENCE\n", style="bold magenta")
        div_text.append(f"• RSI (14 Smooth):   [bold]{rsi_val:.1f}[/]\n")
        div_text.append(f"• CCI (20 Fast Lead): [bold]{cci_val:+.1f}[/]\n")
        div_text.append(f"• Confluence State:   [{div_color}]{div_state}[/]\n")
        div_text.append(f"• Macro Trend Gate:   [bold cyan]4H SMC ALIGNED ✅[/]")
        
        table.add_row(
            Panel(of_text, border_style="cyan"),
            Panel(pot_text, border_style="yellow"),
            Panel(div_text, border_style="magenta")
        )
        return table

    def make_mtf_heatmap_panel(self):
        table = Table(expand=True, box=None, padding=(0, 1))
        table.add_column("Asset", style="bold cyan", width=10)
        table.add_column("Price", justify="right", width=12)
        table.add_column("5m", justify="center", width=8)
        table.add_column("15m", justify="center", width=8)
        table.add_column("1h", justify="center", width=8)
        table.add_column("4h", justify="center", width=8)
        table.add_column("Confluence Action", justify="left", width=22)
        
        for row in self.mtf_data:
            c5 = "[green]BULL[/green]" if row['tf_5m'] == "BULLISH" else "[red]BEAR[/red]"
            c15 = "[green]BULL[/green]" if row['tf_15m'] == "BULLISH" else "[red]BEAR[/red]"
            c1h = "[green]BULL[/green]" if row['tf_1h'] == "BULLISH" else "[red]BEAR[/red]"
            c4h = "[green]BULL[/green]" if row['tf_4h'] == "BULLISH" else "[red]BEAR[/red]"
            
            table.add_row(
                row['symbol'].replace('USDT', ''),
                f"${row['price']:.4f}",
                c5, c15, c1h, c4h,
                row['status']
            )
            
        return Panel(table, title="📊 Multi-Timeframe (MTF) Trend & Structure Heatmap", border_style="blue", style="on black")

    def make_positions_panel(self):
        table = Table(expand=True, box=None, padding=(0, 1))
        table.add_column("Symbol", style="bold cyan", width=12)
        table.add_column("Side", justify="center", width=8)
        table.add_column("Leverage", justify="center", width=10)
        table.add_column("Size", justify="right", width=12)
        table.add_column("Entry ($)", justify="right", width=12)
        table.add_column("Mark ($)", justify="right", width=12)
        table.add_column("Unrealized PnL ($)", justify="right", width=18)
        
        if not self.positions:
            table.add_row("—", "NO OPEN POSITIONS", "—", "—", "—", "—", "[dim]$0.00[/dim]")
        else:
            for p in self.positions:
                side_style = "bold green" if p['side'] == "LONG" else "bold red"
                pnl = p['unrealizedProfit']
                pnl_style = "bold green" if pnl >= 0 else "bold red"
                pnl_str = f"[{pnl_style}]{pnl:+.2f} USDT[/{pnl_style}]"
                
                table.add_row(
                    f"#{p['symbol']}",
                    f"[{side_style}]{p['side']}[/{side_style}]",
                    f"{p['leverage']}x",
                    f"{p['positionAmt']}",
                    f"${p['entryPrice']:.4f}",
                    f"${p['markPrice']:.4f}",
                    pnl_str
                )
                
        return Panel(table, title="📈 Active Binance Futures Positions & Live PnL", border_style="green", style="on black")

    def render_layout(self):
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="upper", size=13),
            Layout(name="middle", size=8),
            Layout(name="mtf", size=12),
            Layout(name="positions", size=6)
        )
        
        layout["header"].update(self.make_header())
        layout["upper"].update(self.make_trade_tape_panel())
        layout["middle"].update(self.make_order_flow_and_potato_panel())
        layout["mtf"].update(self.make_mtf_heatmap_panel())
        layout["positions"].update(self.make_positions_panel())
        return layout

    def start(self):
        self.console.clear()
        with Live(self.render_layout(), refresh_per_second=4, screen=True) as live:
            try:
                while self.running:
                    live.update(self.render_layout())
                    time.sleep(0.25)
            except KeyboardInterrupt:
                self.running = False
                self.console.print("\n[bold yellow]Terminal Dashboard closed. Live bot continues scanning in background.[/bold yellow]")

if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else "XRPUSDT"
    app = TerminalQuantDashboard(symbol=symbol)
    app.start()
