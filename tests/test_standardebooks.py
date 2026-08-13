"""Reading a published translation out of Standard Ebooks, offline."""
from biread.standardebooks import Book, address, by_author, load, parse, search, text_url

# The shape the site actually serves: front and back matter are sections too,
# and are told apart from the body only by what they declare themselves to be.
PAGE = """
<body>
<section class="core-css" id="titlepage" epub:type="frontmatter titlepage">
  <p>By Gustave Flaubert.</p>
  <p>Translated by J. S. Chartres.</p>
</section>
<section id="chapter-1" epub:type="bodymatter chapter z3998:fiction">
  <h2 epub:type="ordinal">I</h2>
  <p>It was at Megara, a suburb of Carthage, in the gardens of Hamilcar.</p>
  <p>The soldiers whom he had commanded in Sicily were feasting.</p>
  <p>short</p>
</section>
<section id="chapter-2" epub:type="bodymatter chapter z3998:fiction">
  <h2 epub:type="ordinal">II</h2>
  <p>Two days afterwards the Mercenaries left Carthage for the open country.</p>
</section>
<section id="colophon" epub:type="backmatter colophon">
  <p>This ebook was produced by volunteers and is in the public domain.</p>
</section>
</body>
"""

# Five result rows as the live site served them on 2026-08-13, from the searches
# for "george sand" and "zola". Verbatim but for the duplicated `<source
# srcset>` elements, dropped for length — the cover URL under test survives
# whole in the `<img>` each row keeps.
#
# Two of them are books the site lists and has *not* made: Little Fadette and
# The Debacle say "We don't have this ebook in our catalog yet" on the page
# behind them, and their /text/single-page is a 404. They are told from the
# three real ones by the cover alone: a produced book's row draws the one the
# site made for it, an unmade book's draws `<div class="placeholder-cover">`.
SEARCH = """
<li typeof="schema:Book" about="/ebooks/george-sand/mauprat/stanley-young">
 <div class="thumbnail-container" aria-hidden="true"> <a href="/ebooks/george-sand/mauprat/stanley-young" tabindex="-1" property="schema:url">
 <picture> <img src="/images/covers/george-sand_mauprat_stanley-young/6cf6194dfcd0ec7ee36fb584d8d6cc56a928e51d/cover@2x.jpg" alt="" property="schema:image" height="335" width="224" loading="lazy"/>
 </picture>
 </a>
 </div>
 <p><a href="/ebooks/george-sand/mauprat/stanley-young" property="schema:url"><span property="schema:name">Mauprat</span></a></p>
 <p class="author" typeof="schema:Person" property="schema:author" resource="/ebooks/george-sand"><a href="https://standardebooks.org/ebooks/george-sand" property="schema:url"><span property="schema:name">George Sand</span></a></p>
 </li>
<li typeof="schema:Book" about="/ebooks/george-sand/the-devils-pool/jane-minot-sedgwick_ellery-sedgwick">
 <div class="thumbnail-container" aria-hidden="true"> <a href="/ebooks/george-sand/the-devils-pool/jane-minot-sedgwick_ellery-sedgwick" tabindex="-1" property="schema:url">
 <picture> <img src="/images/covers/george-sand_the-devils-pool_jane-minot-sedgwick_ellery-sedgwick/edb054abfe1aea5f60dd9ded21abac1c7c847e6e/cover@2x.jpg" alt="" property="schema:image" height="335" width="224" loading="lazy"/>
 </picture>
 </a>
 </div>
 <p><a href="/ebooks/george-sand/the-devils-pool/jane-minot-sedgwick_ellery-sedgwick" property="schema:url"><span property="schema:name">The Devil’s Pool</span></a></p>
 <p class="author" typeof="schema:Person" property="schema:author" resource="/ebooks/george-sand"><a href="https://standardebooks.org/ebooks/george-sand" property="schema:url"><span property="schema:name">George Sand</span></a></p>
 </li>
<li typeof="schema:Book" about="/ebooks/george-sand/little-fadette/hamish-miles">
 <div class="thumbnail-container" aria-hidden="true"> <a href="/ebooks/george-sand/little-fadette/hamish-miles" tabindex="-1" property="schema:url">
 <div class="placeholder-cover"></div> </a>
 </div>
 <p><a href="/ebooks/george-sand/little-fadette/hamish-miles" property="schema:url"><span property="schema:name">Little Fadette</span></a></p>
 <p class="author" typeof="schema:Person" property="schema:author" resource="/ebooks/george-sand"><a href="https://standardebooks.org/ebooks/george-sand" property="schema:url"><span property="schema:name">George Sand</span></a></p>
 </li>
<li typeof="schema:Book" about="/ebooks/matthew-arnold/poetry">
 <div class="thumbnail-container" aria-hidden="true"> <a href="/ebooks/matthew-arnold/poetry" tabindex="-1" property="schema:url">
 <picture> <img src="/images/covers/matthew-arnold_poetry/e88d785e6d2cbb80a6a2e858656f85b52d5523c0/cover@2x.jpg" alt="" property="schema:image" height="335" width="224" loading="lazy"/>
 </picture>
 </a>
 </div>
 <p><a href="/ebooks/matthew-arnold/poetry" property="schema:url"><span property="schema:name">Poetry</span></a></p>
 <p class="author" typeof="schema:Person" property="schema:author" resource="/ebooks/matthew-arnold"><a href="https://standardebooks.org/ebooks/matthew-arnold" property="schema:url"><span property="schema:name">Matthew Arnold</span></a></p>
 </li>
<li typeof="schema:Book" about="/ebooks/emile-zola/the-debacle">
 <div class="thumbnail-container" aria-hidden="true"> <a href="/ebooks/emile-zola/the-debacle" tabindex="-1" property="schema:url">
 <div class="placeholder-cover"></div> </a>
 </div>
 <p><a href="/ebooks/emile-zola/the-debacle" property="schema:url"><span property="schema:name">The Debacle</span></a></p>
 <p class="author" typeof="schema:Person" property="schema:author" resource="/ebooks/emile-zola"><a href="https://standardebooks.org/ebooks/emile-zola" property="schema:url"><span property="schema:name">Émile Zola</span></a></p>
 </li>
"""


PARTED = """
<body>
<section id="halftitlepage" epub:type="frontmatter halftitlepage"><p>Les Miserables</p></section>
<section id="volume-1" epub:type="bodymatter part">
  <h2>Fantine</h2>
  <section id="chapter-1-1-1" epub:type="chapter">
    <h3>Monsieur Myriel</h3>
    <p>In 1815, Monsieur Charles-Francois-Bienvenu Myriel was Bishop of Digne.</p>
  </section>
  <section id="chapter-1-1-2" epub:type="chapter">
    <h3>Monsieur Myriel Becomes Monseigneur Bienvenu</h3>
    <p>The episcopal palace of Digne adjoined the hospital, a narrow building.</p>
  </section>
</section>
</body>
"""


def test_a_chapter_knows_where_it_sits_in_the_work():
    """Read as two flat runs, Les Misérables' 364 French chapters against 365
    English ones drift: one missing chapter shifts every pairing after it, and
    the drift is silent because the opening chapters still look right. Both
    editions state the real address, so pair on that."""
    assert [address(c) for c in parse(PARTED)] == [(1, 1, 1), (1, 1, 2)]


def test_a_chapter_with_no_address_says_so_rather_than_guessing():
    assert address({"id": None}) is None
    assert address({}) is None


def test_a_book_divided_into_parts_still_yields_its_chapters():
    """Les Miserables carries bodymatter on the division and chapter on the 365
    sections inside it, so requiring both words on one section finds nothing."""
    chapters = parse(PARTED)
    assert [c["title"] for c in chapters] == [
        "Monsieur Myriel", "Monsieur Myriel Becomes Monseigneur Bienvenu"]
    assert chapters[0]["paragraphs"][0].startswith("In 1815")


def test_the_part_itself_is_not_counted_as_a_chapter():
    assert len(parse(PARTED)) == 2  # not 3 — "Fantine" is a division, not a chapter


def test_only_the_bodymatter_chapters_are_read():
    """The title page and the colophon are sections too — the file says which."""
    chapters = parse(PAGE)
    assert [c["number"] for c in chapters] == ["1", "2"]
    assert "Translated by" not in " ".join(chapters[0]["paragraphs"])
    assert "public domain" not in " ".join(chapters[-1]["paragraphs"])


def test_the_chapter_keeps_its_prose_and_its_heading():
    first = parse(PAGE)[0]
    assert first["title"] == "I"
    assert first["paragraphs"][0].startswith("It was at Megara")
    assert "short" not in first["paragraphs"]  # too short to be a paragraph


def test_the_translator_comes_from_the_url_so_a_card_costs_no_extra_request():
    found = search("george sand", fetch=lambda url: SEARCH)
    assert found[0] == Book("/ebooks/george-sand/mauprat/stanley-young",
                            "George Sand", "Mauprat", "Stanley Young")
    assert found[0].label == "Mauprat · Stanley Young"


def test_an_uncredited_edition_is_not_called_an_english_original():
    """A missing third segment is a missing credit and nothing more. It happens
    to an English original (Dickens carries none) and to a translation nobody
    has been assigned to yet — nine of Zola's works here are uncredited and
    every one of them is a translation."""
    found = search("zola", fetch=lambda url: SEARCH, include_unproduced=True)
    debacle = next(b for b in found if b.title == "The Debacle")
    assert debacle.translator is None
    assert debacle.label == "The Debacle"


def test_two_translators_are_credited_the_way_the_site_credits_them():
    """The Devil's Pool is `jane-minot-sedgwick_ellery-sedgwick`, and the site
    reads that out as "Jane Minot Sedgwick and Ellery Sedgwick". The underscore
    was missing from the path pattern, so this book — produced and readable, and
    one of only two George Sand editions that exist here — was dropped from
    every search it appeared in."""
    found = search("george sand", fetch=lambda url: SEARCH)
    pool = next(b for b in found if b.path.endswith("_ellery-sedgwick"))
    assert pool.translator == "Jane Minot Sedgwick and Ellery Sedgwick"


def test_a_book_the_site_has_not_made_is_not_offered():
    """Search lists what is in the public domain beside what has been produced,
    in the same markup. Little Fadette and The Debacle say "We don't have this
    ebook in our catalog yet" on the page behind them and their
    /text/single-page is a 404, so a reader who picked one from the lookup
    screen chose a book that failed at fetch time, minutes later, having already
    been offered it."""
    titles = [b.title for b in search("george sand", fetch=lambda url: SEARCH)]
    assert "Little Fadette" not in titles
    assert titles == ["Mauprat", "The Devils Pool", "Poetry"]


def test_an_unmade_book_is_marked_rather_than_guessed_at_when_it_is_asked_for():
    """Read off the row's own cover, so a caller that wants the whole listing
    still knows which half of it can be read."""
    everything = search("george sand", fetch=lambda url: SEARCH, include_unproduced=True)
    made = {b.title: b.produced for b in everything}
    assert made == {"Mauprat": True, "The Devils Pool": True, "Little Fadette": False,
                    "Poetry": True, "The Debacle": False}


def test_the_two_covers_are_the_only_two_things_a_row_says_about_itself():
    """The marker read is the cover, not the placeholder, because the two
    failures are not equal: were the placeholder renamed, reading it would call
    every unmade book produced and send readers back into builds that 404. This
    pins the pair so a rename is caught here instead."""
    rows = SEARCH.split("<li ")[1:]
    for row in rows:
        assert ("/images/covers/" in row) != ("placeholder-cover" in row)


def test_a_work_is_listed_once_however_often_the_page_links_it():
    """Each row links the same work three times over: the cover, the title and
    a translator's name all point at it."""
    assert len(search("george sand", fetch=lambda url: SEARCH)) == 3


def test_an_authors_shelf_holds_nobody_elses():
    """A title alone is too loose to trust — searching the live site for
    "germinal" also returns Voltairine de Cleyre's poetry — so results are held
    to the author, and offering the wrong book is worse than offering none."""
    mine = by_author("George Sand", fetch=lambda url: SEARCH)
    assert [b.title for b in mine] == ["Mauprat", "The Devils Pool"]


def test_an_author_is_the_same_author_however_the_url_had_to_spell_them():
    """Wikisource writes "Émile Zola"; a URL slug cannot, and says emile-zola."""
    zola = by_author("Émile Zola", fetch=lambda url: SEARCH, include_unproduced=True)
    assert [b.title for b in zola] == ["The Debacle"]


def test_an_author_the_site_lists_but_has_made_nothing_by_comes_back_empty():
    """Zola is the case to picture: twelve works there and two of them made, so
    an author can be present and still have nothing to offer. Empty is what the
    lookup screen already knows how to say."""
    assert by_author("Émile Zola", fetch=lambda url: SEARCH) == []


def test_an_author_nobody_here_carries_comes_back_empty_not_approximate():
    assert by_author("Marcel Proust", fetch=lambda url: SEARCH) == []
    assert by_author("", fetch=lambda url: SEARCH) == []


def test_nothing_opens_a_socket_by_itself():
    seen = []

    def fetch(url):
        seen.append(url)
        return PAGE

    load("/ebooks/gustave-flaubert/salammbo/j-s-chartres", fetch=fetch)
    assert seen == [text_url("/ebooks/gustave-flaubert/salammbo/j-s-chartres")]
    assert seen[0].endswith("/text/single-page")


NOTED = """
<body>
<section id="chapter-1" epub:type="bodymatter chapter z3998:fiction">
  <p>Down with the Pope, the whole pack of them!<a href="endnotes.xhtml#note-1" epub:type="noteref">1</a></p>
  <p>Comme la nuit se fait lorsque le jour s’en va.<a href="endnotes.xhtml#note-115"
     epub:type="noteref">115</a></p>
  <p>It was the year 1815, and he had been bishop since 1806 in that town.</p>
</section>
</body>
"""


def test_an_endnote_marker_does_not_end_up_glued_to_the_prose():
    """Les Misérables ended on "…lorsque le jour s'en va.115" and carried 104 of
    these; Notre-Dame 37. Dropped on the file's own say-so, never by hunting for
    digits — which would take the year out of a date."""
    chapters = parse(NOTED)
    paragraphs = chapters[0]["paragraphs"]
    assert paragraphs[0] == "Down with the Pope, the whole pack of them!"
    assert paragraphs[1].endswith("lorsque le jour s’en va.")
    assert "1815" in paragraphs[2] and "1806" in paragraphs[2]
