from typing import Callable

_REGISTRY: dict[str, Callable] = {}

def register(feed_type: str):
    def decorator(fn):
        _REGISTRY[feed_type] = fn
        return fn
    return decorator

def get_parser(feed_type: str) -> Callable | None:
    return _REGISTRY.get(feed_type)
