import pytest

from biread.errors import ExtractError
from biread.extract import get_extractor
from biread.extract.txt import TxtExtractor


def test_reads_utf8(tmp_path):
    path = tmp_path / "book.txt"
    path.write_text("Déjà vu — « oui »", encoding="utf-8")
    assert TxtExtractor().extract(path) == "Déjà vu — « oui »"


def test_strips_a_byte_order_mark(tmp_path):
    path = tmp_path / "book.txt"
    path.write_bytes("﻿Texte".encode("utf-8"))
    assert TxtExtractor().extract(path) == "Texte"


def test_falls_back_to_cp1252(tmp_path):
    # Legacy French texts are common; utf-8 validates itself, so trying it
    # first means this fallback only runs on genuinely non-utf-8 files.
    path = tmp_path / "book.txt"
    path.write_bytes("Déjà vu".encode("cp1252"))
    assert TxtExtractor().extract(path) == "Déjà vu"


def test_normalises_line_endings(tmp_path):
    path = tmp_path / "book.txt"
    path.write_bytes(b"Ligne un\r\nLigne deux\rLigne trois")
    assert TxtExtractor().extract(path) == "Ligne un\nLigne deux\nLigne trois"


def test_undecodable_file_is_reported(tmp_path):
    path = tmp_path / "book.txt"
    path.write_bytes(b"\x81\x8d\x8f")  # undefined in cp1252
    with pytest.raises(ExtractError, match="could not decode"):
        TxtExtractor().extract(path)


def test_dispatch_is_case_insensitive(tmp_path):
    assert isinstance(get_extractor(tmp_path / "BOOK.TXT"), TxtExtractor)


def test_planned_formats_say_so(tmp_path):
    with pytest.raises(ExtractError, match="planned, not built yet"):
        get_extractor(tmp_path / "book.epub")


def test_unknown_format_lists_what_is_supported(tmp_path):
    with pytest.raises(ExtractError, match=r"Supported: \.txt"):
        get_extractor(tmp_path / "book.rtf")
