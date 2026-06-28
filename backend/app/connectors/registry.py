"""Connector registry: look up a connector by its public name."""
from __future__ import annotations

from app.connectors.base import BaseConnector

_REGISTRY: dict[str, type[BaseConnector]] = {}


def register(cls: type[BaseConnector]) -> type[BaseConnector]:
    _REGISTRY[cls.name] = cls
    return cls


def get_connector(name: str) -> BaseConnector:
    if name not in _REGISTRY:
        raise KeyError(f"Conector desconocido: {name}. Disponibles: {list(_REGISTRY)}")
    return _REGISTRY[name]()


def list_connectors() -> list[dict[str, str]]:
    out = []
    for name, cls in _REGISTRY.items():
        out.append({"name": name, "platform": cls.source.value})
    return out


def _load_builtin() -> None:
    # Import side-effects register the connectors.
    from app.connectors import crypto_com_bank, crypto_exchange, revolut, revolut_exchange  # noqa: F401


_load_builtin()
