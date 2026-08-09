import json

import pytest

from biread.cache import SCHEMA_VERSION, Cache
from biread.errors import CacheError, CacheSchemaError


def test_missing_file_starts_empty(tmp_path):
    cache = Cache.load(tmp_path / "nested" / "translations.json")
    assert len(cache) == 0
    assert "anything" not in cache


def test_roundtrip(tmp_path):
    path = tmp_path / "translations.json"
    Cache.load(path).update({"abc": "Hello", "def": "World"})

    reloaded = Cache.load(path)
    assert len(reloaded) == 2
    assert reloaded.get("abc") == "Hello"
    assert "def" in reloaded


def test_update_is_one_write(tmp_path, monkeypatch):
    path = tmp_path / "translations.json"
    cache = Cache.load(path)
    writes = []
    monkeypatch.setattr(Cache, "flush", lambda self: writes.append(1))
    cache.update({"a": "1", "b": "2", "c": "3"})
    assert len(writes) == 1


def test_empty_update_writes_nothing(tmp_path):
    path = tmp_path / "translations.json"
    Cache.load(path).update({})
    assert not path.exists()


def test_non_ascii_survives(tmp_path):
    path = tmp_path / "translations.json"
    Cache.load(path).update({"k": "déjà vu — « guillemets »"})
    assert Cache.load(path).get("k") == "déjà vu — « guillemets »"


def test_schema_mismatch_raises(tmp_path):
    path = tmp_path / "translations.json"
    path.write_text(json.dumps({"schema_version": 99, "entries": {"a": "b"}}))
    with pytest.raises(CacheSchemaError) as excinfo:
        Cache.load(path)
    assert excinfo.value.path == path


def test_corrupt_file_raises_actionable_error(tmp_path):
    path = tmp_path / "translations.json"
    path.write_text("{not json")
    with pytest.raises(CacheError, match="Delete it"):
        Cache.load(path)


def test_foreign_json_is_rejected(tmp_path):
    path = tmp_path / "translations.json"
    path.write_text(json.dumps({"something": "else"}))
    with pytest.raises(CacheError, match="not a biread cache"):
        Cache.load(path)


def test_rebuild_discards_entries(tmp_path):
    path = tmp_path / "translations.json"
    path.write_text(json.dumps({"schema_version": 99, "entries": {"a": "b"}}))
    cache = Cache.rebuild(path)
    assert len(cache) == 0
    assert json.loads(path.read_text())["schema_version"] == SCHEMA_VERSION


def test_write_leaves_no_temp_file(tmp_path):
    path = tmp_path / "translations.json"
    Cache.load(path).update({"a": "b"})
    assert [p.name for p in tmp_path.iterdir()] == ["translations.json"]


def test_concurrent_runs_do_not_clobber_each_other(tmp_path):
    # Two runs on the same book each hold the whole cache in memory. Without a
    # merge on write, whichever finishes second discards the other's work.
    path = tmp_path / "translations.json"
    first = Cache.load(path)
    second = Cache.load(path)

    first.update({"a": "from the first run"})
    second.update({"b": "from the second run"})

    merged = Cache.load(path)
    assert merged.get("a") == "from the first run"
    assert merged.get("b") == "from the second run"


def test_our_own_entries_win_on_merge(tmp_path):
    path = tmp_path / "translations.json"
    Cache.load(path).update({"a": "older"})
    mine = Cache.load(tmp_path / "translations.json")
    mine.update({"a": "newer"})
    assert Cache.load(path).get("a") == "newer"


def test_flush_ignores_an_unreadable_file_rather_than_losing_work(tmp_path):
    path = tmp_path / "translations.json"
    cache = Cache.load(path)
    path.write_text("{corrupt")
    cache.update({"a": "kept"})
    assert Cache.load(path).get("a") == "kept"


def test_an_entry_is_handed_out_as_it_lands(tmp_path):
    """What the browser keeps a build by. With no file to write to, `on_write`
    is the only way a paid-for paragraph outlives the tab that bought it."""
    seen = []
    cache = Cache(None, on_write=seen.append)
    cache.update({"a": "un"})
    cache.update({"b": "deux", "c": "trois"})
    cache.update({})

    assert seen == [{"a": "un"}, {"b": "deux", "c": "trois"}]
    assert cache.get("c") == "trois"


def test_entries_handed_in_are_the_cache(tmp_path):
    """A resumed build reads what an earlier one wrote, and adding to it adds to
    the caller's own store — the dict is shared, not copied."""
    held = {"a": "un"}
    cache = Cache(None, held)
    cache.update({"b": "deux"})

    assert "a" in cache
    assert held == {"a": "un", "b": "deux"}
