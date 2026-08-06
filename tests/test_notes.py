"""Finding a book's apparatus without eating its prose."""
from biread.notes import Note, references, scan

PROSE = "Il s'appelait Micromégas[1], nom qui lui convient fort."
NOTE = "[1] De micros, petit, et de megas, grand."


def test_a_note_the_prose_points_at_is_taken_out():
    prose, notes = scan([PROSE, NOTE])
    assert prose == [PROSE]
    assert notes == [Note(1, NOTE)]


def test_a_paragraph_shaped_like_a_note_but_referred_to_by_nothing_stays():
    """"1." opens a note in one book and an ordinary list in another, and there
    is no telling them apart by looking. A wrongly deleted sentence is silent."""
    listed = ["Trois choses le frappèrent :", "1. la taille des habitants.",
              "2. leur nombre.", "3. leur silence."]
    prose, notes = scan(listed[:2])
    assert prose == listed[:2]
    assert notes == []


def test_the_run_of_notes_that_closes_a_chapter_goes_without_being_referred_to():
    # Editions often print the notes and drop the marks from the prose.
    body = ["Le vrai texte du livre.", "1. Une note.", "2. Une autre note."]
    prose, notes = scan(body)
    assert prose == ["Le vrai texte du livre."]
    assert [n.number for n in notes] == [1, 2]


def test_one_trailing_numbered_paragraph_is_not_a_run():
    body = ["Le vrai texte.", "1. Une phrase qui commence par un chiffre."]
    prose, notes = scan(body)
    assert prose == body
    assert notes == []


def test_a_trailing_run_must_be_numbered_in_order():
    body = ["Le texte.", "5. Cinquième.", "9. Neuvième."]
    assert scan(body)[1] == []


def test_every_shape_an_edition_writes_a_note_in():
    for text, marker in [("[2] A note.", "un mot[2] ici"), ("(2) A note.", "un mot(2) ici"),
                         ("² A note.", "un mot² ici"), ("2. A note.", "un mot[2] ici")]:
        prose, notes = scan([marker, text])
        assert notes and notes[0].number == 2, text


def test_a_bare_marker_in_the_prose_is_not_a_reference():
    # A note's own opening marker must not corroborate the note itself.
    prose, notes = scan(["[1] De micros, petit."])
    assert prose == ["[1] De micros, petit."]
    assert notes == []


def test_references_reads_every_mark_the_prose_carries():
    assert references(["un mot[1] et un autre¹", "puis(3) enfin"]) == {1, 3}


def test_a_book_with_no_apparatus_is_returned_untouched():
    body = ["Premier paragraphe.", "Deuxième paragraphe."]
    assert scan(body) == (body, [])


# ---- through the whole pipeline ----

def test_a_note_is_taken_out_by_a_real_clean_run():
    from biread.cleanup import clean

    source = (
        "CHAPITRE I.\nTitre\n\n"
        "Il s'appelait Micromégas(1), nom qui lui convient fort.\n\n"
        "(1) De micros, petit, et de megas, grand.\n"
    )
    chapters, removed = clean(source)
    assert chapters[0].paragraphs == ["Il s'appelait Micromégas(1), nom qui lui convient fort."]
    assert [r.detail for r in removed if r.kind == "Note"] == [
        "[1] (1) De micros, petit, et de megas, grand."
    ]


def test_a_chapter_of_plain_prose_keeps_every_paragraph():
    from biread.cleanup import clean

    source = "CHAPITRE I.\nTitre\n\nPremier paragraphe.\n\nDeuxième paragraphe.\n"
    chapters, removed = clean(source)
    assert len(chapters[0].paragraphs) == 2
    assert not [r for r in removed if r.kind == "Note"]


# ---- a whole apparatus run together into one paragraph ----

FUSED = (
    "FIN [1] - Un mot laissé en blanc. [2] - Un mot est raturé, un autre "
    "rajouté en surcharge est illisible. [3] - Du soir, évidemment. "
    "[4] - Le texte du feuillet sans date s'arrête ici."
)


def test_an_apparatus_fused_into_one_paragraph_is_split_back_out():
    """An edition whose notes are set close together arrives as a single block:
    the French Nausea ends on twelve editor's notes and the novel's last word in
    one paragraph of fourteen hundred characters."""
    prose, notes = scan(["Le vrai texte du livre.", FUSED])
    assert prose == ["Le vrai texte du livre.", "FIN"]
    assert [n.number for n in notes] == [1, 2, 3, 4]
    assert notes[2].text == "[3] - Du soir, évidemment."


def test_a_paragraph_that_is_nothing_but_its_notes_leaves_nothing_behind():
    prose, notes = scan([FUSED.removeprefix("FIN ")])
    assert prose == []
    assert len(notes) == 4


def test_numbers_that_do_not_count_are_left_where_they_are():
    """Prose does not enumerate itself, which is the whole of the corroboration.
    Bracketed figures that are not a run are somebody's citation."""
    cited = "Voyez Berger [6] et Champion [11] sur ce point, et aussi [2] plus haut."
    prose, notes = scan([cited])
    assert prose == [cited]
    assert notes == []


def test_a_fused_run_must_start_at_one():
    # A note numbered 5 with nothing before it is a reference into an apparatus
    # printed elsewhere, not the apparatus itself.
    tail = "Le texte. [5] - Cinquième. [6] - Sixième. [7] - Septième."
    prose, notes = scan([tail])
    assert prose == [tail]
    assert notes == []


def test_two_fused_notes_are_too_few():
    # A break that is not in the file is weaker evidence than one that is, so it
    # is asked for more: three where a paragraph of its own needs two.
    pair = "Le texte. [1] - Une note. [2] - Une autre."
    prose, notes = scan([pair])
    assert prose == [pair]
    assert notes == []
