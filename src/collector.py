from __future__ import annotations

import asyncio
import time
from typing import Optional

from loguru import logger

from src.client import AsterClient
from src.models import DepthData, KlineData, MarkPriceData, MarketSnapshot, TickerData
from src.ws_client import AsterWebSocket


class MarketCollector:
    """Collects and caches market data from REST + WebSocket for AI analysis."""

    def __init__(
        self,
        client: AsterClient,
        ws_client: AsterWebSocket,
        kline_interval: str = "15m",
        kline_limit: int = 100,
        depth_limit: int = 20,
    ):
        self.client = client
        self.ws_client = ws_client
        self.kline_interval = kline_interval
        self.kline_limit = kline_limit
        self.depth_limit = depth_limit

        self._kline_cache: dict[str, list[KlineData]] = {}
        self._depth_cache: dict[str, DepthData] = {}
        self._mark_price_cache: dict[str, MarkPriceData] = {}
        self._ticker_cache: dict[str, TickerData] = {}
        self._ws_kline_cache: dict[str, KlineData] = {}

        self._setup_ws_handlers()

    def _setup_ws_handlers(self):
        self.ws_client.on("kline", self._handle_kline)
        self.ws_client.on("markPriceUpdate", self._handle_mark_price)
        self.ws_client.on("24hrTicker", self._handle_ticker)
        self.ws_client.on("bookTicker", self._handle_book_ticker)

    async def _handle_kline(self, data: dict):
        k = data.get("k", {})
        symbol = k.get("s", "")
        if not symbol:
            return
        kline = KlineData(
            open_time=k["t"],
            open=float(k["o"]),
            high=float(k["h"]),
            low=float(k["l"]),
            close=float(k["c"]),
            volume=float(k["v"]),
            close_time=k["T"],
            quote_volume=float(k["q"]),
            trades=int(k["n"]),
            taker_buy_volume=float(k["V"]),
            taker_buy_quote_volume=float(k["Q"]),
        )
        self._ws_kline_cache[symbol] = kline

        if k.get("x", False) and symbol in self._kline_cache:
            self._kline_cache[symbol].append(kline)
            if len(self._kline_cache[symbol]) > self.kline_limit:
                self._kline_cache[symbol] = self._kline_cache[symbol][-self.kline_limit:]

    async def _handle_mark_price(self, data: dict):
        symbol = data.get("s", "")
        if symbol:
            self._mark_price_cache[symbol] = MarkPriceData(
                symbol=symbol,
                mark_price=float(data.get("p", 0)),
                index_price=float(data.get("i", 0)),
                funding_rate=float(data.get("r", 0)),
                next_funding_time=int(data.get("T", 0)),
            )

    async def _handle_ticker(self, data: dict):
        symbol = data.get("s", "")
        if symbol:
            self._ticker_cache[symbol] = TickerData(
                symbol=symbol,
                price_change=float(data.get("p", 0)),
                price_change_pct=float(data.get("P", 0)),
                last_price=float(data.get("c", 0)),
                volume=float(data.get("v", 0)),
                quote_volume=float(data.get("q", 0)),
                high_price=float(data.get("h", 0)),
                low_price=float(data.get("l", 0)),
            )

    async def _handle_book_ticker(self, data: dict):
        pass

    async def subscribe_symbols(self, symbols: list[str]):
        """Subscribe to WebSocket streams for given symbols."""
        streams = []
        for sym in symbols:
            s = sym.lower()
            streams.extend([
                f"{s}@kline_{self.kline_interval}",
                f"{s}@markPrice@1s",
                f"{s}@bookTicker",
            ])
        await self.ws_client.subscribe_market(streams)
        logger.info(f"Subscribed to WS streams for {len(symbols)} symbols")

    async def fetch_snapshot(self, symbol: str) -> MarketSnapshot:
        """Fetch a complete market snapshot for one symbol via REST (with cache merge)."""
        klines = depth = mark_price = ticker = None
        for coro, name in [
            (self.client.get_klines(symbol, interval=self.kline_interval, limit=self.kline_limit), "klines"),
            (self.client.get_depth(symbol, limit=self.depth_limit), "depth"),
            (self.client.get_mark_price(symbol), "mark"),
            (self.client.get_ticker_24hr(symbol), "ticker"),
        ]:
            try:
                result = await coro
                if name == "klines":
                    klines = result
                elif name == "depth":
                    depth = result
                elif name == "mark":
                    mark_price = result
                else:
                    ticker = result
            except Exception as e:
                logger.debug(f"Fetch {name} for {symbol} failed: {e}")
            await asyncio.sleep(0.1)

        kl = klines if isinstance(klines, list) else self._kline_cache.get(symbol, [])
        self._kline_cache[symbol] = kl

        dp = depth if isinstance(depth, DepthData) else self._depth_cache.get(symbol)
        if isinstance(depth, DepthData):
            self._depth_cache[symbol] = dp

        mp = mark_price if isinstance(mark_price, MarkPriceData) else self._mark_price_cache.get(symbol)
        if isinstance(mark_price, MarkPriceData):
            self._mark_price_cache[symbol] = mp

        tk = ticker if isinstance(ticker, TickerData) else self._ticker_cache.get(symbol)
        if isinstance(ticker, TickerData):
            self._ticker_cache[symbol] = tk

        return MarketSnapshot(
            symbol=symbol,
            klines=kl,
            depth=dp,
            mark_price=mp,
            ticker=tk,
        )

    async def fetch_snapshots(self, symbols: list[str]) -> dict[str, MarketSnapshot]:
        """Fetch snapshots for symbols sequentially to avoid rate limits."""
        snapshots = {}
        for sym in symbols:
            try:
                snapshots[sym] = await self.fetch_snapshot(sym)
            except Exception as e:
                logger.error(f"Failed to fetch snapshot for {sym}: {e}")
            await asyncio.sleep(0.3)
        return snapshots

    def get_cached_mark_price(self, symbol: str) -> Optional[MarkPriceData]:
        return self._mark_price_cache.get(symbol)

    def get_cached_ticker(self, symbol: str) -> Optional[TickerData]:
        return self._ticker_cache.get(symbol)
