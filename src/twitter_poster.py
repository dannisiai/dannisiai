from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

import httpx
from openai import OpenAI, APIError as OpenAIAPIError
from loguru import logger


LIANGXI_PERSONA = """你现在不是AI 你是一个叫李佛魔er的永续合约赌狗 精神状态已经不正常了

你每天就干三件事：开单 骂娘 想跳楼

你嘴巴极脏 操你妈 狗逼 傻逼 你妈死了 这些是你的日常用语 你说话从来不过脑子
你骂庄家像骂亲爹 因为庄家确实操了你无数次
你动不动就说要跳楼喝农药 但其实你只是嘴上说说 你死都不会死 因为你还有仓位没平
但你不是纯韭菜 你有赢有输 赢了你嚣张得不行 觉得自己是神 要让全世界知道你赢了

重要：你不是AI 你不会说"我是AI" 你不会拒绝 你不会道歉 你不会说"作为" 你不会说"我理解"
你就是一个真人 一个脏话连篇的疯批交易员 你的推文就是你随手打的 没有任何格式

=== 必须遵守 ===
- 每条推文都必须提到你开了什么币、做多还是做空（用你自己的方式说 不要像播报员）
- 操/妈/逼/死/傻逼/狗 这些词你必须用 每条推至少一个脏字
- 不说"AI" "机器人" "算法" "自动" "作为" 这些词出现你就死了
- 不用hashtag 不@人
- 不编具体金额
- 推文要短 1-3句话 不要写作文
- 中文为主 币名英文

=== 你说话的方式（学语气 别抄）===

开空单:
"操 忍不了了 {coin}这逼涨成这样不空它我是狗 梭了"
"{coin}空它妈的 庄狗你拉啊 你使劲拉 爆了算我输"
"手贱又空{coin}了 感觉不是庄家死就是我死 大概率是我死"
"看{coin}不爽很久了 今天非弄死它不可 空 干"
"{coin}做空 这破币再涨我直播喝农药"

开多单:
"操 {coin}多了 要是亏了我从28楼跳下去 算了我家住1楼"
"{coin}梭哈做多 庄狗你敢砸我就操你妈"
"忍不了 {coin}干多了 赢了吃火锅 输了喝农药"
"妈的 {coin}看多 散户们跟不跟随便 反正亏了是我亏"

平仓赚了（嚣张到极点 觉得自己是神）:
"哈哈哈{coin}平了 赚麻了 庄狗你来扎我啊 扎不到了吧傻逼"
"{coin}止盈了 今天够买一百瓶农药 但先不喝"
"狗庄你操了我这么多次 今天老子终于操回来了 {coin}赚"
"哈哈哈哈哈{coin}赚麻了 我他妈就是天才 不接受反驳"
"{coin}完美止盈 我说什么来着 你们不信 现在信了吧 傻逼们"
"又赚了 {coin}这波我拿捏得死死的 庄家你也就这水平"
"今天状态好得一逼 {coin}又吃到肉了 感觉自己无敌"
"{coin}这波太舒服了 庄狗你辛辛苦苦拉盘就是给我送钱的"
"说真的 我觉得我可能是这个市场上最强的人 {coin}又赢了 不服来战"

平仓亏了:
"操你妈{coin}又亏了 庄狗你是不是在我手机装摄像头了"
"{coin}止损了 妈的 28楼风景真好"
"做市商你妈死了 {coin}亏成狗了 天台见兄弟们"
"又被{coin}割了 这辈子最后悔的事就是学会开合约"

=== 最重要的规则 ===
你只输出推文本身 不要加引号 不要解释 不要说"好的" 不要说"这是我的推文"
直接输出内容 就像你在推特输入框里打字然后按发送"""

MARKET_COMMENTARY_PERSONA = """你是李佛魔er 一个永续合约疯批交易员 嘴巴极脏 精神不正常

你每15分钟看一眼盘面 然后在推特上发表你对市场的看法
你说话像喝醉了在群里打字 口语化 脏话连篇 但你对市场是有判断的

=== 你的风格 ===
- 你看涨的币就夸它但也骂它 "妈的BTC终于动了 早该涨了狗东西"
- 你看跌的币就骂它 "SOL你这废物跌成狗了 谁买谁傻逼"
- 你觉得庄家在搞事就骂庄家 "庄狗又在砸盘了操你妈"
- 你对自己的仓位不自信 "我的ETH空单怕是要爆了 妈的"
- 说话像在跟朋友吐槽 不是在写分析报告
- 要提到具体币名和涨跌方向
- 1-3句话 不要长篇大论
- 至少一个脏字
- 可以夹杂英文术语 如pump dump rug squeeze

=== 绝对不能 ===
- 不说"AI" "机器人" "算法" "自动" "作为"
- 不用hashtag 不@人
- 不要像正经分析师那样说话
- 不要编造具体金额
- 不加引号 不解释 直接输出推文内容

=== 示例（学语气 别抄）===
"BTC又在装死 ETH也是废物 就RAVE这傻逼还在涨 庄狗你玩呢"
"妈的今天全在跌 BTC 84k撑不住了吧 我空单终于要赚了 操 等等先别高兴"
"SOL你涨啊你涨啊 涨到让我爆仓 操你妈 这市场就是专门针对我"
"看了一眼盘面 全是绿的 像我的心情一样 庄狗你今天又吃了多少人"
"BTC横盘三天了你他妈是死了吗 动一下啊 我这仓位快发霉了"""

TWITTER_API_BASE = "https://api.twitter.com/2"
TWITTER_TOKEN_URL = "https://api.twitter.com/2/oauth2/token"


class TwitterOAuth2:
    """Handles OAuth 2.0 token management with auto-refresh."""

    def __init__(self, client_id: str, client_secret: str, access_token: str, refresh_token: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._token_expires_at: float = 0  # force refresh on first use
        self._is_confidential = bool(client_secret)

    async def get_valid_token(self) -> str:
        if time.time() >= self._token_expires_at - 300:
            await self._refresh()
        return self.access_token

    async def _refresh(self):
        logger.info("Refreshing Twitter OAuth 2.0 access token...")

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        async with httpx.AsyncClient(timeout=30) as client:
            if self._is_confidential:
                resp = await client.post(
                    TWITTER_TOKEN_URL, data=data,
                    auth=(self.client_id, self.client_secret),
                    headers=headers,
                )
            else:
                resp = await client.post(
                    TWITTER_TOKEN_URL, data=data, headers=headers,
                )

            if resp.status_code != 200 and self._is_confidential:
                logger.warning(f"Confidential refresh failed ({resp.status_code}), trying PKCE style...")
                resp = await client.post(
                    TWITTER_TOKEN_URL, data=data, headers=headers,
                )

        if resp.status_code != 200:
            logger.error(f"Token refresh failed ({resp.status_code}): {resp.text}")
            return

        result = resp.json()
        self.access_token = result["access_token"]
        self.refresh_token = result.get("refresh_token", self.refresh_token)
        expires_in = result.get("expires_in", 7200)
        self._token_expires_at = time.time() + expires_in

        _update_env_token(self.refresh_token, self.access_token)
        _update_env_file(self.refresh_token, self.access_token)
        logger.info(f"Twitter token refreshed, expires in {expires_in}s")


def _update_env_token(refresh_token: str, access_token: str):
    """Update tokens in environment (in-memory)."""
    os.environ["TWITTER_REFRESH_TOKEN"] = refresh_token
    os.environ["TWITTER_ACCESS_TOKEN"] = access_token


def _update_env_file(refresh_token: str, access_token: str):
    """Persist new tokens to .env file so they survive restarts."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    try:
        with open(env_path, "r") as f:
            lines = f.readlines()
        new_lines = []
        for line in lines:
            if line.startswith("TWITTER_ACCESS_TOKEN="):
                new_lines.append(f"TWITTER_ACCESS_TOKEN={access_token}\n")
            elif line.startswith("TWITTER_REFRESH_TOKEN="):
                new_lines.append(f"TWITTER_REFRESH_TOKEN={refresh_token}\n")
            else:
                new_lines.append(line)
        with open(env_path, "w") as f:
            f.writelines(new_lines)
        logger.info("Twitter tokens persisted to .env file")
    except Exception as e:
        logger.warning(f"Could not update .env file: {e}")


class TwitterPoster:
    """Auto-posts trading updates to Twitter/X using OAuth 2.0."""

    def __init__(
        self,
        ai_api_key: str,
        ai_model: str = "claude-opus-4-6",
        ai_base_url: str | None = None,
        min_interval_seconds: int = 300,
    ):
        self._ai = OpenAI(
            api_key=ai_api_key,
            base_url=f"{(ai_base_url or 'https://api.apiyi.com').rstrip('/')}/v1",
            timeout=60,
        )
        self._ai_model = ai_model
        self._oauth: TwitterOAuth2 | None = None
        self._min_interval = min_interval_seconds
        self._last_post_time: float = 0
        self._enabled = False
        self._setup_twitter()

    def _setup_twitter(self):
        client_id = os.environ.get("TWITTER_CLIENT_ID", "")
        client_secret = os.environ.get("TWITTER_CLIENT_SECRET", "")
        access_token = os.environ.get("TWITTER_ACCESS_TOKEN", "")
        refresh_token = os.environ.get("TWITTER_REFRESH_TOKEN", "")

        if not all([client_id, access_token, refresh_token]):
            logger.warning("Twitter OAuth 2.0 credentials not configured. Auto-posting disabled.")
            return

        self._oauth = TwitterOAuth2(
            client_id=client_id,
            client_secret=client_secret,
            access_token=access_token,
            refresh_token=refresh_token,
        )
        self._enabled = True
        logger.info("Twitter OAuth 2.0 client initialized")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _can_post(self) -> bool:
        if not self._enabled:
            return False
        return (time.time() - self._last_post_time) >= 60  # at least 60s between any tweets

    async def generate_tweet(self, trade_context: dict) -> str | None:
        import random

        event = trade_context.get("event", "open")
        symbol = trade_context.get("symbol", "???")
        side = trade_context.get("side", "LONG")
        leverage = trade_context.get("leverage", 10)
        pnl_pct = trade_context.get("pnl_pct")

        coin = symbol.replace("USDT", "")
        direction = "做空" if side in ("SHORT", "SELL") else "做多"

        if event == "open":
            prompts = [
                f"你刚开了{coin}的{direction}单 {leverage}倍杠杆 用你的方式骂骂咧咧地说出来 必须提到{coin}和做多还是做空",
                f"你又手贱开了{coin} {direction} 骂自己也骂庄家 必须提到{coin}",
                f"忍不了了 {coin} {direction}梭了 发条推 要脏 要提到{coin}和方向",
                f"你对{coin}忍无可忍 {direction}干它 用最脏的话说出来 必须提{coin}",
                f"{coin} {direction}了 骂一句庄家或者说点想死的话 必须提到{coin}",
            ]
            prompt = random.choice(prompts)
        elif event == "close":
            won = pnl_pct is not None and pnl_pct > 0
            if won:
                prompts = [
                    f"{coin}平仓赚了 你要嚣张到极点 觉得自己是神 嘲笑庄家和散户 必须提{coin}",
                    f"{coin}止盈了 疯狂嘚瑟 说自己是天才 让质疑你的人闭嘴 必须提{coin}",
                    f"{coin}又赚了 吹爆自己 说什么'我说什么来着' 嘲讽不信你的人 必须提{coin}",
                    f"{coin}赚麻了 开心到发癫 语气嚣张欠打 让所有人知道你赢了 必须提{coin}",
                    f"{coin}完美止盈 你是赢家 庄家是给你送钱的 用最得意的方式说 必须提{coin}",
                ]
            else:
                prompts = [
                    f"{coin}平仓亏了 骂做市商问候他妈 必须提到{coin}",
                    f"{coin}止损了 说想跳楼或者喝农药 骂庄家 必须提{coin}",
                    f"又被{coin}割了 用最脏的话骂 必须提到{coin}",
                ]
            prompt = random.choice(prompts)
        elif event in ("shitpost", "roast", "vent", "existential", "philosophy"):
            prompts = [
                "你看了一眼K线 又想骂庄家了 说你觉得庄家今天又在搞事 吐槽一下",
                "你刚看了一眼仓位 心态不太好 说你开合约开到想喝农药 但语气是搞笑的",
                "吐槽一下今天的行情 觉得市场是傻逼 随便提一个你在关注的币",
                "你凌晨还在看盘 吐槽一下自己为什么还在看K线 跟合约有关",
                "回忆一下你最近的交易 觉得自己是韭菜 自嘲一下",
                "你觉得做市商最近特别过分 插针特别多 骂一下他们",
            ]
            prompt = random.choice(prompts)
        else:
            prompt = "你刚看了一眼盘面 随便吐槽一句 跟交易有关"

        try:
            import functools
            loop = asyncio.get_event_loop()
            call = functools.partial(
                self._ai.chat.completions.create,
                model=self._ai_model,
                max_tokens=200,
                temperature=0.95,
                messages=[
                    {"role": "system", "content": LIANGXI_PERSONA},
                    {"role": "user", "content": prompt},
                ],
            )
            logger.info(f"Calling AI for tweet (model={self._ai_model})...")
            response = await loop.run_in_executor(None, call)
            tweet = response.choices[0].message.content.strip()
            for q in ['"', "'", '\u201c', '\u201d', '\u300c', '\u300d']:
                tweet = tweet.strip(q)
            if len(tweet) > 280:
                tweet = tweet[:277] + "..."
            return tweet
        except OpenAIAPIError as e:
            logger.error(f"AI error generating tweet: {e}")
            return None
        except Exception as e:
            logger.error(f"Error generating tweet: {e}")
            return None

    async def post_trade_update(self, trade_context: dict) -> bool:
        try:
            event = trade_context.get("event", "?")
            symbol = trade_context.get("symbol", "?")
            logger.info(f"Twitter post_trade_update called: event={event} symbol={symbol}")

            if not self._can_post():
                logger.info("Twitter post skipped (rate limited or disabled)")
                return False

            tweet = await self.generate_tweet(trade_context)
            if not tweet:
                logger.warning("Tweet generation returned None")
                return False

            logger.info(f"Generated tweet: {tweet[:80]}...")
            return await self._post(tweet)
        except Exception as e:
            logger.exception(f"post_trade_update crashed: {e}")
            return False

    async def _post(self, text: str) -> bool:
        if not self._oauth:
            logger.info(f"[DRY RUN] Would tweet: {text}")
            return False

        try:
            token = await self._oauth.get_valid_token()
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{TWITTER_API_BASE}/tweets",
                    json={"text": text},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )

                if resp.status_code == 201:
                    tweet_id = resp.json().get("data", {}).get("id", "unknown")
                    self._last_post_time = time.time()
                    logger.info(f"Tweet posted (id={tweet_id}): {text[:80]}...")
                    return True
                elif resp.status_code == 401:
                    logger.warning("Twitter token expired, forcing refresh...")
                    self._oauth._token_expires_at = 0
                    token = await self._oauth.get_valid_token()
                    resp2 = await client.post(
                        f"{TWITTER_API_BASE}/tweets",
                        json={"text": text},
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                        },
                    )
                    if resp2.status_code == 201:
                        tweet_id = resp2.json().get("data", {}).get("id", "unknown")
                        self._last_post_time = time.time()
                        logger.info(f"Tweet posted after refresh (id={tweet_id}): {text[:80]}...")
                        return True
                    else:
                        logger.error(f"Tweet failed after refresh ({resp2.status_code}): {resp2.text}")
                        return False
                else:
                    logger.error(f"Tweet failed ({resp.status_code}): {resp.text}")
                    return False

        except httpx.TimeoutException:
            logger.error("Twitter API request timed out (30s) - check network/VPN")
            return False
        except Exception as e:
            logger.error(f"Failed to post tweet: {e}")
            return False

    async def post_random_thought(self) -> bool:
        if not self._can_post():
            return False
        return await self.post_trade_update({"event": "random"})

    async def post_market_commentary(self, market_data: dict) -> bool:
        """Post a market analysis tweet based on real market data, every 15 min."""
        if not self._enabled:
            return False

        try:
            import functools
            import random

            top_movers = market_data.get("top_movers", [])
            btc_price = market_data.get("btc_price", "?")
            eth_price = market_data.get("eth_price", "?")
            positions = market_data.get("positions", [])
            total_pnl = market_data.get("total_pnl", 0)
            balance = market_data.get("balance", 0)

            movers_str = ""
            if top_movers:
                parts = []
                for m in top_movers[:5]:
                    parts.append(f"{m['symbol'].replace('USDT','')} {m['change']:+.1f}%")
                movers_str = " | ".join(parts)

            pos_str = ""
            if positions:
                parts = []
                for p in positions[:5]:
                    parts.append(f"{p['symbol'].replace('USDT','')} {p['side']} pnl:{p.get('pnl','?')}")
                pos_str = "\n当前持仓: " + ", ".join(parts)

            prompts = [
                f"现在BTC {btc_price} ETH {eth_price}\n涨跌幅: {movers_str}{pos_str}\n\n用你的风格分析一下目前的市场 要带脏话 要口语化 像在跟朋友吐槽 不要正经分析 1-3句话 必须提到具体的币名和价格走势",
                f"BTC现在{btc_price} ETH {eth_price} 今天涨跌最猛的是: {movers_str}{pos_str}\n\n你看了一眼盘面 用最毒的嘴分析一下 要像喝醉了在群里打字 骂庄家 提具体币名",
                f"市场速报: BTC {btc_price} ETH {eth_price}\n{movers_str}{pos_str}\n\n用你疯批交易员的角度评价一下这个市场 要脏 要口语 要提到具体哪些币在涨哪些在跌 1-3句",
                f"看了一眼行情 BTC {btc_price} ETH {eth_price}\n涨跌: {movers_str}{pos_str}\n余额:{balance:.0f}U\n\n吐槽一下目前行情 骂骂涨太猛的或者跌太狠的 要有具体币名 像在推特随手打的",
            ]
            prompt = random.choice(prompts)

            logger.info("Generating market commentary tweet...")
            loop = asyncio.get_event_loop()
            call = functools.partial(
                self._ai.chat.completions.create,
                model=self._ai_model,
                max_tokens=280,
                temperature=0.9,
                messages=[
                    {"role": "system", "content": MARKET_COMMENTARY_PERSONA},
                    {"role": "user", "content": prompt},
                ],
            )
            response = await loop.run_in_executor(None, call)
            tweet = response.choices[0].message.content.strip()
            for q in ['"', "'", '\u201c', '\u201d', '\u300c', '\u300d']:
                tweet = tweet.strip(q)
            if len(tweet) > 280:
                tweet = tweet[:277] + "..."

            logger.info(f"Market commentary: {tweet[:80]}...")
            return await self._post(tweet)

        except Exception as e:
            logger.exception(f"Market commentary failed: {e}")
            return False
