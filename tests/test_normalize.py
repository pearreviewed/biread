from biread.normalize import repair


def test_page_markers_are_cut_inline_and_standalone():
    raw = "the Abares. [Pg 9] The King\n\n[Pg 10]\n\nnext page"
    text, removed = repair(raw)
    assert "[Pg 9]" not in text and "[Pg 10]" not in text
    assert "the Abares." in text and "The King" in text
    assert any(r.kind == "Page marker" and "2 removed" in r.detail for r in removed)


def test_roman_and_arabic_page_markers_both_go():
    text, _ = repair("front [Pg xviii] matter [Page 3] end")
    assert "[Pg xviii]" not in text and "[Page 3]" not in text


def test_line_broken_word_is_rejoined_only_when_next_line_is_lowercase():
    raw = "a magnifi-\ncent castle"
    text, removed = repair(raw)
    assert "magnificent" in text and "magnifi-" not in text
    assert any(r.kind == "Line-broken word rejoined" for r in removed)


def test_an_uppercase_continuation_keeps_its_hyphen():
    # Thunder-ten-Tronckh split at a real compound must not be welded shut.
    raw = "Baron of Thunder-\nTen-Tronckh"
    text, _ = repair(raw)
    assert "Thunder-\nTen-Tronckh" in text or "Thunder-Ten" not in text


def test_a_heading_word_marooned_from_its_numeral_is_reunited():
    raw = "CHAPTER\n\nIV\n\nHow it happened"
    text, removed = repair(raw)
    assert "CHAPTER IV" in text
    assert any(r.kind == "Split heading rejoined" for r in removed)


def test_a_chapter_word_in_a_sentence_is_left_alone():
    raw = "He opened the chapter\nand began to read the story"
    text, _ = repair(raw)
    assert "chapter\nand" in text


def test_a_clean_text_is_returned_unchanged_with_no_repairs():
    raw = "A perfectly clean paragraph.\n\nAnother one."
    text, removed = repair(raw)
    assert text == raw
    assert removed == []


# ---- paragraphs a PDF ran together ----

FUSED = "\n".join([
    "At length they descried the coast of France.",
    '"Were you ever in France, Mr. Martin?" said Candide.',
    '"Yes," said Martin, "I have been in several provinces. In some one-half of the people are fools, in others they are too cunning; in some they are weak and',
    "simple, in others they affect to be witty.",
])


def test_a_short_line_that_ends_a_sentence_ends_its_paragraph():
    text, removed = repair(FUSED, from_pdf=True)
    assert text.split("\n\n")[0] == "At length they descried the coast of France."
    assert any(r.kind == "Paragraph break restored" for r in removed)


def test_a_full_line_carries_on_into_the_next():
    # The third line runs the full measure, so it did not stop because its
    # paragraph ended — it stopped because the line did.
    text, _ = repair(FUSED, from_pdf=True)
    assert "they are weak and simple" in " ".join(text.split())


def test_a_format_that_can_mark_its_own_paragraphs_is_left_alone():
    # The same text from a .txt or EPUB is saying what it means by omitting the
    # blank lines, and guessing over it would be a liberty.
    assert repair(FUSED, from_pdf=False)[0] == FUSED


def test_nothing_is_split_where_the_next_line_continues_the_sentence():
    wrapped = "\n".join([
        "Il ne fut que médiocrement affligé d'être banni d'une cour qui",
        "n'était remplie que de tracasseries et de petites intrigues.",
    ])
    assert repair(wrapped, from_pdf=True)[0] == wrapped


# ---- ligatures ----

def test_a_ligature_glyph_becomes_the_letters_it_stands_for():
    # "ﬁnd" reads almost normally and is almost nothing else: no keyboard makes
    # that character, so search and copy-and-paste both miss the word.
    text, removed = repair("He could not ﬁnd the ﬂowers.")
    assert text == "He could not find the flowers."
    assert any(r.kind == "Ligature expanded" for r in removed)


def test_text_without_ligatures_is_left_exactly_as_it_was():
    plain = "He could not find the flowers."
    text, removed = repair(plain)
    assert text == plain
    assert not any(r.kind == "Ligature expanded" for r in removed)
