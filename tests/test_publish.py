"""Putting a book on the shelf, without fetching one or paying for one.

What is worth testing here is not the alignment — that has its own suite — but
the things around it that decide whether a wrong book reaches a reader: that
`--dry-run` really calls nothing, that approval is a separate act from building,
that a book which fails the three-place look is not approved by accident, and
that the manifest the bundle reads is the manifest this writes.
"""
from __future__ import annotations

import json

import pytest

from biread import publish
from biread.build import BuildResult
from biread.errors import BireadError


@pytest.fixture(autouse=True)
def manifest_at(tmp_path, monkeypatch):
    """Never the real shelf: these tests approve books."""
    path = tmp_path / "published.json"
    monkeypatch.setattr(publish, "MANIFEST", path)
    monkeypatch.setattr(publish, "BOOKS", tmp_path)
    return path


def test_nothing_is_published_before_anything_is_approved(manifest_at):
    assert publish.read_manifest() == {"books": []}


def test_approving_writes_the_row_the_bundle_reads(manifest_at):
    publish.approve("candide", "candide.html", "Smollett · 1920", "2026-08-02")
    written = json.loads(manifest_at.read_text(encoding="utf-8"))
    assert written["books"] == [{
        "slug": "candide", "file": "candide.html",
        "english": "Smollett · 1920", "approved": "2026-08-02",
    }]


def test_approving_the_same_book_twice_replaces_rather_than_repeats(manifest_at):
    publish.approve("candide", "candide.html", "Smollett · 1920", "2026-08-02")
    publish.approve("micromegas", "micromegas.html", "Phalen", "2026-08-02")
    publish.approve("candide", "candide.html", "Smollett · 1920", "2026-08-09")

    books = publish.read_manifest()["books"]
    assert [b["slug"] for b in books] == ["micromegas", "candide"]
    assert books[-1]["approved"] == "2026-08-09", "a re-approval is the newer one"


def test_a_book_that_is_not_on_the_shelf_is_refused_before_anything_is_fetched():
    with pytest.raises(BireadError, match="no book on the shelf"):
        publish.make("germinal", embedder=object())


def test_a_dry_run_calls_nothing_at_all(capsys, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("--dry-run reached the network")

    monkeypatch.setattr(publish, "load_pair", explode)
    monkeypatch.setattr(publish, "build_aligned", explode)
    monkeypatch.setattr(publish, "embedder_for", explode)

    assert publish.main(["candide", "--dry-run"]) == 0
    said = capsys.readouterr().out
    assert "Candide" in said and "Nothing was called" in said
    assert "paragraphs" in said


def test_an_unknown_slug_says_where_to_look(capsys):
    assert publish.main(["nosuchbook"]) == 2
    assert "python -m biread.shelf" in capsys.readouterr().err


class FakeEmbedder:
    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


def _made(monkeypatch, tmp_path, *, unmatched=0, glossed=0):
    from biread.align import AlignmentReport
    from biread.cleanup import Chapter

    chapters = [Chapter("I", None, ["Il y avait en Vestphalie."])]
    monkeypatch.setattr(publish, "load_pair",
                        lambda *a, **k: (chapters, chapters, {}))
    report = AlignmentReport(method="pivot", chapters_matched=True, total=10,
                             unmatched=unmatched)
    gloss = None
    if glossed:
        from biread.gloss import GlossRun
        gloss = GlossRun(glosses={}, total=10, glossed=glossed)
    monkeypatch.setattr(publish, "build_aligned", lambda **k: BuildResult(
        html="<script type=\"application/json\" id=\"book-data\">{}</script>",
        alignment=report, gloss=gloss))
    return publish.make("candide", embedder=FakeEmbedder(), out_dir=tmp_path)


def test_making_a_book_writes_it_and_reports_what_came_out(monkeypatch, tmp_path):
    made = _made(monkeypatch, tmp_path, unmatched=2)
    assert made.path == tmp_path / "candide.html" and made.path.is_file()
    assert made.paragraphs == 10 and made.blank == 2
    assert made.coverage == pytest.approx(0.8)


def test_making_a_book_does_not_publish_it(monkeypatch, tmp_path, manifest_at):
    _made(monkeypatch, tmp_path)
    assert publish.read_manifest()["books"] == [], (
        "a book that merely aligned is not a book somebody vouched for"
    )


def test_a_book_with_no_glosses_says_so_rather_than_nothing(monkeypatch, tmp_path, capsys):
    publish.report_made(_made(monkeypatch, tmp_path))
    assert "a reader adds them as they read" in capsys.readouterr().out


def test_a_glossed_book_reports_the_count(monkeypatch, tmp_path, capsys):
    publish.report_made(_made(monkeypatch, tmp_path, glossed=10))
    assert "10 glossed" in capsys.readouterr().out


def test_a_book_that_fails_the_look_is_not_approved(monkeypatch, tmp_path, capsys):
    """The check is the bar, so failing it has to actually stop the publishing."""
    from biread.check import Look

    monkeypatch.setattr(publish, "load_pair", lambda *a, **k: _stub_chapters())
    monkeypatch.setattr(publish, "build_aligned", lambda **k: _stub_result())
    monkeypatch.setattr(publish, "embedder_for", lambda args: FakeEmbedder())
    monkeypatch.setattr(publish, "BOOKS", tmp_path)
    monkeypatch.setattr(
        "biread.check.spot_check",
        lambda path, shots_dir=None: Look(total=3, faults=["the end spread is nearly empty"]))

    assert publish.main(["candide", "--approve"]) == 1
    assert publish.read_manifest()["books"] == []
    assert "Not approved" in capsys.readouterr().out


def _stub_chapters():
    from biread.cleanup import Chapter

    chapters = [Chapter("I", None, ["Il y avait en Vestphalie."])]
    return chapters, chapters, {}


def _stub_result():
    from biread.align import AlignmentReport

    return BuildResult(html="<html></html>",
                       alignment=AlignmentReport(method="pivot", chapters_matched=True,
                                                 total=10))


# ---- giving a published book its EPUB, long after it was built --------------
# The whole point is that this touches nothing else: it must not fetch, must not
# align, and must not cost anything. What it acts on is the file on disk.

def _shelved(tmp_path, manifest_at, **kwargs):
    from biread.cleanup import Chapter
    from biread.render import render_html

    book = [Chapter("I", "Titre", ["Il y avait en Vestphalie."])]
    (tmp_path / "candide.html").write_text(render_html("Candide", book, {}, **kwargs),
                                           encoding="utf-8")
    publish.approve("candide", "candide.html", "Smollett · 1920", "2026-08-02")


def _typeset(monkeypatch, blob=b"PK\x03\x04"):
    """Stand in for the browser: what is being tested here is the plumbing
    around the typesetting, which has its own suite."""
    seen = {}

    def fake(html, out_dir, formats, author=""):
        seen["html"], seen["formats"], seen["author"] = html, formats, author
        return [(fmt, "translation", f"Candide.{fmt}", blob) for fmt in formats]

    monkeypatch.setattr("biread.export.refit.formats_from_html", fake)
    return seen


def test_a_published_book_gains_the_format_inside_itself(tmp_path, manifest_at, monkeypatch):
    import base64
    import json

    from biread.render import BOOK_DATA_RE

    _shelved(tmp_path, manifest_at)
    _typeset(monkeypatch)
    publish.add_formats("candide", ["epub"])

    html = (tmp_path / "candide.html").read_text(encoding="utf-8")
    data = json.loads(BOOK_DATA_RE.search(html).group(2))
    assert [d["format"] for d in data["downloads"]] == ["epub"]
    assert base64.b64encode(b"PK\x03\x04").decode() in html


def test_the_shelf_supplies_the_one_thing_the_file_cannot_say(tmp_path, manifest_at,
                                                              monkeypatch):
    """A finished book carries its title and not its author, so the author comes
    off the shelf record — everything else is read from the book."""
    _shelved(tmp_path, manifest_at)
    seen = _typeset(monkeypatch)
    publish.add_formats("candide", ["epub"])
    assert seen["author"] == "Voltaire"


def test_all_means_every_book_on_the_shelf(tmp_path, manifest_at, monkeypatch):
    _shelved(tmp_path, manifest_at)
    publish.approve("micromegas", "micromegas.html", None, "2026-08-02")
    (tmp_path / "micromegas.html").write_text(
        (tmp_path / "candide.html").read_text(encoding="utf-8"), encoding="utf-8")
    _typeset(monkeypatch)
    assert [slug for slug, _ in publish.add_formats("all", ["epub"])] == \
        ["candide", "micromegas"]


def test_a_book_nobody_published_is_refused_by_name(tmp_path, manifest_at, monkeypatch):
    _shelved(tmp_path, manifest_at)
    _typeset(monkeypatch)
    with pytest.raises(BireadError, match="not a published book"):
        publish.add_formats("bovary", ["epub"])


def test_a_published_book_whose_file_is_gone_stops_rather_than_guessing(
        tmp_path, manifest_at, monkeypatch):
    _shelved(tmp_path, manifest_at)
    (tmp_path / "candide.html").unlink()
    _typeset(monkeypatch)
    with pytest.raises(BireadError, match="has no file"):
        publish.add_formats("candide", ["epub"])


def test_adding_a_format_fetches_nothing_and_aligns_nothing(tmp_path, manifest_at,
                                                            monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a format is made from the book, not from the network")

    monkeypatch.setattr(publish, "load_pair", refuse)
    monkeypatch.setattr(publish, "build_aligned", refuse)
    monkeypatch.setattr(publish, "embedder_for", refuse)
    _shelved(tmp_path, manifest_at)
    _typeset(monkeypatch)
    assert publish.main(["candide", "--formats"]) == 0


def test_a_book_that_already_carries_a_pdf_keeps_it(tmp_path, manifest_at, monkeypatch):
    import json

    from biread.render import BOOK_DATA_RE

    _shelved(tmp_path, manifest_at,
             downloads=[("pdf", "translation", "Candide.pdf", b"%PDF-1.4")])
    _typeset(monkeypatch)
    publish.add_formats("candide", ["epub"])

    html = (tmp_path / "candide.html").read_text(encoding="utf-8")
    data = json.loads(BOOK_DATA_RE.search(html).group(2))
    assert {d["format"] for d in data["downloads"]} == {"epub", "pdf"}


def test_a_format_the_book_already_carries_is_not_made_again(tmp_path, manifest_at,
                                                             monkeypatch, capsys):
    """Re-running over the whole shelf must cost only the books that are actually
    missing one — that is what makes it a habit rather than an afternoon."""
    _shelved(tmp_path, manifest_at,
             downloads=[("epub", "translation", "Candide.epub", b"PK")])
    seen = _typeset(monkeypatch)
    made = publish.add_formats("candide", ["epub"], on_book=publish.report_formats)
    assert made == [("candide", [])] and "formats" not in seen
    assert "already carries it" in capsys.readouterr().out


def test_remaking_replaces_a_format_typeset_by_an_older_exporter(tmp_path, manifest_at,
                                                                 monkeypatch):
    """Micromégas carried the reflowable EPUB — the design that was reverted for
    the fixed-layout spread — and was skipped for having one at all."""
    import base64

    _shelved(tmp_path, manifest_at,
             downloads=[("epub", "translation", "Candide.epub", b"reflowable")])
    _typeset(monkeypatch, blob=b"fixed-layout")
    publish.add_formats("candide", ["epub"], remake=True)

    html = (tmp_path / "candide.html").read_text(encoding="utf-8")
    assert base64.b64encode(b"fixed-layout").decode() in html
    assert base64.b64encode(b"reflowable").decode() not in html
