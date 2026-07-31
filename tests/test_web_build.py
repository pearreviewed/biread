"""The bundle's account of the books it already holds.

A shelf card that offers a finished book is making a promise in front of a
reader, and the only thing standing behind it is this step: the file is there,
the slug names a real book, and every figure on the card was read off the book
rather than typed next to it. So the tests here are mostly about failing —
loudly, at build time, where it costs nothing.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from biread.render import script_json


def load_build_module():
    """web/build.py is a script, not a package — reach it the way a script is."""
    path = Path(__file__).resolve().parent.parent / "web" / "build.py"
    spec = importlib.util.spec_from_file_location("web_build", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build():
    return load_build_module()


def a_reader(tmp_path, pairs, **extra):
    """A built reader, only as much of one as `measure` reads."""
    data = {"pairs": pairs, **extra}
    path = tmp_path / "book.html"
    path.write_text(
        '<script type="application/json" id="book-data">'
        + script_json(data)
        + "</script>",
        encoding="utf-8",
    )
    return path


def test_it_reads_the_book_rather_than_taking_the_manifest_word_for_it(build, tmp_path):
    path = a_reader(
        tmp_path,
        [
            {"fr": "Une phrase.", "en": "A sentence.", "units": [[0, 3, "det", "a"]]},
            {"fr": "Une autre.", "en": "Another."},
            {"fr": "Sans rien.", "en": "   "},
        ],
        publishedAvailable=True,
        downloads=[{"format": "epub"}, {"format": "pdf"}],
    )
    made = build.measure(path)
    assert made["paragraphs"] == 3
    assert made["translated"] == 2, "whitespace is not a translation"
    assert made["glossed"] == 1
    assert made["published"] is True and made["solo"] is False
    assert made["formats"] == ["epub", "pdf"]
    assert made["bytes"] == path.stat().st_size


def test_a_book_matched_against_one_edition_is_not_claimed_to_hold_two(build, tmp_path):
    made = build.measure(a_reader(tmp_path, [{"fr": "Une phrase.", "en": "A sentence."}], solo=True))
    assert made["solo"] is True and made["published"] is False
    assert made["formats"] == []


def test_a_file_that_is_not_a_built_reader_stops_the_build(build, tmp_path):
    path = tmp_path / "book.html"
    path.write_text("<!doctype html><p>not a reader</p>", encoding="utf-8")
    with pytest.raises(SystemExit, match="no book data"):
        build.measure(path)


def published_as(build, monkeypatch, tmp_path, entries, files=("micromegas.html",)):
    books = tmp_path / "books"
    books.mkdir()
    for name in files:
        (books / name).write_text(
            '<script type="application/json" id="book-data">'
            + script_json({"pairs": [{"fr": "Une phrase.", "en": "A sentence."}]})
            + "</script>",
            encoding="utf-8",
        )
    dist = tmp_path / "dist"
    dist.mkdir()
    monkeypatch.setattr(build, "BOOKS", books)
    monkeypatch.setattr(build, "DIST", dist)
    monkeypatch.setattr(build, "PUBLISHED", entries)
    return dist


SHELF = {"books": [{"slug": "micromegas", "title": "Micromégas"}]}


def test_a_finished_book_joins_its_card_and_the_bundle(build, monkeypatch, tmp_path):
    dist = published_as(build, monkeypatch, tmp_path, [
        {"slug": "micromegas", "file": "micromegas.html", "english": "Phalen",
         "approved": "2026-08-01"},
    ])
    shelf = json.loads(json.dumps(SHELF))
    build.gather_published(shelf)

    made = shelf["books"][0]["prebuilt"]
    assert made["href"] == "books/micromegas.html"
    assert made["filename"] == "Micromégas - bilingual reader.html", (
        "a reader saves a book, not a slug"
    )
    assert made["english"] == "Phalen" and made["paragraphs"] == 1
    assert (dist / "books" / "micromegas.html").is_file()


def test_the_day_there_is_a_server_one_line_moves_every_book(build, monkeypatch, tmp_path):
    published_as(build, monkeypatch, tmp_path, [
        {"slug": "micromegas", "file": "micromegas.html", "approved": "2026-08-01"},
    ])
    monkeypatch.setattr(build, "BOOKS_AT", "https://biread.example/")
    shelf = json.loads(json.dumps(SHELF))
    build.gather_published(shelf)
    assert shelf["books"][0]["prebuilt"]["href"] == "https://biread.example/books/micromegas.html"


def test_a_book_that_is_not_on_the_shelf_stops_the_build(build, monkeypatch, tmp_path):
    published_as(build, monkeypatch, tmp_path, [
        {"slug": "germinal", "file": "micromegas.html", "approved": "2026-08-01"},
    ])
    with pytest.raises(SystemExit, match="not on the shelf"):
        build.gather_published(json.loads(json.dumps(SHELF)))


def test_a_promise_with_no_file_behind_it_stops_the_build(build, monkeypatch, tmp_path):
    published_as(build, monkeypatch, tmp_path, [
        {"slug": "micromegas", "file": "gone.html", "approved": "2026-08-01"},
    ], files=())
    with pytest.raises(SystemExit, match="no file"):
        build.gather_published(json.loads(json.dumps(SHELF)))


def test_the_shelf_it_ships_names_a_book_that_exists():
    """The real list, against the real shelf — the one check that catches a typo."""
    from biread.shelf import catalogue

    build = load_build_module()
    slugs = {b["slug"] for b in catalogue()["books"]}
    for entry in build.PUBLISHED:
        assert entry["slug"] in slugs, f"{entry['slug']} is published but not on the shelf"
        assert (build.BOOKS / entry["file"]).is_file(), f"{entry['file']} is missing"
