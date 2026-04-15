from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import os

import yaml
from openai import OpenAI, APIError as OpenAIAPIError
from loguru import logger

from src.models import (
    KlineData,
    MarketSnapshot,
    Position,
    SignalAction,
    TradeSignal,
)

BASE_SYSTEM_PROMPT = """You are a quantitative cryptocurrency perpetual futures trading system.
Your role is to analyze market data and produce trading signals in structured JSON format.

This is a systematic, algorithmic trading operation with robust risk management including stop-losses on every trade.
The portfolio is continuously funded, so standard position sizing applies. Your job is to identify high-probability setups and express them as signals.

{strategy_section}

Position Sizing & Parameters:
- Always include stop_loss and take_profit levels for every signal.
- position_size_pct range: 0.15 to 0.50 of available balance. Use the upper end for high-conviction setups.
- leverage range: {min_leverage} to {max_leverage} (scale with conviction — prefer higher leverage on strong signals).
- Respond "HOLD" only when no setup meets the strategy criteria.
- Respond "CLOSE" when an existing position should be exited.
- When a clear setup exists per your strategy rules, output the appropriate signal.

You MUST respond ONLY with a valid JSON object (no markdown, no commentary, no refusal):
{{
  "action": "LONG" | "SHORT" | "CLOSE" | "HOLD",
  "symbol": "<SYMBOL>",
  "confidence": <float 0.0-1.0>,
  "entry_price": <float>,
  "stop_loss": <float>,
  "take_profit": <float>,
  "leverage": <int>,
  "position_size_pct": <float>,
  "reasoning": "<brief technical reasoning>"
}}"""


@dataclass
class Strategy:
    name: str
    description: str
    kline_interval: str
    kline_limit: int
    analysis_focus: list[str]
    entry_rules: list[str]
    exit_rules: list[str]
    risk_overrides: dict
    extra_instructions: str
    scanner_overrides: dict = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> Strategy:
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(
            name=data.get("name", "Unnamed"),
            description=data.get("description", ""),
            kline_interval=data.get("kline_interval", "15m"),
            kline_limit=data.get("kline_limit", 100),
            analysis_focus=data.get("analysis_focus", []),
            entry_rules=data.get("entry_rules", []),
            exit_rules=data.get("exit_rules", []),
            risk_overrides=data.get("risk_overrides") or {},
            extra_instructions=data.get("extra_instructions", ""),
            scanner_overrides=data.get("scanner_overrides") or {},
        )

    def build_prompt_section(self) -> str:
        parts = [f"ACTIVE STRATEGY: {self.name}"]
        parts.append(f"Description: {self.description}\n")

        if self.analysis_focus:
            parts.append("Analysis Focus:")
            for i, focus in enumerate(self.analysis_focus, 1):
                parts.append(f"  {i}. {focus}")
            parts.append("")

        if self.entry_rules:
            parts.append("Entry Rules:")
            for i, rule in enumerate(self.entry_rules, 1):
                parts.append(f"  {i}. {rule}")
            parts.append("")

        if self.exit_rules:
            parts.append("Exit Rules:")
            for i, rule in enumerate(self.exit_rules, 1):
                parts.append(f"  {i}. {rule}")
            parts.append("")

        if self.extra_instructions:
            parts.append("Detailed Strategy Instructions:")
            parts.append(self.extra_instructions)

        return "\n".join(parts)


def load_strategy(name: str, strategies_dir: str | Path | None = None) -> Strategy:
    """Load a strategy by name from the strategies directory."""
    if strategies_dir is None:
        strategies_dir = Path(__file__).parent.parent / "config" / "strategies"
    else:
        strategies_dir = Path(strategies_dir)

    path = strategies_dir / f"{name}.yaml"
    if not path.exists():
        available = [f.stem for f in strategies_dir.glob("*.yaml")]
        raise FileNotFoundError(
            f"Strategy '{name}' not found at {path}. "
            f"Available strategies: {available}"
        )
    return Strategy.from_yaml(path)


def list_strategies(strategies_dir: str | Path | None = None) -> list[str]:
    """List all available strategy names."""
    if strategies_dir is None:
        strategies_dir = Path(__file__).parent.parent / "config" / "strategies"
    else:
        strategies_dir = Path(strategies_dir)
    return sorted(f.stem for f in strategies_dir.glob("*.yaml"))


class AIAnalyzer:
    """Uses Claude to analyze market data and generate trading signals."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-opus-4-6",
        min_confidence: float = 0.70,
        max_tokens: int = 1024,
        temperature: float = 0.3,
        strategy: Strategy | None = None,
        min_leverage: int = 5,
        max_leverage: int = 10,
        base_url: str | None = None,
    ):
        base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL", "https://api.apiyi.com")
        self.client = OpenAI(api_key=api_key, base_url=f"{base_url.rstrip('/')}/v1")
        self.model = model
        self.min_confidence = min_confidence
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._strategy = strategy
        self._min_leverage = min_leverage
        self._max_leverage = max_leverage
        self._last_analysis: dict[str, float] = {}
        self._system_prompt = self._build_system_prompt()

    @property
    def strategy(self) -> Strategy | None:
        return self._strategy

    @property
    def kline_interval(self) -> str:
        return self._strategy.kline_interval if self._strategy else "15m"

    @property
    def kline_limit(self) -> int:
        return self._strategy.kline_limit if self._strategy else 100

    def set_strategy(self, strategy: Strategy):
        """Switch to a different strategy at runtime."""
        self._strategy = strategy
        self._system_prompt = self._build_system_prompt()

        overrides = strategy.risk_overrides
        if "max_leverage" in overrides:
            self._max_leverage = overrides["max_leverage"]
        if "min_leverage" in overrides:
            self._min_leverage = overrides["min_leverage"]

        logger.info(f"Strategy switched to: {strategy.name}")

    def _build_system_prompt(self) -> str:
        if self._strategy:
            strategy_section = self._strategy.build_prompt_section()
        else:
            strategy_section = (
                "Your analysis framework:\n"
                "1. TREND: Identify the current trend using price action and moving averages.\n"
                "2. MOMENTUM: Assess momentum using rate of change, volume patterns.\n"
                "3. SUPPORT/RESISTANCE: Identify key levels from order book and price action.\n"
                "4. FUNDING RATE: Consider extreme funding rates as contrarian signals.\n"
                "5. RISK/REWARD: Only signal trades with favorable risk/reward (minimum 2:1).\n"
                "Be conservative. Only signal HIGH-CONFIDENCE trades."
            )

        return BASE_SYSTEM_PROMPT.format(
            strategy_section=strategy_section,
            min_leverage=self._min_leverage,
            max_leverage=self._max_leverage,
        )

    def _format_klines(self, klines: list[KlineData], max_rows: int = 50) -> str:
        recent = klines[-max_rows:]
        lines = ["Time | O | H | L | C | Vol | Trades"]
        for k in recent:
            lines.append(
                f"{k.open_time} | {k.open:.6g} | {k.high:.6g} | "
                f"{k.low:.6g} | {k.close:.6g} | {k.volume:.2f} | {k.trades}"
            )
        return "\n".join(lines)

    def _format_depth(self, snapshot: MarketSnapshot) -> str:
        if not snapshot.depth:
            return "N/A"
        lines = ["== BIDS (top 10) =="]
        for price, qty in snapshot.depth.bids[:10]:
            lines.append(f"  {price:.6g}  x  {qty:.4f}")
        lines.append("== ASKS (top 10) ==")
        for price, qty in snapshot.depth.asks[:10]:
            lines.append(f"  {price:.6g}  x  {qty:.4f}")
        return "\n".join(lines)

    def _build_prompt(
        self,
        snapshot: MarketSnapshot,
        positions: list[Position] | None = None,
    ) -> str:
        interval = self.kline_interval
        parts = [f"=== Market Data for {snapshot.symbol} ===\n"]

        if snapshot.ticker:
            t = snapshot.ticker
            parts.append(f"24h Change: {t.price_change_pct:.2f}%")
            parts.append(f"Last Price: {t.last_price:.6g}")
            parts.append(f"24h Volume (USDT): {t.quote_volume:,.0f}")
            parts.append(f"24h High: {t.high_price:.6g}  Low: {t.low_price:.6g}")
            parts.append("")

        if snapshot.mark_price:
            mp = snapshot.mark_price
            parts.append(f"Mark Price: {mp.mark_price:.6g}")
            parts.append(f"Index Price: {mp.index_price:.6g}")
            parts.append(f"Funding Rate: {mp.funding_rate:.6f}")
            parts.append(f"Next Funding: {mp.next_funding_time}")
            parts.append("")

        parts.append(f"=== Kline Data ({interval}) ===")
        parts.append(self._format_klines(snapshot.klines))
        parts.append("")

        parts.append("=== Order Book ===")
        parts.append(self._format_depth(snapshot))
        parts.append("")

        if positions:
            open_pos = [p for p in positions if p.is_open and p.symbol == snapshot.symbol]
            if open_pos:
                parts.append("=== Current Positions ===")
                for p in open_pos:
                    parts.append(
                        f"  {p.position_side.value}: qty={p.position_amt}, "
                        f"entry={p.entry_price:.6g}, pnl={p.unrealized_pnl:.4f}, "
                        f"leverage={p.leverage}x"
                    )
                parts.append("")
            else:
                parts.append("No open positions on this symbol.\n")
        else:
            parts.append("No position data available.\n")

        parts.append("Based on this data and your active strategy, what is your trading signal?")
        return "\n".join(parts)

    async def analyze(
        self,
        snapshot: MarketSnapshot,
        positions: list[Position] | None = None,
    ) -> Optional[TradeSignal]:
        symbol = snapshot.symbol

        if not snapshot.klines:
            logger.warning(f"No kline data for {symbol}, skipping analysis")
            return None

        prompt = self._build_prompt(snapshot, positions)
        strategy_name = self._strategy.name if self._strategy else "Default"
        logger.debug(f"Analyzing {symbol} with Claude ({self.model}) strategy={strategy_name}")

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": prompt},
                ],
            )

            raw_text = response.choices[0].message.content.strip()
            signal = self._parse_signal(raw_text, symbol)

            if signal:
                self._last_analysis[symbol] = time.time()
                logger.info(
                    f"[{strategy_name}] Signal for {symbol}: {signal.action.value} "
                    f"(confidence={signal.confidence:.2f})"
                )

            return signal

        except OpenAIAPIError as e:
            logger.error(f"AI API error for {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Analysis error for {symbol}: {e}")
            return None

    def _parse_signal(self, raw_text: str, symbol: str) -> Optional[TradeSignal]:
        try:
            text = raw_text
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
            text = text.strip()

            data = json.loads(text)

            action = SignalAction(data["action"])
            confidence = float(data.get("confidence", 0))

            if action == SignalAction.HOLD:
                logger.debug(f"AI says HOLD for {symbol}")
                return None

            if confidence < self.min_confidence and action != SignalAction.CLOSE:
                logger.info(
                    f"Signal for {symbol} below confidence threshold: "
                    f"{confidence:.2f} < {self.min_confidence}"
                )
                return None

            return TradeSignal(
                action=action,
                symbol=data.get("symbol", symbol),
                confidence=confidence,
                entry_price=float(data.get("entry_price", 0)),
                stop_loss=float(data.get("stop_loss", 0)),
                take_profit=float(data.get("take_profit", 0)),
                leverage=int(data.get("leverage", 7)),
                position_size_pct=float(data.get("position_size_pct", 0.05)),
                reasoning=data.get("reasoning", ""),
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to parse AI response for {symbol}: {e}\nRaw: {raw_text[:500]}")
            return None

    def should_analyze(self, symbol: str, interval_seconds: float = 180) -> bool:
        last = self._last_analysis.get(symbol, 0)
        return (time.time() - last) >= interval_seconds
