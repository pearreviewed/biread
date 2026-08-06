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


# A hard-wrapped paragraph whose last line stops short, repeated until the whole
# stands as one block far longer than any prose is set in: a PDF flattened into
# Word or text, which keeps every line and no paragraph mark.
FLATTENED = "".join([
    "Le mieux serait d'ecrire les evenements au jour le jour. Tenir un journal\n",
    "pour y voir clair, ne pas laisser echapper les nuances, les petits faits,\n",
    "meme s'ils n'ont l'air de rien, et surtout les classer.\n",
]) * 40


def test_a_file_that_never_broke_at_all_is_repaired_whatever_its_format():
    # Not a PDF, and repaired all the same: a file arriving as one block the
    # length of a chapter is not describing its house style, it has lost the
    # marks, and refusing it would send a reader back to a file they no longer
    # have.
    text, removed = repair(FLATTENED, from_pdf=False)
    assert len(text.split("\n\n")) == 40
    assert any(r.kind == "Paragraph break restored" for r in removed)


def test_a_long_file_that_did_break_is_still_left_alone():
    # The guard on the rescue above: the same passage set out as paragraphs is
    # untouched however long the file runs, because now it *is* saying what it
    # means. This is what keeps every verified EPUB and text in the corpus as it
    # was.
    broken = "\n\n".join([FUSED] * 40)
    assert repair(broken, from_pdf=False)[0] == broken


def test_nothing_is_split_where_the_next_line_continues_the_sentence():
    wrapped = "\n".join([
        "Il ne fut que médiocrement affligé d'être banni d'une cour qui",
        "n'était remplie que de tracasseries et de petites intrigues.",
    ])
    assert repair(wrapped, from_pdf=True)[0] == wrapped


# ---- paragraphs the file marks by indenting them ----

# A scan of a printed page: every paragraph set in four spaces, every line after
# it flush, and not a blank line anywhere the compositor put one.
INDENTED = "\n".join([
    "    The best thing would be to write down events from day to day.",
    "Keep a diary to see clearly, let none of the nuances escape, even",
    "if they have the air of nothing at all, and above all classify them.",
    "    I must tell how I see this table, the street, the people, my",
    "packet of tobacco, since that is what has changed. I must determine",
    "the exact extent and nature of this change.",
    "    For instance, here is a cardboard box holding my bottle of ink.",
    "I should try to tell how I saw it before and how I see it now. Well,",
    "it is a rectangular parallelepiped and it stands out against the wall.",
]) + "\n"


def test_an_indent_is_read_as_the_paragraph_mark_it_is():
    text, removed = repair(INDENTED)
    assert len(text.split("\n\n")) == 3
    assert any(r.kind == "Paragraph indent read" for r in removed)


def test_a_blank_line_is_not_trusted_where_the_indent_speaks():
    # A scan sets its leading wherever a line happened to measure tall. Once the
    # file has said where its paragraphs begin, a blank line that the indent does
    # not corroborate cannot cut one in half.
    scanned = INDENTED.replace("Keep a diary", "\nKeep a diary")
    assert repair(scanned)[0] == repair(INDENTED)[0]


def test_an_indent_the_sentence_runs_straight_through_is_declined():
    # A margin the scanner mismeasured: the line above stops mid-clause and the
    # line below picks the clause up. Two marks disagreeing, and the prose wins.
    wandering = INDENTED.replace(
        "    For instance, here is a cardboard box", "    of this change"
    ).replace("the exact extent and nature of this change.", "the exact extent and nature")
    assert len(repair(wandering)[0].split("\n\n")) == 2


def test_a_few_centred_headings_are_not_a_convention():
    # Two lines set in from the margin among forty is a heading or a page number,
    # not a house style, and reading it as one would cut the book at each.
    body = "\n".join(["A line of perfectly ordinary prose, set flush left."] * 40)
    _, removed = repair(f"          I\n{body}\n          II\n{body}")
    assert not any(r.kind == "Paragraph indent read" for r in removed)


def test_a_file_that_indents_is_not_also_guessed_at():
    # The short-line guess is the weaker of the two signals and stands down where
    # the better one is present, rather than adding breaks on top of it.
    text, removed = repair(INDENTED, from_pdf=True)
    assert not any(r.kind == "Paragraph break restored" for r in removed)
    assert len(text.split("\n\n")) == 3


def test_a_heading_set_flush_is_not_swallowed_by_the_paragraph_above_it():
    # A file that indents says where paragraphs begin and nothing about a line
    # that begins none, so a heading joined whatever preceded it: both scans of
    # Nausea came out reading "Il ne faut pas avoir peur. JEUDI."
    dated = INDENTED.replace(
        "    I must tell how I see this table", "THURSDAY:\n    I must tell how I see this table"
    )
    blocks = repair(dated)[0].split("\n\n")
    assert len(blocks) == 4
    assert blocks[1].strip() == "THURSDAY:"


def test_a_paragraphs_own_last_line_is_not_read_as_a_heading():
    # The line above a heading has finished saying something; the line above a
    # paragraph's last line is still mid-clause, which is what tells them apart.
    blocks = repair(INDENTED)[0].split("\n\n")
    assert len(blocks) == 3
    assert all("cardboard box" not in b or b.count("\n") == 2 for b in blocks)


def test_a_long_flush_line_is_prose_however_it_is_placed():
    # Length is the first of the three conditions: a heading is set on its own,
    # and a line running most of the measure is a sentence.
    running_on = INDENTED.replace(
        "    I must tell how I see this table",
        "And then he walked the whole length of the boulevard without once looking up.\n"
        "    I must tell how I see this table",
    )
    assert len(repair(running_on)[0].split("\n\n")) == 3


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
