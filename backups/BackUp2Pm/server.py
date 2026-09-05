#!/usr/bin/env python3
"""
WEATHER-ENSEMBLE AI WEB DASHBOARD & BOT REST API SERVER
Serves the Web Dashboard and provides:
- Bot Process Control: /api/start, /api/stop, /api/status
- Live Engine Logs: /api/logs
- Live Binance Futures Positions & Account: /api/positions, /api/close_position, /api/close_all
"""

import os
import sys
import json
import subprocess
import urllib.parse
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# Import Binance helper functions from weather_ensemble_bot
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from weather_ensemble_bot import (
        get_binance_futures_positions,
        get_binance_futures_usdt_balance,
        close_binance_futures_position,
        close_all_binance_futures_positions,
        get_mtf_heatmap_data,
        MILESTONE_MANAGER,
        check_potato_sr_levels,
        get_divergence_status
    )
    from order_flow_engine import OrderFlowEngine
except Exception:
    get_binance_futures_positions = lambda: []
    get_binance_futures_usdt_balance = lambda: 0.0
    close_binance_futures_position = lambda sym: {'error': 'Helper not available'}
    close_all_binance_futures_positions = lambda: []
    get_mtf_heatmap_data = lambda: []
    MILESTONE_MANAGER = None
    check_potato_sr_levels = lambda sym: {'status': 'error'}
    get_divergence_status = lambda sym: {'status': 'error'}
    OrderFlowEngine = None

BOT_PROCESS = None
PORT = 8080
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(PROJECT_DIR, 'bot_output.log')

MIME_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon'
}

def get_python_executable():
    """Detect virtual environment Python or fallback to current sys.executable."""
    venv_py_win = os.path.join(PROJECT_DIR, '.venv', 'Scripts', 'python.exe')
    venv_py_unix = os.path.join(PROJECT_DIR, '.venv', 'bin', 'python')
    if os.path.exists(venv_py_win):
        return venv_py_win
    if os.path.exists(venv_py_unix):
        return venv_py_unix
    return sys.executable

class WebDashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/api/status':
            self.handle_api_status()
            return
        elif path == '/api/logs':
            self.handle_api_logs()
            return
        elif path == '/api/positions':
            self.handle_api_positions()
            return
        elif path == '/api/orderflow':
            self.handle_api_orderflow(parsed)
            return
        elif path == '/api/mtf_heatmap':
            self.handle_api_mtf_heatmap()
            return
        elif path == '/api/milestones':
            self.handle_api_milestones()
            return
        elif path == '/api/potato_sr':
            self.handle_api_potato_sr(parsed)
            return
        elif path == '/api/divergence':
            self.handle_api_divergence(parsed)
            return

        if path in ['/', '']:
            path = '/index.html'

        filepath = os.path.normpath(os.path.join(PROJECT_DIR, path.lstrip('/')))
        if not filepath.startswith(PROJECT_DIR):
            self.send_error(403, "Forbidden")
            return

        if os.path.exists(filepath) and os.path.isfile(filepath):
            _, ext = os.path.splitext(filepath)
            mime = MIME_TYPES.get(ext.lower(), 'application/octet-stream')
            with open(filepath, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404, "File Not Found")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == '/api/start':
            self.handle_api_start()
        elif path == '/api/stop':
            self.handle_api_stop()
        elif path == '/api/close_position':
            self.handle_api_close_position()
        elif path == '/api/close_all':
            self.handle_api_close_all()
        else:
            self.send_error(404, "Endpoint not found")

    def handle_api_status(self):
        global BOT_PROCESS
        is_running = BOT_PROCESS is not None and BOT_PROCESS.poll() is None
        pid = BOT_PROCESS.pid if is_running else None
        
        if not is_running:
            try:
                import psutil
                for p in psutil.process_iter(['pid', 'cmdline']):
                    cmd = p.info.get('cmdline') or []
                    if any('weather_ensemble_bot.py' in str(arg) for arg in cmd):
                        is_running = True
                        pid = p.info.get('pid')
                        break
            except Exception:
                pass

        data = {
            'running': is_running,
            'pid': pid
        }
        self.send_json_response(200, data)

    def handle_api_logs(self):
        lines = []
        if os.path.exists(LOG_FILE_PATH):
            try:
                with open(LOG_FILE_PATH, 'r', encoding='utf-8', errors='ignore') as f:
                    all_lines = f.readlines()
                    lines = all_lines[-75:] if len(all_lines) > 75 else all_lines
            except Exception as e:
                lines = [f"Error reading log file: {str(e)}"]
        self.send_json_response(200, {'logs': ''.join(lines)})

    def handle_api_positions(self):
        try:
            positions = get_binance_futures_positions()
            usdt_bal = get_binance_futures_usdt_balance()
            total_unrealized_pnl = sum(p['unrealizedProfit'] for p in positions)
            data = {
                'status': 'success',
                'balance': usdt_bal,
                'total_unrealized_pnl': total_unrealized_pnl,
                'positions_count': len(positions),
                'positions': positions
            }
        except Exception as e:
            data = {
                'status': 'error',
                'balance': 0.0,
                'total_unrealized_pnl': 0.0,
                'positions_count': 0,
                'positions': [],
                'error': str(e)
            }
        self.send_json_response(200, data)

    def handle_api_orderflow(self, parsed):
        query = urllib.parse.parse_qs(parsed.query)
        symbol = query.get('symbol', ['XRPUSDT'])[0]
        if OrderFlowEngine:
            engine = OrderFlowEngine(symbol=symbol)
            res = engine.analyze_order_flow()
            self.send_json_response(200, {'status': 'success', 'data': res})
        else:
            self.send_json_response(200, {'status': 'error', 'message': 'OrderFlowEngine unavailable'})

    def handle_api_mtf_heatmap(self):
        try:
            data = get_mtf_heatmap_data()
            self.send_json_response(200, {'status': 'success', 'heatmap': data})
        except Exception as e:
            self.send_json_response(200, {'status': 'error', 'error': str(e), 'heatmap': []})

    def handle_api_milestones(self):
        try:
            bal = get_binance_futures_usdt_balance()
            if MILESTONE_MANAGER:
                locked = MILESTONE_MANAGER.update(bal)
                peak = MILESTONE_MANAGER.peak_balance
                next_m = next((m for m in MILESTONE_MANAGER.milestones if m > bal), MILESTONE_MANAGER.milestones[-1])
            else:
                locked, peak, next_m = 0.0, bal, 30.0
            data = {
                'status': 'success',
                'current_balance': bal,
                'peak_balance': peak,
                'locked_milestone': locked,
                'next_milestone': next_m,
                'progress_pct': min(100.0, (bal / next_m) * 100.0) if next_m > 0 else 100.0
            }
        except Exception as e:
            data = {'status': 'error', 'error': str(e)}
        self.send_json_response(200, data)

    def handle_api_potato_sr(self, parsed):
        query = urllib.parse.parse_qs(parsed.query)
        symbol = query.get('symbol', ['XRPUSDT'])[0]
        data = check_potato_sr_levels(symbol=symbol)
        self.send_json_response(200, data)

    def handle_api_divergence(self, parsed):
        query = urllib.parse.parse_qs(parsed.query)
        symbol = query.get('symbol', ['XRPUSDT'])[0]
        data = get_divergence_status(symbol=symbol)
        self.send_json_response(200, data)

    def handle_api_close_position(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else '{}'
        try:
            params = json.loads(body)
        except Exception:
            params = {}
        symbol = params.get('symbol')
        if not symbol:
            self.send_json_response(400, {'error': 'Missing symbol parameter'})
            return

        res = close_binance_futures_position(symbol)
        self.send_json_response(200, {'status': 'success', 'result': res, 'symbol': symbol})

    def handle_api_close_all(self):
        results = close_all_binance_futures_positions()
        self.send_json_response(200, {'status': 'success', 'message': 'Close all executed', 'closed_positions': results})

    def handle_api_start(self):
        global BOT_PROCESS
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else '{}'
        try:
            params = json.loads(body)
        except Exception:
            params = {}

        mode = params.get('sizing_mode', 'margin')
        margin_pct = params.get('margin_pct', 0.03)
        leverage = params.get('leverage', 50)
        threshold = params.get('threshold', 30)
        timeframe = params.get('timeframe', '15m')
        max_positions = params.get('max_positions', 5)

        if BOT_PROCESS is None or BOT_PROCESS.poll() is not None:
            py_exec = get_python_executable()
            cmd = [
                py_exec,
                os.path.join(PROJECT_DIR, 'weather_ensemble_bot.py'),
                '--trade-live',
                '--sizing-mode', str(mode),
                '--margin-pct', str(margin_pct),
                '--leverage', str(leverage),
                '--threshold', str(threshold),
                '--timeframe', str(timeframe),
                '--max-positions', str(max_positions)
            ]
            try:
                log_file = open(LOG_FILE_PATH, 'a', encoding='utf-8')
                log_file.write(f"\n--- BOT STARTED: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} ---\n")
                log_file.flush()
                BOT_PROCESS = subprocess.Popen(cmd, cwd=PROJECT_DIR, stdout=log_file, stderr=subprocess.STDOUT)
                res = {'status': 'success', 'message': f'Bot started (PID: {BOT_PROCESS.pid})', 'running': True, 'pid': BOT_PROCESS.pid}
            except Exception as e:
                res = {'status': 'error', 'message': f'Failed to start bot: {str(e)}', 'running': False}
        else:
            res = {'status': 'already_running', 'message': f'Bot is already running (PID: {BOT_PROCESS.pid})', 'running': True, 'pid': BOT_PROCESS.pid}

        self.send_json_response(200, res)

    def handle_api_stop(self):
        global BOT_PROCESS
        if BOT_PROCESS is not None and BOT_PROCESS.poll() is None:
            BOT_PROCESS.terminate()
            try:
                BOT_PROCESS.wait(timeout=3)
            except subprocess.TimeoutExpired:
                BOT_PROCESS.kill()
            BOT_PROCESS = None
            res = {'status': 'success', 'message': 'Bot stopped successfully', 'running': False}
        else:
            BOT_PROCESS = None
            res = {'status': 'not_running', 'message': 'Bot is not running', 'running': False}

        self.send_json_response(200, res)

    def send_json_response(self, code, data):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

if __name__ == '__main__':
    os.chdir(PROJECT_DIR)
    server = HTTPServer(('0.0.0.0', PORT), WebDashboardHandler)
    print(f"=======================================================")
    print(f" WEATHER-ENSEMBLE WEB DASHBOARD & BOT CONTROL SERVER ACTIVE")
    print(f" URL: http://localhost:{PORT}")
    print(f" API Endpoints: /api/start, /api/stop, /api/status, /api/logs, /api/positions, /api/close_position, /api/close_all")
    print(f" Python Interpreter: {get_python_executable()}")
    print(f"=======================================================")
    server.serve_forever()
