import pytest

from biread.targets import (
    DEFAULT_LANG,
    ENGLISH,
    SPANISH,
    TARGETS,
    _ENGLISH_UI,
    get_target,
)


def test_every_target_carries_the_full_ui_table():
    # A missing key would render as a blank label in the reader.
    for target in TARGETS.values():
        assert set(target.ui) == set(_ENGLISH_UI), target.key


def test_english_is_the_default_and_stays_english():
    assert DEFAULT_LANG == "english"
    assert ENGLISH.code == "en" and ENGLISH.chapter_word == "Chapter"
    # Functional chrome is now English (was French "Chapitres"/"Signets").
    assert ENGLISH.ui["chapters"] == "Chapters"
    assert ENGLISH.ui["bookmarks"] == "Bookmarks"


def test_spanish_row_is_fully_spanish():
    assert SPANISH.code == "es" and SPANISH.chapter_word == "Capítulo"
    assert SPANISH.ui["chapters"] == "Capítulos"
    assert SPANISH.ui["loading"] == "Abriendo el libro…"


def test_get_target_rejects_unknown_and_lists_options():
    assert get_target("spanish") is SPANISH
    with pytest.raises(KeyError, match="available"):
        get_target("klingon")
