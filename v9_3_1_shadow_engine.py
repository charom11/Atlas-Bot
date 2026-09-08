"""V9.3.1 Shadow Layer Engine: Real-Time Opportunity Admission & Outcome Telemetry.

Strictly decoupled observer layer:
- Evaluates live 15m candle evidence against Candidate V9.3.1 policy.
- Zero live execution risk: never accesses order placement endpoints.
- Tracks simulated forward positions bar-by-bar to evaluate true forward edge.
- Persists opportunity logs, open positions, and resolved trade outcomes atomically.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Mapping, Sequence, Optional
from pathlib import Path
import json
import os
import sys
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd

from strategy_candidate_v9 import (
    LONG,
    SHORT,
    FLAT,
    SETUPS,
    REGIMES,
    _num,
    add_indicators,
    classify_regime,
    setup_votes,
)
from strategy_candidate_v9_3_1 import (
    V931Config,
    ShadowOpportunity,
    ACTIVE_SETUPS_V931,
    DISABLED_SETUPS_V931,
    ALLOWED_REGIMES_V931,
    GATED_REGIMES_V931,
    TIER_1,
    TIER_2,
    TIER_3,
    asset_allowed,
    target_stop_atr,
    admit_opportunity,
)

DEFAULT_DATA_DIR = Path("data") / "shadow_v9_3_1"


@dataclass
class ShadowPosition:
    position_id: str
    symbol: str
    side: int  # 1 for LONG, -1 for SHORT
    setup: str
    regime: str
    entry_bar_time: str
    entry_price: float
    stop_price: float
    target_price: float
    atr: float
    score: int
    confirmations: int
    bars_held: int = 0
    max_favorable_price: float = 0.0
    max_adverse_price: float = 0.0
    # Layer 1 — Strategy
    predicted_entry: float = 0.0
    predicted_stop: float = 0.0
    predicted_target: float = 0.0
    predicted_r: float = 2.0
    # Layer 2 — Market
    entry_bid: float = 0.0
    entry_ask: float = 0.0
    spread_usd: float = 0.0
    spread_bps: float = 0.0
    mark_price: float = 0.0
    volatility_atr_pct: float = 0.0
    funding_rate_8h: float = 0.0
    bid_qty: float = 0.0
    ask_qty: float = 0.0
    # Layer 3 — Execution Simulation
    theoretical_candle_open_fill: float = 0.0
    observable_market_price_fill: float = 0.0
    estimated_realistic_fill: float = 0.0
    entry_slippage_r: float = 0.0
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["layer1_strategy"] = {
            "predicted_entry": self.predicted_entry or self.entry_price,
            "predicted_stop": self.predicted_stop or self.stop_price,
            "predicted_target": self.predicted_target or self.target_price,
            "setup": self.setup,
            "regime": self.regime,
            "asset": self.symbol,
            "predicted_r": self.predicted_r,
        }
        d["layer2_market"] = {
            "bid_at_signal": self.entry_bid,
            "ask_at_signal": self.entry_ask,
            "spread_usd": self.spread_usd,
            "spread_bps": self.spread_bps,
            "mark_price": self.mark_price,
            "volatility_atr_pct": self.volatility_atr_pct,
            "funding_rate_8h": self.funding_rate_8h,
            "order_book_depth": {
                "bid_qty": self.bid_qty,
                "ask_qty": self.ask_qty,
            },
        }
        d["layer3_execution"] = {
            "theoretical_candle_open_fill": self.theoretical_candle_open_fill or self.entry_price,
            "observable_market_price_fill": self.observable_market_price_fill or self.entry_price,
            "estimated_realistic_fill": self.estimated_realistic_fill or self.entry_price,
            "entry_slippage_r": self.entry_slippage_r,
            "latency_ms": self.latency_ms,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ShadowPosition:
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        if "predicted_entry" not in filtered and "entry_price" in filtered:
            filtered["predicted_entry"] = filtered["entry_price"]
        if "predicted_stop" not in filtered and "stop_price" in filtered:
            filtered["predicted_stop"] = filtered["stop_price"]
        if "predicted_target" not in filtered and "target_price" in filtered:
            filtered["predicted_target"] = filtered["target_price"]
        if "theoretical_candle_open_fill" not in filtered and "entry_price" in filtered:
            filtered["theoretical_candle_open_fill"] = filtered["entry_price"]
        return cls(**filtered)


@dataclass
class ShadowOutcome:
    position_id: str
    symbol: str
    side: int
    setup: str
    regime: str
    entry_bar_time: str
    exit_bar_time: str
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    outcome_type: str  # "TARGET", "STOP", "TIMEOUT"
    gross_r: float
    net_r: float
    friction_r: float
    bars_held: int
    resolved_at: str
    # Layer 1 — Strategy
    predicted_entry: float = 0.0
    predicted_stop: float = 0.0
    predicted_target: float = 0.0
    predicted_r: float = 2.0
    # Layer 2 — Market
    bid_at_signal: float = 0.0
    ask_at_signal: float = 0.0
    spread_usd: float = 0.0
    spread_bps: float = 0.0
    mark_price: float = 0.0
    volatility_atr_pct: float = 0.0
    funding_rate_8h: float = 0.0
    bid_qty: float = 0.0
    ask_qty: float = 0.0
    # Layer 3 — Execution Simulation
    theoretical_candle_open_fill: float = 0.0
    observable_market_price_fill: float = 0.0
    estimated_realistic_fill: float = 0.0
    exit_theoretical_fill: float = 0.0
    exit_realistic_fill: float = 0.0
    slippage_in_r: float = 0.0
    funding_drag_in_r: float = 0.0
    theoretical_net_r: float = 0.0
    final_net_r: float = 0.0
    latency_ms: float = 0.0
    entry_spread_bps: float = 0.0
    exit_spread_bps: float = 0.0
    realized_slippage_r: float = 0.0
    realized_funding_r: float = 0.0
    total_friction_r: float = 0.026
    empirical_net_r: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["layer1_strategy"] = {
            "predicted_entry": self.predicted_entry or self.entry_price,
            "predicted_stop": self.predicted_stop or self.stop_price,
            "predicted_target": self.predicted_target or self.target_price,
            "setup": self.setup,
            "regime": self.regime,
            "asset": self.symbol,
            "predicted_r": self.predicted_r,
        }
        d["layer2_market"] = {
            "bid_at_signal": self.bid_at_signal or self.entry_price,
            "ask_at_signal": self.ask_at_signal or self.entry_price,
            "spread_usd": self.spread_usd,
            "spread_bps": self.spread_bps or self.entry_spread_bps,
            "mark_price": self.mark_price or self.entry_price,
            "volatility_atr_pct": self.volatility_atr_pct,
            "funding_rate_8h": self.funding_rate_8h,
            "order_book_depth": {
                "bid_qty": self.bid_qty,
                "ask_qty": self.ask_qty,
            },
        }
        d["layer3_execution"] = {
            "theoretical_candle_open_fill": self.theoretical_candle_open_fill or self.entry_price,
            "observable_market_price_fill": self.observable_market_price_fill or self.entry_price,
            "estimated_realistic_fill": self.estimated_realistic_fill or self.entry_price,
            "slippage_in_r": self.slippage_in_r or self.realized_slippage_r,
            "funding_drag_in_r": self.funding_drag_in_r or self.realized_funding_r,
            "theoretical_net_r": self.theoretical_net_r or self.net_r,
            "final_net_r": self.final_net_r or self.empirical_net_r or self.net_r,
            "latency_ms": self.latency_ms,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ShadowOutcome:
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        if "predicted_entry" not in filtered and "entry_price" in filtered:
            filtered["predicted_entry"] = filtered["entry_price"]
        if "predicted_stop" not in filtered and "stop_price" in filtered:
            filtered["predicted_stop"] = filtered["stop_price"]
        if "predicted_target" not in filtered and "target_price" in filtered:
            filtered["predicted_target"] = filtered["target_price"]
        if "theoretical_candle_open_fill" not in filtered and "entry_price" in filtered:
            filtered["theoretical_candle_open_fill"] = filtered["entry_price"]
        if "theoretical_net_r" not in filtered and "net_r" in filtered:
            filtered["theoretical_net_r"] = filtered["net_r"]
        if "final_net_r" not in filtered and "net_r" in filtered:
            filtered["final_net_r"] = filtered.get("empirical_net_r", filtered["net_r"])
        return cls(**filtered)


class V931ShadowEngine:
    """Core stateful shadow engine evaluating opportunities and tracking forward trade outcomes."""

    def __init__(
        self,
        config: V931Config = V931Config(),
        data_dir: Path | str = DEFAULT_DATA_DIR,
        friction_r: float = 0.026,
        max_hold_bars: int = 32,
    ):
        self.config = config
        self.data_dir = Path(data_dir)
        self.friction_r = friction_r
        self.max_hold_bars = max_hold_bars

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.opps_file = self.data_dir / "opportunities.jsonl"
        self.outcomes_file = self.data_dir / "outcomes.jsonl"
        self.positions_file = self.data_dir / "open_positions.json"
        self.summary_file = self.data_dir / "telemetry_summary.json"

        self.open_positions: dict[str, ShadowPosition] = {}
        self.pending_admissions: dict[str, ShadowOpportunity] = {}
        self.last_evaluated_bar: dict[str, str] = {}

        self.load_state()

    def load_state(self) -> None:
        """Atomic recovery of active shadow positions from disk."""
        if self.positions_file.exists():
            try:
                with open(self.positions_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.open_positions = {
                        k: ShadowPosition.from_dict(v) for k, v in data.get("open_positions", {}).items()
                    }
                    self.last_evaluated_bar = data.get("last_evaluated_bar", {})
            except Exception as e:
                print(f"[V9.3.1 SHADOW WARN] Failed to load state from {self.positions_file}: {e}", flush=True)

    def save_state(self) -> None:
        """Atomically persist open shadow positions to disk."""
        temp_file = self.positions_file.with_suffix(".tmp")
        data = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_evaluated_bar": self.last_evaluated_bar,
            "open_positions": {k: v.to_dict() for k, v in self.open_positions.items()},
        }
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self.positions_file)
        except Exception as e:
            print(f"[V9.3.1 SHADOW ERROR] Failed to save state to {self.positions_file}: {e}", flush=True)

    def evaluate_bar(
        self,
        symbol: str,
        df: pd.DataFrame,
        market_context: Optional[dict] = None,
    ) -> tuple[Optional[ShadowOpportunity], list[ShadowOutcome]]:
        """Process a completed 15m candle for symbol.

        1. Updates any open shadow position for this symbol against the latest completed candle.
        2. Opens any position that was admitted on the previous candle using this candle's open.
        3. Evaluates admission evidence on the latest candle for the next bar.
        """
        symbol = symbol.upper()
        if df is None or len(df) <= 201:
            return None, []

        resolved_outcomes: list[ShadowOutcome] = []

        # Prepare indicator DataFrame
        data = add_indicators(df)
        if "symbol" not in data.columns:
            data["symbol"] = symbol
        data["regime"] = data.apply(classify_regime, axis=1)

        last_row = data.iloc[-1]
        prev_row = data.iloc[-2]
        bar_timestamp = str(last_row.name)

        # Prevent duplicate evaluation of the exact same completed bar
        if self.last_evaluated_bar.get(symbol) == bar_timestamp:
            return None, []

        # Inject volatility metric into market_context if available
        if market_context is not None and "volatility_atr_pct" not in market_context:
            close_p = float(last_row["close"]) if float(last_row["close"]) > 0 else 1.0
            market_context["volatility_atr_pct"] = float((last_row.get("atr", 0.0) / close_p) * 100.0)

        # 1. Update any existing open shadow position using latest candle
        if symbol in self.open_positions:
            outcome = self._update_position(symbol, last_row, bar_timestamp, market_context=market_context)
            if outcome:
                resolved_outcomes.append(outcome)

        # 2. Check if there was a pending admission waiting to open on this candle's open
        if symbol in self.pending_admissions and symbol not in self.open_positions:
            pending_opp = self.pending_admissions.pop(symbol)
            open_px = float(last_row["open"])
            self._open_shadow_position(pending_opp, open_px, bar_timestamp, market_context=market_context)

        # 3. Evaluate the latest closed candle for candidate opportunities
        votes = setup_votes(last_row, prev_row)
        opp = admit_opportunity(last_row, votes, self.config)

        # Log opportunity telemetry
        self._record_opportunity(opp, bar_timestamp, symbol, market_context=market_context)

        if opp and opp.admitted and symbol not in self.open_positions:
            # Stage for next-bar open execution
            self.pending_admissions[symbol] = opp

        self.last_evaluated_bar[symbol] = bar_timestamp
        self.save_state()
        if resolved_outcomes:
            self.update_summary()

        return opp, resolved_outcomes

    def _open_shadow_position(
        self,
        opp: ShadowOpportunity,
        entry_price: float,
        bar_timestamp: str,
        market_context: Optional[dict] = None,
    ) -> ShadowPosition:
        """Initialize and register an admitted forward shadow trade with 3-layer audit telemetry."""
        stop_mult, target_mult = target_stop_atr(opp.setup, self.config)
        stop_price = entry_price - opp.side * stop_mult * opp.atr
        target_price = entry_price + opp.side * target_mult * opp.atr
        pos_id = f"{opp.symbol}_{opp.setup}_{int(time.time())}"

        # Layer 1: Strategy predicted R
        predicted_r = target_mult / stop_mult if stop_mult > 0 else 2.0

        # Layer 2: Market conditions
        bid = market_context.get("bid", 0.0) if market_context else 0.0
        ask = market_context.get("ask", 0.0) if market_context else 0.0
        mid = (bid + ask) / 2.0 if (bid + ask) > 0 else entry_price
        spread_usd = market_context.get("spread_usd", 0.0) if market_context else 0.0
        spread_bps = market_context.get("spread_bps", 0.0) if market_context else 0.0
        mark_price = market_context.get("mark_price", mid) if market_context else mid
        vol_atr_pct = market_context.get("volatility_atr_pct", 0.0) if market_context else 0.0
        funding_rate = market_context.get("funding_rate_8h", 0.0001) if market_context else 0.0001
        bid_qty = market_context.get("bid_qty", 0.0) if market_context else 0.0
        ask_qty = market_context.get("ask_qty", 0.0) if market_context else 0.0
        latency_ms = market_context.get("latency_ms", 0.0) if market_context else 0.0

        # Layer 3: Execution simulation (at entry)
        theoretical_fill = entry_price
        observable_fill = mid if mid > 0 else entry_price
        if opp.side == LONG:
            realistic_fill = max(theoretical_fill, ask) if ask > 0 else theoretical_fill
        else:
            realistic_fill = min(theoretical_fill, bid) if bid > 0 else theoretical_fill

        denom = max(abs(entry_price - stop_price), 1e-12)
        entry_slip_usd = abs(realistic_fill - theoretical_fill)
        entry_slip_r = entry_slip_usd / denom

        pos = ShadowPosition(
            position_id=pos_id,
            symbol=opp.symbol,
            side=opp.side,
            setup=opp.setup,
            regime=opp.regime,
            entry_bar_time=bar_timestamp,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            atr=opp.atr,
            score=opp.score,
            confirmations=opp.confirmations,
            bars_held=0,
            max_favorable_price=entry_price,
            max_adverse_price=entry_price,
            predicted_entry=entry_price,
            predicted_stop=stop_price,
            predicted_target=target_price,
            predicted_r=round(predicted_r, 2),
            entry_bid=bid,
            entry_ask=ask,
            spread_usd=round(spread_usd, 6),
            spread_bps=round(spread_bps, 2),
            mark_price=round(mark_price, 4),
            volatility_atr_pct=round(vol_atr_pct, 4),
            funding_rate_8h=funding_rate,
            bid_qty=bid_qty,
            ask_qty=ask_qty,
            theoretical_candle_open_fill=theoretical_fill,
            observable_market_price_fill=observable_fill,
            estimated_realistic_fill=realistic_fill,
            entry_slippage_r=round(entry_slip_r, 4),
            latency_ms=round(latency_ms, 1),
        )
        self.open_positions[opp.symbol] = pos
        return pos

    def _update_position(
        self,
        symbol: str,
        row: pd.Series,
        bar_timestamp: str,
        market_context: Optional[dict] = None,
    ) -> Optional[ShadowOutcome]:
        """Check stop, target, or timeout on current candle with 3-layer execution simulation."""
        pos = self.open_positions[symbol]
        pos.bars_held += 1

        high_px = float(row["high"])
        low_px = float(row["low"])
        close_px = float(row["close"])

        # Track extreme excursions
        if pos.side == LONG:
            pos.max_favorable_price = max(pos.max_favorable_price, high_px)
            pos.max_adverse_price = min(pos.max_adverse_price, low_px)
        else:
            pos.max_favorable_price = min(pos.max_favorable_price, low_px)
            pos.max_adverse_price = max(pos.max_adverse_price, high_px)

        stop_hit = (low_px <= pos.stop_price) if pos.side == LONG else (high_px >= pos.stop_price)
        target_hit = (high_px >= pos.target_price) if pos.side == LONG else (low_px <= pos.target_price)
        timeout_hit = pos.bars_held >= self.max_hold_bars

        if not (stop_hit or target_hit or timeout_hit):
            return None

        # Layer 2: Exit market conditions
        exit_bid = market_context.get("bid", 0.0) if market_context else 0.0
        exit_ask = market_context.get("ask", 0.0) if market_context else 0.0
        exit_spread_bps = market_context.get("spread_bps", 0.0) if market_context else 0.0

        # Layer 3: Determine outcome & execution fills
        if stop_hit:
            exit_theoretical = pos.stop_price
            outcome_type = "STOP"
            exit_realistic = min(pos.stop_price, exit_bid) if pos.side == LONG and exit_bid > 0 else (max(pos.stop_price, exit_ask) if exit_ask > 0 else pos.stop_price)
        elif target_hit:
            exit_theoretical = pos.target_price
            outcome_type = "TARGET"
            exit_realistic = min(pos.target_price, exit_bid) if pos.side == LONG and exit_bid > 0 else (max(pos.target_price, exit_ask) if exit_ask > 0 else pos.target_price)
        else:
            exit_theoretical = close_px
            outcome_type = "TIMEOUT"
            exit_realistic = exit_bid if pos.side == LONG and exit_bid > 0 else (exit_ask if exit_ask > 0 else close_px)

        denom = max(abs(pos.entry_price - pos.stop_price), 1e-12)
        gross_r = pos.side * (exit_theoretical - pos.entry_price) / denom
        theoretical_net_r = gross_r - self.friction_r

        # Slippage calculation
        entry_slip_usd = abs(pos.estimated_realistic_fill - pos.theoretical_candle_open_fill)
        exit_slip_usd = abs(exit_realistic - exit_theoretical)
        total_slip_usd = entry_slip_usd + exit_slip_usd
        total_slip_r = total_slip_usd / denom

        funding_rate = pos.funding_rate_8h if pos.funding_rate_8h != 0 else (market_context.get("funding_rate_8h", 0.0001) if market_context else 0.0001)
        funding_drag_r = (pos.bars_held / 32.0) * funding_rate * (pos.entry_price / denom)
        total_friction_r = self.friction_r + total_slip_r + funding_drag_r
        final_net_r = gross_r - total_friction_r

        outcome = ShadowOutcome(
            position_id=pos.position_id,
            symbol=pos.symbol,
            side=pos.side,
            setup=pos.setup,
            regime=pos.regime,
            entry_bar_time=pos.entry_bar_time,
            exit_bar_time=bar_timestamp,
            entry_price=pos.entry_price,
            exit_price=exit_theoretical,
            stop_price=pos.stop_price,
            target_price=pos.target_price,
            outcome_type=outcome_type,
            gross_r=gross_r,
            net_r=theoretical_net_r,
            friction_r=self.friction_r,
            bars_held=pos.bars_held,
            resolved_at=datetime.now(timezone.utc).isoformat(),
            predicted_entry=pos.predicted_entry or pos.entry_price,
            predicted_stop=pos.predicted_stop or pos.stop_price,
            predicted_target=pos.predicted_target or pos.target_price,
            predicted_r=pos.predicted_r,
            bid_at_signal=pos.entry_bid,
            ask_at_signal=pos.entry_ask,
            spread_usd=pos.spread_usd,
            spread_bps=pos.spread_bps,
            mark_price=pos.mark_price,
            volatility_atr_pct=pos.volatility_atr_pct,
            funding_rate_8h=pos.funding_rate_8h,
            bid_qty=pos.bid_qty,
            ask_qty=pos.ask_qty,
            theoretical_candle_open_fill=pos.theoretical_candle_open_fill or pos.entry_price,
            observable_market_price_fill=pos.observable_market_price_fill or pos.entry_price,
            estimated_realistic_fill=pos.estimated_realistic_fill or pos.entry_price,
            exit_theoretical_fill=exit_theoretical,
            exit_realistic_fill=exit_realistic,
            slippage_in_r=round(total_slip_r, 4),
            funding_drag_in_r=round(funding_drag_r, 4),
            theoretical_net_r=round(theoretical_net_r, 4),
            final_net_r=round(final_net_r, 4),
            latency_ms=market_context.get("latency_ms", 0.0) if market_context else 0.0,
            entry_spread_bps=pos.spread_bps,
            exit_spread_bps=exit_spread_bps,
            realized_slippage_r=round(total_slip_r, 4),
            realized_funding_r=round(funding_drag_r, 4),
            total_friction_r=round(total_friction_r, 4),
            empirical_net_r=round(final_net_r, 4),
        )

        del self.open_positions[symbol]
        self._record_outcome(outcome)
        return outcome

    def _record_opportunity(
        self,
        opp: Optional[ShadowOpportunity],
        bar_timestamp: str,
        symbol: str,
        market_context: Optional[dict] = None,
    ) -> None:
        """Append opportunity evaluation to JSON Lines log."""
        record = {
            "timestamp": bar_timestamp,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "admitted": bool(opp.admitted) if opp else False,
            "side": opp.side if opp else FLAT,
            "setup": opp.setup if opp else "NONE",
            "regime": opp.regime if opp else "UNKNOWN",
            "score": opp.score if opp else 0,
            "confirmations": opp.confirmations if opp else 0,
            "entry_price": opp.entry_price if opp else 0.0,
            "stop_price": opp.stop_price if opp else 0.0,
            "target_price": opp.target_price if opp else 0.0,
            "atr": opp.atr if opp else 0.0,
            "rejection_reason": opp.rejection_reason if opp else "No candidate opportunity found",
            "spread_bps": market_context.get("spread_bps", 0.0) if market_context else 0.0,
            "funding_rate_8h": market_context.get("funding_rate_8h", 0.0) if market_context else 0.0,
            "latency_ms": market_context.get("latency_ms", 0.0) if market_context else 0.0,
        }
        try:
            with open(self.opps_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            print(f"[V9.3.1 SHADOW ERROR] Failed to append opportunity record: {e}", flush=True)

    def _record_outcome(self, outcome: ShadowOutcome) -> None:
        """Append resolved outcome to JSON Lines log."""
        try:
            with open(self.outcomes_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(outcome.to_dict()) + "\n")
        except Exception as e:
            print(f"[V9.3.1 SHADOW ERROR] Failed to append outcome record: {e}", flush=True)

    def update_summary(self) -> dict:
        """Recalculate and persist rolling performance metrics."""
        outcomes: list[dict] = []
        if self.outcomes_file.exists():
            with open(self.outcomes_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            outcomes.append(json.loads(line))
                        except Exception:
                            pass

        total_trades = len(outcomes)
        wins = sum(1 for o in outcomes if o["net_r"] > 0)
        win_rate = (wins / total_trades) if total_trades > 0 else 0.0
        gross_wins_r = sum(o["net_r"] for o in outcomes if o["net_r"] > 0)
        gross_losses_r = -sum(o["net_r"] for o in outcomes if o["net_r"] < 0)
        profit_factor = round(gross_wins_r / gross_losses_r, 2) if gross_losses_r > 0 else (999.0 if gross_wins_r > 0 else 0.0)
        net_r = sum(o["net_r"] for o in outcomes)
        expectancy_r = (net_r / total_trades) if total_trades > 0 else 0.0

        summary = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "candidate": "V9.3.1",
            "total_outcomes": total_trades,
            "wins": wins,
            "losses": total_trades - wins,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "net_realized_r": net_r,
            "expectancy_r": expectancy_r,
            "active_positions_count": len(self.open_positions),
            "by_setup": {},
            "by_symbol": {},
        }

        for setup in ACTIVE_SETUPS_V931:
            s_outcomes = [o for o in outcomes if o["setup"] == setup]
            s_trades = len(s_outcomes)
            s_wins = sum(1 for o in s_outcomes if o["net_r"] > 0)
            summary["by_setup"][setup] = {
                "trades": s_trades,
                "win_rate": (s_wins / s_trades) if s_trades > 0 else 0.0,
                "net_r": sum(o["net_r"] for o in s_outcomes),
            }

        for sym in list(TIER_1) + list(TIER_2):
            sym_outcomes = [o for o in outcomes if o["symbol"] == sym]
            sym_trades = len(sym_outcomes)
            sym_wins = sum(1 for o in sym_outcomes if o["net_r"] > 0)
            summary["by_symbol"][sym] = {
                "trades": sym_trades,
                "win_rate": (sym_wins / sym_trades) if sym_trades > 0 else 0.0,
                "net_r": sum(o["net_r"] for o in sym_outcomes),
            }

        temp_file = self.summary_file.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
            temp_file.replace(self.summary_file)
        except Exception as e:
            print(f"[V9.3.1 SHADOW ERROR] Failed to update telemetry summary: {e}", flush=True)

        return summary
