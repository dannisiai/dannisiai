from __future__ import annotations

import asyncio
from typing import Optional

from loguru import logger

from src.client import AsterClient, APIError
from src.models import (
    OrderResult,
    OrderStatus,
    OrderType,
    Position,
    Side,
    SignalAction,
    SymbolInfo,
    TradeSignal,
)
from src.risk_manager import RiskManager


class OrderManager:
    """Executes trade signals: sets leverage, places entry + stop-loss orders."""

    def __init__(
        self,
        client: AsterClient,
        risk_manager: RiskManager,
        position_mode: str = "hedge",
    ):
        self.client = client
        self.risk = risk_manager
        self.position_mode = position_mode
        self._pending_orders: dict[str, list[OrderResult]] = {}

    async def execute_signal(
        self,
        signal: TradeSignal,
        balance: float,
        positions: list[Position],
    ) -> Optional[OrderResult]:
        """Full execution flow: validate -> set leverage -> place entry + stop loss."""

        # 1. Risk validation
        valid, reason = self.risk.validate_signal(signal, balance, positions)
        if not valid:
            logger.info(f"Signal rejected for {signal.symbol}: {reason}")
            return None

        # 2. Handle CLOSE action
        if signal.action == SignalAction.CLOSE:
            return await self._close_position(signal.symbol, positions)

        # 3. Get symbol info for precision
        sym_info = self.client.get_symbol_info(signal.symbol)
        if not sym_info:
            logger.error(f"No symbol info for {signal.symbol}. Call get_exchange_info() first.")
            return None

        # 4. Query max leverage for this symbol and cap accordingly
        max_lev = await self.client.get_max_leverage(signal.symbol)
        original_leverage = signal.leverage
        if signal.leverage > max_lev:
            signal.leverage = max_lev

        # Try to set leverage (with fallback)
        leverage_set = False
        for attempt_lev in [signal.leverage, signal.leverage // 2, max_lev, 5, 3, 1]:
            if attempt_lev < 1:
                attempt_lev = 1
            if attempt_lev > max_lev:
                continue
            try:
                await self.client.set_leverage(signal.symbol, attempt_lev)
                signal.leverage = attempt_lev
                logger.info(f"Set leverage for {signal.symbol} to {attempt_lev}x (max={max_lev}x)")
                leverage_set = True
                break
            except APIError as e:
                if e.code in (-4028, -2030):
                    logger.warning(f"Leverage {attempt_lev}x rejected for {signal.symbol}, trying lower")
                    continue
                elif "No need to change" in str(e.msg):
                    leverage_set = True
                    break
                else:
                    logger.error(f"Failed to set leverage: {e}")
                    return None

        if not leverage_set:
            logger.error(f"Could not set any valid leverage for {signal.symbol}")
            return None

        # If leverage was reduced, scale up position size to compensate
        if signal.leverage < original_leverage and original_leverage > 0:
            scale_factor = original_leverage / signal.leverage
            new_pct = min(signal.position_size_pct * scale_factor, 0.50)
            logger.info(
                f"Leverage reduced {original_leverage}x→{signal.leverage}x, "
                f"scaling position {signal.position_size_pct:.0%}→{new_pct:.0%}"
            )
            signal.position_size_pct = new_pct

        # 5. Calculate quantity
        qty = self.risk.calc_position_size(
            balance=balance,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            leverage=signal.leverage,
            max_pct=signal.position_size_pct,
        )
        qty = sym_info.round_qty(qty)

        if qty < sym_info.min_qty:
            logger.warning(f"Quantity {qty} below minimum {sym_info.min_qty} for {signal.symbol}")
            return None

        notional = qty * signal.entry_price
        if notional < sym_info.min_notional:
            logger.warning(f"Notional {notional:.2f} below minimum {sym_info.min_notional}")
            return None

        # 6. Determine sides
        entry_side = Side.BUY if signal.action == SignalAction.LONG else Side.SELL
        stop_side = Side.SELL if signal.action == SignalAction.LONG else Side.BUY

        if self.position_mode == "hedge":
            pos_side = "LONG" if signal.action == SignalAction.LONG else "SHORT"
        else:
            pos_side = "BOTH"

        # 7. Place entry order (MARKET)
        logger.info(
            f"Placing {entry_side.value} {signal.symbol} qty={qty} "
            f"leverage={signal.leverage}x pos_side={pos_side}"
        )

        try:
            entry_order = await self.client.place_order(
                symbol=signal.symbol,
                side=entry_side.value,
                order_type=OrderType.MARKET.value,
                quantity=qty,
                position_side=pos_side,
            )
            logger.info(
                f"Entry order placed: {entry_order.order_id} "
                f"status={entry_order.status.value}"
            )
        except APIError as e:
            logger.error(f"Failed to place entry order: {e}")
            return None

        # 8. Place stop-loss order (STOP_MARKET)
        if signal.stop_loss > 0:
            sl_price = sym_info.round_price(signal.stop_loss)
            try:
                sl_order = await self.client.place_order(
                    symbol=signal.symbol,
                    side=stop_side.value,
                    order_type=OrderType.STOP_MARKET.value,
                    quantity=qty,
                    stop_price=sl_price,
                    position_side=pos_side,
                    working_type="MARK_PRICE",
                    reduce_only=True if self.position_mode != "hedge" else None,
                )
                logger.info(f"Stop-loss placed at {sl_price}: order {sl_order.order_id}")
            except APIError as e:
                logger.error(f"Failed to place stop-loss: {e}")

        # 9. Place take-profit order (TAKE_PROFIT_MARKET)
        if signal.take_profit > 0:
            tp_price = sym_info.round_price(signal.take_profit)
            tp_qty = sym_info.round_qty(qty * self.risk.config.partial_tp_pct)
            if tp_qty >= sym_info.min_qty:
                try:
                    tp_order = await self.client.place_order(
                        symbol=signal.symbol,
                        side=stop_side.value,
                        order_type=OrderType.TAKE_PROFIT_MARKET.value,
                        quantity=tp_qty,
                        stop_price=tp_price,
                        position_side=pos_side,
                        working_type="MARK_PRICE",
                        reduce_only=True if self.position_mode != "hedge" else None,
                    )
                    logger.info(
                        f"Take-profit placed at {tp_price} for {tp_qty} qty: "
                        f"order {tp_order.order_id}"
                    )
                except APIError as e:
                    logger.error(f"Failed to place take-profit: {e}")

        return entry_order

    async def _close_position(
        self, symbol: str, positions: list[Position]
    ) -> Optional[OrderResult]:
        """Close all positions on a symbol."""
        open_pos = [p for p in positions if p.is_open and p.symbol == symbol]
        if not open_pos:
            logger.info(f"No open positions to close on {symbol}")
            return None

        # Cancel all open orders on the symbol first
        try:
            await self.client.cancel_all_orders(symbol)
            logger.info(f"Cancelled all open orders on {symbol}")
        except APIError as e:
            logger.warning(f"Failed to cancel orders on {symbol}: {e}")

        last_result = None
        for pos in open_pos:
            if abs(pos.position_amt) == 0:
                continue

            close_side = Side.SELL if pos.position_amt > 0 else Side.BUY
            qty = abs(pos.position_amt)

            try:
                result = await self.client.place_order(
                    symbol=symbol,
                    side=close_side.value,
                    order_type=OrderType.MARKET.value,
                    quantity=qty,
                    position_side=pos.position_side.value,
                    reduce_only=True if self.position_mode != "hedge" else None,
                )
                logger.info(
                    f"Closed {pos.position_side.value} position on {symbol}: "
                    f"qty={qty}, order={result.order_id}"
                )
                last_result = result
            except APIError as e:
                logger.error(f"Failed to close position on {symbol}: {e}")

        return last_result

    async def cancel_symbol_orders(self, symbol: str):
        """Cancel all open orders for a symbol."""
        try:
            await self.client.cancel_all_orders(symbol)
            logger.info(f"All orders cancelled for {symbol}")
        except APIError as e:
            logger.error(f"Failed to cancel orders for {symbol}: {e}")

    async def handle_order_update(self, data: dict):
        """Process ORDER_TRADE_UPDATE event from WebSocket."""
        order_data = data.get("o", {})
        symbol = order_data.get("s", "")
        order_id = order_data.get("i", 0)
        status = order_data.get("X", "")
        exec_type = order_data.get("x", "")
        side = order_data.get("S", "")
        order_type = order_data.get("o", "")
        qty = float(order_data.get("q", 0))
        price = float(order_data.get("L", 0))
        realized_pnl = float(order_data.get("rp", 0))

        logger.info(
            f"Order update: {symbol} {side} {order_type} "
            f"status={status} exec={exec_type} price={price} qty={qty} "
            f"pnl={realized_pnl}"
        )

        if realized_pnl != 0:
            self.risk.record_pnl(realized_pnl)

        if status == "FILLED" and exec_type == "TRADE":
            logger.info(
                f"Order {order_id} FILLED: {side} {qty} {symbol} @ {price}, "
                f"realized PnL: {realized_pnl}"
            )
