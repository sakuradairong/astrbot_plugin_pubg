"""Offline tests for PUBG queries and rendering."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import main as pubg


def test_calc_kd_normal():
    assert pubg._calc_kd(10, 5) == 2.0
    assert abs(pubg._calc_kd(7, 3) - 7 / 3) < 1e-9


def test_calc_kd_zero_deaths():
    assert pubg._calc_kd(5, 0) == 5.0
    assert pubg._calc_kd(0, 0) == 0.0


def test_normalize_ban_type():
    assert pubg._normalize_ban_type("Innocent") is None
    assert pubg._normalize_ban_type("NotBanned") is None
    assert pubg._normalize_ban_type(None) is None
    assert pubg._normalize_ban_type("") is None
    assert pubg._normalize_ban_type("PermanentBan") == "PermanentBan"
    assert pubg._normalize_ban_type("TemporaryBan") == "TemporaryBan"


def test_mode_stat_rows_kd_uses_deaths():
    gm = {
        "solo": {
            "roundsPlayed": 10,
            "wins": 2,
            "top10s": 4,
            "kills": 20,
            "deaths": 10,
            "assists": 1,
            "damageDealt": 1500.0,
            "timeSurvived": 6000.0,
        },
        "duo": {"roundsPlayed": 0},
    }
    rows = pubg._mode_stat_rows(gm)
    assert len(rows) == 1
    assert rows[0].label == "单排TPP"
    assert rows[0].kd == 2.0
    assert rows[0].deaths == 10
    assert rows[0].win_pct == 20.0


def test_mode_stat_rows_empty():
    assert pubg._mode_stat_rows({}) == []
    assert pubg._mode_stat_rows({"solo": {"roundsPlayed": 0}}) == []


def test_missing_deaths_is_distinct_from_zero():
    stats = {"solo": {"roundsPlayed": 4, "wins": 1, "kills": 9}}
    text = pubg._render_text("Tester", "steam", stats, "pid", [])
    assert "死亡 —" in text and "K/D —" in text
    stats["solo"]["deaths"] = 0
    text = pubg._render_text("Tester", "steam", stats, "pid", [])
    assert "死亡 0" in text and "K/D 9.00" in text


def test_parse_match_success():
    match = {
        "data": {
            "attributes": {
                "mapName": "Baltic_Main",
                "gameMode": "squad-fpp",
                "createdAt": "2026-01-15T12:00:00Z",
            }
        },
        "included": [
            {
                "type": "participant",
                "attributes": {
                    "stats": {
                        "playerId": "account.abc",
                        "winPlace": 1,
                        "kills": 3,
                        "assists": 1,
                        "damageDealt": 400.5,
                        "headshotKills": 1,
                        "longestKill": 120.0,
                        "timeSurvived": 1800.0,
                    }
                },
            }
        ],
    }
    entry = pubg._parse_match(match, "account.abc")
    assert entry is not None
    assert entry["map"] == "Erangel"
    assert entry["mode"] == "四排FPP"
    assert entry["place"] == 1
    assert entry["kills"] == 3
    assert abs(entry["survive"] - 30.0) < 1e-9


def test_parse_match_wrong_player():
    match = {
        "data": {"attributes": {"mapName": "x", "gameMode": "solo", "createdAt": ""}},
        "included": [
            {
                "type": "participant",
                "attributes": {"stats": {"playerId": "other", "winPlace": 5}},
            }
        ],
    }
    assert pubg._parse_match(match, "account.abc") is None


def test_parse_match_malformed():
    assert pubg._parse_match({}, "id") is None
    assert pubg._parse_match({"data": {}}, "id") is None


def test_recent_matches_skip_unusable_records():
    valid = {
        "data": {"attributes": {}},
        "included": [
            {"type": "participant", "attributes": {}},
            {"type": "participant", "attributes": {"stats": {"playerId": "pid", "winPlace": 1}}},
        ],
    }
    unusable = {"data": {"attributes": None}}
    text = pubg._render_text("Tester", "steam", {}, "pid", [unusable, valid])
    assert "[1]" in text and "[2]" not in text and "排名 吃鸡" in text
    assert "最近对局" not in pubg._render_text("Tester", "steam", {}, "pid", [unusable])


def test_render_text_includes_kd_and_deaths():
    gm = {
        "squad": {
            "roundsPlayed": 4,
            "wins": 1,
            "top10s": 2,
            "kills": 8,
            "deaths": 4,
            "assists": 2,
            "damageDealt": 800.0,
            "timeSurvived": 2400.0,
        }
    }
    text = pubg._render_text("Tester", "steam", gm, "pid", [], ban_type=None)
    assert "K/D 2.00" in text
    assert "死亡 4" in text
    assert "账号状态: 正常" in text


def test_render_text_banned_and_empty():
    text = pubg._render_text(
        "BannedUser", "psn", {}, "pid", [], ban_type="PermanentBan"
    )
    assert "永久封禁" in text
    assert "暂无战绩数据" in text


def test_valid_platforms_no_stadia():
    assert "stadia" not in pubg.VALID_PLATFORMS
    assert pubg.VALID_PLATFORMS == frozenset({"steam", "psn", "xbox", "kakao"})


def test_font_cache_reuses_instance():
    pubg._font_cache.clear()
    if not pubg.PIL_OK:
        return
    a = pubg._load_font(18)
    b = pubg._load_font(18)
    assert a is b


def test_tool_uses_configured_platform_unless_overridden():
    plugin = pubg.PubgPlugin(None, {"default_platform": "psn", "api_key": "test"})
    info = pubg.PlayerInfo("pid", "Tester", "psn", None)
    with patch.object(plugin, "_fetch_all", new=AsyncMock(return_value=(info, {}, []))) as fetch:
        asyncio.run(plugin.pubg_query_tool(None, "Tester"))
        fetch.assert_awaited_with("Tester", "psn", "test")
        asyncio.run(plugin.pubg_query_tool(None, "Tester", "steam"))
        fetch.assert_awaited_with("Tester", "steam", "test")


def test_cancel_lookup_finishes_lifetime_request_before_closing_session():
    async def run():
        started = asyncio.Event()
        finished = asyncio.Event()
        player = {
            "id": "pid",
            "attributes": {"name": "Tester"},
            "relationships": {"matches": {"data": [{"id": "mid"}]}},
        }

        async def request(session, url, **kwargs):
            if url.endswith("/players"):
                return {"data": [player]}
            if url.endswith("/lifetime"):
                started.set()
                try:
                    await asyncio.Future()
                finally:
                    finished.set()
            await asyncio.Future()

        plugin = pubg.PubgPlugin(None)
        session = MagicMock()

        async def check_session_exit(*args):
            assert finished.is_set()

        session.__aexit__.side_effect = check_session_exit
        with patch.object(pubg.aiohttp, "ClientSession", return_value=session), \
             patch.object(pubg, "_api_request", request):
            lookup = asyncio.create_task(plugin._fetch_all("Tester", "steam", "test"))
            await asyncio.wait_for(started.wait(), timeout=1)
            lookup.cancel()
            try:
                await lookup
            except asyncio.CancelledError:
                pass
            assert lookup.cancelled()
            session.__aexit__.assert_awaited_once()

    asyncio.run(run())
