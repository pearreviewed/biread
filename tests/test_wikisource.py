"""Wikisource, read offline: every fetch here is a dict lookup."""
from __future__ import annotations

import json

import pytest

from biread import wikisource as ws


def page(body: str, current: str = "", **fields: str) -> str:
    """A page shaped like the REST API's, with the bits the parser reads."""
    head = ""
    if current:
        head += '<span data-mw=\'{"parts":[{"template":{"target":{"wt":"header"},' \
                '"params":{"current":{"wt":"%s"}}}}]}\'></span>' % current
    if fields:
        params = ",".join('"%s":{"wt":"%s"}' % (k, v) for k, v in fields.items())
        head += "<span data-mw='{\"params\":{%s}}'></span>" % params
    return f"<html><body>{head}{body}</body></html>"


def links(*hrefs: str) -> str:
    return "".join(f'<a href="./{h.replace(" ", "_")}">x</a>' for h in hrefs)


def fetcher(pages: dict[str, str]):
    """A fetch that answers from a dict, keyed by page name."""
    seen = []

    def fetch(url: str) -> str:
        import urllib.parse
        name = urllib.parse.unquote(url.rsplit("/", 1)[-1]).replace("_", " ")
        seen.append(name)
        if name not in pages:
            raise LookupError(f"no such page: {name}")
        return pages[name]

    fetch.seen = seen
    return fetch


# --- reading a page ---------------------------------------------------------

def test_paragraphs_are_the_body_and_nothing_else():
    html = page(
        "<p>" + "A paragraph long enough to count as one." + "</p>"
        "<p class='pagenum'>A scan number line that is quite long really.</p>"
        "<div class='ws-noexport'><p>Navigation the wiki flags as not the book.</p></div>"
        "<table><p>A table is never prose in these editions at all.</p></table>"
        "<p>short</p>"
        "<p>The second real paragraph of the chapter body.</p>"
    )
    _, paras = ws.parse(html)
    assert paras == ["A paragraph long enough to count as one.",
                     "The second real paragraph of the chapter body."]


def test_footnote_markers_go_but_superscripts_in_names_stay():
    html = page("<p>Mlle Cunégonde said something worth keeping here"
                "<sup class='reference'>[1]</sup>.</p>")
    _, paras = ws.parse(html)
    assert paras == ["Mlle Cunégonde said something worth keeping here."]


def test_header_names_the_chapter():
    html = page("<p>Body text that is easily long enough to survive.</p>",
                current="Chapitre premier")
    title, _ = ws.parse(html)
    assert title == "Chapitre premier"


def test_a_header_that_is_only_a_number_is_a_label_not_a_title():
    assert ws.header_title(page("", current="XVII")) is None
    assert ws.header_title(page("", current="Chapter 4")) is None


def test_wikitext_templates_are_unwrapped():
    assert ws.header_title(page("", current="{{sc|Première partie}}")) == "Première partie"


def test_a_title_repeated_as_the_first_line_is_dropped():
    html = page("<p>How Candide Was Brought Up in a Castle</p>"
                "<p>In the country of Westphalia there lived a baron.</p>",
                current="How Candide Was Brought Up in a Magnificent Castle")
    _, paras = ws.parse(html)
    assert paras == ["In the country of Westphalia there lived a baron."]


def test_credits_are_read_never_guessed():
    html = page("<p>x</p>", title="Candide, ou l&apos;Optimisme", author="Voltaire",
                translator="Tobias Smollett", year="1920")
    c = ws.credits(html)
    assert (c.author, c.translator, c.year) == ("Voltaire", "Tobias Smollett", "1920")
    assert c.edition == "Smollett · 1920"


def test_credits_of_a_page_that_names_no_translator():
    c = ws.credits(page("<p>x</p>", author="Jules Verne", year="1911"))
    assert c.translator is None
    assert c.edition == "1911"


# --- dialogue ---------------------------------------------------------------

def test_a_french_speech_run_comes_apart_at_the_dashes():
    fused = ("Il dit que oui. — Vraiment ? demanda-t-elle. "
             "— Vraiment, répondit-il.")
    assert ws.split_speeches(fused) == [
        "Il dit que oui.", "Vraiment ? demanda-t-elle.", "Vraiment, répondit-il."]


def test_a_dash_inside_a_sentence_is_left_alone():
    line = "Le baron — un homme de poids — entra sans frapper."
    assert ws.split_speeches(line) == [line]


def test_only_dash_dialogue_languages_are_split():
    html = page("<p>He said yes. — Really? she asked in plain English.</p>")
    assert len(ws.parse(html, split_dialogue=False)[1]) == 1
    assert len(ws.parse(html, split_dialogue=True)[1]) == 2
    assert "fr" in ws.DASH_DIALOGUE and "en" not in ws.DASH_DIALOGUE


# --- apparatus --------------------------------------------------------------

def test_a_colophon_at_either_end_is_dropped_and_reported():
    chapters = [{"paragraphs": ["Transcriber's note: this text was prepared from scans.",
                                "The book itself opens here, at last."]},
                {"paragraphs": ["The book itself ends here, at last.",
                                "This edition of the work was printed and bound in Kent."]}]
    kept, removed = ws.trim_apparatus(chapters)
    assert kept[0]["paragraphs"] == ["The book itself opens here, at last."]
    assert kept[1]["paragraphs"] == ["The book itself ends here, at last."]
    assert len(removed) == 2


def test_the_body_is_never_searched_for_apparatus():
    middle = {"paragraphs": ["He read the words all rights reserved on the flyleaf.",
                             "And then he went out into the rain."]}
    chapters = [{"paragraphs": ["The opening line of the book, unremarkable."]},
                middle,
                {"paragraphs": ["The closing line of the book, unremarkable."]}]
    kept, removed = ws.trim_apparatus(chapters)
    assert removed == []
    assert kept[1] is middle


# --- finding the chapters ---------------------------------------------------

def test_a_chapter_is_a_subpage_ending_in_a_number():
    assert ws.numbered("Candide/Chapter 1") == 1
    assert ws.numbered("Micromégas/Chapitre IV") == 4
    assert ws.numbered("Candide/Texte entier") is None
    assert ws.numbered("Madame Bovary/Procès") is None


def test_apparatus_pages_are_named_by_the_wiki_not_by_the_book():
    assert ws.is_apparatus_page("Salammbô/Notes")
    assert ws.is_apparatus_page("Candide/Texte entier")
    assert not ws.is_apparatus_page("Salammbô/Le Festin")


def test_numbered_subpages_resolve_straight_away():
    fetch = fetcher({"Candide": page(links("Candide/Chapter 1", "Candide/Chapter 2",
                                           "Candide/Audio"))})
    r = ws.resolve("en", "Candide", fetch)
    assert r.shape == "chapters"
    assert r.pages == ["Candide/Chapter 1", "Candide/Chapter 2"]


def test_named_chapters_resolve_once_apparatus_is_set_aside():
    fetch = fetcher({"Salammbô": page(links("Salammbô/Le Festin", "Salammbô/À Sicca",
                                            "Salammbô/Tanit", "Salammbô/Notes"))})
    r = ws.resolve("fr", "Salammbô", fetch)
    assert r.shape == "named"
    assert "Salammbô/Notes" not in r.pages
    assert len(r.pages) == 3


def test_a_translation_hub_is_followed_and_its_choices_kept():
    fetch = fetcher({
        "Madame Bovary": page("<p>English-language translations of Madame Bovary "
                              "include the following editions:</p>"
                              + links("Madame Bovary (Marx-Aveling translation)",
                                      "Madame Bovary (Russell translation)")),
        "Madame Bovary (Marx-Aveling translation)":
            page(links("Madame Bovary (Marx-Aveling translation)/Chapter 1",
                       "Madame Bovary (Marx-Aveling translation)/Chapter 2")),
    })
    r = ws.resolve("en", "Madame Bovary", fetch)
    assert r.shape == "translation"
    assert len(r.pages) == 2
    assert "Madame Bovary (Russell translation)" in r.choices


def test_editions_descend_into_whichever_holds_the_most_chapters():
    fetch = fetcher({
        "Candide, ou l’Optimisme": page(links("Candide, ou l’Optimisme/Beuchot 1829",
                                              "Candide, ou l’Optimisme/Garnier 1877")),
        "Candide, ou l’Optimisme/Beuchot 1829":
            page(links("Candide, ou l’Optimisme/Beuchot 1829/Chapitre 1")),
        "Candide, ou l’Optimisme/Garnier 1877":
            page(links("Candide, ou l’Optimisme/Garnier 1877/Chapitre 1",
                       "Candide, ou l’Optimisme/Garnier 1877/Chapitre 2")),
    })
    r = ws.resolve("fr", "Candide, ou l’Optimisme", fetch)
    assert r.shape == "edition"
    assert r.pages == ["Candide, ou l’Optimisme/Garnier 1877/Chapitre 1",
                       "Candide, ou l’Optimisme/Garnier 1877/Chapitre 2"]


def test_a_landing_page_finds_the_edition_standing_beside_it():
    fetch = fetcher({
        "Le Père Goriot": page(links("Le Père Goriot (1855)", "Auteur:Balzac")),
        "Le Père Goriot (1855)": page(links("Le Père Goriot (1855)/1",
                                            "Le Père Goriot (1855)/2")),
    })
    r = ws.resolve("fr", "Le Père Goriot", fetch)
    assert r.shape == "edition"
    assert len(r.pages) == 2


def test_a_work_on_one_page_is_that_page():
    fetch = fetcher({"Micromegas": page("<p>A voyage to the planet Saturn, told at length.</p>")})
    r = ws.resolve("en", "Micromegas", fetch)
    assert r.shape == "single"
    assert r.pages == ["Micromegas"]


def test_a_page_that_does_not_exist_is_not_offered_as_a_choice():
    fetch = fetcher({"Around the World in Eighty Days": page(
        '<a href="./Around_the_World_in_Eighty_Days_(Towle)">a</a>'
        '<a href="./Tour_of_the_World?action=edit&amp;redlink=1">b</a>')})
    r = ws.resolve("en", "Around the World in Eighty Days", fetch)
    assert all("?" not in c for c in r.choices)


def test_an_edition_that_resolves_to_nothing_says_so():
    fetch = fetcher({"Nothing": page("")})
    with pytest.raises(LookupError):
        ws.load("fr", "Nothing", fetch)


# --- loading ----------------------------------------------------------------

def test_load_reads_the_chapters_and_credits_the_edition():
    body = "<p>A paragraph of the chapter, long enough to be kept.</p>"
    fetch = fetcher({
        "Candide": page(links("Candide/Chapter 1", "Candide/Chapter 2"),
                        author="Voltaire", translator="Tobias Smollett", year="1920"),
        "Candide/Chapter 1": page(body, current="What Befell Candide"),
        "Candide/Chapter 2": page(body, current="What Befell Him Next"),
    })
    edition = ws.load("en", "Candide", fetch)
    assert [c["title"] for c in edition.chapters] == ["What Befell Candide", "What Befell Him Next"]
    assert edition.credits.translator == "Tobias Smollett"
    assert edition.paragraphs == 2
    assert ws.to_chapters(edition)[0].number == "1"


def test_a_chapter_with_no_prose_is_not_a_chapter():
    fetch = fetcher({
        "Book": page(links("Book/1", "Book/2")),
        "Book/1": page("<p>Real prose, and enough of it to be counted.</p>"),
        "Book/2": page("<p>tiny</p>"),
    })
    edition = ws.load("fr", "Book", fetch)
    assert len(edition.chapters) == 1


def test_progress_is_reported_page_by_page():
    fetch = fetcher({
        "Book": page(links("Book/1", "Book/2")),
        "Book/1": page("<p>Real prose, and enough of it to be counted.</p>"),
        "Book/2": page("<p>More real prose, and enough of it to count.</p>"),
    })
    seen = []
    ws.load("fr", "Book", fetch, lambda i, t: seen.append((i, t)))
    assert seen == [(1, 2), (2, 2)]


# --- looking a book up ------------------------------------------------------

def test_search_returns_works_not_chapters():
    hits = json.dumps({"query": {"search": [
        {"title": "Germinal", "snippet": "Émile <span>Germinal</span> Zola"},
        {"title": "Germinal/Partie I/Chapitre 4", "snippet": "x"},
        {"title": "Germinal (Pouget)", "snippet": "y"},
    ]}})
    found = ws.search("germinal", "fr", 6, fetch=lambda url: hits)
    assert [h.title for h in found.hits] == ["Germinal", "Germinal (Pouget)"]
    assert found.hits[0].snippet == "Émile Germinal Zola"
    assert found.more == 0


def test_a_search_pages_on_works_and_counts_what_it_did_not_show():
    """The cap the lookup used to keep to itself: four shown, the rest silent."""
    rows = [{"title": f"Book {i}", "snippet": "s"} for i in range(1, 8)]
    rows.insert(2, {"title": "Book 2/Chapitre 1", "snippet": "not a work"})
    hits = json.dumps({"query": {"search": rows}})

    first = ws.search("zola", "fr", 4, fetch=lambda url: hits)
    assert [h.title for h in first.hits] == ["Book 1", "Book 2", "Book 3", "Book 4"]
    # A chapter page is not one of the three left behind.
    assert first.more == 3

    second = ws.search("zola", "fr", 4, offset=4, fetch=lambda url: hits)
    assert [h.title for h in second.hits] == ["Book 5", "Book 6", "Book 7"]
    assert second.more == 0


def test_a_header_is_read_in_the_language_the_wiki_writes_it_in():
    """fr.wikisource's Germinal says `auteur`, not `author` — so looking for one
    spelling read the byline off half the library, and the French half is the
    half every original comes from."""
    french = page("<p>x</p>", auteur="[[Auteur:Émile Zola|Émile Zola]]",
                  titre="Germinal", annee="1885")
    assert ws.credits(french).author == "Émile Zola"
    assert ws.credits(french).title == "Germinal"
    assert ws.credits(french).year == "1885"
    english = page("<p>x</p>", author="Emile Zola", translator="Havelock Ellis")
    assert ws.credits(english).author == "Emile Zola"
    assert ws.credits(english).translator == "Havelock Ellis"
    assert ws.credits(page("<p>x</p>")).author is None


def test_a_counterpart_is_the_wikis_own_link_or_nothing():
    reply = json.dumps({"query": {"pages": [
        {"title": "Madame Bovary", "langlinks": [{"lang": "en", "title": "Madame Bovary"}]},
        {"title": "Germinal"},
    ]}})
    found = ws.counterparts(["Madame Bovary", "Germinal"], "fr", "en", lambda url: reply)
    assert found == {"Madame Bovary": "Madame Bovary", "Germinal": None}


def test_asking_after_nothing_asks_the_wiki_nothing():
    def refuse(url):
        raise AssertionError("should not have called out")

    assert ws.counterparts([], fetch=refuse) == {}


# The wiki's own drop-cap markup, byte for byte as Madame Bovary carries it: the
# space sits *inside* the floated span, where rendering swallows it and reading
# does not.
DROP_CAP = (
    '<p><span style="font-size:0; line-height:0; display:block" class="lettrine">'
    '<br/></span><span class="dropinitial" style="float: left">N </span>'
    '<span class="sc">ous</span> étions à l’étude, quand le Proviseur entra, '
    'suivi d’un nouveau habillé en bourgeois.</p>'
)


def test_a_drop_cap_does_not_split_the_first_word():
    """The most looked-at word in a book is the one it opens with."""
    _, paragraphs = ws.parse(page(DROP_CAP))
    assert paragraphs[0].startswith("Nous étions à l’étude")


def test_a_drop_cap_leaves_the_rest_of_the_paragraph_alone():
    _, paragraphs = ws.parse(page(DROP_CAP))
    assert paragraphs[0].endswith("habillé en bourgeois.")
    assert "  " not in paragraphs[0]


# Twenty Thousand Leagues sets its drop cap as a scan of the printed initial.
# The letter is in the image's alt text and nowhere else, so a parser that drops
# images beheads the first word of every chapter: "HE year 1866".
DROP_CAP_IMAGE = (
    '<p><span class="dropinitial drop-initial-image"><span class="dropinitial-mid">'
    '<span class="dropinitial-initial"><span typeof="mw:File"><a href="./File:Initial_T.png">'
    '<img alt="T" resource="./File:Initial_T.png" height="64" width="60"/></a>'
    '</span></span></span></span>HE year 1866 was signalized by a remarkable incident.</p>'
)

# The same edition's heading, which it sets as an ordinary centred paragraph
# with no header to name it. The <br> is what puts the space in "XIII THE".
HEADING_PARA = (
    '<div class="wst-center"><p>CHAPTER XIII<br/>'
    '<span style="font-size:69%;">THE BLACK RIVER</span></p></div>'
    '<p>The part of the terrestrial globe which we were crossing was vast indeed.</p>'
)


def test_a_drop_cap_drawn_as_a_picture_still_reads_as_its_letter():
    """The alt text is the wiki naming the letter, not us guessing it."""
    _, paragraphs = ws.parse(page(DROP_CAP_IMAGE))
    assert paragraphs[0].startswith("THE year 1866")


def test_a_picture_that_is_not_a_drop_cap_contributes_nothing():
    """Elsewhere an alt describes an illustration and is not part of the prose."""
    _, paragraphs = ws.parse(page(
        '<p>The Nautilus lay still.<img alt="The Nautilus at rest"/> Nobody spoke '
        'for a long while, and the lamps burned low.</p>'))
    assert "The Nautilus at rest" not in paragraphs[0]


def test_a_centred_heading_paragraph_becomes_the_chapter_title():
    title, paragraphs = ws.parse(page(HEADING_PARA))
    assert title == "THE BLACK RIVER"
    assert paragraphs[0].startswith("The part of the terrestrial globe")


def test_a_heading_shaped_first_line_that_is_not_centred_is_left_as_prose():
    """Shape alone is not enough — a first sentence may open this way."""
    title, paragraphs = ws.parse(page(
        "<p>Chapter XI was the best of them, and he read it twice over.</p>"
        "<p>Then he put the book down and went out into the rain.</p>"))
    assert title is None
    assert paragraphs[0].startswith("Chapter XI was the best")


def test_the_heading_is_found_under_a_volume_title_standing_above_it():
    """Chapter one prints the book's name over the heading — the one chapter
    everybody opens, and the only one a top-of-page rule would have missed."""
    title, paragraphs = ws.parse(page(
        '<div class="wst-center"><p>Twenty Thousand Leagues Under the Sea.</p></div>'
        + HEADING_PARA))
    assert title == "THE BLACK RIVER"
    assert paragraphs[0] == "Twenty Thousand Leagues Under the Sea."


def test_ordinary_spans_keep_the_spaces_around_them():
    """The fix must not eat the spacing of every other inline span."""
    body = ('<p>He said <i>bonjour</i> and then <span class="sc">left</span> '
            'the room without another word.</p>')
    _, paragraphs = ws.parse(page(body))
    assert paragraphs[0] == "He said bonjour and then left the room without another word."


def test_a_line_break_separates_words():
    """<br> is whitespace. Dropped outright it ran headings together — the 1911
    Twenty Thousand Leagues gave "CHAPTER VIIIMOBILIS IN MOBILI".

    Read off the title now that such a heading is lifted into one, which tests
    the break just as sharply: run together, the numeral swallows the M and the
    title comes out "OBILIS IN MOBILI".
    """
    body = ('<div class="wst-center"><p><span style="font-size:120%;">CHAPTER VIII</span>'
            '<br/><span style="font-size:83%;">MOBILIS IN MOBILI</span></p></div>')
    title, _ = ws.parse(page(body))
    assert title == "MOBILIS IN MOBILI"


def test_verse_set_with_breaks_keeps_its_words_apart():
    body = ("<p>Roses are red<br/>violets are blue<br/>and every line of this "
            "little verse is set with a break.</p>")
    _, paragraphs = ws.parse(page(body))
    assert paragraphs[0] == ("Roses are red violets are blue and every line of this "
                             "little verse is set with a break.")
