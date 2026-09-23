"""Loader for static, human-curated resource URLs (data/resources.json).

The AI is never asked to invent URLs — all links shown in the UI come from
this curated local JSON file.
"""

import json
import os
import threading

_DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "resources.json",
)

_cache: dict | None = None
_lock = threading.Lock()


def _load() -> dict:
    global _cache
    with _lock:
        if _cache is None:
            with open(_DATA_PATH, "r", encoding="utf-8") as fh:
                _cache = json.load(fh)
        return _cache
    return {}


def get_learning_resources() -> list:
    return list(_load().get("learning_resources", []))


def get_job_portals() -> list:
    return list(_load().get("job_portals", []))


def get_resume_builders() -> list:
    return list(_load().get("resume_builders", []))
