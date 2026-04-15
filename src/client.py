from __future__ import annotations

import asyncio
import urllib.parse
from typing import Any, Optional

import httpx
from loguru import logger

from src.auth import AsterAuth
from src.models import (
    AccountBalance,
    DepthData,
    KlineData,
    MarkPriceData,
    OrderResult,
    Position,
    SymbolInfo,
    TickerData,
)


class AsterClient:
    """Async REST client for Aster Futures v3 API."""

    HEADERS = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "AsterBot/1.0",
    }

    def __init__(self, base_url: str, auth: AsterAuth):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self._client: Optional[httpx.AsyncClient] = None
        self._exchange_info_cache: dict[str, SymbolInfo] = {}
        self._max_leverage_cache: dict[str, int] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self.HEADERS,
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── low-level request helpers ──────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        signed: bool = False,
        retries: int = 3,
    ) -> Any:
        params = params or {}
        url = f"{self.base_url}{path}"

        for attempt in range(retries):
            try:
                client = await self._get_client()

                if signed:
                    signed_params = self.auth.sign_params(params)
                    qs = urllib.parse.urlencode(signed_params)
                    full_url = f"{url}?{qs}"
                else:
                    if params:
                        qs = urllib.parse.urlencode(params)
                        full_url = f"{url}?{qs}"
                    else:
                        full_url = url

                resp = await client.request(method, full_url)
                return self._handle_response(resp, path)

            except APIError as e:
                if e.code == -1000 and "Signature" in str(e.msg) and attempt < retries - 1:
                    logger.warning(f"Signature failed on {path}, retrying ({attempt+1}/{retries})...")
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise
            except (httpx.HTTPError, asyncio.TimeoutError) as e:
                logger.warning(f"Request {path} attempt {attempt+1} failed: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))
                else:
                    raise

    def _handle_response(self, resp: httpx.Response, path: str) -> Any:
        used_weight = resp.headers.get("X-MBX-USED-WEIGHT-1M", "?")

        if resp.status_code == 403:
            logger.error(f"403 Forbidden on {path}: {resp.text[:200]}")
            raise APIError(403, f"Forbidden on {path}")

        try:
            data = resp.json()
        except Exception:
            logger.error(f"Non-JSON response on {path} (status={resp.status_code}): {resp.text[:200]}")
            raise APIError(resp.status_code, f"Non-JSON response on {path}")

        if resp.status_code == 429:
            logger.error(f"Rate limited on {path}. Weight used: {used_weight}")
            raise RateLimitError(f"Rate limited on {path}")

        if resp.status_code == 418:
            logger.critical(f"IP banned! Stop all requests.")
            raise IPBannedError("IP has been banned")

        if isinstance(data, dict) and "code" in data and data["code"] not in (200, 0):
            if resp.status_code >= 400:
                logger.error(f"API error on {path}: {data}")
                raise APIError(data.get("code", -1), data.get("msg", "Unknown error"))

        return data

    # ── Market Data ────────────────────────────────────────────────

    async def ping(self) -> dict:
        return await self._request("GET", "/fapi/v3/ping")

    async def get_server_time(self) -> int:
        data = await self._request("GET", "/fapi/v3/time")
        return data["serverTime"]

    async def get_exchange_info(self) -> dict:
        data = await self._request("GET", "/fapi/v3/exchangeInfo")
        for sym in data.get("symbols", []):
            info = SymbolInfo.from_api(sym)
            self._exchange_info_cache[info.symbol] = info
        return data

    def get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        return self._exchange_info_cache.get(symbol)

    async def get_klines(
        self,
        symbol: str,
        interval: str = "15m",
        limit: int = 100,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[KlineData]:
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        data = await self._request("GET", "/fapi/v3/klines", params)
        return [KlineData.from_api(k) for k in data]

    async def get_depth(self, symbol: str, limit: int = 20) -> DepthData:
        data = await self._request("GET", "/fapi/v3/depth", {"symbol": symbol, "limit": limit})
        return DepthData.from_api(data)

    async def get_mark_price(self, symbol: str | None = None) -> MarkPriceData | list[MarkPriceData]:
        params = {}
        if symbol:
            params["symbol"] = symbol
        data = await self._request("GET", "/fapi/v3/premiumIndex", params)
        if isinstance(data, list):
            return [MarkPriceData.from_api(d) for d in data]
        return MarkPriceData.from_api(data)

    async def get_funding_rate(
        self, symbol: str | None = None, limit: int = 100
    ) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/fapi/v3/fundingRate", params)

    async def get_ticker_24hr(self, symbol: str | None = None) -> TickerData | list[TickerData]:
        params = {}
        if symbol:
            params["symbol"] = symbol
        data = await self._request("GET", "/fapi/v3/ticker/24hr", params)
        if isinstance(data, list):
            return [TickerData.from_api(d) for d in data]
        return TickerData.from_api(data)

    async def get_ticker_price(self, symbol: str | None = None) -> dict | list[dict]:
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/fapi/v3/ticker/price", params)

    async def get_book_ticker(self, symbol: str | None = None) -> dict | list[dict]:
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/fapi/v3/ticker/bookTicker", params)

    # ── Account & Position ─────────────────────────────────────────

    async def get_balance(self) -> list[AccountBalance]:
        data = await self._request("GET", "/fapi/v3/balance", signed=True)
        return [AccountBalance.from_api(b) for b in data]

    async def get_account(self) -> dict:
        return await self._request("GET", "/fapi/v3/accountWithJoinMargin", signed=True)

    async def get_positions(self, symbol: str | None = None) -> list[Position]:
        params = {}
        if symbol:
            params["symbol"] = symbol
        data = await self._request("GET", "/fapi/v3/positionRisk", params, signed=True)
        return [Position.from_api(p) for p in data]

    async def set_leverage(self, symbol: str, leverage: int) -> dict:
        return await self._request(
            "POST", "/fapi/v3/leverage",
            {"symbol": symbol, "leverage": leverage},
            signed=True,
        )

    async def set_margin_type(self, symbol: str, margin_type: str) -> dict:
        return await self._request(
            "POST", "/fapi/v3/marginType",
            {"symbol": symbol, "marginType": margin_type},
            signed=True,
        )

    async def set_position_mode(self, dual: bool) -> dict:
        return await self._request(
            "POST", "/fapi/v3/positionSide/dual",
            {"dualSidePosition": str(dual).lower()},
            signed=True,
        )

    async def get_position_mode(self) -> bool:
        data = await self._request("GET", "/fapi/v3/positionSide/dual", signed=True)
        return data.get("dualSidePosition", False)

    # ── Orders ─────────────────────────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float | None = None,
        price: float | None = None,
        position_side: str = "BOTH",
        time_in_force: str | None = None,
        stop_price: float | None = None,
        reduce_only: bool | None = None,
        close_position: bool | None = None,
        new_client_order_id: str | None = None,
        working_type: str | None = None,
    ) -> OrderResult:
        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "positionSide": position_side,
        }
        if quantity is not None:
            params["quantity"] = str(quantity)
        if price is not None:
            params["price"] = str(price)
        if time_in_force:
            params["timeInForce"] = time_in_force
        if stop_price is not None:
            params["stopPrice"] = str(stop_price)
        if reduce_only is not None:
            params["reduceOnly"] = str(reduce_only).lower()
        if close_position is not None:
            params["closePosition"] = str(close_position).lower()
        if new_client_order_id:
            params["newClientOrderId"] = new_client_order_id
        if working_type:
            params["workingType"] = working_type

        data = await self._request("POST", "/fapi/v3/order", params, signed=True)
        return OrderResult.from_api(data)

    async def cancel_order(
        self, symbol: str, order_id: int | None = None, orig_client_order_id: str | None = None
    ) -> OrderResult:
        params: dict[str, Any] = {"symbol": symbol}
        if order_id:
            params["orderId"] = order_id
        if orig_client_order_id:
            params["origClientOrderId"] = orig_client_order_id
        data = await self._request("DELETE", "/fapi/v3/order", params, signed=True)
        return OrderResult.from_api(data)

    async def cancel_all_orders(self, symbol: str) -> dict:
        return await self._request(
            "DELETE", "/fapi/v3/allOpenOrders",
            {"symbol": symbol},
            signed=True,
        )

    async def get_open_orders(self, symbol: str | None = None) -> list[dict]:
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/fapi/v3/openOrders", params, signed=True)

    async def get_order(
        self, symbol: str, order_id: int | None = None, orig_client_order_id: str | None = None
    ) -> dict:
        params: dict[str, Any] = {"symbol": symbol}
        if order_id:
            params["orderId"] = order_id
        if orig_client_order_id:
            params["origClientOrderId"] = orig_client_order_id
        return await self._request("GET", "/fapi/v3/order", params, signed=True)

    async def batch_orders(self, orders: list[dict]) -> list[dict]:
        import json
        params = {"batchOrders": json.dumps(orders)}
        return await self._request("POST", "/fapi/v3/batchOrders", params, signed=True)

    # ── User Data Stream ───────────────────────────────────────────

    async def create_listen_key(self) -> str:
        data = await self._request("POST", "/fapi/v3/listenKey", signed=True)
        return data["listenKey"]

    async def keepalive_listen_key(self) -> dict:
        return await self._request("PUT", "/fapi/v3/listenKey", signed=True)

    async def close_listen_key(self) -> dict:
        return await self._request("DELETE", "/fapi/v3/listenKey", signed=True)

    # ── Income / Trades ────────────────────────────────────────────

    async def get_income(self, symbol: str | None = None, limit: int = 100) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/fapi/v3/income", params, signed=True)

    async def get_user_trades(self, symbol: str, limit: int = 100) -> list[dict]:
        return await self._request(
            "GET", "/fapi/v3/userTrades",
            {"symbol": symbol, "limit": limit},
            signed=True,
        )

    async def get_leverage_brackets(self, symbol: str | None = None) -> list[dict] | dict:
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/fapi/v3/leverageBracket", params, signed=True)

    async def get_max_leverage(self, symbol: str) -> int:
        """Get the maximum allowed leverage for a symbol (cached)."""
        if symbol in self._max_leverage_cache:
            return self._max_leverage_cache[symbol]
        try:
            data = await self.get_leverage_brackets(symbol)
            brackets = []
            if isinstance(data, list):
                for item in data:
                    if item.get("symbol") == symbol:
                        brackets = item.get("brackets", [])
                        break
                if not brackets and data:
                    brackets = data[0].get("brackets", []) if isinstance(data[0], dict) else []
            elif isinstance(data, dict):
                brackets = data.get("brackets", [])

            max_lev = 1
            for b in brackets:
                lev = int(b.get("initialLeverage", b.get("maxLeverage", 1)))
                if lev > max_lev:
                    max_lev = lev
            self._max_leverage_cache[symbol] = max_lev
            logger.info(f"Max leverage for {symbol}: {max_lev}x")
            return max_lev
        except Exception as e:
            logger.warning(f"Could not fetch leverage brackets for {symbol}: {e}")
            return 20

    async def get_commission_rate(self, symbol: str) -> dict:
        return await self._request(
            "GET", "/fapi/v3/commissionRate",
            {"symbol": symbol},
            signed=True,
        )


# ── Exceptions ─────────────────────────────────────────────────────

class APIError(Exception):
    def __init__(self, code: int, msg: str):
        self.code = code
        self.msg = msg
        super().__init__(f"[{code}] {msg}")


class RateLimitError(APIError):
    def __init__(self, msg: str):
        super().__init__(-429, msg)


class IPBannedError(APIError):
    def __init__(self, msg: str):
        super().__init__(-418, msg)
