"""JSON-backed, schema-versioned translation cache.

Every LLM call in the pipeline persists through this, so a re-run never
re-spends tokens on work already done. Writes are atomic (temp file + rename)
and happen once per completed API call, so an interruption loses at most the
batch in flight.
"""
from __future__ import annotations

import json
from pathlib import Path

from .errors import CacheError, CacheSchemaError

SCHEMA_VERSION = 1


class Cache:
    def __init__(self, path: Path, entries: dict[str, str] | None = None):
        self.path = path
        self._entries: dict[str, str] = entries if entries is not None else {}

    @classmethod
    def load(cls, path: Path) -> "Cache":
        """Read the cache at `path`. Raises CacheSchemaError if it was written
        by an incompatible version — the caller decides whether to rebuild."""
        if not path.exists():
            return cls(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise CacheError(
                f"cache at {path} is not readable JSON ({e}). Delete it to start over."
            ) from e
        if not isinstance(data, dict) or "entries" not in data:
            raise CacheError(f"cache at {path} is not a biread cache file.")
        if data.get("schema_version") != SCHEMA_VERSION:
            raise CacheSchemaError(path, data.get("schema_version"), SCHEMA_VERSION)
        return cls(path, dict(data["entries"]))

    @classmethod
    def rebuild(cls, path: Path) -> "Cache":
        cache = cls(path)
        cache.flush()
        return cache

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: str) -> str | None:
        return self._entries.get(key)

    def update(self, entries: dict[str, str]) -> None:
        """Add entries and persist, in one write."""
        if not entries:
            return
        self._entries.update(entries)
        self.flush()

    def _on_disk(self) -> dict[str, str]:
        """Entries currently in the file, or {} if it is missing or unusable."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            return {}
        entries = data.get("entries")
        return entries if isinstance(entries, dict) else {}

    def flush(self) -> None:
        """Write the cache, merging in anything that landed since we loaded.

        Two runs on the same book would otherwise clobber each other: both hold
        the whole cache in memory, so the second to finish writes its own copy
        over the first's translations. Merging is safe because keys are content
        hashes — the same key always describes the same source paragraph.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries = {**self._on_disk(), **self._entries}
        payload = {"schema_version": SCHEMA_VERSION, "entries": self._entries}
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        tmp.replace(self.path)
