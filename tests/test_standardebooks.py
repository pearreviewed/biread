"""Reading a published translation out of Standard Ebooks, offline."""
from biread.standardebooks import Book, address, load, parse, search, text_url

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

SEARCH = """
<a href="/ebooks/gustave-flaubert/salammbo/j-s-chartres">Salammbo</a>
<a href="/ebooks/gustave-flaubert/salammbo/j-s-chartres">Salammbo</a>
<a href="/ebooks/emile-zola/doctor-pascal">Doctor Pascal</a>
<a href="/ebooks/not-a-book">nope</a>
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
    found = search("flaubert", fetch=lambda url: SEARCH)
    assert found[0] == Book("/ebooks/gustave-flaubert/salammbo/j-s-chartres",
                            "Gustave Flaubert", "Salammbo", "J S Chartres")
    assert found[0].label == "Salammbo · J S Chartres"


def test_an_uncredited_translation_is_not_called_an_english_original():
    """Zola's Doctor Pascal carries no translator slug and is still a
    translation. Absence of a credit is absence of a credit, nothing more."""
    found = search("zola", fetch=lambda url: SEARCH)
    pascal = next(b for b in found if b.title == "Doctor Pascal")
    assert pascal.translator is None
    assert pascal.label == "Doctor Pascal"


def test_a_work_is_listed_once_however_often_the_page_links_it():
    assert len(search("flaubert", fetch=lambda url: SEARCH)) == 2


def test_nothing_opens_a_socket_by_itself():
    seen = []

    def fetch(url):
        seen.append(url)
        return PAGE

    load("/ebooks/gustave-flaubert/salammbo/j-s-chartres", fetch=fetch)
    assert seen == [text_url("/ebooks/gustave-flaubert/salammbo/j-s-chartres")]
    assert seen[0].endswith("/text/single-page")
