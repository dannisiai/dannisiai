from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Coroutine, Optional

import websockets
from loguru import logger

from src.client import AsterClient


class AsterWebSocket:
    """WebSocket client for Aster market data and user data streams."""

    def __init__(
        self,
        ws_base: str,
        rest_client: AsterClient,
        on_message: Callable[[dict], Coroutine] | None = None,
    ):
        self.ws_base = ws_base.rstrip("/")
        self.rest_client = rest_client
        self._on_message = on_message
        self._market_ws: Optional[websockets.WebSocketClientProtocol] = None
        self._user_ws: Optional[websockets.WebSocketClientProtocol] = None
        self._listen_key: Optional[str] = None
        self._subscriptions: set[str] = set()
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._event_handlers: dict[str, list[Callable]] = {}
        self._msg_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=10000)

    # ── Event handler registration ─────────────────────────────────

    def on(self, event_type: str, handler: Callable[[dict], Coroutine]):
        """Register an async handler for a specific event type."""
        self._event_handlers.setdefault(event_type, []).append(handler)

    async def _dispatch(self, data: dict):
        """Dispatch event to registered handlers."""
        event_type = data.get("e", "")

        if self._on_message:
            try:
                await self._on_message(data)
            except Exception as e:
                logger.error(f"on_message handler error: {e}")

        handlers = self._event_handlers.get(event_type, [])
        for handler in handlers:
            try:
                await handler(data)
            except Exception as e:
                logger.error(f"Handler error for {event_type}: {e}")

    # ── Market data streams ────────────────────────────────────────

    async def subscribe_market(self, streams: list[str]):
        """Subscribe to market data streams (e.g., ['btcusdt@kline_1m', 'btcusdt@bookTicker'])."""
        self._subscriptions.update(streams)
        if self._market_ws:
            msg = {
                "method": "SUBSCRIBE",
                "params": streams,
                "id": 1,
            }
            await self._market_ws.send(json.dumps(msg))
            logger.info(f"Subscribed to market streams: {streams}")

    async def unsubscribe_market(self, streams: list[str]):
        self._subscriptions -= set(streams)
        if self._market_ws:
            msg = {
                "method": "UNSUBSCRIBE",
                "params": streams,
                "id": 2,
            }
            await self._market_ws.send(json.dumps(msg))

    async def _run_market_ws(self):
        """Connect and listen to market data WebSocket with auto-reconnect."""
        while self._running:
            try:
                if self._subscriptions:
                    streams_param = "/".join(self._subscriptions)
                    url = f"{self.ws_base}/stream?streams={streams_param}"
                else:
                    url = f"{self.ws_base}/ws/!miniTicker@arr"

                logger.info(f"Connecting market WS: {url}")
                async with websockets.connect(url, ping_interval=30, ping_timeout=60) as ws:
                    self._market_ws = ws
                    logger.info("Market WebSocket connected")

                    if self._subscriptions:
                        await self.subscribe_market(list(self._subscriptions))

                    async for raw_msg in ws:
                        try:
                            data = json.loads(raw_msg)
                            if "stream" in data and "data" in data:
                                await self._dispatch(data["data"])
                            elif "e" in data:
                                await self._dispatch(data)
                            elif isinstance(data, list):
                                for item in data:
                                    if isinstance(item, dict):
                                        await self._dispatch(item)
                        except json.JSONDecodeError:
                            logger.warning(f"Invalid JSON from market WS: {raw_msg[:200]}")

            except websockets.ConnectionClosed as e:
                logger.warning(f"Market WS disconnected: {e}. Reconnecting in 5s...")
            except Exception as e:
                logger.error(f"Market WS error: {e}. Reconnecting in 5s...")

            self._market_ws = None
            if self._running:
                await asyncio.sleep(5)

    # ── User data stream ───────────────────────────────────────────

    async def _run_user_ws(self):
        """Connect and listen to user data WebSocket with auto-reconnect."""
        while self._running:
            try:
                self._listen_key = await self.rest_client.create_listen_key()
                url = f"{self.ws_base}/ws/{self._listen_key}"
                logger.info(f"Connecting user data WS with listenKey")

                async with websockets.connect(url, ping_interval=30, ping_timeout=60) as ws:
                    self._user_ws = ws
                    logger.info("User data WebSocket connected")

                    keepalive_task = asyncio.create_task(self._keepalive_loop())

                    try:
                        async for raw_msg in ws:
                            try:
                                data = json.loads(raw_msg)
                                await self._dispatch(data)
                            except json.JSONDecodeError:
                                logger.warning(f"Invalid JSON from user WS: {raw_msg[:200]}")
                    finally:
                        keepalive_task.cancel()
                        try:
                            await keepalive_task
                        except asyncio.CancelledError:
                            pass

            except websockets.ConnectionClosed as e:
                logger.warning(f"User WS disconnected: {e}. Reconnecting in 5s...")
            except Exception as e:
                logger.error(f"User WS error: {e}. Reconnecting in 5s...")

            self._user_ws = None
            if self._running:
                await asyncio.sleep(5)

    async def _keepalive_loop(self):
        """Renew listenKey every 30 minutes."""
        while self._running:
            await asyncio.sleep(30 * 60)
            try:
                await self.rest_client.keepalive_listen_key()
                logger.debug("listenKey renewed")
            except Exception as e:
                logger.error(f"Failed to renew listenKey: {e}")

    # ── Lifecycle ──────────────────────────────────────────────────

    async def start(self, market: bool = True, user_data: bool = True):
        self._running = True
        if market:
            self._tasks.append(asyncio.create_task(self._run_market_ws()))
        if user_data:
            self._tasks.append(asyncio.create_task(self._run_user_ws()))
        logger.info(f"WebSocket client started (market={market}, user_data={user_data})")

    async def stop(self):
        self._running = False
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

        if self._market_ws:
            await self._market_ws.close()
        if self._user_ws:
            await self._user_ws.close()

        if self._listen_key:
            try:
                await self.rest_client.close_listen_key()
            except Exception:
                pass

        logger.info("WebSocket client stopped")
