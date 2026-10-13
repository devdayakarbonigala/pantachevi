"""Loads the rules file. Agents never hard-code a threshold; they read it here."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "chilli_guntur.json"

_lock = threading.Lock()
_cache: dict[str, tuple[int, dict]] = {}  # path -> (mtime_ns, rules)


def load_rules(path: str | None = None) -> dict:
    """Read the rules file, re-reading it whenever it changes on disk.

    If the file is saved in a broken state (bad JSON) after a good load, the last
    good rules keep being used and a warning is logged, so a typo while editing
    cannot take the app down. A broken file on the very first load raises.
    """
    key = str(path or RULES_PATH)
    mtime = Path(key).stat().st_mtime_ns
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
        try:
            with open(key, encoding="utf-8") as fh:
                rules = json.load(fh)
            rules["rules"]  # the one key every caller needs
        except (ValueError, KeyError, TypeError) as exc:
            if hit:
                log.warning("Rules file %s is invalid (%r); keeping the last good rules.", key, exc)
                _cache[key] = (mtime, hit[1])  # do not re-parse the same broken file on every call
                return hit[1]
            raise
        _cache[key] = (mtime, rules)
        return rules


def rule_value(group: str, name: str) -> float:
    return load_rules()["rules"][group][name]["value"]


def rule_is_sample(group: str, name: str) -> bool:
    return load_rules()["rules"][group][name]["status"] != "verified"


def all_rules_verified() -> bool:
    rules = load_rules()["rules"]
    return all(r["status"] == "verified" for group in rules.values() for r in group.values())
