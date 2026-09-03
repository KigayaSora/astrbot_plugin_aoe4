"""AoE4World API 封装。

- base: https://aoe4world.com/api/v0（无认证，v0 不稳定，全部宽松解析）
- 限速：全局 <=1 req/s；429 读取 Retry-After 退避重试
- 缓存：内存 TTL 缓存
- 错误：统一抛出 ApiError 子类，供上层转成中文提示
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import aiohttp

BASE_URL = "https://aoe4world.com/api/v0"


class ApiError(Exception):
    """AoE4World API 调用错误基类。"""


class QueryTooShort(ApiError):
    """搜索词少于 3 个字符。"""


class RateLimitError(ApiError):
    """触发 429 限流且重试耗尽。"""


class ApiTimeout(ApiError):
    """请求超时。"""


class ApiServerError(ApiError):
    """服务端 5xx 或响应异常。"""


class _RateLimiter:
    """简单的全局限速器：保证相邻请求间隔 >= interval 秒。"""

    def __init__(self, interval: float = 1.0) -> None:
        self._interval = interval
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self._interval:
                await asyncio.sleep(self._interval - delta)
            self._last = time.monotonic()


class AoE4WorldApi:
    """AoE4World v0 API 异步客户端。"""

    def __init__(self, session: aiohttp.ClientSession, config: Optional[dict] = None) -> None:
        self._session = session
        cfg = config or {}
        self._ua = cfg.get("user_agent", "AstrBotAoE4Plugin/1.0")
        self._cache_ttl = int(cfg.get("cache_ttl", 120))
        self._max_retry = int(cfg.get("max_retry", 2))
        self._limiter = _RateLimiter(1.0)
        self._cache: dict[tuple[str, tuple], tuple[float, Any]] = {}

    # ---------- 内部 ----------

    def _cache_get(self, key: tuple[str, tuple]) -> Any | None:
        item = self._cache.get(key)
        if not item:
            return None
        ts, data = item
        if time.monotonic() - ts > self._cache_ttl:
            self._cache.pop(key, None)
            return None
        return data

    def _cache_set(self, key: tuple[str, tuple], data: Any) -> None:
        self._cache[key] = (time.monotonic(), data)

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        """带限速/缓存/重试的 GET。返回解析后的 JSON。"""
        params = params or {}
        key = (path, tuple(sorted(params.items())))
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        headers = {"User-Agent": self._ua, "Accept": "application/json"}
        url = BASE_URL + path
        last_exc: Exception | None = None

        for attempt in range(self._max_retry + 1):
            try:
                await self._limiter.wait()
                async with self._session.get(url, params=params, headers=headers) as resp:
                    if resp.status == 429:
                        retry_after = resp.headers.get("Retry-After")
                        wait = float(retry_after) if retry_after else 2.0 * (attempt + 1)
                        if attempt < self._max_retry:
                            await asyncio.sleep(wait)
                            continue
                        raise RateLimitError("AoE4World 接口限流（429）")
                    if resp.status >= 500:
                        if attempt < self._max_retry:
                            await asyncio.sleep(1.0 * (attempt + 1))
                            continue
                        raise ApiServerError(f"AoE4World 服务端错误（HTTP {resp.status}）")
                    if resp.status == 404:
                        raise ApiError("接口返回 404，玩家或资源不存在")
                    if resp.status != 200:
                        raise ApiError(f"接口返回异常（HTTP {resp.status}）")
                    try:
                        data = await resp.json(content_type=None)
                    except Exception as e:
                        raise ApiError(f"接口响应解析失败: {e}") from e
                    self._cache_set(key, data)
                    return data
            except (ApiError,):
                raise
            except asyncio.TimeoutError as e:
                last_exc = e
                if attempt < self._max_retry:
                    continue
                raise ApiTimeout("请求 AoE4World 超时") from e
            except aiohttp.ClientError as e:
                last_exc = e
                if attempt < self._max_retry:
                    await asyncio.sleep(1.0)
                    continue
                raise ApiError(f"网络请求失败: {e}") from e

        raise ApiError(f"请求失败: {last_exc}")

    # ---------- 公开方法 ----------

    async def search_player(self, query: str) -> list[dict]:
        """按名字搜索玩家。返回 players 列表（可能为空）。query 需 >=3 字符。"""
        query = (query or "").strip()
        if len(query) < 3:
            raise QueryTooShort("搜索词至少需要 3 个字符")
        data = await self._get("/players/search", {"query": query})
        players = data.get("players") if isinstance(data, dict) else None
        return players or []

    async def get_player(self, profile_id: int | str) -> dict:
        """玩家资料（含 modes 各模式数据）。"""
        data = await self._get(f"/players/{profile_id}")
        return data if isinstance(data, dict) else {}

    async def get_games(self, profile_id: int | str, limit: int = 10) -> list[dict]:
        """玩家最近对局列表。返回 games 数组（注意 teams 多一层 player 包裹）。"""
        limit = max(1, min(int(limit), 50))
        data = await self._get(f"/players/{profile_id}/games", {"limit": limit})
        games = data.get("games") if isinstance(data, dict) else None
        return games or []

    async def get_civilization_stats(
        self, leaderboard: str = "rm_solo", rank_level: Optional[str] = None
    ) -> dict:
        """文明胜率统计。返回 {leaderboard, rank_level, rating, patch, data[]}。"""
        params: dict[str, str] = {}
        if rank_level:
            params["rank_level"] = rank_level
        data = await self._get(f"/stats/{leaderboard}/civilizations", params)
        return data if isinstance(data, dict) else {}
