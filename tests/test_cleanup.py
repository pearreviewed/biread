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
    # A wrapped block is body text however short, because titles are never wrapped.
    chapters, _ = detect_chapters("CHAPITRE I.\n\nIl faisait\nnuit.\n\nPuis le jour.")
    assert chapters[0].title is None
    assert chapters[0].paragraphs == ["Il faisait nuit.", "Puis le jour."]


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
