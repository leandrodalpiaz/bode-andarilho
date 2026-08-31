"""Superfície HTTP da PWA, independente dos handlers Telegram legados."""

__all__ = ["PwaAPI", "build_pwa_routes"]


def __getattr__(name: str):
    if name in __all__:
        from .api import PwaAPI, build_pwa_routes

        return {"PwaAPI": PwaAPI, "build_pwa_routes": build_pwa_routes}[name]
    raise AttributeError(name)
