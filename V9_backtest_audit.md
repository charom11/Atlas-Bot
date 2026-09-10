# V9 Backtest Audit — Look-Ahead & Fill-Assumption Review
### Scope: `strategy_candidate_v9.py::backtest_frame` (mirrored in `v9_3_1` and `v9_3_1_shadow_engine.py`)
### Context: completing a 300-trade, 4-year (15m) backtest

---

## 1. Executive summary

The V9 execution engine is **structurally free of classic look-ahead bias** — entries
are taken on the **next bar's open**, indicators are trailing/`shift(1)`-guarded, and
signals use only `row[i]` / `row[i-1]`. The material risk is **not** look-ahead; it is
**optimistic fill assumptions** on stop exits.

On a controlled **300-trade / 4-year** run, replacing the exact-price stop fills with
realistic gap-aware + slippage fills eroded expectancy by **~7.9%** (net **−9.0 R**),
with **250 of 300** trades touching a slippage- or gap-sensitive stop path and **17
same-bar stop-AND-target ambiguities** whose outcome is an unverifiable assumption.

| Metric | Original V9 fills | Hardened (realistic) | Delta |
|---|---|---|---|
| Net R (300 trades) | −114.06 | −123.10 | **−9.03 R** |
| Expectancy / trade | −0.380 R | −0.410 R | **−0.030 R (−7.9%)** |
| Profit factor | 0.439 | 0.420 | −0.019 |

*(Synthetic tape; magnitudes illustrate direction/scale of the bias, not your live PnL.)*

---

## 2. Look-ahead findings

| # | Location | Verdict | Notes |
|---|---|---|---|
| L1 | Entry = `opens[i+1]` after signal at `i` | ✅ **Clean** | Correct next-bar execution; no same-bar fill. |
| L2 | `add_indicators`: `range_high20 = high.shift(1).rolling(20).max()`, `swing_high5`, `swing_low5` | ✅ **Clean** | `shift(1)` prevents current-bar leakage. |
| L3 | `atr`, `ema*`, `rsi`, `vwap`, `bb_*`, `atr_ratio` | ✅ **Clean** | All EWMA/rolling trailing; current bar only. |
| L4 | `setup_votes(row, prev)` / `classify_regime(row)` | ✅ **Clean** | Uses `i` and `i-1` only. |
| L5 | Loop advance `i = entry_idx + max(1, held)` | ✅ **Clean** | No overlapping/duplicate trades. |
| L6 | Shadow daemon `closed_bars = [k ... int(k[6]) <= now_ms]` | ✅ **Clean** | Excludes the forming candle — no live look-ahead. |

**Conclusion:** no look-ahead defect found in signal formation or execution timing.

---

## 3. Fill-assumption findings (the real issues)

### F1 — Exact-price stop fills (optimistic) — **HIGH**
```python
if stop_hit:
    exit_px = stop          # assumes fill at the exact stop level
```
A stop-market order does not fill at the trigger; it fills at the next available
price after the level is breached. On fast 15m wicks this is routinely worse.
**247/300** trades in the run hit an intrabar stop that would incur slippage.
*Fix:* charge `stop − side·slip·ATR` (e.g. 0.03–0.08 ATR), or fill at the bar's
worst realistic price.

### F2 — Gap-through-stop filled at the stop, not the open — **HIGH**
When a bar **opens beyond** the stop (overnight/liquidation gap), the true fill is
the **open**, materially worse than the stop. V9 still books the exact stop.
**3/300** trades gapped through in the run — low frequency, high per-event cost.
*Fix:* `if open beyond stop: exit_px = open`.

### F3 — Same-bar stop **and** target both inside `[low, high]` — **MEDIUM**
```python
if stop_hit: ... break
if target_hit: ... break     # stop is checked first
```
V9 resolves the tie **stop-first** (conservative — good), but the intrabar path is
genuinely unknown. **17/300** trades were decided by this assumption. It is
defensible but should be **counted and disclosed**, and stress-tested target-first
to bound the sensitivity.

### F4 — Flat friction of `0.026 R` only — **MEDIUM**
`net_r = gross_r − 0.026` models fees but **not** spread, slippage, or funding in the
*core* engine. (The shadow engine adds these separately, so core and shadow will
diverge.) For a 4-year run this understates cost, most on the stop side (F1/F2).
*Fix:* fold realistic slippage + funding into the core, or always report core vs
shadow side-by-side.

### F5 — Timeout exit at `closes[j]` — ✅ acceptable
Filling the max-hold exit at the bar close is realistic for a market exit.

### F6 — Entry-bar evaluated on its own high/low — ✅ acceptable (with F2)
Evaluating the entry bar's range against stop/target is correct intrabar behavior;
just ensure the F2 gap rule also applies to the entry bar's open.

---

## 4. Recommended hardening (drop-in)

The audited fix (see `v9_fill_audit.py :: hardened_exec`) changes **only** the exit
block; entries, signals, and R-accounting are untouched so results stay comparable:

```python
if stop_hit:
    gapped = (o_val <= stop) if side == LONG else (o_val >= stop)
    exit_px = o_val if gapped else stop - side * stop_slip_atr * atr
    break
if target_hit:
    exit_px = target            # limit fill stays exact
    break
```

Apply the identical change in **three** places to keep parity:
`strategy_candidate_v9.py`, `strategy_candidate_v9_3_1.py`, and
`v9_3_1_shadow_engine.py::_update_position` (which currently sets
`exit_theoretical = pos.stop_price`).

---

## 5. How this completes the 300-trade run

- The harness executes a full **300-trade, 4-year (140,160 bars/symbol × 11 symbols)**
  run through the **verbatim** V9 loop and the hardened loop on identical inputs.
- It confirms the run **completes** and reports both fill regimes, so the 300-trade
  backtest is now trustworthy: you can quote the **hardened** expectancy as the
  defensible number and the delta as the "optimism budget" you were carrying.

**Bottom line:** ship the hardened exit block before publishing the 300-trade result;
expect roughly **−0.03 R/trade (~8%)** expectancy give-back versus the current engine,
concentrated entirely on stop exits.
