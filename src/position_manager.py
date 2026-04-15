from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from src.client import AsterClient, APIError
from src.models import (
    OrderType,
    Position,
    Side,
    SignalAction,
    SymbolInfo,
)
from src.risk_manager import RiskManager


@dataclass
class TrackedPosition:
    symbol: str
    position_side: str  # "LONG" or "SHORT"
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    strategy: str = ""
    trailing_stop: float = 0.0
    highest_price: float = 0.0  # for long trailing
    lowest_price: float = float("inf")  # for short trailing
    partial_tp_done: bool = False
    sl_order_id: Optional[int] = None
    tp_order_id: Optional[int] = None
    max_hold_minutes: int = 120
    opened_at: float = field(default_factory=time.time)


class PositionManager:
    """Tracks open positions and manages trailing stops / partial take-profits."""

    def __init__(
        self,
        client: AsterClient,
        risk_manager: RiskManager,
        position_mode: str = "hedge",
        check_interval: float = 5.0,
        on_close_callback=None,
    ):
        self.client = client
        self.risk = risk_manager
        self.position_mode = position_mode
        self.check_interval = check_interval
        self._tracked: dict[str, TrackedPosition] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._on_close = on_close_callback

    @property
    def tracked_positions(self) -> dict[str, TrackedPosition]:
        return self._tracked

    def track(
        self,
        symbol: str,
        position_side: str,
        entry_price: float,
        quantity: float,
        stop_loss: float,
        take_profit: float,
        strategy: str = "",
        max_hold_minutes: int = 120,
    ):
        key = f"{symbol}_{position_side}"
        self._tracked[key] = TrackedPosition(
            symbol=symbol,
            position_side=position_side,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=strategy,
            highest_price=entry_price,
            lowest_price=entry_price,
            max_hold_minutes=max_hold_minutes,
        )
        logger.info(
            f"Tracking position: {symbol} {position_side} "
            f"strategy={strategy} entry={entry_price} sl={stop_loss} tp={take_profit}"
        )

    def untrack(self, symbol: str, position_side: str):
        key = f"{symbol}_{position_side}"
        if key in self._tracked:
            del self._tracked[key]
            logger.info(f"Untracked position: {symbol} {position_side}")

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Position manager started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Position manager stopped")

    async def _monitor_loop(self):
        """Periodically check positions and update trailing stops."""
        while self._running:
            try:
                await self._check_positions()
            except Exception as e:
                logger.error(f"Position monitor error: {e}")
            await asyncio.sleep(self.check_interval)

    async def _check_positions(self):
        if not self._tracked:
            return

        try:
            all_positions = await self.client.get_positions()
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            return

        position_map: dict[str, Position] = {}
        for p in all_positions:
            key = f"{p.symbol}_{p.position_side.value}"
            position_map[key] = p

        keys_to_remove = []
        for key, tracked in self._tracked.items():
            pos = position_map.get(key)

            if not pos or not pos.is_open:
                logger.info(f"Position {key} closed (no longer open)")
                keys_to_remove.append(key)
                continue

            current_price = pos.mark_price

            # Check hold timeout: close if held too long and not profitable enough
            hold_minutes = (time.time() - tracked.opened_at) / 60
            if hold_minutes >= tracked.max_hold_minutes:
                pnl_pct = pos.unrealized_pnl_pct
                min_profit = self.risk.config.min_profit_pct_to_keep
                if pnl_pct < min_profit:
                    logger.info(
                        f"Hold timeout for {key}: {hold_minutes:.0f}min "
                        f"(max {tracked.max_hold_minutes}min), "
                        f"PnL {pnl_pct:.2%} < {min_profit:.2%}. Closing."
                    )
                    await self._market_close(tracked, pos)
                    keys_to_remove.append(key)
                    continue

            if tracked.position_side == "LONG":
                await self._update_long_trailing(tracked, current_price, pos)
            elif tracked.position_side == "SHORT":
                await self._update_short_trailing(tracked, current_price, pos)

        for key in keys_to_remove:
            del self._tracked[key]

    async def _update_long_trailing(
        self, tracked: TrackedPosition, current_price: float, pos: Position
    ):
        if current_price > tracked.highest_price:
            tracked.highest_price = current_price

            if tracked.partial_tp_done:
                new_trailing = self.risk.calc_trailing_stop(current_price, SignalAction.LONG)
                if new_trailing > tracked.trailing_stop:
                    tracked.trailing_stop = new_trailing
                    await self._update_stop_loss_order(tracked, new_trailing, pos)

        if tracked.partial_tp_done and tracked.trailing_stop > 0:
            if current_price <= tracked.trailing_stop:
                logger.info(
                    f"Trailing stop hit for LONG {tracked.symbol}: "
                    f"price={current_price} trailing={tracked.trailing_stop}"
                )
                await self._market_close(tracked, pos)

    async def _update_short_trailing(
        self, tracked: TrackedPosition, current_price: float, pos: Position
    ):
        if current_price < tracked.lowest_price:
            tracked.lowest_price = current_price

            if tracked.partial_tp_done:
                new_trailing = self.risk.calc_trailing_stop(current_price, SignalAction.SHORT)
                if new_trailing < tracked.trailing_stop or tracked.trailing_stop == 0:
                    tracked.trailing_stop = new_trailing
                    await self._update_stop_loss_order(tracked, new_trailing, pos)

        if tracked.partial_tp_done and tracked.trailing_stop > 0:
            if current_price >= tracked.trailing_stop:
                logger.info(
                    f"Trailing stop hit for SHORT {tracked.symbol}: "
                    f"price={current_price} trailing={tracked.trailing_stop}"
                )
                await self._market_close(tracked, pos)

    async def _update_stop_loss_order(
        self, tracked: TrackedPosition, new_price: float, pos: Position
    ):
        """Cancel old SL and place a new one at the updated trailing price."""
        sym_info = self.client.get_symbol_info(tracked.symbol)
        if not sym_info:
            return

        if tracked.sl_order_id:
            try:
                await self.client.cancel_order(tracked.symbol, order_id=tracked.sl_order_id)
            except APIError:
                pass

        close_side = Side.SELL if tracked.position_side == "LONG" else Side.BUY
        sl_price = sym_info.round_price(new_price)
        remaining_qty = abs(pos.position_amt)

        try:
            result = await self.client.place_order(
                symbol=tracked.symbol,
                side=close_side.value,
                order_type=OrderType.STOP_MARKET.value,
                quantity=remaining_qty,
                stop_price=sl_price,
                position_side=tracked.position_side,
                working_type="MARK_PRICE",
                reduce_only=True if self.position_mode != "hedge" else None,
            )
            tracked.sl_order_id = result.order_id
            logger.debug(
                f"Updated trailing stop for {tracked.symbol} {tracked.position_side}: "
                f"new_sl={sl_price}"
            )
        except APIError as e:
            logger.error(f"Failed to update trailing stop: {e}")

    async def _market_close(self, tracked: TrackedPosition, pos: Position):
        """Market-close the remaining position."""
        close_side = Side.SELL if tracked.position_side == "LONG" else Side.BUY
        qty = abs(pos.position_amt)

        try:
            await self.client.cancel_all_orders(tracked.symbol)
        except APIError:
            pass

        try:
            await self.client.place_order(
                symbol=tracked.symbol,
                side=close_side.value,
                order_type=OrderType.MARKET.value,
                quantity=qty,
                position_side=tracked.position_side,
                reduce_only=True if self.position_mode != "hedge" else None,
            )
            logger.info(f"Market closed {tracked.symbol} {tracked.position_side} qty={qty}")

            if self._on_close:
                try:
                    pnl_pct = pos.unrealized_pnl_pct if hasattr(pos, 'unrealized_pnl_pct') else None
                    await self._on_close({
                        "event": "close",
                        "symbol": tracked.symbol,
                        "side": tracked.position_side,
                        "pnl_pct": pnl_pct,
                        "reasoning": "持仓超时/移动止损触发",
                    })
                except Exception:
                    pass

        except APIError as e:
            logger.error(f"Failed to market close {tracked.symbol}: {e}")

    def handle_order_fill(self, data: dict):
        """Called when an order fills - check if it's a partial TP."""
        order_data = data.get("o", {})
        symbol = order_data.get("s", "")
        status = order_data.get("X", "")
        order_type = order_data.get("ot", "")
        pos_side = order_data.get("ps", "BOTH")

        if status != "FILLED":
            return

        key = f"{symbol}_{pos_side}"
        tracked = self._tracked.get(key)
        if not tracked:
            return

        if order_type in ("TAKE_PROFIT", "TAKE_PROFIT_MARKET"):
            if not tracked.partial_tp_done:
                tracked.partial_tp_done = True
                if tracked.position_side == "LONG":
                    tracked.trailing_stop = self.risk.calc_trailing_stop(
                        tracked.highest_price, SignalAction.LONG
                    )
                else:
                    tracked.trailing_stop = self.risk.calc_trailing_stop(
                        tracked.lowest_price, SignalAction.SHORT
                    )
                logger.info(
                    f"Partial TP filled for {symbol} {pos_side}. "
                    f"Trailing stop activated at {tracked.trailing_stop}"
                )

        elif order_type in ("STOP", "STOP_MARKET"):
            logger.info(f"Stop-loss filled for {symbol} {pos_side}. Removing tracker.")
            self.untrack(symbol, pos_side)

    async def sync_with_exchange(self):
        """Sync tracked positions with actual exchange positions."""
        try:
            positions = await self.client.get_positions()
            open_keys = set()
            for p in positions:
                if p.is_open:
                    key = f"{p.symbol}_{p.position_side.value}"
                    open_keys.add(key)

            stale = [k for k in self._tracked if k not in open_keys]
            for key in stale:
                logger.info(f"Removing stale tracked position: {key}")
                del self._tracked[key]

        except Exception as e:
            logger.error(f"Failed to sync positions: {e}")
