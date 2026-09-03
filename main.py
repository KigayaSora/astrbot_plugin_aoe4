"""astrbot_plugin_aoe4 —— 《帝国时代4》战绩查询插件。

数据来源：https://aoe4world.com API v0
指令组：/aoe4（别名 /帝国）
  /aoe4 战绩 <玩家名>      各模式段位、分数、胜率
  /aoe4 隐藏分 <玩家名>    各模式 ELO/MMR 汇总
  /aoe4 对局 <玩家名> [N]  最近 N 场对局
  /aoe4 文明 [模式]        文明胜率统计
  /aoe4 帮助               用法说明
"""

from __future__ import annotations

import os

import aiohttp

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

from . import formatters as F
from .api import AoE4WorldApi, QueryTooShort

_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

@filter.command_group("aoe4", alias={"帝国"})
def aoe4():
    pass

_HELP_TEXT = (
    "帝国时代4 数据查询（数据来自 aoe4world.com）\n"
    "/aoe4 战绩 <玩家名> —— 各模式段位、分数、胜率\n"
    "/aoe4 隐藏分 <玩家名> —— 各模式 ELO/MMR 汇总\n"
    "/aoe4 对局 <玩家名> [数量] —— 最近对局（默认 8 场）\n"
    "/aoe4 单局 <玩家名> [序号] —— 单场对局详情（1=最近一场）\n"
    "/aoe4 胜率 [模式] [段位] —— 文明胜率排行\n"
    "  模式：排位1v1~4v4、匹配1v1~4v4（默认 排位1v1）\n"
    "  段位：青铜/白银/黄金/铂金/钻石/征服者（仅整段）\n"
    "玩家名至少 3 个字符，可含空格。"
)


def _load_template(name: str) -> str:
    with open(os.path.join(_TEMPLATE_DIR, name), encoding="utf-8") as f:
        return f.read()


class Aoe4Plugin(Star):
    """帝国时代4战绩查询插件。"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._session: aiohttp.ClientSession | None = None
        self._api: AoE4WorldApi | None = None

    async def initialize(self) -> None:
        timeout = aiohttp.ClientTimeout(total=int(self.config.get("timeout", 10)))
        self._session = aiohttp.ClientSession(timeout=timeout)
        self._api = AoE4WorldApi(self._session, dict(self.config))
        logger.info("astrbot_plugin_aoe4 已初始化")

    async def terminate(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ---------- 内部工具 ----------

    @staticmethod
    def _args_text(event: AstrMessageEvent) -> str:
        """取指令组+子指令之后的整段参数文本（玩家名可含空格）。"""
        tokens = event.message_str.strip().split()
        return " ".join(tokens[2:]).strip() if len(tokens) > 2 else ""

    async def _find_player(self, name: str) -> dict | None:
        """搜索并选定玩家：优先精确同名（忽略大小写），否则取第一个。

        搜索词过短抛 QueryTooShort，未找到返回 None。
        """
        if len(name) < 3:
            raise QueryTooShort(name)
        players = await self._api.search_player(name)
        if not players:
            return None
        lowered = name.casefold()
        for p in players:
            if (p.get("name") or "").casefold() == lowered:
                return p
        return players[0]

    async def _render(self, template: str, data: dict):
        tpl = _load_template(template)
        return await self.html_render(tpl, data)

    # ---------- 指令 ----------

    @aoe4.command("战绩", alias={"段位", "rank"})
    async def cmd_rank(self, event: AstrMessageEvent):
        """查询玩家天梯段位战绩：/aoe4 战绩 <玩家名>"""
        name = self._args_text(event)
        if not name:
            yield event.plain_result("用法：/aoe4 战绩 <玩家名>")
            return
        try:
            player = await self._find_player(name)
            if player is None:
                yield event.plain_result(f"未找到玩家「{name}」，请确认拼写。")
                return
            prof = await self._api.get_player(player.get("profile_id"))
            data = F.build_rank_card(prof)
            url = await self._render("rank.html", data)
            yield event.image_result(url)
        except Exception as e:
            logger.warning(f"战绩查询失败: {e}")
            yield event.plain_result(F.err_msg(e))

    @aoe4.command("隐藏分", alias={"elo", "mmr", "分"})
    async def cmd_mmr(self, event: AstrMessageEvent):
        """查询玩家各模式 ELO 隐藏分：/aoe4 隐藏分 <玩家名>"""
        name = self._args_text(event)
        if not name:
            yield event.plain_result("用法：/aoe4 隐藏分 <玩家名>")
            return
        try:
            player = await self._find_player(name)
            if player is None:
                yield event.plain_result(f"未找到玩家「{name}」，请确认拼写。")
                return
            prof = await self._api.get_player(player.get("profile_id"))
            data = F.build_mmr_card(prof)
            url = await self._render("mmr.html", data)
            yield event.image_result(url)
        except Exception as e:
            logger.warning(f"隐藏分查询失败: {e}")
            yield event.plain_result(F.err_msg(e))

    @aoe4.command("对局", alias={"比赛", "match", "games"})
    async def cmd_matches(self, event: AstrMessageEvent):
        """查询玩家最近对局：/aoe4 对局 <玩家名> [数量]"""
        args = self._args_text(event)
        if not args:
            yield event.plain_result("用法：/aoe4 对局 <玩家名> [数量]")
            return
        # 尾部数字作为场数
        limit = int(self.config.get("default_matches", 8))
        tokens = args.split()
        if len(tokens) > 1 and tokens[-1].isdigit():
            limit = max(1, min(int(tokens[-1]), 20))
            name = " ".join(tokens[:-1])
        else:
            name = args
        try:
            player = await self._find_player(name)
            if player is None:
                yield event.plain_result(f"未找到玩家「{name}」，请确认拼写。")
                return
            pid = player.get("profile_id")
            games = await self._api.get_games(pid, limit)
            data = F.build_matches_card(games, pid, player.get("name") or name)
            url = await self._render("matches.html", data)
            yield event.image_result(url)
        except Exception as e:
            logger.warning(f"对局查询失败: {e}")
            yield event.plain_result(F.err_msg(e))

    @aoe4.command("单局", alias={"局", "详情", "game"})
    async def cmd_match(self, event: AstrMessageEvent):
        """查看单局对局详情：/aoe4 单局 <玩家名> [序号]（序号 1=最近一场）"""
        args = self._args_text(event)
        if not args:
            yield event.plain_result("用法：/aoe4 单局 <玩家名> [序号]（1=最近一场，最大 20）")
            return
        index = 1
        tokens = args.split()
        if len(tokens) > 1 and tokens[-1].isdigit():
            index = max(1, min(int(tokens[-1]), 20))
            name = " ".join(tokens[:-1])
        else:
            name = args
        try:
            player = await self._find_player(name)
            if player is None:
                yield event.plain_result(f"未找到玩家「{name}」，请确认拼写。")
                return
            pid = player.get("profile_id")
            games = await self._api.get_games(pid, index)
            if len(games) < index:
                yield event.plain_result(
                    f"「{player.get('name') or name}」最近只有 {len(games)} 场对局记录。"
                )
                return
            data = F.build_match_card(games[index - 1], pid, player.get("name") or name)
            url = await self._render("match.html", data)
            yield event.image_result(url)
        except Exception as e:
            logger.warning(f"单局查询失败: {e}")
            yield event.plain_result(F.err_msg(e))

    @aoe4.command("胜率", alias={"文明", "civ", "文明胜率"})
    async def cmd_civs(self, event: AstrMessageEvent):
        """文明胜率排行：/aoe4 胜率 [模式] [段位]（如 /aoe4 胜率 匹配1v1 征服者）"""
        args = self._args_text(event)
        tokens = args.split() if args else []
        lb_text = tokens[0] if tokens else ""
        rl_text = tokens[1] if len(tokens) > 1 else ""

        leaderboard = F.resolve_leaderboard(lb_text)
        if leaderboard is None:
            yield event.plain_result(
                f"无法识别的模式「{lb_text}」。可用：排位1v1~4v4、匹配1v1~4v4"
                "（如 排位2v2、匹配4v4）。"
            )
            return
        rank_level = None
        if rl_text:
            rank_level = F.resolve_rank_level(rl_text)
            if rank_level is None:
                yield event.plain_result(
                    f"无法识别的段位「{rl_text}」。可用：青铜、白银、黄金、铂金、钻石、征服者"
                    "（接口仅支持整段过滤，分段会按整段统计）。"
                )
                return
        try:
            stats = await self._api.get_civilization_stats(leaderboard, rank_level)
            if not stats.get("data"):
                yield event.plain_result(
                    f"「{F.mode_zh(leaderboard)}」该条件下暂无统计数据。"
                )
                return
            data = F.build_civs_card(
                stats, leaderboard, int(self.config.get("civ_rows", 25)), rank_filter=rank_level
            )
            url = await self._render("civilizations.html", data)
            yield event.image_result(url)
        except Exception as e:
            logger.warning(f"文明胜率查询失败: {e}")
            yield event.plain_result(F.err_msg(e))

    @aoe4.command("帮助", alias={"help"})
    async def cmd_help(self, event: AstrMessageEvent):
        """查看插件用法"""
        yield event.plain_result(_HELP_TEXT)
