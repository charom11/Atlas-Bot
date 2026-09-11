# Comprehensive Fix Plan: main.py Hardening & Simplification

**Target File:** `d:\Bot2\main.py`  
**Associated Files:** `d:\Bot2\data\state\atlas_darwinian_weights.json`, `d:\Bot2\tests\test_silent_exception_hardening.py`  
**Context:** Resolution of critical trading safety bugs, concurrency race conditions, security holes, and Ponytail bloat pruning identified during the comprehensive audit.

---

## Executive Summary of Issues

| Category | Severity | Issue | Impact |
| :--- | :--- | :--- | :--- |
| **Trading Logic** | **CRITICAL (P0)** | Darwinian Channel Attribution Bug | 95%+ of trade outcomes default to `FIBONACCI`, corrupting Darwinian weights (`0.80x` penalty) |
| **Concurrency** | **CRITICAL (P0)** | No Thread Locks in Telegram C2 vs Main Loop | Race conditions on `ACTIVE_POSITION_TARGETS`, order collisions, `RuntimeError` during dict iteration |
| **Trading Safety** | **HIGH (P1)** | Protective Stop Desync on Failure | `target['current_sl'] = tight_sl` set even when Binance rejected the stop |
| **Security** | **HIGH (P1)** | Telegram C2 Fails Open | If `TELEGRAM_CHAT_ID` is empty, ANY user can execute `/live`, `/closeall`, or change leverage |
| **Reliability** | **MEDIUM (P1)** | `_TeeLogger` Rotation Exception on Windows | Closed log handle on `os.rename` failure kills file logging permanently |
| **Complexity** | **PONYTAIL (P2)** | ~500+ Lines of Dead / Over-Engineered Code | Unreachable Quick Scalp framework, dead MTF heatmap, single-method class wrappers |
| **Performance** | **OPTIMIZATION (P2)** | Unpooled HTTP Connections & Redundant Calls | 11 TLS handshakes every 15s; 6 redundant position queries during emergency liquidation |

---

## Phase 1: Critical Trading Safety & Logic Bugs (P0)

### 1.1 Fix Darwinian Channel Attribution Bug
* **Location:** `main.py` lines 489–492 & lines 2732–2735.
* **Root Cause:** In `manage_active_positions_breakeven()`, closed positions are popped from `ACTIVE_POSITION_TARGETS`. When `sync_binance_realized_pnl()` runs later, the symbol is already gone from `ACTIVE_POSITION_TARGETS`, causing `target_ch` to always fall back to `'FIBONACCI'`.
* **Fix:**
  1. Introduce an in-memory TTL/FIFO cache `CLOSED_POSITION_CHANNELS = {}` (symbol -> `{'channel': ch, 'closed_at': timestamp}`).
  2. When a symbol closes in `manage_active_positions_breakeven()`, store its channel in `CLOSED_POSITION_CHANNELS` before popping.
  3. In `sync_binance_realized_pnl()`, look up the channel first from `ACTIVE_POSITION_TARGETS`, then fallback to `CLOSED_POSITION_CHANNELS`.
  4. Reset `data/state/atlas_darwinian_weights.json` so `FIBONACCI` is restored to `1.0x` and weights restart cleanly.

```python
# --- BEFORE ---
# Line 489:
target_ch = ACTIVE_POSITION_TARGETS.get(sym, {}).get('channel', 'FIBONACCI') if 'ACTIVE_POSITION_TARGETS' in globals() else 'FIBONACCI'

# --- AFTER ---
_CLOSED_POSITION_CHANNELS = {}  # sym -> (channel, timestamp)

def record_closed_position_channel(symbol, channel):
    now = time.time()
    _CLOSED_POSITION_CHANNELS[symbol] = (channel, now)
    # Prune records older than 24 hours
    expired = [s for s, (_, ts) in _CLOSED_POSITION_CHANNELS.items() if now - ts > 86400]
    for s in expired:
        _CLOSED_POSITION_CHANNELS.pop(s, None)

def get_channel_for_symbol(symbol):
    if symbol in ACTIVE_POSITION_TARGETS:
        return ACTIVE_POSITION_TARGETS[symbol].get('channel', 'FIBONACCI')
    if symbol in _CLOSED_POSITION_CHANNELS:
        return _CLOSED_POSITION_CHANNELS[symbol][0]
    return 'FIBONACCI'
```

---

### 1.2 Fix Thread Safety & Race Conditions (Telegram C2 vs Main Loop)
* **Location:** `main.py` lines 4007–4480 & lines 2709–2956.
* **Root Cause:** Background thread `poll_telegram_updates` runs `handle_telegram_command` without locks, concurrently mutating `ACTIVE_POSITION_TARGETS`, `latest_model_states`, and placing orders while the main thread evaluates bars and manages stops.
* **Fix:**
  1. Define a global re-entrant lock: `_ENGINE_LOCK = threading.RLock()`.
  2. Wrap dictionary mutations and state updates in `with _ENGINE_LOCK:`.
  3. In Telegram commands (`/models`, `/scalpslots`), iterate over shallow copies (`list(self.latest_model_states.items())`, `list(ACTIVE_POSITION_TARGETS.items())`) to eliminate `RuntimeError: dictionary changed size during iteration`.
  4. Guard `/closeall` and `/live` order placement paths with `_ENGINE_LOCK` to prevent simultaneous order placement.

```python
# --- Thread Synchronization Wrapper ---
_ENGINE_LOCK = threading.RLock()

# In handle_telegram_command:
elif cmd in ['/models', '/matrix', '/consensus']:
    with _ENGINE_LOCK:
        items = list(self.latest_model_states.items())
    for sym, data in items:
        ...

elif cmd in ['/closeall', '/panic']:
    with _ENGINE_LOCK:
        results = close_all_binance_futures_positions()
        cleanup_orphaned_orders()
```

---

### 1.3 Fix Protective Stop Desync on Update Rejection
* **Location:** `main.py` line 2899.
* **Root Cause:**
  ```python
  if new_order_id is not None and tight_str is not None:
      target['sl_order_id'] = new_order_id
      target['current_sl'] = tight_sl
  else:
      target['current_sl'] = tight_sl  # <--- Overwrites SL price even though order failed!
  ```
* **Fix:** Remove the unconditional `else` assignment. If `_replace_protective_stop` fails, keep `target['current_sl']` as the restored stop price or retain the previous safe level.

```python
# --- AFTER ---
if new_order_id is not None and tight_str is not None:
    target['sl_order_id'] = new_order_id
    target['current_sl'] = tight_sl
else:
    print(f"[STOP TIGHTEN WARN] #{sym} stop replacement failed on Binance; retaining current stop ${target.get('current_sl')}.", flush=True)
```

---

### 1.4 Fix Telegram C2 Fail-Open Authentication Security Hole
* **Location:** `main.py` lines 4020–4025.
* **Root Cause:**
  ```python
  def is_authorized(sender_id, chat_id):
      if not TELEGRAM_CHAT_ID or not str(TELEGRAM_CHAT_ID).strip():
          return True  # Fails open to the entire world!
  ```
* **Fix:** Fail closed. If `TELEGRAM_CHAT_ID` is empty, log a warning and return `False`.

```python
# --- AFTER ---
def is_authorized(sender_id, chat_id):
    configured = os.getenv('TELEGRAM_CHAT_ID', TELEGRAM_CHAT_ID).strip().strip('"').strip("'")
    if not configured:
        print(f"[TELEGRAM C2 SECURITY] Rejected command: TELEGRAM_CHAT_ID is not configured in .env! (Fail Closed)", flush=True)
        return False
    allowed = [s.strip() for s in configured.split(',') if s.strip()]
    return str(sender_id) in allowed or str(chat_id) in allowed
```

---

### 1.5 Fix `_TeeLogger` Rotator Silent Failure on Windows
* **Location:** `main.py` lines 77–95.
* **Root Cause:** `self._log.close()` is called before `os.rename()`. If Windows file locks or antivirus trigger an exception during rename, the `except Exception: pass` leaves `self._log` closed.
* **Fix:** Ensure `self._log` is immediately reopened if an exception occurs during rotation, or migrate to standard library `logging.handlers.RotatingFileHandler`.

```python
# --- AFTER (Hardened Reopening) ---
def _rotate_if_needed(self):
    if self._log.tell() < self._max_bytes:
        return
    try:
        self._log.close()
        for i in range(self._backup_count - 1, 0, -1):
            sfn = f"{self._filepath}.{i}"
            dfn = f"{self._filepath}.{i+1}"
            if os.path.exists(sfn):
                if os.path.exists(dfn):
                    os.remove(dfn)
                os.rename(sfn, dfn)
        dfn = f"{self._filepath}.1"
        if os.path.exists(dfn):
            os.remove(dfn)
        if os.path.exists(self._filepath):
            os.rename(self._filepath, dfn)
    except Exception as rot_err:
        pass
    finally:
        # Guarantee log file is ALWAYS open for writes
        if self._log.closed:
            self._log = open(self._filepath, 'a', encoding='utf-8', buffering=1)
```

---

## Phase 2: Ponytail Complexity & Bloat Pruning (P1)

### 2.1 Delete Dead Code & Unused Modules (~250 lines)
1. **Delete `_fetch_single_sym_mtf` & `get_mtf_heatmap_data`** (lines 805–857): 53 lines of dead code that spawn a 9-worker thread pool making 36 unneeded HTTP requests.
2. **Delete `get_mtf_divergence_matrix` & `get_divergence_status`** (lines 1104–1172): 69 lines of dead code that spawn 4 threads. Local divergence is already computed via `calc_rsi_cci_divergence(df)`.
3. **Delete `MilestoneLockManager`** (lines 634–662): 29 lines that hardcode a $14.20 wallet and do not enforce any equity constraints.
4. **Delete Dead Helper Functions**:
   - `get_symbol_min_notional` (lines 1305–1307): 3 lines.
   - `CircuitBreakerManager.record_trade_result` (lines 580–591): 12 lines.
   - `WeatherEnsembleBot.calc_ema` (lines 3323–3324): 2 lines.

---

### 2.2 Purge Dead Quick-Scalp Scaffolding (~150 lines)
* `trade_is_scalp = False` is hardcoded across all strategy channels (Fibonacci, MSS, Consensus, Potato, Divergence).
* `max_scalp_slots = 0` is hardcoded on line 3672.
* Counter-trend trades are strictly blocked in `check_macro_and_mss_bias`.
* **Action:**
  - Remove dead Stage 0 ("Fast Early Breakeven for Quick Scalps", lines 2787–2810).
  - Simplify `place_binance_futures_tp_sl`: remove `if is_quick_scalp` branch and retain unified swing scale-out.
  - Remove dead Telegram commands `/scalpslots`, `/scalpcap` (lines 4358–4410).
  - Remove dead CLI flags `--max-scalp-slots`, `--disable-scalp-cap`.

---

### 2.3 Flatten Over-Engineered Single-Method Classes into Lean Functions
* **`AdversarialCRO`** (lines 742–764) -> Replace class with a 10-line helper function:
  ```python
  def inspect_adversarial_cro(symbol, side, current_price, ema50, atr14, df=None):
      if ema50 > 0 and atr14 > 0 and abs(current_price - ema50) > (2.8 * atr14):
          return False, f"Overextended from 50 EMA (> 2.8x ATR)"
      if df is not None and len(df) >= 4:
          c = df['close'].values
          if (c[-3] > c[-2] < c[-1] or c[-3] < c[-2] > c[-1]) and abs(c[-1] - c[-3]) < 0.20 * atr14:
              return False, "Compressed Micro-Whipsaw Zone"
      return True, "Passed CRO Risk Inspection"
  ```
* **`JanusRegimeDetector`** (lines 769–785) -> Replace class with a 6-line helper function:
  ```python
  def get_adaptive_rr(adx_val, is_trending):
      if is_trending and adx_val >= 28.0:
          return 1.5
      return 2.2 if adx_val <= 20.0 else 1.8
  ```

---

## Phase 3: Performance & Network Optimization (P2)

### 3.1 Persistent HTTP Connection Pool (`requests.Session`)
* **Problem:** `requests.get()` in `fetch_binance_klines`, `check_order_book_imbalance`, and `check_order_flow_absorption` opens and closes TLS connections on every request (11+ TLS handshakes every 15 seconds).
* **Fix:** Reuse a persistent `_BINANCE_HTTP_SESSION = requests.Session()` with connection pooling (`pool_connections=10, pool_maxsize=20`).

### 3.2 Optimize `close_all_binance_futures_positions`
* **Problem:** Calls `get_binance_futures_positions()`, then loops and calls `close_binance_futures_position()` which queries positions *again* for each asset.
* **Fix:** Pass the pre-fetched position object directly to close each asset without redundant API calls.

### 3.3 Periodic Clock Drift Synchronization
* Call `sync_server_time()` once every hour inside the live loop to prevent Windows system clock drift from causing -1021 timestamp errors.

---

## Verification Plan

### Automated Regression Tests
Run the entire repository test suite to verify no regressions:
```bash
d:\Bot2\.venv\Scripts\python -m pytest tests/
```

### New Dedicated Tests to Add
1. **Darwinian Attribution Test**: Verify that closed positions retain their channel association in `CLOSED_POSITION_CHANNELS` and record outcomes correctly to `MSS_SHIFT`, `5MA_CONSENSUS`, etc.
2. **Telegram Auth Fail-Closed Test**: Verify `is_authorized("12345", "12345")` returns `False` when `TELEGRAM_CHAT_ID` is empty.
3. **Thread Safety Test**: Concurrently execute `/models` and `/status` in a thread while mutating `ACTIVE_POSITION_TARGETS` and assert no `RuntimeError` occurs.
4. **Protective Stop Failure Test**: Verify that when `_replace_protective_stop` fails, `target['current_sl']` is NOT updated.
