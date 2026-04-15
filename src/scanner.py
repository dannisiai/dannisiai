from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from src.client import AsterClient
from src.models import MarkPriceData, TickerData


@dataclass
class ScoredPair:
    symbol: str
    score: float
    volume_24h: float
    price_change_pct: float
    volatility: float
    funding_rate: float
    last_price: float


class PairScanner:
    """Dynamically scans and ranks trading pairs by volume, volatility, and funding rate."""

    def __init__(
        self,
        client: AsterClient,
        min_volume_usdt: float = 1_000_000,
        min_price_change_pct: float = 1.0,
        top_n: int = 10,
        excluded_symbols: list[str] | None = None,
        whitelist: list[str] | None = None,
        blacklist: list[str] | None = None,
        category_weights: dict[str, float] | None = None,
        funding_high_threshold: float = 0.001,
        funding_low_threshold: float = -0.001,
    ):
        self.client = client
        self.min_volume_usdt = min_volume_usdt
        self.min_price_change_pct = min_price_change_pct
        self.top_n = top_n
        self.excluded_symbols = set(excluded_symbols or [])
        self.whitelist = set(whitelist or [])
        self.blacklist = set(blacklist or [])
        self.weights = category_weights or {
            "high_volume": 0.3,
            "high_volatility": 0.4,
            "funding_rate_anomaly": 0.3,
        }
        self.funding_high = funding_high_threshold
        self.funding_low = funding_low_threshold

        self._candidates: list[ScoredPair] = []
        self._last_scan_time: float = 0

    @property
    def candidates(self) -> list[ScoredPair]:
        return self._candidates

    async def scan(self) -> list[ScoredPair]:
        """Fetch 24hr tickers + mark prices, score and rank pairs."""
        logger.info("Scanning trading pairs...")

        tickers_raw, mark_prices_raw = await asyncio.gather(
            self.client.get_ticker_24hr(),
            self.client.get_mark_price(),
        )

        tickers: list[TickerData] = tickers_raw if isinstance(tickers_raw, list) else [tickers_raw]
        mark_prices: list[MarkPriceData] = mark_prices_raw if isinstance(mark_prices_raw, list) else [mark_prices_raw]

        funding_map: dict[str, float] = {
            mp.symbol: mp.funding_rate for mp in mark_prices
        }

        exchange_info_cache = self.client._exchange_info_cache
        active_symbols = {
            sym for sym, info in exchange_info_cache.items()
            if info.status == "TRADING"
        } if exchange_info_cache else set()

        scored: list[ScoredPair] = []
        for t in tickers:
            if not self._should_include(t.symbol, active_symbols):
                continue
            if t.quote_volume < self.min_volume_usdt:
                continue
            if abs(t.price_change_pct) < self.min_price_change_pct:
                continue

            funding = funding_map.get(t.symbol, 0.0)
            volatility = self._calc_volatility(t)

            score = self._calc_score(t.quote_volume, volatility, funding, tickers)
            scored.append(ScoredPair(
                symbol=t.symbol,
                score=score,
                volume_24h=t.quote_volume,
                price_change_pct=t.price_change_pct,
                volatility=volatility,
                funding_rate=funding,
                last_price=t.last_price,
            ))

        scored.sort(key=lambda x: x.score, reverse=True)
        self._candidates = scored[:self.top_n]
        self._last_scan_time = time.time()

        symbols = [c.symbol for c in self._candidates]
        logger.info(f"Top {len(self._candidates)} pairs: {symbols}")
        return self._candidates

    def _should_include(self, symbol: str, active_symbols: set[str]) -> bool:
        if symbol in self.blacklist or symbol in self.excluded_symbols:
            return False
        if self.whitelist and symbol not in self.whitelist:
            return False
        if active_symbols and symbol not in active_symbols:
            return False
        if not symbol.endswith("USDT"):
            return False
        return True

    def _calc_volatility(self, ticker: TickerData) -> float:
        if ticker.low_price <= 0:
            return 0.0
        return (ticker.high_price - ticker.low_price) / ticker.low_price

    def _calc_score(
        self,
        volume: float,
        volatility: float,
        funding_rate: float,
        all_tickers: list[TickerData],
    ) -> float:
        max_vol = max((t.quote_volume for t in all_tickers), default=1)
        vol_score = volume / max_vol if max_vol > 0 else 0

        max_volatility = max(
            (self._calc_volatility(t) for t in all_tickers if t.quote_volume > self.min_volume_usdt),
            default=1,
        )
        volatility_score = volatility / max_volatility if max_volatility > 0 else 0

        funding_score = 0.0
        if funding_rate > self.funding_high or funding_rate < self.funding_low:
            funding_score = min(abs(funding_rate) / 0.005, 1.0)

        w = self.weights
        return (
            w.get("high_volume", 0.3) * vol_score
            + w.get("high_volatility", 0.4) * volatility_score
            + w.get("funding_rate_anomaly", 0.3) * funding_score
        )
