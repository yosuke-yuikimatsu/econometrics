from __future__ import annotations

from app.storage import StateStore

_store: StateStore | None = None


def get_store() -> StateStore:
    global _store
    if _store is None:
        _store = StateStore()
    return _store