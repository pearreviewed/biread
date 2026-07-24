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
