import asyncio
import os
import tempfile
from datetime import datetime

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

# ── 颜色主题 ──────────────────────────────────────────────
BG       = (15,  20,  30)       # 深蓝黑背景
CARD     = (25,  32,  48)       # 卡片背景
ACCENT   = (255, 180,  30)      # 金色强调
ACCENT2  = (80, 160, 255)       # 蓝色强调
WHITE    = (240, 240, 240)
GRAY     = (140, 150, 170)
WIN_CLR  = (80, 220, 120)       # 吃鸡绿
SEP      = (40,  50,  70)       # 分隔线

PAD      = 32
COL_W    = 560
FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")


def _load_font(size: int, bold: bool = False) -> "ImageFont.FreeTypeFont | ImageFont.ImageFont":
    candidates = []
    if bold:
        candidates = [
            os.path.join(FONT_DIR, "NotoSansSC-Bold.ttf"),
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        ]
    else:
        candidates = [
            os.path.join(FONT_DIR, "NotoSansSC-Regular.ttf"),
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simsun.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
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
) -> str:
    # ── 先计算内容高度 ────────────────────────────────────
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

    # 估算高度
    H_HEADER   = 90
    H_SEC_TITLE = 44
    H_MODE_ROW  = 110   # 每个模式卡片高度
    H_MATCH_ROW = 80
    H_FOOTER    = 36

    total_h = (
        PAD
        + H_HEADER
        + PAD
        + H_SEC_TITLE
        + len(mode_rows) * (H_MODE_ROW + 10)
        + (PAD + H_SEC_TITLE + len(match_rows) * (H_MATCH_ROW + 8) if match_rows else 0)
        + H_FOOTER
        + PAD
    )

    W = COL_W + PAD * 2
    img = Image.new("RGB", (W, total_h), BG)
    draw = ImageDraw.Draw(img)

    f_big   = _load_font(28, bold=True)
    f_med   = _load_font(20, bold=True)
    f_norm  = _load_font(18)
    f_small = _load_font(15)

    y = PAD

    # ── 标题 ─────────────────────────────────────────────
    draw.rectangle([PAD, y, W - PAD, y + H_HEADER - 10], fill=CARD, outline=ACCENT, width=2)
    draw.text((PAD + 18, y + 14), name, font=f_big, fill=ACCENT)
    plat_text = f"[{platform.upper()}]"
    draw.text((PAD + 18, y + 50), plat_text, font=f_norm, fill=GRAY)
    draw.text((W - PAD - 18 - _text_w(draw, "PUBG 战绩", f_med), y + 28), "PUBG 战绩", font=f_med, fill=ACCENT2)
    y += H_HEADER + PAD // 2

    # ── 终身战绩 ──────────────────────────────────────────
    draw.text((PAD, y), "◆ 终身战绩", font=f_med, fill=ACCENT)
    draw.line([(PAD, y + 30), (W - PAD, y + 30)], fill=ACCENT, width=1)
    y += H_SEC_TITLE

    for _, mode_label, s in mode_rows:
        rounds   = s.get("roundsPlayed", 0)
        wins     = s.get("wins", 0)
        top10    = s.get("top10s", 0)
        kills    = s.get("kills", 0)
        assists  = s.get("assists", 0)
        damage   = s.get("damageDealt", 0.0)
        headshots= s.get("headshotKills", 0)
        longest  = s.get("longestKill", 0.0)
        survived = s.get("timeSurvived", 0.0)

        kd       = kills / rounds if rounds else 0
        win_pct  = wins  / rounds * 100
        top10_pct= top10 / rounds * 100
        avg_dmg  = damage / rounds
        avg_min  = survived / rounds / 60

        # 卡片背景
        draw.rectangle([PAD, y, W - PAD, y + H_MODE_ROW], fill=CARD)
        # 左侧模式标签
        draw.rectangle([PAD, y, PAD + 8, y + H_MODE_ROW], fill=ACCENT2)
        draw.text((PAD + 16, y + 10), mode_label, font=f_med, fill=WHITE)

        # 数据网格 (3列)
        col1_x = PAD + 16
        col2_x = PAD + 16 + (COL_W // 3)
        col3_x = PAD + 16 + (COL_W // 3) * 2
        row2_y = y + 42
        row3_y = y + 72

        # 行1
        draw.text((col1_x, row2_y), f"场次  {rounds}", font=f_norm, fill=GRAY)
        draw.text((col2_x, row2_y), f"胜场  {wins} ({win_pct:.1f}%)", font=f_norm, fill=WIN_CLR)
        draw.text((col3_x, row2_y), f"Top10  {top10} ({top10_pct:.1f}%)", font=f_norm, fill=GRAY)
        # 行2
        draw.text((col1_x, row3_y), f"K/D  {kd:.2f}", font=f_norm, fill=ACCENT)
        draw.text((col2_x, row3_y), f"场均伤害  {avg_dmg:.0f}", font=f_norm, fill=WHITE)
        draw.text((col3_x, row3_y), f"场均存活  {avg_min:.1f}min", font=f_norm, fill=GRAY)

        y += H_MODE_ROW + 10

    # ── 最近对局 ──────────────────────────────────────────
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

            rank_text = "🏆 #1" if is_win else f"#{entry['place']}"
            rank_color = WIN_CLR if is_win else WHITE

            # 行1: 序号 日期 模式 地图
            header_line = f"[{idx}]  {entry['date']}  {entry['mode']}  {entry['map']}"
            draw.text((PAD + 16, y + 8), header_line, font=f_small, fill=GRAY)
            draw.text((W - PAD - 18 - _text_w(draw, rank_text, f_med), y + 6), rank_text, font=f_med, fill=rank_color)

            # 行2: 击杀 伤害 助攻 爆头 最远 存活
            stats_line = (
                f"击杀 {entry['kills']}   伤害 {entry['damage']:.0f}   "
                f"助攻 {entry['assists']}   爆头 {entry['headshots']}   "
                f"最远 {entry['longest']:.0f}m   存活 {entry['survive']:.1f}min"
            )
            draw.text((PAD + 16, y + 36), stats_line, font=f_norm, fill=WHITE)

            y += H_MATCH_ROW + 8

    # ── 底部 ──────────────────────────────────────────────
    y += PAD // 2
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    draw.text((PAD, y), f"数据来源: api.pubg.com  ·  {ts}", font=f_small, fill=SEP)

    buf = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(buf.name, format="PNG")
    buf.close()
    return buf.name


@register(
    "astrbot_plugin_pubg",
    "RainySY",
    "PUBG 玩家战绩查询插件",
    "1.2.0",
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
    async def query_stats(self, event: AstrMessageEvent):
        """用法: /pubg <玩家名> [平台]  平台可选: steam psn xbox kakao"""
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
            name_real, platform_real, gm_stats, player_id, match_results = \
                await self._fetch_all(player_name, platform, api_key)

            if PIL_OK:
                tmp_path = _render_image(name_real, platform_real, gm_stats, player_id, match_results)
                yield event.image_result(tmp_path)
            else:
                text = _render_text(name_real, platform_real, gm_stats, player_id, match_results)
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

        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as session:
            player_data = await _get(
                session,
                f"{self.api_base}/{platform}/players",
                params={"filter[playerNames]": player_name},
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
                *[_get(session, f"{self.api_base}/{platform}/matches/{mid}") for mid in match_ids],
            )

        gm_stats = lifetime_data["data"]["attributes"]["gameModeStats"]
        return player_name_real, platform, gm_stats, player_id, match_results


# ── 文字回退渲染 ──────────────────────────────────────────

def _render_text(name, platform, gm_stats, player_id, match_results) -> str:
    W = 38
    bar = "─" * W
    lines = [
        "┌" + "─" * W + "┐",
        "│" + f"  {name}  [{platform.upper()}]".center(W) + "│",
        "└" + "─" * W + "┘", "",
        "◆ 终身战绩", bar,
    ]
    has_any = False
    for mode_key, mode_label in _MODE_LABELS.items():
        s = gm_stats.get(mode_key, {})
        rounds = s.get("roundsPlayed", 0)
        if rounds == 0:
            continue
        has_any = True
        wins = s.get("wins", 0); top10 = s.get("top10s", 0)
        kills = s.get("kills", 0); assists = s.get("assists", 0)
        damage = s.get("damageDealt", 0.0)
        kd = kills / rounds if rounds else 0
        lines += [
            f"▌{mode_label}",
            f"  场次 {rounds}  胜场 {wins}({wins/rounds*100:.1f}%)  Top10 {top10}({top10/rounds*100:.1f}%)",
            f"  击杀 {kills}  助攻 {assists}  K/D {kd:.2f}",
            f"  场均伤害 {damage/rounds:.0f}  场均存活 {s.get('timeSurvived',0)/rounds/60:.1f}min", "",
        ]
    if not has_any:
        lines += ["  暂无战绩数据", ""]
    if match_results:
        lines += ["◆ 最近对局", bar]
        for idx, md in enumerate(match_results, 1):
            e = _parse_match(md, player_id)
            if not e:
                continue
            tag = "🏆 吃鸡" if e["place"] == 1 else f"#{e['place']}"
            lines += [
                f"[{idx}] {e['date']}  {e['mode']}  {e['map']}",
                f"  排名 {tag}  击杀 {e['kills']}  伤害 {e['damage']:.0f}",
                f"  助攻 {e['assists']}  爆头 {e['headshots']}  最远 {e['longest']:.0f}m  存活 {e['survive']:.1f}min", "",
            ]
    return "\n".join(lines).rstrip()


# ── 工具函数 ──────────────────────────────────────────────

def _parse_match(match_data: dict, player_id: str) -> dict | None:
    try:
        attrs = match_data["data"]["attributes"]
        map_name   = _MAP_NAMES.get(attrs.get("mapName", ""), attrs.get("mapName", ""))
        mode_label = _MODE_LABELS.get(attrs.get("gameMode", ""), attrs.get("gameMode", ""))
        date_str   = _fmt_date(attrs.get("createdAt", ""))
        for item in match_data.get("included", []):
            if item.get("type") != "participant":
                continue
            s = item["attributes"]["stats"]
            if s.get("playerId") != player_id:
                continue
            return {
                "date": date_str, "mode": mode_label, "map": map_name,
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
        return dt.astimezone().strftime("%m-%d %H:%M")
    except Exception:
        return iso[:10]


async def _get(session: aiohttp.ClientSession, url: str, params: dict = None) -> dict:
    async with session.get(url, params=params) as resp:
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
