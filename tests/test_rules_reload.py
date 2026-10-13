import json
import logging
import os

import pytest

from pantachevi import rules


def write(path, value, mtime):
    path.write_text(json.dumps({"status_note": "n", "rules": {"weather": {"max_wind_kmh": {"value": value, "status": "sample", "source": None}}}}))
    os.utime(path, ns=(mtime, mtime))  # force a distinct mtime so the test is not timing dependent


def test_edit_is_picked_up_without_restart(tmp_path):
    f = tmp_path / "r.json"
    write(f, 15, 1_000_000_000)
    assert rules.load_rules(str(f))["rules"]["weather"]["max_wind_kmh"]["value"] == 15
    write(f, 20, 2_000_000_000)
    assert rules.load_rules(str(f))["rules"]["weather"]["max_wind_kmh"]["value"] == 20


def test_unchanged_file_is_not_reparsed(tmp_path, monkeypatch):
    f = tmp_path / "r.json"
    write(f, 15, 1_000_000_000)
    rules.load_rules(str(f))
    monkeypatch.setattr(json, "load", lambda *_: pytest.fail("re-read an unchanged file"))
    rules.load_rules(str(f))


def test_broken_save_keeps_last_good_rules(tmp_path, caplog):
    f = tmp_path / "r.json"
    write(f, 15, 1_000_000_000)
    rules.load_rules(str(f))
    f.write_text("{ not json")
    os.utime(f, ns=(2_000_000_000, 2_000_000_000))
    with caplog.at_level(logging.WARNING):
        got = rules.load_rules(str(f))
    assert got["rules"]["weather"]["max_wind_kmh"]["value"] == 15
    assert "keeping the last good rules" in caplog.text
    write(f, 18, 3_000_000_000)  # fixing the file takes effect again
    assert rules.load_rules(str(f))["rules"]["weather"]["max_wind_kmh"]["value"] == 18


def test_broken_file_on_first_load_raises(tmp_path):
    f = tmp_path / "r.json"
    f.write_text("{ not json")
    with pytest.raises(ValueError):
        rules.load_rules(str(f))
