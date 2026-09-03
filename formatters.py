"""数据格式化层：枚举映射、安全取值、卡片数据构造。

所有解析均为宽松模式（.get + 兜底），容忍 AoE4World v0 的 schema 变动。
本模块不依赖 AstrBot，可在本机独立测试。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .api import (
    ApiError,
    ApiServerError,
    ApiTimeout,
    QueryTooShort,
    RateLimitError,
)

# ---------- 文明映射（实测 23 个，含新 DLC，未知值兜底显示原文） ----------

CIV_MAP: dict[str, str] = {
    "english": "英格兰",
    "french": "法兰西",
    "holy_roman_empire": "神圣罗马帝国",
    "rus": "罗斯",
    "mongols": "蒙古",
    "chinese": "中国",
    "abbasid_dynasty": "阿拔斯王朝",
    "delhi_sultanate": "德里苏丹国",
    "ottomans": "奥斯曼",
    "malians": "马里",
    "byzantines": "拜占庭",
    "japanese": "日本",
    "jeanne_darc": "圣女贞德",
    "ayyubids": "阿尤布王朝",
    "zhu_xis_legacy": "朱子遗训",
    "order_of_the_dragon": "龙骑士团",
    # 新 DLC（实测）
    "golden_horde": "金帐汗国",
    "knights_templar": "圣殿骑士团",
    "macedonian_dynasty": "马其顿王朝",
    "tughlaq_dynasty": "图格拉克王朝",
    "house_of_lancaster": "兰开斯特王朝",
    "jin_dynasty": "金朝",
    "sengoku_daimyo": "战国大名",
}


def civ_zh(civ: Optional[str]) -> str:
    if not civ:
        return "未知"
    return CIV_MAP.get(civ, civ.replace("_", " ").title())


# ---------- 段位映射 ----------

TIER_MAP: dict[str, str] = {
    "bronze": "青铜",
    "silver": "白银",
    "gold": "黄金",
    "platinum": "铂金",
    "diamond": "钻石",
    "conqueror": "征服者",
}

_ROMAN = {1: "Ⅰ", 2: "Ⅱ", 3: "Ⅲ", 4: "Ⅳ"}


def rank_level_to_zh(rank_level: Optional[str]) -> str:
    """rank_level 实测取值：conqueror_1/2/3、unranked、None。"""
    if not rank_level or rank_level == "unranked":
        return "未定级"
    parts = rank_level.rsplit("_", 1)
    tier = TIER_MAP.get(parts[0], parts[0].title())
    if len(parts) == 2 and parts[1].isdigit():
        return f"{tier}{_ROMAN.get(int(parts[1]), parts[1])}"
    return tier


def tier_class(rank_level: Optional[str]) -> str:
    """段位对应的 CSS 类名（用于色块）。"""
    if not rank_level or rank_level == "unranked":
        return "tier-unranked"
    return f"tier-{rank_level.rsplit('_', 1)[0]}"


# ---------- 模式映射 ----------

# 文明/排行榜指令的模式别名（中文 → leaderboard id），仅保留 排位/匹配 1v1~4v4
LEADERBOARD_ALIAS: dict[str, str] = {
    "排位1v1": "rm_solo",
    "排位2v2": "rm_2v2",
    "排位3v3": "rm_3v3",
    "排位4v4": "rm_4v4",
    "匹配1v1": "qm_1v1",
    "匹配2v2": "qm_2v2",
    "匹配3v3": "qm_3v3",
    "匹配4v4": "qm_4v4",
}

_VALID_LEADERBOARDS = {
    "rm_solo", "rm_2v2", "rm_3v3", "rm_4v4",
    "qm_1v1", "qm_2v2", "qm_3v3", "qm_4v4",
}


def resolve_leaderboard(text: str) -> str | None:
    """把用户输入解析为 leaderboard id；无法识别返回 None。"""
    t = (text or "").strip().lower().replace(" ", "")
    if not t:
        return "rm_solo"
    if t in LEADERBOARD_ALIAS:
        return LEADERBOARD_ALIAS[t]
    if t in _VALID_LEADERBOARDS:
        return t
    return None


# 段位过滤别名（中文/英文 → rank_level 参数）
TIER_ALIAS: dict[str, str] = {
    "青铜": "bronze", "白银": "silver", "黄金": "gold",
    "铂金": "platinum", "钻石": "diamond", "征服者": "conqueror",
    "bronze": "bronze", "silver": "silver", "gold": "gold",
    "platinum": "platinum", "diamond": "diamond", "conqueror": "conqueror",
}


def resolve_rank_level(text: str) -> str | None:
    """解析段位过滤参数（青铜~征服者）。

    AoE4World 统计接口仅支持整段过滤；带数字分段（如 钻石3）自动按整段处理。
    段位实际只有 1-3 段（征服者同样只有 Ⅰ~Ⅲ，无第 4 段）。
    """
    t = (text or "").strip().lower().replace(" ", "").replace("_", "")
    if not t:
        return None
    if t and t[-1].isdigit():
        t = t[:-1]  # 忽略分段数字，按整段过滤
    return TIER_ALIAS.get(t)

MODE_MAP: dict[str, str] = {
    "rm_solo": "1v1 排位",
    "rm_team": "团队排位",
    "rm_1v1": "1v1 排位",
    "rm_2v2": "2v2 排位",
    "rm_3v3": "3v3 排位",
    "rm_4v4": "4v4 排位",
    "rm_1v1_elo": "1v1 排位",
    "rm_2v2_elo": "2v2 排位",
    "rm_3v3_elo": "3v3 排位",
    "rm_4v4_elo": "4v4 排位",
    "qm_1v1": "快速 1v1",
    "qm_2v2": "快速 2v2",
    "qm_3v3": "快速 3v3",
    "qm_4v4": "快速 4v4",
    "qm_ffa": "快速混战",
    "custom": "自定义",
}


def mode_zh(key: str) -> str:
    """模式/天梯标识转中文，去 _console / _elo 后缀并标注。"""
    suffix = ""
    base = key
    if base.endswith("_console"):
        base = base[: -len("_console")]
        suffix = "（主机）"
    name = MODE_MAP.get(base) or MODE_MAP.get(base + "_elo") or base.replace("_", " ")
    return name + suffix


# 战绩卡展示的模式键（按展示顺序）
RANK_CARD_MODES = ["rm_solo", "rm_team", "rm_1v1_elo", "rm_2v2_elo", "rm_3v3_elo", "rm_4v4_elo"]
# 隐藏分卡展示的模式键
MMR_CARD_MODES = [
    "rm_1v1_elo",
    "rm_2v2_elo",
    "rm_3v3_elo",
    "rm_4v4_elo",
    "qm_1v1",
    "qm_2v2",
    "qm_3v3",
    "qm_4v4",
    "qm_ffa",
]


# ---------- 通用工具 ----------


def safe_int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def format_duration(sec: Any) -> str:
    sec = safe_int(sec)
    if sec is None:
        return "-"
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}时{m:02d}分"
    return f"{m}分{s:02d}秒"


def format_time_ago(iso: Optional[str]) -> str:
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "-"
    delta = datetime.now(timezone.utc) - dt
    days = delta.days
    if days >= 30:
        return f"{days // 30}个月前"
    if days >= 1:
        return f"{days}天前"
    hours = delta.seconds // 3600
    if hours >= 1:
        return f"{hours}小时前"
    return f"{max(delta.seconds // 60, 1)}分钟前"


def country_flag(code: Optional[str]) -> str:
    """两位国家码转旗帜 emoji，失败返回空串。"""
    if not code or len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c.upper()) - ord("A")) for c in code)


def pick_player(teams: list, profile_id: Any) -> dict:
    """在 teams[i][j] = {'player': {...}} 结构中定位目标玩家。"""
    pid = safe_int(profile_id)
    for team in teams or []:
        for entry in team or []:
            p = (entry or {}).get("player") or {}
            if safe_int(p.get("profile_id")) == pid:
                return p
    return {}


def _mode_win_rate(m: dict) -> Optional[float]:
    wr = m.get("win_rate")
    if isinstance(wr, (int, float)):
        return round(float(wr), 1)
    wins = safe_int(m.get("wins_count")) or 0
    losses = safe_int(m.get("losses_count")) or 0
    total = wins + losses
    return round(wins * 100.0 / total, 1) if total else None


# ---------- 卡片数据构造 ----------


def _profile_head(prof: dict) -> dict:
    avatars = prof.get("avatars") or {}
    return {
        "name": prof.get("name") or "未知玩家",
        "profile_id": prof.get("profile_id"),
        "avatar": avatars.get("medium") or avatars.get("small") or "",
        "country": (prof.get("country") or "").upper(),
        "flag": country_flag(prof.get("country")),
        "site_url": prof.get("site_url") or "",
    }


def build_rank_card(prof: dict) -> dict:
    """战绩卡：各模式段位/分数/胜率。"""
    modes = prof.get("modes") or {}
    rows = []
    seen: dict[str, int] = {}  # 显示名 -> rows 下标，用于去重（rm_solo 与 rm_1v1_elo 同名）
    for key in RANK_CARD_MODES:
        m = modes.get(key)
        if not isinstance(m, dict):
            continue
        games = safe_int(m.get("games_count")) or 0
        if games == 0 and m.get("rating") is None:
            continue  # 完全没打过的模式不展示
        rating = safe_int(m.get("rating"))
        row = {
            "mode": mode_zh(key),
            "ranked": rating is not None,
            "rating": rating if rating is not None else "-",
            "tier_zh": rank_level_to_zh(m.get("rank_level")),
            "tier_class": tier_class(m.get("rank_level")),
            "rank": safe_int(m.get("rank")),
            "win_rate": _mode_win_rate(m),
            "games": games,
            "wins": safe_int(m.get("wins_count")) or 0,
            "losses": safe_int(m.get("losses_count")) or 0,
            "streak": safe_int(m.get("streak")) or 0,
        }
        name = row["mode"]
        if name in seen:
            # 同名模式只保留一行：优先有分数的，其次段位已定的，否则保留场次多的
            old = rows[seen[name]]
            def _score(r: dict) -> tuple:
                return (r["ranked"], r["tier_zh"] != "未定级", r["games"])
            if _score(row) > _score(old):
                rows[seen[name]] = row
            continue
        seen[name] = len(rows)
        rows.append(row)
    return {**_profile_head(prof), "modes": rows}


def build_mmr_card(prof: dict) -> dict:
    """隐藏分卡：各模式 ELO 汇总。"""
    modes = prof.get("modes") or {}
    rows = []
    for key in MMR_CARD_MODES:
        m = modes.get(key)
        if not isinstance(m, dict):
            continue
        rating = safe_int(m.get("rating"))
        games = safe_int(m.get("games_count")) or 0
        if rating is None and games == 0:
            continue
        rows.append(
            {
                "mode": mode_zh(key),
                "rating": rating if rating is not None else "-",
                "max_rating": safe_int(m.get("max_rating")) or "-",
                "max_7d": safe_int(m.get("max_rating_7d")) or "-",
                "max_1m": safe_int(m.get("max_rating_1m")) or "-",
                "games": games,
                "win_rate": _mode_win_rate(m),
            }
        )
    return {**_profile_head(prof), "modes": rows}


def build_matches_card(games: list, profile_id: Any, player_name: str) -> dict:
    """对局卡：最近对局列表。"""
    rows = []
    for g in games or []:
        p = pick_player(g.get("teams"), profile_id)
        if not p:
            continue  # 数据不全的局跳过
        diff = p.get("rating_diff")
        if diff is None:
            diff = p.get("mmr_diff")
        diff = safe_int(diff)
        result = p.get("result") or "unknown"
        rows.append(
            {
                "result": result,
                "result_zh": {"win": "胜利", "loss": "失败"}.get(result, "未知"),
                "civ": civ_zh(p.get("civilization")),
                "map": g.get("map") or "未知地图",
                "duration": format_duration(g.get("duration")),
                "mode": mode_zh(g.get("leaderboard") or g.get("kind") or ""),
                "diff": diff,
                "diff_text": f"{diff:+d}" if diff is not None else "-",
                "time_ago": format_time_ago(g.get("started_at")),
                "ongoing": bool(g.get("ongoing")),
            }
        )
    return {"name": player_name, "matches": rows, "count": len(rows)}


def build_civs_card(stats: dict, leaderboard: str, max_rows: int = 25, rank_filter: str | None = None) -> dict:
    """文明胜率卡。max_rows<=0 表示显示全部。rank_filter 为请求时的段位过滤（整段）。"""
    rows = stats.get("data") or []
    rows = [r for r in rows if isinstance(r, dict) and r.get("civilization")]
    rows.sort(key=lambda r: float(r.get("win_rate") or 0), reverse=True)
    if max_rows and max_rows > 0:
        rows = rows[:max_rows]
    items = []
    for i, r in enumerate(rows, 1):
        wr = r.get("win_rate")
        pr = r.get("pick_rate")
        items.append(
            {
                "rank": i,
                "civ": civ_zh(r.get("civilization")),
                "win_rate": round(float(wr), 1) if isinstance(wr, (int, float)) else None,
                "pick_rate": round(float(pr), 1) if isinstance(pr, (int, float)) else None,
                "games": safe_int(r.get("games_count")) or 0,
            }
        )
    return {
        "leaderboard": mode_zh(leaderboard),
        "patch": stats.get("patch") or "-",
        "rank_filter": rank_level_to_zh(rank_filter) if rank_filter else "",
        "civs": items,
        "total": len(rows),
    }


def build_match_card(game: dict, highlight_pid: Any, queried_name: str) -> dict:
    """单局详情卡：对阵双方玩家名单、文明、分数变化。"""
    hid = safe_int(highlight_pid)
    teams_out = []
    for ti, team in enumerate(game.get("teams") or [], 1):
        players = []
        team_result = "unknown"
        for entry in team or []:
            p = (entry or {}).get("player") or {}
            if not p:
                continue
            if p.get("result") in ("win", "loss"):
                team_result = p["result"]
            rating = safe_int(p.get("rating"))
            if rating is None:
                rating = safe_int(p.get("mmr"))
            diff = p.get("rating_diff")
            if diff is None:
                diff = p.get("mmr_diff")
            diff = safe_int(diff)
            players.append(
                {
                    "name": p.get("name") or "未知",
                    "flag": country_flag(p.get("country")),
                    "civ": civ_zh(p.get("civilization")),
                    "rating": rating if rating is not None else "-",
                    "diff": diff,
                    "diff_text": f"{diff:+d}" if diff is not None else "-",
                    "result": p.get("result") or "unknown",
                    "is_self": safe_int(p.get("profile_id")) == hid,
                }
            )
        teams_out.append(
            {
                "index": ti,
                "result": team_result,
                "result_zh": {"win": "胜利", "loss": "失败"}.get(team_result, "未知"),
                "players": players,
            }
        )
    return {
        "queried_name": queried_name,
        "map": game.get("map") or "未知地图",
        "mode": mode_zh(game.get("leaderboard") or game.get("kind") or ""),
        "duration": format_duration(game.get("duration")),
        "time_ago": format_time_ago(game.get("started_at")),
        "patch": game.get("patch") or "-",
        "season": game.get("season") or "-",
        "avg_rating": safe_int(game.get("average_rating")) or "-",
        "ongoing": bool(game.get("ongoing")),
        "teams": teams_out,
    }


# ---------- 错误消息 ----------


def err_msg(e: Exception) -> str:
    if isinstance(e, QueryTooShort):
        return "玩家名至少需要 3 个字符，请加长后重试。"
    if isinstance(e, RateLimitError):
        return "AoE4World 接口限流中，请稍候几秒再试。"
    if isinstance(e, ApiTimeout):
        return "查询超时，AoE4World 接口响应较慢，请稍后重试。"
    if isinstance(e, ApiServerError):
        return "AoE4World 接口暂时不可用，请稍后再试。"
    if isinstance(e, ApiError):
        return f"查询失败：{e}"
    return f"插件内部错误：{type(e).__name__}: {e}"
