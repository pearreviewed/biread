"""The shelf: what it claims, and what it refuses to claim."""
from __future__ import annotations

from biread import shelf
from tests.test_wikisource import fetcher, links, page


def test_every_book_names_two_pages_and_an_author():
    for book in shelf.SHELF:
        assert book.page and book.title and book.author
        assert book.translations, book.slug
        assert all(t.page for t in book.translations), book.slug


def test_slugs_are_unique():
    slugs = [b.slug for b in shelf.SHELF]
    assert len(set(slugs)) == len(slugs)


def test_a_book_read_through_carries_the_coverage_someone_measured():
    for book in shelf.SHELF:
        if book.read_through:
            assert book.coverage and 0 < book.coverage <= 1, book.slug
        else:
            # Nothing is invented for a book nobody has read: no figure at all
            # beats a plausible one.
            assert book.coverage is None, book.slug


def test_the_default_translation_is_one_that_has_been_measured():
    for book in shelf.SHELF:
        assert book.translation.paragraphs > 0, book.slug
        assert book.translation.chapters > 0, book.slug


def test_build_time_comes_from_the_size_of_both_editions():
    candide = shelf.by_slug("candide")
    bovary = shelf.by_slug("bovary")
    assert candide.minutes < bovary.minutes
    # Measured: Bovary's 5,449 paragraphs took about fourteen minutes.
    assert 12 <= bovary.minutes <= 16


def test_tokens_count_both_editions_once_each():
    book = shelf.by_slug("candide")
    assert book.tokens == round((book.chars + book.translation.chars) / 4)


def test_searching_the_shelf_narrows_it():
    assert [b.slug for b in shelf.search("voltaire")] == ["candide", "micromegas"]
    assert [b.slug for b in shelf.search("bovary")] == ["bovary"]
    assert shelf.search("dickens") == []
    assert len(shelf.search("  ")) == len(shelf.SHELF)


def test_search_finds_a_book_by_its_translator():
    assert [b.slug for b in shelf.search("marx-aveling")] == ["bovary"]


def test_a_filter_that_would_match_everything_is_not_offered():
    one = (shelf.by_slug("candide"),)
    assert catalogue_filters(one) == []
    assert "read" in catalogue_filters(shelf.SHELF)


def catalogue_filters(books):
    return [f["key"] for f in shelf.catalogue(books)["filters"]]


def test_the_filters_that_are_offered_agree_with_the_books():
    got = {f["key"]: f["slugs"] for f in shelf.catalogue()["filters"]}
    assert got["read"] == ["candide", "bovary"]
    assert "80days" in got["several"] and "80days" not in got["whole"]


def test_a_card_says_only_what_the_wiki_says():
    verne = shelf.by_slug("20000").as_dict()
    # The wiki does not name that translator, so the card does not either.
    assert verne["english"] == "1911"
    assert verne["counts"] == [47, 46]


def test_a_book_found_by_a_reader_is_marked_unvouched_for():
    found = shelf.from_lookup("Germinal", "Zola", "Germinal", "fr",
                              shelf.Translation("Germinal (Ellis)", "Ellis", "1894", 40, 100, 400),
                              chapters=40, paragraphs=120, chars=500)
    assert found.added and not found.read_through
    assert found.coverage is None
    assert "not looked" in found.note


def test_loading_a_pair_reads_both_sides_and_credits_them():
    body = "<p>A paragraph of the chapter, long enough to be kept.</p>"
    fetch = fetcher({
        "Micromégas": page(links("Micromégas/Chapitre I", "Micromégas/Chapitre II")),
        "Micromégas/Chapitre I": page(body),
        "Micromégas/Chapitre II": page(body),
        "Micromegas (Phalen)": page(links("Micromegas (Phalen)/1", "Micromegas (Phalen)/2"),
                                    author="Voltaire", translator="Peter Phalen"),
        "Micromegas (Phalen)/1": page(body),
        "Micromegas (Phalen)/2": page(body),
    })
    original, english, info = shelf.load_pair(shelf.by_slug("micromegas"), 0, fetch)
    assert len(original) == len(english) == 2
    assert info["orig"]["title"] == "Micromégas"
    assert info["pub"]["author"] == "Peter Phalen"
    assert info["orig"]["chars"] > 0


def test_progress_names_the_side_being_fetched():
    body = "<p>A paragraph of the chapter, long enough to be kept.</p>"
    fetch = fetcher({
        "Micromégas": page(links("Micromégas/Chapitre I")),
        "Micromégas/Chapitre I": page(body),
        "Micromegas (Phalen)": page(links("Micromegas (Phalen)/1")),
        "Micromegas (Phalen)/1": page(body),
    })
    stages = []
    shelf.load_pair(shelf.by_slug("micromegas"), 0, fetch,
                    lambda s, i, t: stages.append(s))
    assert stages == ["fetch-orig", "fetch-pub"]


def test_the_second_translation_is_reachable():
    body = "<p>A paragraph of the chapter, long enough to be kept.</p>"
    fetch = fetcher({
        "Micromégas": page(links("Micromégas/Chapitre I")),
        "Micromégas/Chapitre I": page(body),
        "The Works of Voltaire/Volume 3/Micromegas": page(body, translator="William F. Fleming"),
    })
    _, english, info = shelf.load_pair(shelf.by_slug("micromegas"), 1, fetch)
    assert len(english) == 1
    assert info["pub"]["author"] == "William F. Fleming"


def test_probing_a_pair_costs_no_chapter_fetches():
    fetch = fetcher({
        "Germinal": page(links("Germinal/Partie I", "Germinal/Partie II", "Germinal/Partie III")),
        "Germinal (Ellis)": page(links("Germinal (Ellis)/1", "Germinal (Ellis)/2"),
                                 translator="Havelock Ellis", year="1894"),
    })
    got = shelf.probe("fr", "Germinal", "en", "Germinal (Ellis)", fetch)
    assert got["buildable"]
    assert (got["chapters"], got["otherChapters"]) == (3, 2)
    assert got["english"] == "Ellis · 1894"
    assert fetch.seen == ["Germinal", "Germinal (Ellis)"]


def test_a_book_with_one_side_only_is_not_buildable():
    fetch = fetcher({
        "Germinie Lacerteux": page(links("Germinie Lacerteux/1", "Germinie Lacerteux/2",
                                         "Germinie Lacerteux/3")),
        "Nothing": page(""),
    })
    got = shelf.probe("fr", "Germinie Lacerteux", "en", "Nothing", fetch)
    assert not got["buildable"]
