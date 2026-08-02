"""Looking at a book at the three places books break.

The point of a checker is what it catches, so most of this is broken books. A
check that passes everything is worse than no check: it makes approving a book
feel like it was inspected.

Needs the browser engine, and skips itself without it — the same bargain the
reader and export suites make.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright not installed")

from biread.check import LOPSIDED, THIN_CHARS, spot_check  # noqa: E402
from biread.cleanup import Chapter  # noqa: E402
from biread.render import render_book  # noqa: E402
from biread.translate import hash_text  # noqa: E402

FR = "Une phrase française assez longue pour remplir une page comme il faut."
EN = "A French sentence long enough to fill a page as it ought to be filled."


def a_book(tmp_path, name="book.html", *, chapters=14, english=lambda fr: None):
    """A book of `chapters` chapters, with the English decided per paragraph."""
    book, translations = [], {}
    for n in range(chapters):
        paragraphs = [f"{FR} [{n}-{i}]" for i in range(6)]
        for paragraph in paragraphs:
            rendered = english(paragraph)
            if rendered is not None:
                translations[hash_text(paragraph)] = rendered
        book.append(Chapter(str(n + 1), f"Chapitre {n + 1}", paragraphs))
    out = tmp_path / name
    render_book("Livre", book, translations, out)
    return out


def test_a_sound_book_is_reported_and_not_faulted(tmp_path):
    look = spot_check(a_book(tmp_path, english=lambda fr: EN + f" [{len(fr)}]"),
                      shots_dir=tmp_path / "shots")
    assert look.total > 3
    assert [s.index for s in look.spreads] == [1, look.total // 2, look.total]
    assert look.faults == []
    assert all(s.french > THIN_CHARS and s.english > THIN_CHARS for s in look.spreads)


def test_it_keeps_a_picture_of_each_place_it_looked(tmp_path):
    shots = tmp_path / "shots"
    spot_check(a_book(tmp_path, english=lambda fr: EN), shots_dir=shots)
    assert {p.name for p in shots.glob("*.png")} == {"opening.png", "middle.png", "end.png"}
    assert all(p.stat().st_size > 1000 for p in shots.glob("*.png"))


def test_a_book_with_an_empty_column_is_caught(tmp_path):
    """The failure this whole thing exists for: the published column came out
    empty and the book still rendered perfectly well."""
    look = spot_check(a_book(tmp_path, english=lambda fr: ""), shots_dir=tmp_path / "shots")
    assert look.faults, "an empty English column must not pass"
    assert any("nearly empty" in fault for fault in look.faults)


def test_a_lopsided_spread_is_caught(tmp_path):
    """One column several times the other is not two editions differing — it is a
    page where one side did not arrive."""
    def stub(fr):
        return EN if fr.endswith("[0]") else "Yes."

    look = spot_check(a_book(tmp_path, english=stub), shots_dir=tmp_path / "shots")
    assert look.faults
    assert any("lopsided" in f or "nearly empty" in f for f in look.faults)


def test_the_thresholds_are_the_ones_it_reports_against():
    """Named rather than buried, because a checker's numbers are the argument."""
    assert THIN_CHARS == 200 and LOPSIDED == 3.0
