import json
import re

import pytest

from biread import cli
from biread.cleanup import Removal

FRENCH = """CHAPITRE I.
Le Départ

Premier paragraphe.

Deuxième paragraphe.

CHAPITRE II.
L'Arrivée

Troisième paragraphe.
"""

# A published translation shares vocabulary with any other translation of the
# same passage; that overlap is what the alignment matches on.
PUBLISHED = """CHAPTER I.
The Departure

A published rendering of Premier paragraphe, set rather more freely.

A published rendering of Deuxième paragraphe, also set freely.

CHAPTER II.
The Arrival

A published rendering of Troisième paragraphe, freely done.
"""


@pytest.fixture
def project(tmp_path, monkeypatch, config, make_client):
    """A source book plus a CLI wired to a fake model."""
    source = tmp_path / "micromegas.txt"
    source.write_text(FRENCH, encoding="utf-8")
    client = make_client()
    monkeypatch.setattr(cli, "load_config", lambda require_key=True: config())
    monkeypatch.setattr(cli, "get_client", lambda cfg: client)

    def invoke(*extra):
        cli.main([
            str(source),
            "-o", str(tmp_path / "out"),
            "--cache-dir", str(tmp_path / "cache"),
            *extra,
        ])

    return type("Project", (), {
        "dir": tmp_path,
        "source": source,
        "client": client,
        "invoke": staticmethod(invoke),
        "html": lambda: next((tmp_path / "out").glob("*.html")).read_text(encoding="utf-8"),
    })


def book_data(html):
    return json.loads(
        re.search(r'id="book-data">(.*?)</script>', html, re.S).group(1)
    )


def test_humanize_filenames():
    assert cli.humanize("les_fleurs-du-mal") == "Les Fleurs Du Mal"
    assert cli.humanize("") == ""


def test_removal_report_groups_and_truncates(capsys):
    cli.report_removals([Removal("Bare page-number artifact", str(n)) for n in range(10)])
    out = capsys.readouterr().out
    assert "Stripped 10 item(s)" in out
    assert "Bare page-number artifact (10)" in out
    assert "… and 7 more" in out


def test_removal_report_when_nothing_matched(capsys):
    cli.report_removals([])
    assert "kept the file as-is" in capsys.readouterr().out


def test_end_to_end_build(project):
    project.invoke()
    data = book_data(project.html())

    assert [p["fr"] for p in data["pairs"]] == [
        "Premier paragraphe.", "Deuxième paragraphe.", "Troisième paragraphe."
    ]
    assert all(p["en"] for p in data["pairs"])
    assert [c["frEyebrow"] for c in data["chapters"]] == ["Chapitre I", "Chapitre II"]
    assert data["publishedAvailable"] is False
    assert (project.dir / "cache" / "micromegas" / "translations.json").exists()


def test_second_run_calls_no_api(project, capsys):
    project.invoke()
    project.client.prompts.clear()
    project.invoke()
    assert project.client.prompts == []
    assert "already cached" in capsys.readouterr().out


def test_dry_run_writes_nothing_and_calls_nothing(project, capsys):
    project.invoke("--dry-run")
    out = capsys.readouterr().out
    assert "Would translate 5 paragraph(s)" in out
    assert "estimated cost" in out
    assert project.client.prompts == []
    assert not (project.dir / "out").exists()


def test_dry_run_warns_when_the_model_has_no_pricing(tmp_path, monkeypatch, config, capsys):
    source = tmp_path / "livre.txt"
    source.write_text(FRENCH, encoding="utf-8")
    monkeypatch.setattr(cli, "load_config", lambda require_key=True: config(price_per_mtok=None))
    cli.main([str(source), "-o", str(tmp_path / "out"), "--cache-dir", str(tmp_path / "c"), "--dry-run"])
    assert "MAX_COST_USD cannot be enforced" in capsys.readouterr().out


def test_published_translation_is_aligned_and_carried_through(project, capsys):
    published = project.dir / "english.txt"
    published.write_text(PUBLISHED, encoding="utf-8")
    project.invoke("--published", str(published))

    data = book_data(project.html())
    assert data["publishedAvailable"] is True
    assert "Premier paragraphe" in data["pairs"][0]["pub"]
    assert "Troisième paragraphe" in data["pairs"][2]["pub"]
    assert "as closely as two editions allow" in data["publishedNote"]
    assert "against the generated translation" in capsys.readouterr().out


def test_a_split_published_paragraph_is_rejoined(project):
    # The translator split one paragraph in two; both halves belong to the same
    # French paragraph and must come back together.
    published = project.dir / "english.txt"
    published.write_text(
        PUBLISHED.replace(
            "A published rendering of Deuxième paragraphe, also set freely.",
            "A published rendering of Deuxième paragraphe;\n\nand the rest of Deuxième paragraphe.",
        ),
        encoding="utf-8",
    )
    project.invoke("--published", str(published))

    pub = book_data(project.html())["pairs"][1]["pub"]
    assert "A published rendering of Deuxième paragraphe" in pub
    assert "the rest of Deuxième paragraphe" in pub


def test_front_matter_is_not_offered_as_a_translation(project):
    published = project.dir / "english.txt"
    published.write_text(
        "Produced by Some Volunteer.  HTML version by Another.\n\n" + PUBLISHED,
        encoding="utf-8",
    )
    project.invoke("--published", str(published))

    for pair in book_data(project.html())["pairs"]:
        assert "Produced by Some Volunteer" not in pair["pub"]


def test_missing_input_exits_with_a_message(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main([str(tmp_path / "nope.txt")])
    assert exit_info.value.code == 1
    assert "input file not found" in capsys.readouterr().err


def test_unsupported_format_exits_with_a_message(tmp_path, capsys):
    source = tmp_path / "book.epub"
    source.write_bytes(b"whatever")
    with pytest.raises(SystemExit):
        cli.main([str(source)])
    assert "planned, not built yet" in capsys.readouterr().err


def test_large_books_need_force(project, monkeypatch, capsys):
    monkeypatch.setattr(cli, "PARAGRAPH_LIMIT", 2)
    with pytest.raises(SystemExit):
        project.invoke()
    assert "safety limit" in capsys.readouterr().err

    project.invoke("--force")
    assert list((project.dir / "out").glob("*.html"))


def test_incompatible_cache_needs_a_decision(project, monkeypatch, capsys):
    project.invoke()
    cache_file = project.dir / "cache" / "micromegas" / "translations.json"
    cache_file.write_text(json.dumps({"schema_version": 99, "entries": {}}))

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit):
        project.invoke()
    assert "--rebuild-cache" in capsys.readouterr().err

    project.invoke("--rebuild-cache")
    assert json.loads(cache_file.read_text())["schema_version"] == 1


def test_html_keeps_the_slug_but_exports_take_the_book_name(project):
    # The hosted reader wants a clean URL; a saved EPUB wants a readable name.
    project.invoke("--title", "Micromégas", "--epub")
    out = project.dir / "out"
    assert (out / "micromegas.html").exists()
    assert (out / "Micromégas - bilingual reader.epub").exists()
    html = (out / "micromegas.html").read_text(encoding="utf-8")
    assert book_data(html)["titleFr"] == "Micromégas"
