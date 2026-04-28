import asyncio
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except ImportError:
    PIL_OK = False

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

BAN_STATUS_LABELS = {
    "PermanentBan": "永久封禁",
    "TemporaryBan": "临时封禁",
    "Banned":       "封禁中",
}

# ── 颜色主题 ──
BG       = (15,  20,  30)
CARD     = (25,  32,  48)
ACCENT   = (255, 180,  30)
ACCENT2  = (80, 160, 255)
WHITE    = (240, 240, 240)
GRAY     = (140, 150, 170)
WIN_CLR  = (80, 220, 120)
SEP      = (40,  50,  70)
BAN_CLR  = (255,  70,  70)
WARN_CLR = (255, 200,  50)

PAD      = 32
COL_W    = 560
FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")

API_TIMEOUT    = 15
API_MAX_RETRY  = 2
MATCH_LIMIT    = 7


@dataclass
class PlayerInfo:
    id: str
    name: str
    platform: str
    ban_type: Optional[str]


def _load_font(size: int, bold: bool = False) -> "ImageFont.FreeTypeFont | ImageFont.ImageFont":
    candidates = [
        os.path.join(FONT_DIR, "NotoSansSC-Bold.ttf" if bold else "NotoSansSC-Regular.ttf"),
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf" if bold else "C:/Windows/Fonts/simsun.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _text_w(draw: "ImageDraw.ImageDraw", text: str, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _render_image(
    name: str,
    platform: str,
    gm_stats: dict,
    player_id: str,
    match_results: list,
    ban_type: Optional[str] = None,
) -> str:
    mode_rows = []
    for mode_key, mode_label in _MODE_LABELS.items():
        s = gm_stats.get(mode_key, {})
        if s.get("roundsPlayed", 0) == 0:
            continue
        mode_rows.append((mode_key, mode_label, s))

    match_rows = []
    for match_data in match_results:
        entry = _parse_match(match_data, player_id)
        if entry:
            match_rows.append(entry)

    is_banned = ban_type is not None
    ban_label = BAN_STATUS_LABELS.get(ban_type, ban_type) if ban_type else None

    H_HEADER    = 90
    H_BAN_BAR   = 32 if is_banned else 0
    H_SEC_TITLE = 44
    H_MODE_ROW  = 110
    H_MATCH_ROW = 80
    H_FOOTER    = 36

    total_h = (
        PAD + H_HEADER + PAD + H_BAN_BAR
        + H_SEC_TITLE + len(mode_rows) * (H_MODE_ROW + 10)
        + (PAD + H_SEC_TITLE + len(match_rows) * (H_MATCH_ROW + 8) if match_rows else 0)
        + H_FOOTER + PAD
    )

    W = COL_W + PAD * 2
    img = Image.new("RGB", (W, total_h), BG)
    draw = ImageDraw.Draw(img)

    f_big   = _load_font(28, bold=True)
    f_med   = _load_font(20, bold=True)
    f_norm  = _load_font(18)
    f_small = _load_font(15)

    y = PAD

    draw.rectangle([PAD, y, W - PAD, y + H_HEADER - 10], fill=CARD, outline=ACCENT, width=2)
    draw.text((PAD + 18, y + 14), name, font=f_big, fill=ACCENT)
    draw.text((PAD + 18, y + 50), f"[{platform.upper()}]", font=f_norm, fill=GRAY)
    draw.text((W - PAD - 18 - _text_w(draw, "PUBG 战绩", f_med), y + 28), "PUBG 战绩", font=f_med, fill=ACCENT2)
    y += H_HEADER + PAD // 2

    if is_banned:
        perm = ban_type in ("PermanentBan", "Banned")
        ban_color = BAN_CLR if perm else WARN_CLR
        draw.rectangle([PAD, y, W - PAD, y + H_BAN_BAR], fill=(40, 20, 20) if perm else (40, 35, 10))
        draw.rectangle([PAD, y, PAD + 8, y + H_BAN_BAR], fill=ban_color)
        draw.text((PAD + 18, y + 4), f"⚠ 账号状态: {ban_label}", font=f_norm, fill=ban_color)
        y += H_BAN_BAR

    draw.text((PAD, y), "◆ 终身战绩", font=f_med, fill=ACCENT)
    draw.line([(PAD, y + 30), (W - PAD, y + 30)], fill=ACCENT, width=1)
    y += H_SEC_TITLE

    for _, mode_label, s in mode_rows:
        rounds    = s.get("roundsPlayed", 0)
        wins      = s.get("wins", 0)
        top10     = s.get("top10s", 0)
        kills     = s.get("kills", 0)
        assists   = s.get("assists", 0)
        damage    = s.get("damageDealt", 0.0)
        headshots = s.get("headshotKills", 0)
        longest   = s.get("longestKill", 0.0)
        survived  = s.get("timeSurvived", 0.0)

        kd        = kills / rounds if rounds else 0
        win_pct   = wins  / rounds * 100
        top10_pct = top10 / rounds * 100
        avg_dmg   = damage / rounds
        avg_min   = survived / rounds / 60

        draw.rectangle([PAD, y, W - PAD, y + H_MODE_ROW], fill=CARD)
        draw.rectangle([PAD, y, PAD + 8, y + H_MODE_ROW], fill=ACCENT2)
        draw.text((PAD + 16, y + 10), mode_label, font=f_med, fill=WHITE)

        col1_x = PAD + 16
        col2_x = PAD + 16 + (COL_W // 3)
        col3_x = PAD + 16 + (COL_W // 3) * 2
        row2_y = y + 42
        row3_y = y + 72

        draw.text((col1_x, row2_y), f"场次  {rounds}", font=f_norm, fill=GRAY)
        draw.text((col2_x, row2_y), f"胜场  {wins} ({win_pct:.1f}%)", font=f_norm, fill=WIN_CLR)
        draw.text((col3_x, row2_y), f"Top10  {top10} ({top10_pct:.1f}%)", font=f_norm, fill=GRAY)
        draw.text((col1_x, row3_y), f"K/D  {kd:.2f}", font=f_norm, fill=ACCENT)
        draw.text((col2_x, row3_y), f"场均伤害  {avg_dmg:.0f}", font=f_norm, fill=WHITE)
        draw.text((col3_x, row3_y), f"场均存活  {avg_min:.1f}min", font=f_norm, fill=GRAY)

        y += H_MODE_ROW + 10

    if match_rows:
        y += PAD // 2
        draw.text((PAD, y), "◆ 最近对局", font=f_med, fill=ACCENT)
        draw.line([(PAD, y + 30), (W - PAD, y + 30)], fill=ACCENT, width=1)
        y += H_SEC_TITLE

        for idx, entry in enumerate(match_rows, 1):
            is_win = entry["place"] == 1
            card_color = (30, 55, 35) if is_win else CARD
            draw.rectangle([PAD, y, W - PAD, y + H_MATCH_ROW], fill=card_color)
            draw.rectangle([PAD, y, PAD + 8, y + H_MATCH_ROW], fill=(WIN_CLR if is_win else ACCENT2))

            rank_text = "#1" if is_win else f"#{entry['place']}"
            rank_color = WIN_CLR if is_win else WHITE

            header_line = f"[{idx}]  {entry['date']}  {entry['mode']}  {entry['map']}"
            draw.text((PAD + 16, y + 8), header_line, font=f_small, fill=GRAY)
            draw.text((W - PAD - 18 - _text_w(draw, rank_text, f_med), y + 6), rank_text, font=f_med, fill=rank_color)

            stats_line = (
                f"击杀 {entry['kills']}   伤害 {entry['damage']:.0f}   "
                f"助攻 {entry['assists']}   爆头 {entry['headshots']}   "
                f"最远 {entry['longest']:.0f}m   存活 {entry['survive']:.1f}min"
            )
            draw.text((PAD + 16, y + 36), stats_line, font=f_norm, fill=WHITE)

            y += H_MATCH_ROW + 8

    y += PAD // 2
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    draw.text((PAD, y), f"数据来源: api.pubg.com  ·  {ts}", font=f_small, fill=SEP)

    buf = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(buf.name, format="PNG")
    buf.close()
    return buf.name


def _render_text(
    name: str,
    platform: str,
    gm_stats: dict,
    player_id: str,
    match_results: list,
    ban_type: Optional[str] = None,
) -> str:
    W = 38
    bar = "─" * W
    lines = [
        "┌" + "─" * W + "┐",
        "│" + f"  {name}  [{platform.upper()}]".center(W) + "│",
        "└" + "─" * W + "┘",
    ]

    if ban_type:
        ban_label = BAN_STATUS_LABELS.get(ban_type, ban_type)
        lines += ["", f"⚠ 账号状态: {ban_label}", ""]
    else:
        lines += ["", f"✓ 账号状态: 正常", ""]

    lines += ["", "◆ 终身战绩", bar]

    has_any = False
    for mode_key, mode_label in _MODE_LABELS.items():
        s = gm_stats.get(mode_key, {})
        rounds = s.get("roundsPlayed", 0)
        if rounds == 0:
            continue
        has_any = True
        wins = s.get("wins", 0)
        top10 = s.get("top10s", 0)
        kills = s.get("kills", 0)
        assists = s.get("assists", 0)
        damage = s.get("damageDealt", 0.0)
        kd = kills / rounds if rounds else 0
        lines += [
            f"▌{mode_label}",
            f"  场次 {rounds}  胜场 {wins}({wins/rounds*100:.1f}%)  Top10 {top10}({top10/rounds*100:.1f}%)",
            f"  击杀 {kills}  助攻 {assists}  K/D {kd:.2f}",
            f"  场均伤害 {damage/rounds:.0f}  场均存活 {s.get('timeSurvived',0)/rounds/60:.1f}min",
            "",
        ]
    if not has_any:
        lines += ["  暂无战绩数据", ""]

    if match_results:
        lines += ["◆ 最近对局", bar]
        for idx, md in enumerate(match_results, 1):
            e = _parse_match(md, player_id)
            if not e:
                continue
            tag = "吃鸡" if e["place"] == 1 else f"#{e['place']}"
            lines += [
                f"[{idx}] {e['date']}  {e['mode']}  {e['map']}",
                f"  排名 {tag}  击杀 {e['kills']}  伤害 {e['damage']:.0f}",
                f"  助攻 {e['assists']}  爆头 {e['headshots']}  最远 {e['longest']:.0f}m  存活 {e['survive']:.1f}min",
                "",
            ]

    return "\n".join(lines).rstrip()


def _parse_match(match_data: dict, player_id: str) -> Optional[dict]:
    try:
        attrs = match_data["data"]["attributes"]
        map_name   = _MAP_NAMES.get(attrs.get("mapName", ""), attrs.get("mapName", ""))
        mode_label = _MODE_LABELS.get(attrs.get("gameMode", ""), attrs.get("gameMode", ""))
        date_str   = _fmt_date(attrs.get("createdAt", ""))

        for item in match_data.get("included", []):
            if item.get("type") != "participant":
                continue
            stats = item["attributes"]["stats"]
            if stats.get("playerId") != player_id:
                continue
            return {
                "date": date_str, "mode": mode_label, "map": map_name,
                "place":     stats.get("winPlace", 0),
                "kills":     stats.get("kills", 0),
                "assists":   stats.get("assists", 0),
                "damage":    stats.get("damageDealt", 0.0),
                "headshots": stats.get("headshotKills", 0),
                "longest":   stats.get("longestKill", 0.0),
                "survive":   stats.get("timeSurvived", 0.0) / 60,
            }
    except (KeyError, TypeError):
        pass
    return None


def _fmt_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%m-%d %H:%M")
    except Exception:
        return iso[:10]


async def _api_request(
    session: aiohttp.ClientSession,
    url: str,
    params: Optional[dict] = None,
    retry: int = 0,
) -> dict:
    for attempt in range(retry + 1):
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 404:
                    raise PubgApiError("资源不存在 (404)")
                if resp.status == 401:
                    raise PubgApiError("API Key 无效或已过期，请检查配置。")
                if resp.status == 403:
                    raise PubgApiError("无权限访问该资源，请检查 API Key 权限。")
                if resp.status == 429:
                    if attempt < retry:
                        wait = 2 ** (attempt + 1)
                        logger.warning(f"[pubg_plugin] 触发限流，{wait}s 后重试…")
                        await asyncio.sleep(wait)
                        continue
                    raise PubgApiError("请求过于频繁，请稍后再试。")
                if resp.status != 200:
                    raise PubgApiError(f"API 请求失败 (HTTP {resp.status})")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt < retry:
                wait = 2 ** (attempt + 1)
                logger.warning(f"[pubg_plugin] 请求异常 ({e})，{wait}s 后重试…")
                await asyncio.sleep(wait)
                continue
            raise PubgApiError(f"网络请求失败: {e}")
    raise PubgApiError("请求失败（已达最大重试次数）")


@register(
    "astrbot_plugin_pubg",
    "RainySY",
    "PUBG 玩家战绩查询插件",
    "1.3.0",
    "https://github.com/RainySY/astrbot_plugin_pubg",
)
class PubgPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config
        self.api_base = "https://api.pubg.com/shards"
        if not PIL_OK:
            logger.warning("[pubg_plugin] 未安装 Pillow，将回退为文字输出。pip install Pillow")

    def _get_api_key(self) -> str:
        if self.config is None:
            return ""
        return self.config.get("api_key", "")

    def _get_platform(self) -> str:
        if self.config is None:
            return "steam"
        return self.config.get("default_platform", "steam")

    @filter.command("pubg")
    @filter.command("查ID")
    @filter.command("查询")
    async def query_stats(self, event: AstrMessageEvent):
        parts = event.message_str.strip().split()
        if len(parts) < 2:
            yield event.plain_result(
                "用法: /pubg <玩家名> [平台]\n"
                "平台可选: steam(默认) | psn | xbox | kakao | stadia\n"
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

        tmp_path = None
        try:
            player_info, gm_stats, match_results = await self._fetch_all(player_name, platform, api_key)

            if PIL_OK:
                tmp_path = _render_image(
                    player_info.name, player_info.platform,
                    gm_stats, player_info.id, match_results,
                    ban_type=player_info.ban_type,
                )
                yield event.image_result(tmp_path)
            else:
                text = _render_text(
                    player_info.name, player_info.platform,
                    gm_stats, player_info.id, match_results,
                    ban_type=player_info.ban_type,
                )
                yield event.plain_result(text)

        except PubgApiError as e:
            yield event.plain_result(str(e))
        except Exception as e:
            logger.error(f"[pubg_plugin] 查询异常: {e}")
            yield event.plain_result("查询时发生未知错误，请稍后重试。")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    async def _fetch_all(self, player_name: str, platform: str, api_key: str):
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/vnd.api+json",
        }

        async with aiohttp.ClientSession(
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
        ) as session:
            player_data = await _api_request(
                session,
                f"{self.api_base}/{platform}/players",
                params={"filter[playerNames]": player_name},
                retry=API_MAX_RETRY,
            )

            if not player_data.get("data"):
                raise PubgApiError(f"找不到玩家: {player_name}（平台: {platform}）")

            player = player_data["data"][0]
            player_id = player["id"]
            player_name_real = player["attributes"]["name"]
            ban_type = player["attributes"].get("banType") or None

            logger.info(f"[pubg_plugin] 玩家 {player_name_real} banType={ban_type}")

            match_ids = [
                m["id"]
                for m in player.get("relationships", {})
                                .get("matches", {})
                                .get("data", [])
            ][:MATCH_LIMIT]

            lifetime_data, *match_results = await asyncio.gather(
                _api_request(
                    session,
                    f"{self.api_base}/{platform}/players/{player_id}/seasons/lifetime",
                    retry=API_MAX_RETRY,
                ),
                *[
                    _api_request(
                        session,
                        f"{self.api_base}/{platform}/matches/{mid}",
                        retry=API_MAX_RETRY,
                    )
                    for mid in match_ids
                ],
            )

        gm_stats = lifetime_data["data"]["attributes"]["gameModeStats"]
        player_info = PlayerInfo(
            id=player_id,
            name=player_name_real,
            platform=platform,
            ban_type=ban_type,
        )
        return player_info, gm_stats, match_results


class PubgApiError(Exception):
    pass
