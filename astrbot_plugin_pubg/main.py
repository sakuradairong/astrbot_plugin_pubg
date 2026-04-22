import asyncio
from datetime import datetime, timezone

import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

_MAP_NAMES = {
    "Baltic_Main":      "Erangel",
    "Desert_Main":      "Miramar",
    "Savage_Main":      "Sanhok",
    "DihorOtok_Main":   "Vikendi",
    "Summerland_Main":  "Karakin",
    "Tiger_Main":       "Taego",
    "Kiki_Main":        "Deston",
    "Neon_Main":        "Rondo",
    "Range_Main":       "Camp Jackal",
    "Chimera_Main":     "Paramo",
    "Heaven_Main":      "Haven",
}

_MODE_LABELS = {
    "squad-fpp": "四排FPP",
    "squad":     "四排TPP",
    "duo-fpp":   "双排FPP",
    "duo":       "双排TPP",
    "solo-fpp":  "单排FPP",
    "solo":      "单排TPP",
}


@register(
    "astrbot_plugin_pubg",
    "RainySY",
    "PUBG 玩家战绩查询插件",
    "1.1.0",
    "https://github.com/RainySY/astrbot_plugin_pubg",
)
class PubgPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config
        self.api_base = "https://api.pubg.com/shards"

    def _get_api_key(self) -> str:
        if self.config is None:
            return ""
        return self.config.get("api_key", "")

    def _get_platform(self) -> str:
        if self.config is None:
            return "steam"
        return self.config.get("default_platform", "steam")

    @filter.command("pubg")
    async def query_stats(self, event: AstrMessageEvent):
        """用法: /pubg <玩家名> [平台]  平台可选: steam psn xbox kakao"""
        parts = event.message_str.strip().split()
        if len(parts) < 2:
            yield event.plain_result(
                "用法: /pubg <玩家名> [平台]\n"
                "平台可选: steam(默认) | psn | xbox | kakao\n"
                "示例: /pubg shroud steam"
            )
            return

        player_name = parts[1]
        platform = parts[2].lower() if len(parts) > 2 else self._get_platform()

        valid_platforms = {"steam", "psn", "xbox", "kakao", "stadia"}
        if platform not in valid_platforms:
            yield event.plain_result(
                f"不支持的平台: {platform}\n可选: {', '.join(sorted(valid_platforms))}"
            )
            return

        api_key = self._get_api_key()
        if not api_key:
            yield event.plain_result(
                "未配置 PUBG API Key，请在插件配置中填写 api_key。\n"
                "申请地址: https://developer.pubg.com/"
            )
            return

        yield event.plain_result(f"正在查询 {player_name} 的战绩，请稍候…")

        try:
            result = await self._fetch_all(player_name, platform, api_key)
            yield event.plain_result(result)
        except PubgApiError as e:
            yield event.plain_result(str(e))
        except Exception as e:
            logger.error(f"[pubg_plugin] 查询异常: {e}")
            yield event.plain_result("查询时发生未知错误，请稍后重试。")

    # ------------------------------------------------------------------ #

    async def _fetch_all(self, player_name: str, platform: str, api_key: str) -> str:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/vnd.api+json",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            player_data = await _get(
                session,
                f"{self.api_base}/{platform}/players?filter[playerNames]={player_name}",
            )

            if not player_data.get("data"):
                raise PubgApiError(f"找不到玩家: {player_name}（平台: {platform}）")

            player = player_data["data"][0]
            player_id = player["id"]
            player_name_real = player["attributes"]["name"]
            match_ids = [
                m["id"]
                for m in player.get("relationships", {})
                                .get("matches", {})
                                .get("data", [])
            ][:7]

            lifetime_data, *match_results = await asyncio.gather(
                _get(session, f"{self.api_base}/{platform}/players/{player_id}/seasons/lifetime"),
                *[
                    _get(session, f"{self.api_base}/{platform}/matches/{mid}")
                    for mid in match_ids
                ],
            )

        gm_stats = lifetime_data["data"]["attributes"]["gameModeStats"]
        return _render(player_name_real, platform, gm_stats, player_id, match_results)


# ------------------------------------------------------------------ #
# Rendering
# ------------------------------------------------------------------ #

def _render(
    name: str,
    platform: str,
    gm_stats: dict,
    player_id: str,
    match_results: list,
) -> str:
    W = 38
    bar = "─" * W

    lines: list[str] = []

    # ── header ──
    title = f"  {name}  [{platform.upper()}]"
    lines += [
        "┌" + "─" * W + "┐",
        "│" + title.center(W) + "│",
        "└" + "─" * W + "┘",
        "",
    ]

    # ── lifetime stats ──
    lines.append("◆ 终身战绩")
    lines.append(bar)

    has_any = False
    for mode_key, mode_label in _MODE_LABELS.items():
        s = gm_stats.get(mode_key, {})
        rounds = s.get("roundsPlayed", 0)
        if rounds == 0:
            continue
        has_any = True

        wins        = s.get("wins", 0)
        top10       = s.get("top10s", 0)
        kills       = s.get("kills", 0)
        assists     = s.get("assists", 0)
        damage      = s.get("damageDealt", 0.0)
        headshots   = s.get("headshotKills", 0)
        longest     = s.get("longestKill", 0.0)
        survived    = s.get("timeSurvived", 0.0)

        kd          = kills / max(rounds - wins, 1)
        win_pct     = wins  / rounds * 100
        top10_pct   = top10 / rounds * 100
        avg_dmg     = damage   / rounds
        avg_min     = survived / rounds / 60

        lines += [
            f"▌{mode_label}",
            f"  场次 {rounds}  胜场 {wins}({win_pct:.1f}%)  Top10 {top10}({top10_pct:.1f}%)",
            f"  击杀 {kills}  助攻 {assists}  K/D {kd:.2f}",
            f"  爆头 {headshots}  最远 {longest:.0f}m",
            f"  场均伤害 {avg_dmg:.0f}  场均存活 {avg_min:.1f}min",
            "",
        ]

    if not has_any:
        lines.append("  暂无战绩数据")
        lines.append("")

    # ── recent matches ──
    if match_results:
        lines.append("◆ 最近对局")
        lines.append(bar)

        for idx, match_data in enumerate(match_results, 1):
            entry = _parse_match(match_data, player_id)
            if entry is None:
                continue

            result_tag = "🏆 吃鸡" if entry["place"] == 1 else f"#{entry['place']}"
            lines += [
                f"[{idx}] {entry['date']}  {entry['mode']}  {entry['map']}",
                f"  排名 {result_tag}  击杀 {entry['kills']}  伤害 {entry['damage']:.0f}",
                f"  助攻 {entry['assists']}  爆头 {entry['headshots']}  最远 {entry['longest']:.0f}m  存活 {entry['survive']:.1f}min",
                "",
            ]

    return "\n".join(lines).rstrip()


def _parse_match(match_data: dict, player_id: str) -> dict | None:
    try:
        attrs = match_data["data"]["attributes"]
        game_mode = attrs.get("gameMode", "")
        map_raw   = attrs.get("mapName", "")
        created   = attrs.get("createdAt", "")

        map_name  = _MAP_NAMES.get(map_raw, map_raw)
        mode_label = _MODE_LABELS.get(game_mode, game_mode)
        date_str  = _fmt_date(created)

        for item in match_data.get("included", []):
            if item.get("type") != "participant":
                continue
            s = item["attributes"]["stats"]
            if s.get("playerId") != player_id:
                continue
            return {
                "date":      date_str,
                "mode":      mode_label,
                "map":       map_name,
                "place":     s.get("winPlace", 0),
                "kills":     s.get("kills", 0),
                "assists":   s.get("assists", 0),
                "damage":    s.get("damageDealt", 0.0),
                "headshots": s.get("headshotKills", 0),
                "longest":   s.get("longestKill", 0.0),
                "survive":   s.get("timeSurvived", 0.0) / 60,
            }
    except (KeyError, TypeError):
        pass
    return None


def _fmt_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%m-%d %H:%M")
    except Exception:
        return iso[:10]


async def _get(session: aiohttp.ClientSession, url: str) -> dict:
    async with session.get(url) as resp:
        if resp.status == 404:
            raise PubgApiError("资源不存在 (404)")
        if resp.status == 401:
            raise PubgApiError("API Key 无效或已过期，请检查配置。")
        if resp.status == 429:
            raise PubgApiError("请求过于频繁，请稍后再试。")
        if resp.status != 200:
            raise PubgApiError(f"API 请求失败 (HTTP {resp.status})")
        return await resp.json(content_type=None)


class PubgApiError(Exception):
    pass
