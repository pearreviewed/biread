from pathlib import Path

from ..errors import ExtractError
from .base import Extractor
from .txt import TxtExtractor

# Adding a format = add a module and register its class here. Nothing else changes.
EXTRACTORS: tuple[type[Extractor], ...] = (TxtExtractor,)

# Formats the design calls for but that have no extractor yet — worth a more
# specific message than "unsupported".
PLANNED = {".pdf", ".epub"}

__all__ = ["Extractor", "TxtExtractor", "get_extractor"]


def get_extractor(path: Path) -> Extractor:
    for cls in EXTRACTORS:
        if cls.handles(path):
            return cls()
    supported = ", ".join(sorted(s for cls in EXTRACTORS for s in cls.suffixes))
    suffix = path.suffix.lower() or "(no extension)"
    planned = " (planned, not built yet)" if suffix in PLANNED else ""
    raise ExtractError(
        f"no extractor for {suffix} files{planned}: {path.name}. Supported: {supported}."
    )
