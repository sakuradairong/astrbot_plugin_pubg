from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import aiohttp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except ImportError:
    PIL_OK = False

if TYPE_CHECKING:
    from PIL import ImageDraw as IDraw
    from PIL.ImageFont import FreeTypeFont, ImageFont as FontClass

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

_BAN_STATUS_LABELS = {
    "PermanentBan": "永久封禁",
    "TemporaryBan": "临时封禁",
    "Banned":       "封禁中",
}

VALID_PLATFORMS = frozenset({"steam", "psn", "xbox", "kakao"})

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

API_TIMEOUT         = 10
API_MAX_RETRY       = 2
MATCH_LIMIT         = 7
MATCH_CONCURRENCY   = 3
QUERY_COOLDOWN_SEC  = 8

_font_cache: dict[tuple[int, bool], object] = {}


@dataclass
class PlayerInfo:
    id: str
    name: str
    platform: str
    ban_type: Optional[str]


@dataclass(frozen=True)
class ModeStatRow:
    label: str
    rounds: int
    wins: int
    top10: int
    kills: int
    assists: int
    deaths: Optional[int]
    kd: Optional[float]
    win_pct: float
    top10_pct: float
    avg_dmg: float
    avg_min: float

    @property
    def kd_text(self) -> str:
        return f"{self.kd:.2f}" if self.kd is not None else "—"


def _calc_kd(kills: int | float, deaths: int | float) -> float:
    """K/D = kills / deaths；deaths 为 0 时回退为击杀数。"""
    kills_f = float(kills or 0)
    deaths_f = float(deaths or 0)
    if deaths_f <= 0:
        return kills_f
    return kills_f / deaths_f


def _normalize_ban_type(raw_ban: Optional[str]) -> Optional[str]:
    if raw_ban and raw_ban not in ("Innocent", "NotBanned"):
        return raw_ban
    return None


def _mode_stat_rows(gm_stats: dict) -> list[ModeStatRow]:
    rows: list[ModeStatRow] = []
    for mode_key, mode_label in _MODE_LABELS.items():
        s = gm_stats.get(mode_key, {})
        rounds = s.get("roundsPlayed", 0) or 0
        if rounds == 0:
            continue
        wins = s.get("wins", 0) or 0
        top10 = s.get("top10s", 0) or 0
        kills = s.get("kills", 0) or 0
        assists = s.get("assists", 0) or 0
        deaths = s.get("deaths")
        damage = float(s.get("damageDealt", 0.0) or 0.0)
        survived = float(s.get("timeSurvived", 0.0) or 0.0)
        rows.append(
            ModeStatRow(
                label=mode_label,
                rounds=rounds,
                wins=wins,
                top10=top10,
                kills=kills,
                assists=assists,
                deaths=deaths,
                kd=_calc_kd(kills, deaths) if deaths is not None else None,
                win_pct=wins / rounds * 100,
                top10_pct=top10 / rounds * 100,
                avg_dmg=damage / rounds,
                avg_min=survived / rounds / 60,
            )
        )
    return rows


def _load_font(size: int, bold: bool = False) -> FreeTypeFont | FontClass:
    cache_key = (size, bold)
    cached = _font_cache.get(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    font = _discover_font(size, bold)
    _font_cache[cache_key] = font
    return font


def _discover_font(size: int, bold: bool = False) -> FreeTypeFont | FontClass:
    # 1. Scan local fonts/ directory for any .ttf/.ttc/.otf
    if os.path.isdir(FONT_DIR):
        for fname in sorted(os.listdir(FONT_DIR)):
            if fname.lower().endswith((".ttf", ".ttc", ".otf")):
                path = os.path.join(FONT_DIR, fname)
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue

    # 2. Hardcoded well-known paths
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf" if bold else "C:/Windows/Fonts/simsun.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSerifCJK-Bold.ttc" if bold else "/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size, encoding="unic")
            except Exception:
                continue

    # 3. Dynamic fontconfig lookup (Linux)
    try:
        for pattern in (
            "Noto Sans CJK SC:lang=zh",
            "Noto Sans CJK:lang=zh",
            "WenQuanYi Micro Hei:lang=zh",
            "WenQuanYi Zen Hei:lang=zh",
            "Droid Sans Fallback:lang=zh",
            "sans:lang=zh",
        ):
            result = subprocess.run(
                ["fc-match", "-f", "%{file}", pattern],
                capture_output=True, text=True, timeout=5,
            )
            path = result.stdout.strip()
            if path:
                try:
                    return ImageFont.truetype(path, size, encoding="unic")
                except Exception:
                    continue
        result = subprocess.run(
            ["fc-list", ":lang=zh", "-f", "%{file}\n"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                path = line.strip()
                if path:
                    try:
                        return ImageFont.truetype(path, size, encoding="unic")
                    except Exception:
                        continue
    except Exception:
        pass

    return ImageFont.load_default()


def _text_w(draw: IDraw.ImageDraw, text: str, font: FreeTypeFont | FontClass) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _truncate_text(draw: IDraw.ImageDraw, text: str, font: FreeTypeFont | FontClass, max_px: int) -> str:
    if _text_w(draw, text, font) <= max_px:
        return text
    while text and _text_w(draw, text + "…", font) > max_px:
        text = text[:-1]
    return text + "…"


def _render_image(
    name: str,
    platform: str,
    gm_stats: dict,
    player_id: str,
    match_results: list,
    ban_type: Optional[str] = None,
) -> str:
    mode_rows = _mode_stat_rows(gm_stats)

    match_rows = _match_rows(match_results, player_id)

    is_banned = ban_type is not None
    ban_label = _BAN_STATUS_LABELS.get(ban_type, ban_type) if ban_type else None

    H_HEADER    = 90
    H_BAN_BAR   = 32 if is_banned else 0
    H_SEC_TITLE = 44
    H_MODE_ROW  = 110
    H_EMPTY_ROW = 40
    H_MATCH_ROW = 80
    H_FOOTER    = 36

    mode_block_h = (
        len(mode_rows) * (H_MODE_ROW + 10) if mode_rows else H_EMPTY_ROW
    )
    total_h = (
        PAD + H_HEADER + PAD + H_BAN_BAR
        + H_SEC_TITLE + mode_block_h
        + (PAD // 2 + H_SEC_TITLE + len(match_rows) * (H_MATCH_ROW + 8) if match_rows else 0)
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
    name_max_w = COL_W - 36 - _text_w(draw, "PUBG 战绩", f_med) - 28
    draw.text((PAD + 18, y + 14), _truncate_text(draw, name, f_big, name_max_w), font=f_big, fill=ACCENT)
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

    if not mode_rows:
        draw.text((PAD + 16, y + 8), "暂无战绩数据", font=f_norm, fill=GRAY)
        y += H_EMPTY_ROW
    else:
        for row in mode_rows:
            draw.rectangle([PAD, y, W - PAD, y + H_MODE_ROW], fill=CARD)
            draw.rectangle([PAD, y, PAD + 8, y + H_MODE_ROW], fill=ACCENT2)
            draw.text((PAD + 16, y + 10), row.label, font=f_med, fill=WHITE)

            col1_x = PAD + 16
            col2_x = PAD + 16 + (COL_W // 3)
            col3_x = PAD + 16 + (COL_W // 3) * 2
            row2_y = y + 42
            row3_y = y + 72

            draw.text((col1_x, row2_y), f"场次  {row.rounds}", font=f_norm, fill=GRAY)
            draw.text((col2_x, row2_y), f"胜场  {row.wins} ({row.win_pct:.1f}%)", font=f_norm, fill=WIN_CLR)
            draw.text((col3_x, row2_y), f"Top10  {row.top10} ({row.top10_pct:.1f}%)", font=f_norm, fill=GRAY)
            draw.text((col1_x, row3_y), f"K/D  {row.kd_text}", font=f_norm, fill=ACCENT)
            draw.text((col2_x, row3_y), f"场均伤害  {row.avg_dmg:.0f}", font=f_norm, fill=WHITE)
            draw.text((col3_x, row3_y), f"场均存活  {row.avg_min:.1f}min", font=f_norm, fill=GRAY)

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
    try:
        img.save(buf.name, format="PNG")
    except Exception:
        buf.close()
        os.remove(buf.name)
        raise
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
        ban_label = _BAN_STATUS_LABELS.get(ban_type, ban_type)
        lines += ["", f"⚠ 账号状态: {ban_label}", ""]
    else:
        lines += ["", "✓ 账号状态: 正常", ""]

    lines += ["", "◆ 终身战绩", bar]

    mode_rows = _mode_stat_rows(gm_stats)
    if not mode_rows:
        lines += ["  暂无战绩数据", ""]
    else:
        for row in mode_rows:
            deaths = row.deaths if row.deaths is not None else "—"
            lines += [
                f"▌{row.label}",
                f"  场次 {row.rounds}  胜场 {row.wins}({row.win_pct:.1f}%)  Top10 {row.top10}({row.top10_pct:.1f}%)",
                f"  击杀 {row.kills}  死亡 {deaths}  助攻 {row.assists}  K/D {row.kd_text}",
                f"  场均伤害 {row.avg_dmg:.0f}  场均存活 {row.avg_min:.1f}min",
                "",
            ]

    match_rows = _match_rows(match_results, player_id)
    if match_rows:
        lines += ["◆ 最近对局", bar]
        for idx, e in enumerate(match_rows, 1):
            tag = "吃鸡" if e["place"] == 1 else f"#{e['place']}"
            lines += [
                f"[{idx}] {e['date']}  {e['mode']}  {e['map']}",
                f"  排名 {tag}  击杀 {e['kills']}  伤害 {e['damage']:.0f}",
                f"  助攻 {e['assists']}  爆头 {e['headshots']}  最远 {e['longest']:.0f}m  存活 {e['survive']:.1f}min",
                "",
            ]

    return "\n".join(lines).rstrip()


def _match_rows(match_results: list, player_id: str) -> list[dict]:
    rows = []
    for match_data in match_results:
        entry = _parse_match(match_data, player_id)
        if entry is not None:
            rows.append(entry)
    return rows


def _parse_match(match_data: dict, player_id: str) -> Optional[dict]:
    try:
        attrs = match_data["data"]["attributes"]
        if not isinstance(attrs, dict):
            return None
        map_name   = _MAP_NAMES.get(attrs.get("mapName", ""), attrs.get("mapName", ""))
        mode_label = _MODE_LABELS.get(attrs.get("gameMode", ""), attrs.get("gameMode", ""))
        date_str   = _fmt_date(attrs.get("createdAt") or "")

        for item in match_data.get("included", []):
            if not isinstance(item, dict) or item.get("type") != "participant":
                continue
            participant = item.get("attributes")
            stats = participant.get("stats") if isinstance(participant, dict) else None
            if not isinstance(stats, dict) or stats.get("playerId") != player_id:
                continue
            return {
                "date": date_str, "mode": mode_label, "map": map_name,
                "place":     stats.get("winPlace", 0),
                "kills":     stats.get("kills", 0),
                "assists":   stats.get("assists", 0),
                "damage":    float(stats.get("damageDealt") or 0.0),
                "headshots": stats.get("headshotKills", 0),
                "longest":   float(stats.get("longestKill") or 0.0),
                "survive":   float(stats.get("timeSurvived") or 0.0) / 60,
            }
    except (KeyError, TypeError, ValueError):
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
    request_timeout: int = API_TIMEOUT,
) -> dict:
    # 参数清洗：仅保留 str / int / float 类型的值，过滤 event 等非法对象
    if params is not None:
        params = {
            k: v for k, v in params.items()
            if isinstance(v, (str, int, float))
        }
    for attempt in range(retry + 1):
        try:
            async with session.get(
                url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=request_timeout),
            ) as resp:
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
    "sakuradairong",
    "PUBG 玩家战绩查询插件",
    "1.5.0",
    "https://github.com/sakuradairong/astrbot_plugin_pubg",
)
class PubgPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config
        self.api_base = "https://api.pubg.com/shards"
        self._cooldown_until: dict[str, float] = {}
        logger.info(f"[pubg_plugin] 插件已加载，Pillow={'可用' if PIL_OK else '不可用（将回退为文字输出）'}")
        if not PIL_OK:
            logger.warning("[pubg_plugin] 未安装 Pillow，将回退为文字输出。pip install Pillow")

    def _get_api_key(self) -> str:
        if self.config is None:
            return ""
        return self.config.get("api_key", "")

    def _get_platform(self) -> str:
        if self.config is None:
            return "steam"
        platform = str(self.config.get("default_platform", "steam")).lower()
        return platform if platform in VALID_PLATFORMS else "steam"

    def _check_cooldown(self, sender_id: str) -> Optional[float]:
        """若仍在冷却中，返回剩余秒数；否则登记本次查询并返回 None。"""
        now = time.monotonic()
        until = self._cooldown_until.get(sender_id, 0.0)
        if until > now:
            return until - now
        self._cooldown_until[sender_id] = now + QUERY_COOLDOWN_SEC
        # 清理过期条目，避免无限增长
        if len(self._cooldown_until) > 256:
            self._cooldown_until = {
                k: v for k, v in self._cooldown_until.items() if v > now
            }
        return None

    @filter.command("pubg", alias={"查ID", "查pubg"})
    async def query_stats(self, event: AstrMessageEvent):
        logger.info(f"[pubg_plugin] query_stats 被调用: message={event.message_str!r}")
        parts = event.message_str.strip().split()
        if len(parts) < 2:
            yield event.plain_result(
                "用法: /pubg <玩家名> [平台]\n"
                f"平台可选: steam | psn | xbox | kakao（默认 {self._get_platform()}）\n"
                "示例: /pubg shroud steam"
            )
            return

        player_name = parts[1]
        platform = parts[2].lower() if len(parts) > 2 else self._get_platform()
        logger.info(f"[pubg_plugin] 开始查询: player={player_name}, platform={platform}")

        if platform not in VALID_PLATFORMS:
            yield event.plain_result(
                f"不支持的平台: {platform}\n可选: {', '.join(sorted(VALID_PLATFORMS))}"
            )
            return

        api_key = self._get_api_key()
        if not api_key:
            yield event.plain_result(
                "未配置 PUBG API Key，请在插件配置中填写 api_key。\n"
                "申请地址: https://developer.pubg.com/"
            )
            return

        sender_id = ""
        try:
            sender_id = str(event.get_sender_id())
        except Exception:
            sender_id = event.get_session_id() if hasattr(event, "get_session_id") else "unknown"

        remaining = self._check_cooldown(sender_id)
        if remaining is not None:
            yield event.plain_result(f"查询过于频繁，请 {remaining:.0f} 秒后再试。")
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

    @filter.llm_tool(name="pubg_query")
    async def pubg_query_tool(
        self,
        event: AstrMessageEvent,
        player_name: str,
        platform: str = "",
    ) -> str:
        """查询 PUBG 玩家终身战绩和最近对局数据，包括 K/D、胜率、场均伤害、场均存活时间。

        Args:
            player_name(string): PUBG 玩家游戏昵称，必须精确匹配
            platform(string): 游戏平台，可选 steam、psn、xbox、kakao，省略时使用插件配置
        """
        if not isinstance(player_name, str) or not player_name.strip():
            return "请提供玩家昵称。用法: /pubg <玩家名> [平台]"
        platform = platform.strip().lower() if isinstance(platform, str) else ""
        platform = platform or self._get_platform()
        if platform not in VALID_PLATFORMS:
            return f"不支持的平台: {platform}。可选: {', '.join(sorted(VALID_PLATFORMS))}"

        api_key = self._get_api_key()
        if not api_key:
            return "未配置 PUBG API Key，请在插件配置中填写 api_key。"

        try:
            info, stats, matches = await self._fetch_all(player_name.strip(), platform, api_key)
            return _render_text(info.name, info.platform, stats, info.id, matches, info.ban_type)
        except PubgApiError as e:
            return str(e)
        except Exception as e:
            logger.error(f"[pubg_plugin] LLM 工具查询异常: {e}")
            return "查询时发生未知错误，请稍后重试。"

    async def _fetch_all(self, player_name: str, platform: str, api_key: str):
        if not isinstance(player_name, str):
            logger.warning(f"[pubg_plugin] _fetch_all: player_name 类型异常 ({type(player_name).__name__}), 强制转换")
            player_name = str(player_name)
        if not isinstance(platform, str):
            platform = str(platform)
        platform = platform.lower()
        if platform not in VALID_PLATFORMS:
            raise PubgApiError(f"不支持的平台: {platform}")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/vnd.api+json",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
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
            ban_type = _normalize_ban_type(player["attributes"].get("banType"))

            logger.info(f"[pubg_plugin] 玩家 {player_name_real} banType={ban_type}")

            match_ids = [
                m["id"]
                for m in player.get("relationships", {})
                                .get("matches", {})
                                .get("data", [])
            ][:MATCH_LIMIT]
            logger.info(f"[pubg_plugin] 获取该玩家的 {len(match_ids)} 场对局详情")

            lifetime_task = asyncio.create_task(
                _api_request(
                    session,
                    f"{self.api_base}/{platform}/players/{player_id}/seasons/lifetime",
                    retry=API_MAX_RETRY,
                )
            )
            try:
                match_results_raw = await self._fetch_matches(session, platform, match_ids)
            except BaseException:
                lifetime_task.cancel()
                await asyncio.gather(lifetime_task, return_exceptions=True)
                raise
            try:
                lifetime_data = await lifetime_task
            except PubgApiError:
                raise
            except Exception as e:
                raise PubgApiError(f"获取生涯数据失败: {e}") from e

        match_results = [
            r for r in match_results_raw
            if not isinstance(r, Exception)
        ]
        if match_results_raw and not match_results:
            logger.warning("[pubg_plugin] 所有对局详情获取失败，仅显示生涯数据")

        gm_stats = lifetime_data["data"]["attributes"]["gameModeStats"]
        player_info = PlayerInfo(
            id=player_id,
            name=player_name_real,
            platform=platform,
            ban_type=ban_type,
        )
        return player_info, gm_stats, match_results

    async def _fetch_matches(
        self,
        session: aiohttp.ClientSession,
        platform: str,
        match_ids: list[str],
    ) -> list:
        if not match_ids:
            return []
        sem = asyncio.Semaphore(MATCH_CONCURRENCY)

        async def _one(mid: str):
            async with sem:
                try:
                    return await _api_request(
                        session,
                        f"{self.api_base}/{platform}/matches/{mid}",
                        retry=API_MAX_RETRY,
                    )
                except Exception as e:
                    return e

        return list(await asyncio.gather(*[_one(mid) for mid in match_ids]))


class PubgApiError(Exception):
    pass
