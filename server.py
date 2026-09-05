#!/usr/bin/env python3
"""Local web dashboard and authenticated bot-control API.

Security model:
- Bind to localhost by default. Remote binding requires ATLAS_API_TOKEN.
- Destructive POST endpoints require the token when configured/remote.
- Read-only APIs remain available to the local dashboard.
"""

import json
import os
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from main import (
        get_binance_futures_positions,
        get_binance_futures_usdt_balance,
        close_binance_futures_position,
        close_all_binance_futures_positions,
        get_mtf_heatmap_data,
        MILESTONE_MANAGER,
        check_potato_sr_levels,
        get_divergence_status,
    )
    from order_flow_engine import OrderFlowEngine
except Exception:
    get_binance_futures_positions = lambda: []
    get_binance_futures_usdt_balance = lambda: 0.0
    close_binance_futures_position = lambda sym: {"error": "Helper not available"}
    close_all_binance_futures_positions = lambda: []
    get_mtf_heatmap_data = lambda: []
    MILESTONE_MANAGER = None
    check_potato_sr_levels = lambda sym: {"status": "error"}
    get_divergence_status = lambda sym: {"status": "error"}
    OrderFlowEngine = None

BOT_PROCESS = None
PORT = int(os.getenv("ATLAS_PORT", "8080"))
HOST = os.getenv("ATLAS_BIND_HOST", "127.0.0.1").strip()
API_TOKEN = os.getenv("ATLAS_API_TOKEN", "").strip()
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(PROJECT_DIR, "bot_output.log")

# A non-local bind is intentionally impossible without explicit authentication.
if HOST not in {"127.0.0.1", "localhost", "::1"} and not API_TOKEN:
    raise RuntimeError("ATLAS_API_TOKEN must be configured before binding the dashboard remotely")

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def get_python_executable():
    """Detect virtual environment Python or fall back to current interpreter."""
    venv_py_win = os.path.join(PROJECT_DIR, ".venv", "Scripts", "python.exe")
    venv_py_unix = os.path.join(PROJECT_DIR, ".venv", "bin", "python")
    if os.path.exists(venv_py_win):
        return venv_py_win
    if os.path.exists(venv_py_unix):
        return venv_py_unix
    return sys.executable


class WebDashboardHandler(BaseHTTPRequestHandler):
    server_version = "AtlasDashboard/2"

    def _authorized(self):
        """Authorize state-changing operations without leaking the expected token."""
        # Localhost-only mode is the safe default and preserves local dashboard UX.
        if not API_TOKEN and HOST in {"127.0.0.1", "localhost", "::1"}:
            return True
        supplied = self.headers.get("X-Atlas-Token", "")
        return bool(API_TOKEN and supplied == API_TOKEN)

    def _require_auth(self):
        if self._authorized():
            return True
        self.send_json_response(401, {"status": "error", "error": "Authentication required"})
        return False

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        handlers = {
            "/api/status": self.handle_api_status,
            "/api/logs": self.handle_api_logs,
            "/api/positions": self.handle_api_positions,
            "/api/orderflow": lambda: self.handle_api_orderflow(parsed),
            "/api/mtf_heatmap": self.handle_api_mtf_heatmap,
            "/api/milestones": self.handle_api_milestones,
            "/api/potato_sr": lambda: self.handle_api_potato_sr(parsed),
            "/api/divergence": lambda: self.handle_api_divergence(parsed),
        }
        if path in handlers:
            handlers[path]()
            return

        if path in ["/", ""]:
            path = "/index.html"
        candidate_dist = os.path.normpath(os.path.join(PROJECT_DIR, "frontend", "dist", path.lstrip("/")))
        candidate_web = os.path.normpath(os.path.join(PROJECT_DIR, "web", path.lstrip("/")))
        candidate_root = os.path.normpath(os.path.join(PROJECT_DIR, path.lstrip("/")))

        # Reject path traversal even if normalization produces an existing file.
        project_root = os.path.realpath(PROJECT_DIR)
        candidates = [candidate_dist, candidate_web, candidate_root]
        filepath = next(
            (p for p in candidates if os.path.isfile(p) and os.path.realpath(p).startswith(project_root + os.sep)),
            None,
        )
        if filepath is None:
            spa_index = os.path.join(PROJECT_DIR, "frontend", "dist", "index.html")
            filepath = spa_index if os.path.isfile(spa_index) else None

        if filepath and os.path.isfile(filepath):
            _, ext = os.path.splitext(filepath)
            mime = MIME_TYPES.get(ext.lower(), "application/octet-stream")
            with open(filepath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404, "File Not Found")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_POST(self):
        if not self._require_auth():
            return
        parsed = urllib.parse.urlparse(self.path)
        handlers = {
            "/api/start": self.handle_api_start,
            "/api/stop": self.handle_api_stop,
            "/api/close_position": self.handle_api_close_position,
            "/api/close_all": self.handle_api_close_all,
        }
        handler = handlers.get(parsed.path)
        if handler:
            handler()
        else:
            self.send_error(404, "Endpoint not found")

    def handle_api_status(self):
        global BOT_PROCESS
        is_running = BOT_PROCESS is not None and BOT_PROCESS.poll() is None
        pid = BOT_PROCESS.pid if is_running else None
        if not is_running:
            try:
                import psutil
                for p in psutil.process_iter(["pid", "cmdline"]):
                    cmd = p.info.get("cmdline") or []
                    if any(name in str(arg) for name in ["main.py", "weather_ensemble_bot.py"] for arg in cmd):
                        is_running, pid = True, p.info.get("pid")
                        break
            except Exception:
                pass
        self.send_json_response(200, {"running": is_running, "pid": pid})

    def handle_api_logs(self):
        lines = []
        if os.path.exists(LOG_FILE_PATH):
            try:
                with open(LOG_FILE_PATH, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()[-75:]
            except OSError as exc:
                lines = [f"Error reading log file: {exc}"]
        self.send_json_response(200, {"logs": "".join(lines)})

    def handle_api_positions(self):
        try:
            positions = get_binance_futures_positions()
            if positions is None:
                raise RuntimeError("Binance position state unavailable")
            usdt_bal = get_binance_futures_usdt_balance()
            total_unrealized_pnl = sum(float(p.get("unrealizedProfit", 0)) for p in positions)
            self.send_json_response(200, {"status": "success", "balance": usdt_bal,
                "total_unrealized_pnl": total_unrealized_pnl, "positions_count": len(positions), "positions": positions})
        except Exception as exc:
            self.send_json_response(503, {"status": "error", "error": str(exc), "positions": []})

    def handle_api_orderflow(self, parsed):
        symbol = urllib.parse.parse_qs(parsed.query).get("symbol", ["XRPUSDT"])[0].upper()
        if not OrderFlowEngine:
            self.send_json_response(503, {"status": "error", "message": "OrderFlowEngine unavailable"})
            return
        try:
            self.send_json_response(200, {"status": "success", "data": OrderFlowEngine(symbol=symbol).analyze_order_flow()})
        except Exception as exc:
            self.send_json_response(503, {"status": "error", "error": str(exc)})

    def handle_api_mtf_heatmap(self):
        try:
            self.send_json_response(200, {"status": "success", "heatmap": get_mtf_heatmap_data()})
        except Exception as exc:
            self.send_json_response(503, {"status": "error", "error": str(exc), "heatmap": []})

    def handle_api_milestones(self):
        try:
            bal = get_binance_futures_usdt_balance()
            if MILESTONE_MANAGER:
                locked = MILESTONE_MANAGER.update(bal)
                peak = MILESTONE_MANAGER.peak_balance
                next_m = next((m for m in MILESTONE_MANAGER.milestones if m > bal), MILESTONE_MANAGER.milestones[-1])
            else:
                locked, peak, next_m = 0.0, bal, 30.0
            self.send_json_response(200, {"status": "success", "current_balance": bal, "peak_balance": peak,
                "locked_milestone": locked, "next_milestone": next_m,
                "progress_pct": min(100.0, (bal / next_m) * 100.0) if next_m > 0 else 100.0})
        except Exception as exc:
            self.send_json_response(503, {"status": "error", "error": str(exc)})

    def handle_api_potato_sr(self, parsed):
        symbol = urllib.parse.parse_qs(parsed.query).get("symbol", ["XRPUSDT"])[0].upper()
        try:
            self.send_json_response(200, check_potato_sr_levels(symbol=symbol))
        except Exception as exc:
            self.send_json_response(503, {"status": "error", "error": str(exc)})

    def handle_api_divergence(self, parsed):
        symbol = urllib.parse.parse_qs(parsed.query).get("symbol", ["XRPUSDT"])[0].upper()
        try:
            self.send_json_response(200, get_divergence_status(symbol=symbol))
        except Exception as exc:
            self.send_json_response(503, {"status": "error", "error": str(exc)})

    def _read_json_body(self):
        try:
            length = min(int(self.headers.get("Content-Length", 0)), 64 * 1024)
        except (TypeError, ValueError):
            length = 0
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def handle_api_close_position(self):
        params = self._read_json_body()
        if params is None or not isinstance(params, dict):
            self.send_json_response(400, {"error": "Invalid JSON body"})
            return
        symbol = str(params.get("symbol", "")).upper()
        if not symbol or len(symbol) > 32 or not symbol.isalnum():
            self.send_json_response(400, {"error": "Invalid symbol parameter"})
            return
        try:
            res = close_binance_futures_position(symbol)
            self.send_json_response(200, {"status": "success", "result": res, "symbol": symbol})
        except Exception as exc:
            self.send_json_response(502, {"status": "error", "error": str(exc), "symbol": symbol})

    def handle_api_close_all(self):
        try:
            results = close_all_binance_futures_positions()
            self.send_json_response(200, {"status": "success", "message": "Close all executed", "closed_positions": results})
        except Exception as exc:
            self.send_json_response(502, {"status": "error", "error": str(exc)})

    def handle_api_start(self):
        global BOT_PROCESS
        params = self._read_json_body()
        if params is None or not isinstance(params, dict):
            self.send_json_response(400, {"error": "Invalid JSON body"})
            return
        if BOT_PROCESS is not None and BOT_PROCESS.poll() is None:
            self.send_json_response(409, {"status": "already_running", "pid": BOT_PROCESS.pid})
            return
        values = {
            "sizing_mode": params.get("sizing_mode", "margin"),
            "margin_pct": params.get("margin_pct", 0.03),
            "leverage": params.get("leverage", 75),
            "threshold": params.get("threshold", 30),
            "timeframe": params.get("timeframe", "15m"),
            "max_positions": params.get("max_positions", 5),
            "directional_cap": params.get("directional_cap", 5),
        }
        py_exec = get_python_executable()
        cmd = [py_exec, os.path.join(PROJECT_DIR, "main.py"), "--trade-live"]
        for key, value in values.items():
            cmd.extend([f"--{key.replace('_', '-')}", str(value)])
        try:
            with open(LOG_FILE_PATH, "a", encoding="utf-8") as log_file:
                log_file.write(f"\n--- BOT STARTED: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} ---\n")
                log_file.flush()
                BOT_PROCESS = subprocess.Popen(cmd, cwd=PROJECT_DIR, stdout=log_file, stderr=subprocess.STDOUT)
            self.send_json_response(200, {"status": "success", "message": f"Bot started (PID: {BOT_PROCESS.pid})", "running": True, "pid": BOT_PROCESS.pid})
        except OSError as exc:
            BOT_PROCESS = None
            self.send_json_response(500, {"status": "error", "message": f"Failed to start bot: {exc}", "running": False})

    def handle_api_stop(self):
        global BOT_PROCESS
        if BOT_PROCESS is None or BOT_PROCESS.poll() is not None:
            BOT_PROCESS = None
            self.send_json_response(409, {"status": "not_running", "running": False})
            return
        BOT_PROCESS.terminate()
        try:
            BOT_PROCESS.wait(timeout=3)
        except subprocess.TimeoutExpired:
            BOT_PROCESS.kill()
            BOT_PROCESS.wait(timeout=3)
        finally:
            BOT_PROCESS = None
        self.send_json_response(200, {"status": "success", "message": "Bot stopped successfully", "running": False})

    def send_json_response(self, code, data):
        try:
            payload = json.dumps(data).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:8080")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Atlas-Token")
        self.end_headers()


if __name__ == "__main__":
    os.chdir(PROJECT_DIR)
    server = ThreadingHTTPServer((HOST, PORT), WebDashboardHandler)
    print("=======================================================")
    print(" ATLAS WEB DASHBOARD & BOT CONTROL SERVER ACTIVE")
    print(f" URL: http://{HOST}:{PORT}")
    print(f" Authentication: {'enabled' if API_TOKEN else 'localhost-only'}")
    print(f" Python Interpreter: {get_python_executable()}")
    print("=======================================================")
    server.serve_forever()
