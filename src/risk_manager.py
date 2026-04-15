from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from src.models import (
    AccountBalance,
    Position,
    SignalAction,
    TradeSignal,
)


@dataclass
class RiskConfig:
    min_position_pct: float = 0.20
    max_position_pct: float = 0.50
    max_total_exposure_pct: float = 5.0
    stop_loss_pct: float = 0.15
    take_profit_ratio: float = 3.0
    partial_tp_pct: float = 0.50
    trailing_stop_pct: float = 0.02
    daily_loss_limit_pct: float = 0.0  # 0 = disabled, infinite ammo
    max_open_positions: int = 20
    min_leverage: int = 10
    max_leverage: int = 75
    max_hold_minutes: int = 45
    min_profit_pct_to_keep: float = 0.005


@dataclass
class DailyPnL:
    date: str = ""
    realized_pnl: float = 0.0
    starting_balance: float = 0.0
    trades_count: int = 0

    @property
    def loss_pct(self) -> float:
        if self.starting_balance <= 0:
            return 0.0
        return -self.realized_pnl / self.starting_balance if self.realized_pnl < 0 else 0.0


class RiskManager:
    """Validates trade signals against risk management rules."""

    def __init__(self, config: RiskConfig | None = None):
        self.config = config or RiskConfig()
        self._daily_pnl = DailyPnL()
        self._trading_paused = False
        self._pause_reason = ""

    @property
    def is_paused(self) -> bool:
        return self._trading_paused

    @property
    def pause_reason(self) -> str:
        return self._pause_reason

    def reset_daily(self, balance: float):
        today = time.strftime("%Y-%m-%d")
        if self._daily_pnl.date != today:
            self._daily_pnl = DailyPnL(date=today, starting_balance=balance)
            self._trading_paused = False
            self._pause_reason = ""
            logger.info(f"Daily PnL reset. Starting balance: {balance:.2f}")

    def record_pnl(self, pnl: float):
        self._daily_pnl.realized_pnl += pnl
        self._daily_pnl.trades_count += 1

        if self.config.daily_loss_limit_pct > 0 and self._daily_pnl.loss_pct >= self.config.daily_loss_limit_pct:
            self._trading_paused = True
            self._pause_reason = (
                f"Daily loss limit reached: {self._daily_pnl.loss_pct:.2%} "
                f"(limit: {self.config.daily_loss_limit_pct:.2%})"
            )
            logger.warning(self._pause_reason)

    def validate_signal(
        self,
        signal: TradeSignal,
        balance: float,
        positions: list[Position],
    ) -> tuple[bool, str]:
        """
        Validate a trade signal against all risk rules.
        Returns (is_valid, rejection_reason).
        """
        if self._trading_paused:
            return False, f"Trading paused: {self._pause_reason}"

        if signal.action == SignalAction.HOLD:
            return False, "Signal is HOLD"

        if signal.action == SignalAction.CLOSE:
            return True, ""

        # Check leverage bounds
        if signal.leverage < self.config.min_leverage:
            signal.leverage = self.config.min_leverage
        if signal.leverage > self.config.max_leverage:
            signal.leverage = self.config.max_leverage

        # Check position size limit
        if signal.position_size_pct > self.config.max_position_pct:
            signal.position_size_pct = self.config.max_position_pct
            logger.info(f"Position size capped to {self.config.max_position_pct:.0%}")

        notional = balance * signal.position_size_pct * signal.leverage
        if notional <= 0:
            return False, "Calculated notional is zero or negative"

        # Check max open positions
        open_positions = [p for p in positions if p.is_open]
        if len(open_positions) >= self.config.max_open_positions:
            return False, f"Max open positions ({self.config.max_open_positions}) reached"

        # Check total exposure
        total_exposure = sum(p.notional for p in open_positions)
        new_exposure = total_exposure + notional
        max_exposure = balance * self.config.max_total_exposure_pct * signal.leverage
        if new_exposure > max_exposure:
            return False, (
                f"Total exposure {new_exposure:.0f} would exceed limit "
                f"{max_exposure:.0f}"
            )

        # Check for duplicate positions on same symbol + same direction
        for p in open_positions:
            if p.symbol != signal.symbol:
                continue
            if signal.action == SignalAction.LONG and p.position_amt > 0:
                return False, f"Already have a LONG position on {signal.symbol}"
            if signal.action == SignalAction.SHORT and p.position_amt < 0:
                return False, f"Already have a SHORT position on {signal.symbol}"

        # Validate stop loss direction only
        if signal.entry_price > 0 and signal.stop_loss > 0:
            if signal.action == SignalAction.LONG:
                sl_pct = (signal.entry_price - signal.stop_loss) / signal.entry_price
            else:
                sl_pct = (signal.stop_loss - signal.entry_price) / signal.entry_price

            if sl_pct <= 0:
                return False, "Stop loss is on wrong side of entry price"

        return True, ""

    def calc_position_size(
        self,
        balance: float,
        entry_price: float,
        stop_loss: float,
        leverage: int,
        max_pct: float | None = None,
    ) -> float:
        """Calculate position size based on risk per trade."""
        if entry_price <= 0 or stop_loss <= 0:
            return 0.0

        risk_per_trade = balance * self.config.stop_loss_pct
        price_distance = abs(entry_price - stop_loss)

        if price_distance <= 0:
            return 0.0

        qty = risk_per_trade / price_distance

        max_pct = max_pct or self.config.max_position_pct
        max_qty_by_balance = (balance * max_pct * leverage) / entry_price
        qty = min(qty, max_qty_by_balance)

        return qty

    def calc_take_profit(
        self,
        entry_price: float,
        stop_loss: float,
        action: SignalAction,
        ratio: float | None = None,
    ) -> float:
        """Calculate take profit price based on risk/reward ratio."""
        ratio = ratio or self.config.take_profit_ratio
        risk = abs(entry_price - stop_loss)

        if action == SignalAction.LONG:
            return entry_price + risk * ratio
        else:
            return entry_price - risk * ratio

    def calc_trailing_stop(
        self,
        current_price: float,
        action: SignalAction,
    ) -> float:
        """Calculate trailing stop price."""
        pct = self.config.trailing_stop_pct
        if action == SignalAction.LONG:
            return current_price * (1 - pct)
        else:
            return current_price * (1 + pct)

    def get_daily_stats(self) -> dict:
        return {
            "date": self._daily_pnl.date,
            "realized_pnl": self._daily_pnl.realized_pnl,
            "loss_pct": self._daily_pnl.loss_pct,
            "trades_count": self._daily_pnl.trades_count,
            "is_paused": self._trading_paused,
        }
