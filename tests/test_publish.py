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
