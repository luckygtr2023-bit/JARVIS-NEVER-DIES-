"""Deterministic memory command tests (single authoritative memory store)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import memory.memory_manager as mm


def _use_tmp_memory(monkeypatch, tmp_path: Path) -> Path:
    path = tmp_path / "long_term.json"
    monkeypatch.setattr(mm, "MEMORY_PATH", path)
    return path


def test_remember_and_forget_roundtrip(monkeypatch, tmp_path: Path):
    _use_tmp_memory(monkeypatch, tmp_path)
    result = mm.remember("name", "Lucky", "identity")
    assert result.startswith("Remembered: identity/name")

    memory = mm.load_memory()
    assert memory["identity"]["name"]["value"] == "Lucky"

    result = mm.forget("name", "identity")
    assert result.startswith("Forgotten: identity/name")
    assert mm.load_memory()["identity"] == {}


def test_forget_missing_key_reports_not_found(monkeypatch, tmp_path: Path):
    _use_tmp_memory(monkeypatch, tmp_path)
    assert mm.forget("ghost", "notes").startswith("Not found")


def test_list_remembered_memory_output(monkeypatch, tmp_path: Path):
    _use_tmp_memory(monkeypatch, tmp_path)
    mm.remember("name", "Lucky", "identity")
    mm.remember("coffee", "black, no sugar", "preferences")
    summary = mm.list_remembered_memory()
    assert "identity › name: Lucky" in summary
    assert "preferences › coffee: black, no sugar" in summary
    # Empty store -> empty summary
    mm.clear_all_memory()
    assert mm.list_remembered_memory() == ""


def test_clear_all_memory_counts_and_wipes(monkeypatch, tmp_path: Path):
    _use_tmp_memory(monkeypatch, tmp_path)
    mm.remember("a", "1", "notes")
    mm.remember("b", "2", "notes")
    assert mm.clear_all_memory() == 2
    assert mm.load_memory() == mm._empty_memory()
    assert mm.clear_all_memory() == 0


def test_list_handles_plain_string_entries(monkeypatch, tmp_path: Path):
    _use_tmp_memory(monkeypatch, tmp_path)
    mm.save_memory(mm._empty_memory())
    mm.update_memory({"notes": {"plain": "just a string"}})
    summary = mm.list_remembered_memory()
    assert "notes › plain: just a string" in summary


def test_invalid_category_falls_back_to_notes(monkeypatch, tmp_path: Path):
    # The category classifier lives in main.py (BrahmaLive) and is exercised
    # there; here we only pin the valid categories the store accepts.
    _use_tmp_memory(monkeypatch, tmp_path)
    assert mm.remember("k", "v", "not-a-category").startswith("Remembered: notes/k")
