from biread.numbering import to_roman
from biread.cleanup import clean, detect_chapters, rejoin_paragraphs, strip_boilerplate

GUTENBERG = """The Project Gutenberg eBook of Something
Licensing blah blah.

*** START OF THE PROJECT GUTENBERG EBOOK SOMETHING ***

CHAPITRE I.
Le Commencement

Voici le premier paragraphe qui
continue sur une deuxième ligne.

*** END OF THE PROJECT GUTENBERG EBOOK SOMETHING ***

Footer with license terms.
"""


def test_strips_gutenberg_wrapper():
    text, removed = strip_boilerplate(GUTENBERG)
    assert "Licensing blah blah" not in text
    assert "Footer with license terms" not in text
    assert "premier paragraphe" in text
    assert {r.kind for r in removed} == {
        "Project Gutenberg license header",
        "Project Gutenberg license footer",
    }


def test_leaves_unrecognized_text_alone():
    text, removed = strip_boilerplate("Juste du texte.\n\nEt encore.")
    assert text == "Juste du texte.\n\nEt encore."
    assert removed == []


def test_strips_wikisource_chrome():
    source = "\n".join([
        "Micromégas/Texte entier",
        "Ajouter des langues",
        "< Micromégas",
        "◄  Chapitre précédent",
        "Catégories : Romans",
        "Ce texte est dans le domaine public.",
        "Le vrai texte du livre.",
    ])
    text, removed = strip_boilerplate(source)
    assert text.strip() == "Le vrai texte du livre."
    assert len(removed) == 6


def test_rejoins_hard_wrapped_lines():
    paragraphs, _ = rejoin_paragraphs("Une ligne\nqui continue.\n\nUn autre bloc.")
    assert paragraphs == ["Une ligne qui continue.", "Un autre bloc."]


def test_collapses_justified_spacing_runs():
    """A PDF laid out with justified text arrives with runs of spaces between
    words; a paragraph should read with single spaces regardless."""
    paragraphs, _ = rejoin_paragraphs("Pangloss     enseignait     la\nmétaphysico.")
    assert paragraphs == ["Pangloss enseignait la métaphysico."]


def test_drops_bare_page_numbers():
    paragraphs, removed = rejoin_paragraphs("Du texte.\n[122]\n123\n\nPlus de texte.")
    assert paragraphs == ["Du texte.", "Plus de texte."]
    assert [r.detail for r in removed] == ["[122]", "123"]


def test_text_without_headings_is_one_chapter():
    chapters, _ = detect_chapters("Premier.\n\nDeuxième.")
    assert len(chapters) == 1
    assert chapters[0].number is None
    assert chapters[0].paragraphs == ["Premier.", "Deuxième."]


def test_detects_chapters_and_titles():
    source = "Avant-propos.\n\nCHAPITRE I.\nLe Départ\n\nUn paragraphe.\n\nCHAPITRE II.\nL'Arrivée\n\nUn autre.\n"
    chapters, _ = detect_chapters(source)
    assert [c.number for c in chapters] == [None, "I", "II"]
    assert [c.title for c in chapters] == [None, "Le Départ", "L'Arrivée"]
    assert chapters[1].paragraphs == ["Un paragraphe."]


def test_heading_and_title_may_share_a_block():
    # Wikisource runs the heading straight into its subtitle with no blank line.
    chapters, _ = detect_chapters("CHAPITRE I.\nLe Départ\n\nUn paragraphe.")
    assert chapters[0].title == "Le Départ"
    assert chapters[0].paragraphs == ["Un paragraphe."]


def test_short_opening_paragraph_is_not_mistaken_for_a_title():
    # The body's own opening — short sentences about as long as what follows —
    # stays body, even wrapped, because a title is clearly shorter than its passage.
    chapters, _ = detect_chapters("CHAPITRE I.\n\nIl faisait\nnuit.\n\nPuis le jour.")
    assert chapters[0].title is None
    assert chapters[0].paragraphs == ["Il faisait nuit.", "Puis le jour."]


def test_a_wrapped_argument_is_recognised_as_a_title():
    # An edition like Candide sets a descriptive argument under each chapter
    # number, which pypdf breaks across lines. It is short and clearly introduces
    # a much longer passage, so it is the chapter's title, not its first paragraph.
    argument = "Comment Candide fut eleve dans un\nbeau chateau, et comment il fut chasse."
    body = ("Il y avait en Westphalie, dans le chateau du baron, un jeune garcon a qui la "
            "nature avait donne les moeurs les plus douces, et le jugement le plus droit, "
            "avec l'esprit le plus simple; c'est, je crois, pour cette raison qu'on le nommait.")
    chapters, _ = detect_chapters(f"CHAPITRE I.\n\n{argument}\n\n{body}")
    assert chapters[0].title == "Comment Candide fut eleve dans un beau chateau, et comment il fut chasse."
    assert chapters[0].paragraphs == [body]


def test_chapter_with_a_single_block_keeps_it_as_body():
    chapters, _ = detect_chapters("CHAPITRE I.\n\nUne seule ligne.")
    assert chapters[0].title is None
    assert chapters[0].paragraphs == ["Une seule ligne."]


def test_clean_runs_the_whole_pipeline():
    chapters, removed = clean(GUTENBERG)
    assert [c.number for c in chapters] == ["I"]
    assert chapters[0].title == "Le Commencement"
    assert chapters[0].paragraphs == [
        "Voici le premier paragraphe qui continue sur une deuxième ligne."
    ]
    assert removed


FOOTNOTED = """CHAPITRE I.
Le Commencement

Le vrai texte du livre, qui continue
sur une deuxième ligne.

FIN DE L'HISTOIRE.
↑ De micros, petit, et de megas, grand.
↑ Voici ce passage tel qu'il est transcrit :

Ἐντελέχειά τις ἐςὶ καὶ λόγος.

Ce passage d'Aristote est ainsi traduit par Casaubon.

↑ Hypothèse des idées innées.
"""


def test_strips_the_trailing_footnote_apparatus():
    chapters, removed = clean(FOOTNOTED)
    body = [p for c in chapters for p in c.paragraphs]
    assert body == [
        "Le vrai texte du livre, qui continue sur une deuxième ligne.",
        "FIN DE L'HISTOIRE.",
    ]
    assert any(r.kind == "Wikisource footnote apparatus" for r in removed)


def test_footnote_content_without_a_marker_goes_too():
    # A note can run on past blank lines; Micromégas ends with one whose body
    # is Aristotle in Greek. Dropping only marked lines strands it in the book.
    chapters, _ = clean(FOOTNOTED)
    body = " ".join(p for c in chapters for p in c.paragraphs)
    assert "Ἐντελέχειά" not in body
    assert "Casaubon" not in body


def test_the_end_line_is_kept_and_not_glued_to_the_notes():
    # No blank line separates it from the first note in the source, so it would
    # otherwise be rejoined into one enormous paragraph.
    chapters, _ = clean(FOOTNOTED)
    assert "FIN DE L'HISTOIRE." in [p for c in chapters for p in c.paragraphs]
    assert all("micros" not in p for c in chapters for p in c.paragraphs)


def test_text_without_footnotes_is_untouched():
    chapters, removed = clean("CHAPITRE I.\nTitre\n\nUn paragraphe.\n")
    assert [p for c in chapters for p in c.paragraphs] == ["Un paragraphe."]
    assert not any(r.kind == "Wikisource footnote apparatus" for r in removed)


def test_strips_inline_footnote_references():
    chapters, removed = clean(
        "CHAPITRE I.\nTitre\n\nIl s'appelait Micromégas[1], nom qui convient[12] fort.\n"
    )
    assert chapters[0].paragraphs == ["Il s'appelait Micromégas, nom qui convient fort."]
    assert any(r.kind == "Footnote reference marker" for r in removed)


def test_a_footnote_body_is_dropped_whole_even_when_wrapped():
    # Published editions hard-wrap their notes; only the first line carries the
    # marker, so a line-by-line rule would leave the remainder as body text.
    source = (
        "CHAPITRE I.\nTitre\n\nLe vrai texte.\n\n"
        "[1] From micros, small, and from\nmegas, large. This note runs\nover three lines.\n"
    )
    chapters, removed = clean(source)
    assert chapters[0].paragraphs == ["Le vrai texte."]
    assert any(r.kind == "Footnote text" for r in removed)


def test_a_footnote_body_keeps_the_marker_that_identifies_it():
    # The inline rule is anchored on a preceding non-space precisely so a
    # paragraph that *is* a footnote is still recognisable as one.
    from biread.cleanup import FOOTNOTE_BODY_RE, FOOTNOTE_REF_RE
    assert FOOTNOTE_REF_RE.sub("", "[1] From micros, small.") == "[1] From micros, small."
    assert FOOTNOTE_BODY_RE.match("[1] From micros, small.")


def test_a_bare_page_number_is_not_mistaken_for_a_footnote():
    chapters, removed = clean("CHAPITRE I.\nTitre\n\nDu texte.\n[122]\n\nPlus de texte.\n")
    assert chapters[0].paragraphs == ["Du texte.", "Plus de texte."]
    assert any(r.kind == "Bare page-number artifact" for r in removed)


# ---- the transcription's own header ----

WIKISOURCE_HEADER = """Voltaire
Micromégas
Micromégas, Garnier, 1877, tome 21 (p. 105-122).
MICROMÉGAS
HISTOIRE PHILOSOPHIQUE

(1752)

CHAPITRE I.
LE DÉPART

Dans une de ces planètes il y avait un jeune homme.
"""


def test_the_source_citation_header_is_not_body_text():
    chapters, removed = clean(WIKISOURCE_HEADER)
    paragraphs = [p for c in chapters for p in c.paragraphs]
    assert not any("Garnier" in p for p in paragraphs)
    assert not any("HISTOIRE PHILOSOPHIQUE" in p for p in paragraphs)
    # The book opens on its first real sentence, not the header or the date.
    assert paragraphs[0] == "Dans une de ces planètes il y avait un jeune homme."
    assert [r.kind for r in removed].count("Source citation header") == 1


def test_a_page_citation_inside_the_book_is_left_alone():
    # The rule reads a leading block as apparatus. The same shape further in is
    # the author writing, and eating it would be losing text.
    body = WIKISOURCE_HEADER + "\nVoyez son Traité (p. 40-41) sur la matière.\n"
    paragraphs = [p for c in clean(body)[0] for p in c.paragraphs]
    assert any("Traité (p. 40-41)" in p for p in paragraphs)


def test_a_book_with_no_header_keeps_its_first_paragraph():
    plain = "CHAPITRE I.\nLE DÉPART\n\nIl monta l'escalier sans rien dire.\n"
    paragraphs = [p for c in clean(plain)[0] for p in c.paragraphs]
    assert paragraphs == ["Il monta l'escalier sans rien dire."]


def test_a_bare_year_in_the_front_matter_is_dropped():
    # "(1752)" is the work's date, apparatus — not the book's first paragraph.
    text = "(1752)\n\nCHAPITRE I.\nLE DÉPART\n\nDans une de ces planètes.\n"
    chapters, removed = clean(text)
    paragraphs = [p for c in chapters for p in c.paragraphs]
    assert paragraphs == ["Dans une de ces planètes."]
    assert any(r.kind == "Publication date" for r in removed)


def test_a_year_in_parentheses_inside_prose_is_kept():
    # Once real text has been kept, a parenthesised year is the author's own.
    text = "CHAPITRE I.\nLE DÉPART\n\nIl la publia (1752) sans un mot.\n"
    paragraphs = [p for c in clean(text)[0] for p in c.paragraphs]
    assert paragraphs == ["Il la publia (1752) sans un mot."]


def test_chapters_marked_by_a_lone_numeral_are_detected():
    # A Gutenberg PDF sets Candide's chapters as a bare roman numeral over an
    # all-caps title, with no "CHAPTER" word at all.
    text = (
        "Front matter no one numbered.\n\n"
        "I\n\nHOW IT BEGAN\n\nThe first thing that happened.\n\n"
        "II\n\nWHAT CAME NEXT\n\nThe second thing that happened.\n\n"
        "III\n\nTHE END\n\nThe third thing that happened.\n"
    )
    chapters, _ = clean(text)
    numbered = [c for c in chapters if c.number]
    assert [c.number for c in numbered] == ["I", "II", "III"]
    assert numbered[0].title == "HOW IT BEGAN"


def test_a_stray_numeral_in_prose_does_not_become_a_heading():
    # A lone numeral outside the ascending spine of real chapters is left as text.
    text = (
        "I\n\nFIRST\n\nA paragraph.\n\n"
        "II\n\nSECOND\n\nA paragraph mentioning\n\nV\n\nout of order.\n\n"
        "III\n\nTHIRD\n\nAnother paragraph.\n"
    )
    chapters, _ = clean(text)
    assert [c.number for c in chapters if c.number] == ["I", "II", "III"]


def test_two_lone_numerals_are_too_few_to_be_a_spine():
    text = "I\n\nsome text here that is ordinary prose.\n\nII\n\nmore ordinary prose.\n"
    chapters, _ = clean(text)
    # Not enough of a run to trust; the file stays one untitled section.
    assert all(c.number is None for c in chapters)


def test_page_numbers_that_merely_ascend_are_not_a_spine():
    # The Nausea PDF: a diary with no chapters at all, whose page numbers 99 and
    # 146 sit on lines of their own beside the tail of a wrapped sentence. All
    # three ascend, and the book was read as having four chapters — after which
    # trimming to the first of them deleted its opening third.
    text = (
        "The best thing would be to write down events from day to day.\n\n"
        "one.\n\n"
        "I must not put in strangeness where there is none.\n\n"
        "99\n\n"
        "I am the one who pulls myself from the nothingness.\n\n"
        "146\n\n"
        "There were many episodes I could no longer recall.\n"
    )
    chapters, _ = clean(text)
    assert all(c.number is None for c in chapters)


def test_a_lowercase_word_is_the_tail_of_a_sentence_not_a_heading():
    # "one." ends a sentence a PDF wrapped; "One." heads a chapter. Case is what
    # tells them apart, since both read as the number 1.
    from biread.cleanup import _written_as_a_heading
    assert _written_as_a_heading("One.") and _written_as_a_heading("IV") and _written_as_a_heading("12")
    assert not _written_as_a_heading("one.")


def test_chapters_headed_by_a_spelled_out_word_are_still_found():
    # Eleanor Marx's Madame Bovary heads its chapters "One", "Two", "Three" with
    # no heading word — capitalized, consecutive, and a spine.
    text = (
        "One\n\nA paragraph of ordinary prose.\n\n"
        "Two\n\nAnother paragraph of ordinary prose.\n\n"
        "Three\n\nA third paragraph of ordinary prose.\n"
    )
    chapters, _ = clean(text)
    assert [c.number for c in chapters if c.number] == ["One", "Two", "Three"]


def test_explicit_chapter_headings_still_win():
    text = "CHAPITRE I.\nLE DÉBUT\n\nUn paragraphe.\n\nCHAPITRE II.\nLA SUITE\n\nDeux.\n"
    chapters, _ = clean(text)
    assert [c.number for c in chapters if c.number] == ["I", "II"]


# ---- books in parts, and the contents list that shadows them ----

def _in_parts(counts):
    """A book whose chapters are numbered afresh in each part."""
    out = []
    for chapters in counts:
        for n in range(1, chapters + 1):
            out.append(f"{to_roman(n)}\n\nUne page de prose ordinaire, assez longue.\n")
    return "\n".join(out)


def test_numbering_that_starts_over_reads_as_a_new_part():
    # Madame Bovary is three parts numbered I..IX, I..XV, I..XI. Read as one
    # ascending spine, only the longest stretch survives and the rest is lost.
    chapters, _ = clean(_in_parts([9, 15, 11]))
    numbered = [c for c in chapters if c.number]
    assert len(numbered) == 35
    assert [c.part for c in numbered] == [1] * 9 + [2] * 15 + [3] * 11


def test_a_book_that_simply_counts_upward_is_in_no_parts():
    chapters, _ = clean(_in_parts([6]))
    assert {c.part for c in chapters if c.number} == {None}


def test_a_table_of_contents_does_not_become_the_book():
    """Its entries are headed exactly as the chapters are, and it comes first, so
    it offers a complete false spine. Bovary's whole novel landed under the last
    of its thirty-five contents lines."""
    contents = "\n".join(to_roman(n) for n in range(1, 7))
    chapters, _ = clean(contents + "\n\n" + _in_parts([6]))
    numbered = [c for c in chapters if c.number]
    assert len(numbered) == 6
    assert all(c.paragraphs for c in numbered)
