try:
    from .main import PubgPlugin, PubgApiError

    __all__ = ["PubgPlugin", "PubgApiError"]
except ImportError:  # pragma: no cover - unit tests without AstrBot installed
    __all__ = []
