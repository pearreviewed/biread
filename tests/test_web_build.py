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
import zipfile
from pathlib import Path

import pytest

from biread.render import script_json
from biread.targets import ENGLISH


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
            + script_json({
                "titleFr": "Micromégas", "slug": "micromegas", "lang": "en",
                "ui": dict(ENGLISH.ui), "chapters": [],
                "pairs": [{"fr": "Une phrase.", "en": "A sentence."}],
            })
            + "</script>",
            encoding="utf-8",
        )
    dist = tmp_path / "dist"
    dist.mkdir()
    manifest = books / "published.json"
    manifest.write_text(json.dumps({"books": entries}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(build, "BOOKS", books)
    monkeypatch.setattr(build, "DIST", dist)
    monkeypatch.setattr(build, "MANIFEST", manifest)
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
    assert build.published(), "the shelf publishes nothing at all"
    for entry in build.published():
        assert entry["slug"] in slugs, f"{entry['slug']} is published but not on the shelf"
        assert (build.BOOKS / entry["file"]).is_file(), f"{entry['file']} is missing"


def a_wheel(tmp_path, engine: bytes, when=(2026, 8, 6, 12, 0, 0)) -> Path:
    """A wheel, as far as the stamping is concerned: a zip with an engine in it.

    `when` is the moment the zip says its members were written, which is the one
    thing that differs between two builds of identical source.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "biread-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr(zipfile.ZipInfo("biread/build.py", when), engine)
    return path


def test_a_changed_engine_arrives_under_a_changed_name(build, tmp_path):
    """The whole point: a host caches the wheel for a year under one URL, so two
    engines must never share one. A returning reader got today's worker against
    the engine cached on their first visit, and it called a function that engine
    did not have."""
    one = build.fingerprint(a_wheel(tmp_path / "a", b"import biread"))
    two = build.fingerprint(a_wheel(tmp_path / "b", b"import biread  # and recut"))
    assert one.name != two.name


def test_an_unchanged_engine_stays_where_it_is(build, tmp_path):
    """Built twice from one source, the wheel is two different files — a zip
    stamps the hour onto every member. Keyed on that, a rebuild would send every
    reader after 300 KB to arrive where they already were, and the year-long
    cache would be worth nothing."""
    first = build.fingerprint(a_wheel(tmp_path / "a", b"import biread"))
    later = build.fingerprint(
        a_wheel(tmp_path / "b", b"import biread", when=(2026, 9, 1, 3, 30, 0)))
    assert first.name == later.name


def test_the_stamped_wheel_is_still_a_wheel_micropip_can_read(build, tmp_path):
    """The hash rides in the build tag, which is the one field free to hold it —
    the version is what micropip resolves by, and must go on saying 0.1.0."""
    from packaging.utils import parse_wheel_filename

    stamped = build.fingerprint(a_wheel(tmp_path / "a", b"import biread"))
    name, version, _build, tags = parse_wheel_filename(stamped.name)
    assert (name, str(version)) == ("biread", "0.1.0")
    assert str(next(iter(tags))) == "py3-none-any"


def test_the_worker_names_the_wheel_pip_will_actually_produce(build):
    """Both halves of the stamping hang off this name: the build fails loudly if
    the worker does not carry it, and rewrites it to the stamped one on the way
    into the bundle. A version bumped in pyproject.toml and nowhere else would
    take the fingerprinting down with it."""
    import re

    root = Path(__file__).resolve().parent.parent
    version = re.search(
        r'^version = "(.+?)"', (root / "pyproject.toml").read_text(), re.M).group(1)
    worker = (root / "web" / "worker.js").read_text(encoding="utf-8")
    assert f"biread-{version}-py3-none-any.whl" in worker


def test_a_shelf_that_has_published_nothing_yet_builds_fine(build, monkeypatch, tmp_path):
    """The manifest is written by `biread.publish`, so it does not exist until the
    first book is approved — and a bundle with no books is a normal bundle."""
    monkeypatch.setattr(build, "MANIFEST", tmp_path / "absent.json")
    assert build.published() == []
    shelf = json.loads(json.dumps(SHELF))
    build.gather_published(shelf)
    assert "prebuilt" not in shelf["books"][0]


def test_the_python_the_worker_carries_is_python():
    """Half the engine's browser side is Python written inside JavaScript string
    arrays, where a typo is invisible until a reader is halfway through paying
    for a book. Every block of it is compiled here."""
    import re

    root = Path(__file__).resolve().parent.parent
    worker = (root / "web" / "worker.js").read_text(encoding="utf-8")
    blocks = re.findall(r"^const ([A-Z_]+) = \[\n(.*?)^\]\.join", worker, re.S | re.M)
    assert {name for name, _ in blocks} >= {"SETUP", "LOAD", "BUILD", "ALIGN", "SAMPLE", "ESTIMATE"}

    for name, block in blocks:
        lines = []
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("//") or not line:
                continue
            # One block splices another in by name, sometimes indented into a
            # suite. It is compiled on its own turn; here it stands as a body.
            spliced = re.fullmatch(r"(indent\()*[A-Z_]+\)*,", line)
            if spliced:
                lines.append("    " * line.count("indent(") + "pass")
                continue
            quoted = re.fullmatch(r'"(.*)",?', line) or re.fullmatch(r"`(.*)`,?", line)
            assert quoted, f"{name}: not a plain Python line — {line}"
            text = quoted.group(1).replace('\\"', '"').replace("\\\\", "\\")
            # A JS template hole is a value the page fills in; any value compiles.
            lines.append(re.sub(r"\$\{[^}]*\}", "0", text))
        compile("\n".join(lines), f"worker.js:{name}", "exec")
