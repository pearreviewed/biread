from pathlib import Path

from ..errors import ExtractError
from .base import Extractor

# utf-8 first because it validates itself: invalid sequences raise rather than
# decoding to mojibake. cp1252 covers the legacy French texts that fall through.
ENCODINGS = ("utf-8-sig", "cp1252")


class TxtExtractor(Extractor):
    suffixes = (".txt",)

    def extract(self, path: Path) -> str:
        raw = path.read_bytes()
        for encoding in ENCODINGS:
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ExtractError(
                f"could not decode {path.name} as {' or '.join(ENCODINGS)} — "
                f"convert it to UTF-8 and try again."
            )
        return text.replace("\r\n", "\n").replace("\r", "\n")
