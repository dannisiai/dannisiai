from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from loguru import logger

from src.ai_analyzer import AIAnalyzer, load_strategy, list_strategies, Strategy
from src.auth import AsterAuth
from src.client import AsterClient
from src.collector import MarketCollector
from src.models import Position, SignalAction
from src.order_manager import OrderManager
from src.position_manager import PositionManager
from src.risk_manager import RiskConfig, RiskManager
from src.scanner import PairScanner
from src.twitter_poster import TwitterPoster
from src.ws_client import AsterWebSocket


def _fire_and_log(coro):
    """Create a task that logs exceptions instead of silently swallowing them."""
    async def _wrapper():
        try:
            await coro
        except Exception as e:
            logger.exception(f"Background task failed: {e}")
    return asyncio.create_task(_wrapper())


def load_config() -> dict:
    config_path = Path(__file__).parent / "config" / "settings.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    filter_path = Path(__file__).parent / "config" / "pairs_filter.yaml"
    if filter_path.exists():
        with open(filter_path) as f:
            cfg["pairs_filter"] = yaml.safe_load(f) or {}

    return cfg


def setup_logging(cfg: dict):
    log_cfg = cfg.get("logging", {})
    logger.remove()
    logger.add(sys.stderr, level=log_cfg.get("level", "INFO"))

    log_file = log_cfg.get("file", "logs/trading.log")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_file,
        level=log_cfg.get("level", "INFO"),
        rotation=log_cfg.get("rotation", "10 MB"),
        retention=log_cfg.get("retention", "7 days"),
    )


class StrategyRunner:
    """Runs a single strategy's scan-analyze-trade loop."""

    def __init__(
        self,
        name: str,
        strategy: Strategy,
        scanner: PairScanner,
        collector: MarketCollector,
        ai: AIAnalyzer,
        order_mgr: OrderManager,
        position_mgr: PositionManager,
        risk: RiskManager,
        client: AsterClient,
        scan_interval: int,
        analysis_interval: int,
        symbol_lock: dict[str, str],
        twitter: TwitterPoster | None = None,
    ):
        self.name = name
        self.strategy = strategy
        self.scanner = scanner
        self.collector = collector
        self.ai = ai
        self.order_mgr = order_mgr
        self.position_mgr = position_mgr
        self.risk = risk
        self.client = client
        self._scan_interval = scan_interval
        self._analysis_interval = analysis_interval
        self._symbol_lock = symbol_lock
        self._twitter = twitter
        self._running = False

    async def run(self):
        self._running = True
        logger.info(f"[{self.name}] Strategy loop started (interval={self._scan_interval}s)")

        while self._running:
            try:
                if self.risk.is_paused:
                    logger.warning(f"[{self.name}] Trading paused: {self.risk.pause_reason}")
                    await asyncio.sleep(60)
                    continue

                candidates = await self.scanner.scan()
                if not candidates:
                    logger.info(f"[{self.name}] No candidates. Waiting {self._scan_interval}s...")
                    await asyncio.sleep(self._scan_interval)
                    continue

                symbols = [c.symbol for c in candidates]
                await self.collector.subscribe_symbols(symbols)
                snapshots = await self.collector.fetch_snapshots(symbols)

                positions = await self.client.get_positions()
                balances = await self.client.get_balance()
                usdt_bal = next((b for b in balances if b.asset == "USDT"), None)
                balance = usdt_bal.available_balance if usdt_bal else 0

                if balance <= 0:
                    logger.warning(f"[{self.name}] No available USDT balance")
                    await asyncio.sleep(self._scan_interval)
                    continue

                self.risk.reset_daily(usdt_bal.wallet_balance if usdt_bal else 0)

                for symbol in symbols:
                    # Skip symbols currently claimed by another strategy
                    locked_by = self._symbol_lock.get(symbol)
                    if locked_by and locked_by != self.name:
                        continue

                    if not self.ai.should_analyze(symbol, self._analysis_interval):
                        continue

                    snapshot = snapshots.get(symbol)
                    if not snapshot:
                        continue

                    self._symbol_lock[symbol] = self.name

                    signal = await self.ai.analyze(snapshot, positions)
                    if not signal:
                        self._symbol_lock.pop(symbol, None)
                        continue

                    if signal.action in (SignalAction.LONG, SignalAction.SHORT):
                        logger.info(
                            f"[{self.name}] Signal: {signal.action.value} {signal.symbol} "
                            f"conf={signal.confidence:.2f}"
                        )
                        result = await self.order_mgr.execute_signal(signal, balance, positions)

                        if result:
                            max_hold = self.strategy.risk_overrides.get(
                                "max_hold_minutes",
                                self.risk.config.max_hold_minutes,
                            )
                            pos_side = "LONG" if signal.action == SignalAction.LONG else "SHORT"
                            self.position_mgr.track(
                                symbol=signal.symbol,
                                position_side=pos_side,
                                entry_price=signal.entry_price,
                                quantity=result.orig_qty,
                                stop_loss=signal.stop_loss,
                                take_profit=signal.take_profit,
                                strategy=self.name,
                                max_hold_minutes=max_hold,
                            )

                            if self._twitter:
                                _fire_and_log(self._twitter.post_trade_update({
                                    "event": "open",
                                    "symbol": signal.symbol,
                                    "side": signal.action.value,
                                    "leverage": signal.leverage,
                                    "entry_price": signal.entry_price,
                                    "confidence": signal.confidence,
                                    "reasoning": signal.reasoning,
                                }))

                            positions = await self.client.get_positions()
                            balances = await self.client.get_balance()
                            usdt_bal = next((b for b in balances if b.asset == "USDT"), None)
                            balance = usdt_bal.available_balance if usdt_bal else 0

                    elif signal.action == SignalAction.CLOSE:
                        await self.order_mgr.execute_signal(signal, balance, positions)

                        if self._twitter:
                            _fire_and_log(self._twitter.post_trade_update({
                                "event": "close",
                                "symbol": signal.symbol,
                                "side": "CLOSE",
                                "reasoning": signal.reasoning,
                            }))

                        self.position_mgr.untrack(signal.symbol, "LONG")
                        self.position_mgr.untrack(signal.symbol, "SHORT")
                        self._symbol_lock.pop(symbol, None)

                    await asyncio.sleep(2)

                await self.position_mgr.sync_with_exchange()

                stats = self.risk.get_daily_stats()
                open_count = len([p for p in positions if p.is_open])
                logger.info(
                    f"[{self.name}] Cycle done | Bal: {balance:.2f} | "
                    f"Open: {open_count} | PnL: {stats['realized_pnl']:.2f} | "
                    f"Trades: {stats['trades_count']}"
                )

                # ~10% chance per cycle to post a random shitpost/thought
                import random
                if self._twitter and self.name == "pump_short" and random.random() < 0.10:
                    _fire_and_log(self._twitter.post_trade_update({
                        "event": random.choice(["shitpost", "philosophy", "roast", "vent"]),
                    }))

                await asyncio.sleep(self._scan_interval)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception(f"[{self.name}] Error in strategy loop: {e}")
                await asyncio.sleep(30)

    def stop(self):
        self._running = False


class TradingBot:
    """Multi-strategy orchestrator."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._running = False

        self.auth = AsterAuth(
            user=os.environ["ASTER_USER"],
            signer=os.environ["ASTER_SIGNER"],
            private_key=os.environ["ASTER_PRIVATE_KEY"],
            chain_id=cfg["api"].get("chain_id", 1666),
        )

        self.client = AsterClient(
            base_url=cfg["api"]["rest_base"],
            auth=self.auth,
        )

        self.ws = AsterWebSocket(
            ws_base=cfg["api"]["ws_base"],
            rest_client=self.client,
        )

        # Shared risk manager
        risk_cfg = dict(cfg.get("risk", {}))
        self.risk = RiskManager(RiskConfig(
            min_position_pct=risk_cfg.get("min_position_pct", 0.05),
            max_position_pct=risk_cfg.get("max_position_pct", 0.10),
            max_total_exposure_pct=risk_cfg.get("max_total_exposure_pct", 0.50),
            stop_loss_pct=risk_cfg.get("stop_loss_pct", 0.20),
            take_profit_ratio=risk_cfg.get("take_profit_ratio", 2.0),
            partial_tp_pct=risk_cfg.get("partial_tp_pct", 0.50),
            trailing_stop_pct=risk_cfg.get("trailing_stop_pct", 0.03),
            daily_loss_limit_pct=risk_cfg.get("daily_loss_limit_pct", 0.10),
            max_open_positions=risk_cfg.get("max_open_positions", 8),
            min_leverage=risk_cfg.get("min_leverage", cfg.get("trading", {}).get("min_leverage", 3)),
            max_leverage=risk_cfg.get("max_leverage", cfg.get("trading", {}).get("max_leverage", 10)),
            max_hold_minutes=risk_cfg.get("max_hold_minutes", 120),
            min_profit_pct_to_keep=risk_cfg.get("min_profit_pct_to_keep", 0.02),
        ))

        # Shared order & position managers
        trading_cfg = cfg.get("trading", {})
        self.order_mgr = OrderManager(
            client=self.client,
            risk_manager=self.risk,
            position_mode=trading_cfg.get("mode", "hedge"),
        )
        self.position_mgr = PositionManager(
            client=self.client,
            risk_manager=self.risk,
            position_mode=trading_cfg.get("mode", "hedge"),
            on_close_callback=self._on_position_closed,
        )

        # Twitter poster
        twitter_cfg = cfg.get("twitter", {})
        self.twitter: TwitterPoster | None = None
        if twitter_cfg.get("enabled", False):
            self.twitter = TwitterPoster(
                ai_api_key=os.environ["ANTHROPIC_API_KEY"],
                ai_model=cfg.get("ai", {}).get("model", "claude-opus-4-6"),
                ai_base_url=os.environ.get("ANTHROPIC_BASE_URL"),
                min_interval_seconds=twitter_cfg.get("post_interval_seconds", 300),
            )

        # Global symbol lock: {symbol: strategy_name}
        self._symbol_lock: dict[str, str] = {}
        self._strategy_tasks: list[asyncio.Task] = []
        self._runners: list[StrategyRunner] = []

    def _build_runners(self):
        cfg = self.cfg
        pf = cfg.get("pairs_filter", {})
        sc_base = dict(cfg.get("scanner", {}))
        ai_cfg = cfg.get("ai", {})
        strategy_names = cfg.get("strategies", {}).get("enabled", [])

        if not strategy_names:
            strategy_names = [cfg.get("strategy", {}).get("active", "trend_following")]

        available = list_strategies()
        logger.info(f"Available strategies: {available}")
        logger.info(f"Enabled strategies: {strategy_names}")

        for sname in strategy_names:
            try:
                strategy = load_strategy(sname)
            except FileNotFoundError as e:
                logger.warning(f"Strategy '{sname}' not found, skipping: {e}")
                continue

            # Per-strategy scanner config
            sc = dict(sc_base)
            if strategy.scanner_overrides:
                sc.update(strategy.scanner_overrides)

            scanner_weights = pf.get("category_weights")
            if "category_weights" in strategy.scanner_overrides:
                scanner_weights = strategy.scanner_overrides["category_weights"]

            scanner = PairScanner(
                client=self.client,
                min_volume_usdt=sc.get("min_volume_usdt", 1_000_000),
                min_price_change_pct=sc.get("min_price_change_pct", 1.0),
                top_n=sc.get("top_n_pairs", 10),
                excluded_symbols=sc.get("excluded_symbols", []),
                whitelist=pf.get("whitelist", []),
                blacklist=pf.get("blacklist", []),
                category_weights=scanner_weights,
                funding_high_threshold=sc.get("funding_high_threshold",
                    pf.get("funding_rate", {}).get("high_threshold", 0.001)),
                funding_low_threshold=sc.get("funding_low_threshold",
                    pf.get("funding_rate", {}).get("low_threshold", -0.001)),
            )

            # Per-strategy collector
            collector = MarketCollector(
                client=self.client,
                ws_client=self.ws,
                kline_interval=strategy.kline_interval,
                kline_limit=strategy.kline_limit,
            )

            # Per-strategy risk overrides for AI leverage bounds
            strat_risk = dict(cfg.get("risk", {}))
            if strategy.risk_overrides:
                strat_risk.update(strategy.risk_overrides)

            ai = AIAnalyzer(
                api_key=os.environ["ANTHROPIC_API_KEY"],
                model=ai_cfg.get("model", "claude-opus-4-6"),
                min_confidence=ai_cfg.get("min_confidence", 0.70),
                max_tokens=ai_cfg.get("max_tokens", 1024),
                temperature=ai_cfg.get("temperature", 0.3),
                strategy=strategy,
                min_leverage=strat_risk.get("min_leverage", self.risk.config.min_leverage),
                max_leverage=strat_risk.get("max_leverage", self.risk.config.max_leverage),
                base_url=os.environ.get("ANTHROPIC_BASE_URL"),
            )

            runner = StrategyRunner(
                name=sname,
                strategy=strategy,
                scanner=scanner,
                collector=collector,
                ai=ai,
                order_mgr=self.order_mgr,
                position_mgr=self.position_mgr,
                risk=self.risk,
                client=self.client,
                scan_interval=sc.get("interval_seconds", 60),
                analysis_interval=ai_cfg.get("analysis_interval_seconds", 60),
                symbol_lock=self._symbol_lock,
                twitter=self.twitter,
            )
            self._runners.append(runner)
            logger.info(f"Loaded strategy runner: {strategy.name} ({sname})")

    async def _on_position_closed(self, context: dict):
        """Called by PositionManager when a position is market-closed."""
        if self.twitter:
            await self.twitter.post_trade_update(context)

    async def _market_commentary_loop(self):
        """Post market commentary every 15 minutes in a separate task."""
        await asyncio.sleep(60)  # wait 1 min for bot to warm up
        logger.info("Market commentary loop started (every 15 min)")

        while self._running:
            try:
                market_data = await self._gather_market_snapshot()
                if self.twitter:
                    await self.twitter.post_market_commentary(market_data)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception(f"Market commentary error: {e}")
            await asyncio.sleep(900)  # 15 minutes

    async def _gather_market_snapshot(self) -> dict:
        """Collect current market data for commentary."""
        import time as _time

        data: dict = {}

        try:
            tickers = await self.client.get_ticker_24hr()
            if not isinstance(tickers, list):
                tickers = [tickers]
            btc = next((t for t in tickers if t.symbol == "BTCUSDT"), None)
            eth = next((t for t in tickers if t.symbol == "ETHUSDT"), None)
            data["btc_price"] = f"${btc.last_price:,.0f}" if btc else "?"
            data["eth_price"] = f"${eth.last_price:,.0f}" if eth else "?"

            usdt_tickers = [t for t in tickers if t.symbol.endswith("USDT") and t.quote_volume > 100000]
            sorted_tickers = sorted(usdt_tickers, key=lambda t: abs(t.price_change_pct), reverse=True)
            data["top_movers"] = [
                {"symbol": t.symbol, "change": t.price_change_pct}
                for t in sorted_tickers[:8]
            ]
        except Exception as e:
            logger.warning(f"Failed to get tickers for commentary: {e}")
            data["btc_price"] = "?"
            data["eth_price"] = "?"
            data["top_movers"] = []

        try:
            positions = await self.client.get_positions()
            open_pos = [p for p in positions if p.is_open]
            data["positions"] = [
                {
                    "symbol": p.symbol,
                    "side": p.position_side.value,
                    "pnl": f"{p.unrealized_pnl:+.2f}",
                }
                for p in open_pos[:5]
            ]
        except Exception:
            data["positions"] = []

        try:
            balances = await self.client.get_balance()
            usdt = next((b for b in balances if b.asset == "USDT"), None)
            data["balance"] = usdt.available_balance if usdt else 0
        except Exception:
            data["balance"] = 0

        return data

    async def start(self):
        logger.info("=" * 60)
        logger.info("  Aster AI Trading Bot — Multi-Strategy Engine")
        logger.info("=" * 60)

        self._running = True

        logger.info("Loading exchange info...")
        for attempt in range(5):
            try:
                await self.client.get_exchange_info()
                logger.info(f"Loaded {len(self.client._exchange_info_cache)} symbols")
                break
            except Exception as e:
                wait = 30 * (attempt + 1)
                logger.warning(f"Exchange info failed ({e}), retrying in {wait}s...")
                await asyncio.sleep(wait)
        else:
            logger.error("Failed to load exchange info after 5 attempts")
            return

        await self.client.ping()
        server_time = await self.client.get_server_time()
        logger.info(f"Server time: {server_time}")

        from src.auth import get_nonce
        get_nonce.set_server_offset(server_time)
        local_ms = int(__import__('time').time() * 1000)
        offset = server_time - local_ms
        logger.info(f"Time offset calibrated: {offset}ms (server - local)")

        trading_cfg = self.cfg.get("trading", {})
        try:
            is_hedge = trading_cfg.get("mode", "hedge") == "hedge"
            await self.client.set_position_mode(dual=is_hedge)
            logger.info(f"Position mode: {'hedge' if is_hedge else 'one-way'}")
        except Exception as e:
            logger.warning(f"Could not set position mode (may already be set): {e}")

        balances = await self.client.get_balance()
        usdt_bal = next((b for b in balances if b.asset == "USDT"), None)
        if usdt_bal:
            logger.info(
                f"USDT Balance: {usdt_bal.wallet_balance:.2f} "
                f"(available: {usdt_bal.available_balance:.2f})"
            )
            self.risk.reset_daily(usdt_bal.wallet_balance)
        else:
            logger.warning("No USDT balance found")

        self.ws.on("ORDER_TRADE_UPDATE", self._on_order_update)
        self.ws.on("ACCOUNT_UPDATE", self._on_account_update)
        await self.ws.start(market=True, user_data=True)

        await self.position_mgr.start()

        self._build_runners()

        if not self._runners:
            logger.error("No strategy runners loaded. Check settings.yaml strategies.enabled")
            await self.shutdown()
            return

        for i, runner in enumerate(self._runners):
            async def _staggered_start(r, delay):
                if delay > 0:
                    await asyncio.sleep(delay)
                await r.run()
            task = asyncio.create_task(_staggered_start(runner, i * 30))
            self._strategy_tasks.append(task)

        logger.info(f"Started {len(self._runners)} strategy runners (staggered 30s apart)")

        if self.twitter and self.twitter.enabled:
            commentary_task = asyncio.create_task(self._market_commentary_loop())
            self._strategy_tasks.append(commentary_task)
            logger.info("Market commentary loop scheduled (every 15 min)")

        try:
            await asyncio.gather(*self._strategy_tasks)
        except asyncio.CancelledError:
            logger.info("Strategy tasks cancelled")
        finally:
            await self.shutdown()

    async def _on_order_update(self, data: dict):
        await self.order_mgr.handle_order_update(data)
        self.position_mgr.handle_order_fill(data)

    async def _on_account_update(self, data: dict):
        reason = data.get("a", {}).get("m", "")
        logger.debug(f"Account update: reason={reason}")

    async def shutdown(self):
        logger.info("Shutting down...")
        self._running = False
        for runner in self._runners:
            runner.stop()
        for task in self._strategy_tasks:
            task.cancel()
        await self.position_mgr.stop()
        await self.ws.stop()
        await self.client.close()
        logger.info("Shutdown complete")


async def main():
    load_dotenv()

    required_env = ["ASTER_USER", "ASTER_SIGNER", "ASTER_PRIVATE_KEY", "ANTHROPIC_API_KEY"]
    missing = [k for k in required_env if not os.environ.get(k)]
    if missing:
        print(f"Missing environment variables: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    cfg = load_config()
    setup_logging(cfg)

    bot = TradingBot(cfg)

    loop = asyncio.get_event_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        try:
            import signal
            loop.add_signal_handler(
                getattr(signal, sig_name),
                lambda: asyncio.create_task(bot.shutdown()),
            )
        except (NotImplementedError, AttributeError):
            pass

    await bot.start()


if __name__ == "__main__":
    asyncio.run(main())
