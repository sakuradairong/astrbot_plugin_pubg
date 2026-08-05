"""Pytest bootstrap: stub AstrBot before any plugin import."""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


def pytest_configure():
    if "astrbot.api" in sys.modules:
        return

    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api_event = types.ModuleType("astrbot.api.event")
    api_star = types.ModuleType("astrbot.api.star")

    class AstrBotConfig(dict):
        pass

    class AstrMessageEvent:
        pass

    class Context:
        pass

    class Star:
        def __init__(self, context=None):
            self.context = context

    def register(*_a, **_k):
        def deco(cls):
            return cls

        return deco

    class _Filter:
        def command(self, *_a, **_k):
            def deco(fn):
                return fn

            return deco

        def llm_tool(self, *_a, **_k):
            def deco(fn):
                return fn

            return deco

    api.AstrBotConfig = AstrBotConfig
    api.logger = MagicMock()
    api_event.filter = _Filter()
    api_event.AstrMessageEvent = AstrMessageEvent
    api_star.Context = Context
    api_star.Star = Star
    api_star.register = register

    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api
    sys.modules["astrbot.api.event"] = api_event
    sys.modules["astrbot.api.star"] = api_star
