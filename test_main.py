"""Unit tests for pure helpers in main.py."""
from __future__ import annotations

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
