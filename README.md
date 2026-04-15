# Aster AI Trading Bot

AI-powered automated perpetual futures trading bot for [Aster DEX](https://www.asterdex.com), using Claude for market analysis and signal generation.

## Features

- **AI-Driven Signals**: Claude analyzes klines, order book depth, funding rates, and generates structured trading signals
- **Dynamic Pair Scanning**: Automatically selects high-volume, high-volatility trading pairs with anomalous funding rates
- **Risk Management**: Position sizing, leverage limits, stop-loss/take-profit, daily loss limits, and exposure caps
- **Trailing Stops**: Partial take-profit at 2:1 R/R, then trailing stop on the remainder
- **Real-time Monitoring**: WebSocket streams for market data and account/order updates
- **Auto-Reconnect**: WebSocket connections automatically reconnect on failure

## Architecture

```
main.py                  # Entry point & orchestration loop
src/
  auth.py                # EIP-712 signing for Aster v3 API
  client.py              # Async REST API client
  ws_client.py           # WebSocket client (market + user data)
  scanner.py             # Dynamic pair scanner & ranking
  collector.py           # Market data aggregation (REST + WS)
  ai_analyzer.py         # Claude AI analysis & signal generation
  order_manager.py       # Order execution (entry + SL/TP)
  position_manager.py    # Position tracking & trailing stops
  risk_manager.py        # Risk validation engine
  models.py              # Data models
config/
  settings.yaml          # Main configuration
  pairs_filter.yaml      # Pair whitelist/blacklist & filters
```

## Setup

### 1. Prerequisites

- Python 3.11+
- Aster DEX account with API wallet (Pro API)
- Anthropic API key

### 2. Install Dependencies

```bash
cd asterBot
pip install -r requirements.txt
```

### 3. Configure Credentials

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```
ASTER_USER=0xYourMainWalletAddress
ASTER_SIGNER=0xYourAPIWalletAddress
ASTER_PRIVATE_KEY=0xYourAPIWalletPrivateKey
ANTHROPIC_API_KEY=sk-ant-xxxxx
```

To create an API wallet (signer), go to https://www.asterdex.com/en/api-wallet and switch to **Pro API**.

### 4. Configure Trading Parameters

Edit `config/settings.yaml`:

| Section | Key Parameters |
|---------|---------------|
| `trading` | `mode` (hedge/one_way), `default_leverage` (5-10x) |
| `risk` | `max_position_pct` (10%), `stop_loss_pct` (2%), `daily_loss_limit_pct` (5%) |
| `scanner` | `min_volume_usdt`, `top_n_pairs`, scan interval |
| `ai` | Claude `model`, `min_confidence` (0.70), analysis interval |

Edit `config/pairs_filter.yaml` for whitelist/blacklist.

### 5. Run

```bash
python main.py
```

## Trading Flow

1. **Scan** - Every 5 min, fetch all 24hr tickers and funding rates, rank by volume + volatility + funding anomaly
2. **Collect** - Fetch klines, order book depth, mark price for top N candidates
3. **Analyze** - Send market data to Claude, receive structured JSON signal (LONG/SHORT/CLOSE/HOLD)
4. **Validate** - Risk manager checks position size, leverage, exposure, daily loss limits
5. **Execute** - Place MARKET entry + STOP_MARKET stop-loss + TAKE_PROFIT_MARKET partial TP
6. **Monitor** - Track positions via WebSocket, activate trailing stop after partial TP fills

## Risk Controls

| Rule | Default |
|------|---------|
| Max position size | 10% of balance |
| Max total exposure | 50% of balance |
| Leverage range | 5-10x |
| Stop loss | 2% per trade |
| Take profit | 2:1 risk/reward ratio |
| Partial TP | 50% at first target |
| Trailing stop | 1% after partial TP |
| Daily loss limit | 5% - pauses trading |
| Max open positions | 5 |

## API Reference

Built on Aster Futures v3 API:
- REST: `https://fapi3.asterdex.com`
- WebSocket: `wss://fstream.asterdex.com`
- Auth: EIP-712 Typed Data signature (chainId=1666)
- Docs: https://asterdex.github.io/aster-api-website/

## Disclaimer

This software is for educational purposes. Cryptocurrency trading involves substantial risk of loss. Use at your own risk. Always test with small amounts first.
## 撰稿人 / Author

**撰稿人**：丹尼斯  
**GitHub**：[@dannisiai](https://github.com/dannisiai)  
**更新时间**：2026年4月

这是我个人修改和维护的 Aster DEX AI 交易机器人项目。
欢迎提出 Issue 或建议！
