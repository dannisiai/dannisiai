from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PositionSide(str, Enum):
    BOTH = "BOTH"
    LONG = "LONG"
    SHORT = "SHORT"


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP = "STOP"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT = "TAKE_PROFIT"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"
    TRAILING_STOP_MARKET = "TRAILING_STOP_MARKET"


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    GTX = "GTX"
    HIDDEN = "HIDDEN"


class MarginType(str, Enum):
    ISOLATED = "ISOLATED"
    CROSSED = "CROSSED"


class SignalAction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    CLOSE = "CLOSE"
    HOLD = "HOLD"


@dataclass
class KlineData:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    quote_volume: float
    trades: int
    taker_buy_volume: float
    taker_buy_quote_volume: float

    @classmethod
    def from_api(cls, raw: list) -> KlineData:
        return cls(
            open_time=int(raw[0]),
            open=float(raw[1]),
            high=float(raw[2]),
            low=float(raw[3]),
            close=float(raw[4]),
            volume=float(raw[5]),
            close_time=int(raw[6]),
            quote_volume=float(raw[7]),
            trades=int(raw[8]),
            taker_buy_volume=float(raw[9]),
            taker_buy_quote_volume=float(raw[10]),
        )


@dataclass
class TickerData:
    symbol: str
    price_change: float
    price_change_pct: float
    last_price: float
    volume: float
    quote_volume: float
    high_price: float
    low_price: float

    @classmethod
    def from_api(cls, raw: dict) -> TickerData:
        return cls(
            symbol=raw["symbol"],
            price_change=float(raw.get("priceChange", 0)),
            price_change_pct=float(raw.get("priceChangePercent", 0)),
            last_price=float(raw.get("lastPrice", 0)),
            volume=float(raw.get("volume", 0)),
            quote_volume=float(raw.get("quoteVolume", 0)),
            high_price=float(raw.get("highPrice", 0)),
            low_price=float(raw.get("lowPrice", 0)),
        )


@dataclass
class MarkPriceData:
    symbol: str
    mark_price: float
    index_price: float
    funding_rate: float
    next_funding_time: int

    @classmethod
    def from_api(cls, raw: dict) -> MarkPriceData:
        return cls(
            symbol=raw["symbol"],
            mark_price=float(raw.get("markPrice", 0)),
            index_price=float(raw.get("indexPrice", 0)),
            funding_rate=float(raw.get("lastFundingRate", 0)),
            next_funding_time=int(raw.get("nextFundingTime", 0)),
        )


@dataclass
class DepthData:
    bids: list[list[float]]
    asks: list[list[float]]
    last_update_id: int

    @classmethod
    def from_api(cls, raw: dict) -> DepthData:
        return cls(
            bids=[[float(p), float(q)] for p, q in raw.get("bids", [])],
            asks=[[float(p), float(q)] for p, q in raw.get("asks", [])],
            last_update_id=int(raw.get("lastUpdateId", 0)),
        )


@dataclass
class SymbolInfo:
    symbol: str
    status: str
    base_asset: str
    quote_asset: str
    price_precision: int
    quantity_precision: int
    tick_size: float
    step_size: float
    min_qty: float
    max_qty: float
    min_notional: float

    @classmethod
    def from_api(cls, raw: dict) -> SymbolInfo:
        filters = {f["filterType"]: f for f in raw.get("filters", [])}
        price_filter = filters.get("PRICE_FILTER", {})
        lot_size = filters.get("LOT_SIZE", {})
        min_notional = filters.get("MIN_NOTIONAL", {})
        return cls(
            symbol=raw["symbol"],
            status=raw.get("status", ""),
            base_asset=raw.get("baseAsset", ""),
            quote_asset=raw.get("quoteAsset", ""),
            price_precision=int(raw.get("pricePrecision", 8)),
            quantity_precision=int(raw.get("quantityPrecision", 8)),
            tick_size=float(price_filter.get("tickSize", "0.01")),
            step_size=float(lot_size.get("stepSize", "0.01")),
            min_qty=float(lot_size.get("minQty", "0.001")),
            max_qty=float(lot_size.get("maxQty", "1000000")),
            min_notional=float(min_notional.get("notional", "1")),
        )

    def round_price(self, price: float) -> float:
        if self.tick_size <= 0:
            return price
        precision = len(str(self.tick_size).rstrip("0").split(".")[-1])
        return round(round(price / self.tick_size) * self.tick_size, precision)

    def round_qty(self, qty: float) -> float:
        if self.step_size <= 0:
            return qty
        precision = len(str(self.step_size).rstrip("0").split(".")[-1])
        return round(int(qty / self.step_size) * self.step_size, precision)


@dataclass
class Position:
    symbol: str
    position_side: PositionSide
    position_amt: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: int
    margin_type: MarginType
    isolated_margin: float
    liquidation_price: float

    @classmethod
    def from_api(cls, raw: dict) -> Position:
        return cls(
            symbol=raw["symbol"],
            position_side=PositionSide(raw.get("positionSide", "BOTH")),
            position_amt=float(raw.get("positionAmt", 0)),
            entry_price=float(raw.get("entryPrice", 0)),
            mark_price=float(raw.get("markPrice", 0)),
            unrealized_pnl=float(raw.get("unRealizedProfit", 0)),
            leverage=int(raw.get("leverage", 1)),
            margin_type=MarginType.ISOLATED if raw.get("marginType") == "isolated" else MarginType.CROSSED,
            isolated_margin=float(raw.get("isolatedMargin", 0)),
            liquidation_price=float(raw.get("liquidationPrice", 0)),
        )

    @property
    def is_open(self) -> bool:
        return abs(self.position_amt) > 0

    @property
    def notional(self) -> float:
        return abs(self.position_amt) * self.mark_price

    @property
    def unrealized_pnl_pct(self) -> float:
        cost = abs(self.position_amt) * self.entry_price
        if cost <= 0:
            return 0.0
        return self.unrealized_pnl / cost


@dataclass
class OrderResult:
    order_id: int
    client_order_id: str
    symbol: str
    side: Side
    position_side: PositionSide
    order_type: OrderType
    status: OrderStatus
    price: float
    orig_qty: float
    executed_qty: float
    avg_price: float

    @classmethod
    def from_api(cls, raw: dict) -> OrderResult:
        return cls(
            order_id=int(raw.get("orderId", 0)),
            client_order_id=raw.get("clientOrderId", ""),
            symbol=raw.get("symbol", ""),
            side=Side(raw.get("side", "BUY")),
            position_side=PositionSide(raw.get("positionSide", "BOTH")),
            order_type=OrderType(raw.get("type", "MARKET")),
            status=OrderStatus(raw.get("status", "NEW")),
            price=float(raw.get("price", 0)),
            orig_qty=float(raw.get("origQty", 0)),
            executed_qty=float(raw.get("executedQty", 0)),
            avg_price=float(raw.get("avgPrice", 0)),
        )


@dataclass
class TradeSignal:
    action: SignalAction
    symbol: str
    confidence: float
    entry_price: float
    stop_loss: float
    take_profit: float
    leverage: int
    position_size_pct: float
    reasoning: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class MarketSnapshot:
    """All market data for a single symbol, packaged for AI analysis."""
    symbol: str
    klines: list[KlineData]
    depth: Optional[DepthData]
    mark_price: Optional[MarkPriceData]
    ticker: Optional[TickerData]
    timestamp: float = field(default_factory=time.time)


@dataclass
class AccountBalance:
    asset: str
    wallet_balance: float
    available_balance: float
    cross_wallet_balance: float
    unrealized_pnl: float

    @classmethod
    def from_api(cls, raw: dict) -> AccountBalance:
        return cls(
            asset=raw.get("asset", ""),
            wallet_balance=float(raw.get("balance", raw.get("walletBalance", 0))),
            available_balance=float(raw.get("availableBalance", 0)),
            cross_wallet_balance=float(raw.get("crossWalletBalance", 0)),
            unrealized_pnl=float(raw.get("crossUnPnl", raw.get("unrealizedProfit", 0))),
        )
