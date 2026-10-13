"""Loads the rules file. Agents never hard-code a threshold; they read it here."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "chilli_guntur.json"


@lru_cache(maxsize=1)
def load_rules(path: str | None = None) -> dict:
    with open(path or RULES_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def rule_value(group: str, name: str) -> float:
    return load_rules()["rules"][group][name]["value"]


def rule_is_sample(group: str, name: str) -> bool:
    return load_rules()["rules"][group][name]["status"] != "verified"


def all_rules_verified() -> bool:
    rules = load_rules()["rules"]
    return all(r["status"] == "verified" for group in rules.values() for r in group.values())
