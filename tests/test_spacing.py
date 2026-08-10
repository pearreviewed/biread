"""Putting back the spaces a scan lost, without a word being rewritten.

The tests that matter here are the adversarial ones. What reaches the page is the
book's own characters carrying the model's spacing, so the guarantee lives
entirely in `respaced` — and a rule like that is worth exactly what it refuses.
Most of what follows hands it a model that is wrong in a different way each time
and requires the book to survive it.
"""
from __future__ import annotations

import pytest

from biread.cleanup import Chapter
from biread.spacing import (
    came_apart,
    letters,
    respace,
    respaced,
    run_together,
    suspect,
)

JOINED = "The firstsheet is undated, but there isvery good reason to believe it."
SPACED = "The first sheet is undated, but there is very good reason to believe it."


class Model:
    """A model that answers with whatever it is told to, in order."""

    def __init__(self, *replies, fail=False):
        self.replies = list(replies)
        self.fail = fail
        self.asked = []

    def complete(self, system, user, max_tokens):
        self.asked.append(user)
        if self.fail:
            raise RuntimeError("the provider hung up")
        return type("Reply", (), {"text": self.replies.pop(0), "truncated": False})()


def book(*paragraphs):
    return [Chapter(None, None, list(paragraphs))]


def body(chapters):
    return [p for c in chapters for p in c.paragraphs]


# ---- the check, which is the whole safety argument -------------------------

def test_a_reply_that_only_respaces_is_taken():
    assert respaced(JOINED, SPACED) == SPACED


def test_a_reply_that_rewrites_a_word_is_refused():
    assert respaced(JOINED, SPACED.replace("undated", "not dated")) is None


def test_a_reply_that_corrects_a_misreading_is_refused():
    """A misread word is the file's and not the model's to fix: `lloquentin`
    stays `lloquentin`, because a model allowed to mend one word is a model
    writing into a book."""
    joined = "papers of Antoine lloquentin. Theyare published"
    assert respaced(joined, "papers of Antoine Roquentin. They are published") is None
    assert respaced(joined, "papers of Antoine lloquentin. They are published") == \
        "papers of Antoine lloquentin. They are published"


def test_a_reply_that_translates_the_passage_is_refused():
    assert respaced("Il y avait en Vestphalie", "There was in Westphalia") is None


def test_a_reply_that_answers_in_words_of_its_own_is_refused():
    assert respaced(JOINED, "Sure! Here is the corrected passage:\n" + SPACED) is None


def test_a_reply_that_drops_the_end_of_the_passage_is_refused():
    assert respaced(JOINED, SPACED[:40]) is None


def test_a_straightened_quotation_mark_costs_the_repair_nothing():
    """The one shape a model may differ in, because the mark that goes on the
    page is the book's either way. Sonnet straightened the apostrophe in half of
    the real passages it respaced, and a rule about the reply's own characters
    threw those repairs away over it."""
    assert respaced("he said “no” thenagain", 'he said "no" then again') == \
        "he said “no” then again"


def test_an_empty_or_unchanged_reply_changes_nothing():
    assert respaced(JOINED, "") is None
    assert respaced(JOINED, JOINED) is None


def test_letters_is_what_may_not_change():
    assert letters("a b\nc\td") == "abcd"


# ---- which passages are worth paying to look at ---------------------------

def test_a_word_the_book_never_uses_whose_halves_it_always_does():
    paragraphs = ["is very good"] * 3 + ["the first sheet of it"] * 3 + [JOINED]
    assert set(run_together(paragraphs)) == {"firstsheet", "isvery"}
    assert suspect(paragraphs) == [6]


def test_a_book_with_nothing_run_together_costs_nothing():
    paragraphs = ["is very good"] * 3 + ["the first sheet of it"] * 3
    assert run_together(paragraphs) == []
    assert suspect(paragraphs) == []


def test_a_word_the_book_uses_on_its_own_is_never_a_candidate():
    """`notebooks` answers the same description as `firstsheet` and is a word.
    What tells them apart is that the book settles on one of them."""
    paragraphs = ["note the books"] * 3 + ["his notebooks lay open"] * 3
    assert "notebooks" not in run_together(paragraphs)


def test_nothing_is_asked_of_the_model_where_nothing_is_suspect():
    model = Model()
    chapters, run = respace(book("is very good", "is very good", "is very good"), model)
    assert model.asked == [] and run.looked_at == 0 and not run.changed


# ---- the pass ------------------------------------------------------------

def _scanned_book():
    return book(*(["is very good"] * 3 + ["the first sheet of it"] * 3 + [JOINED]))


def test_a_repaired_passage_replaces_the_one_the_scan_gave():
    chapters, run = respace(_scanned_book(), Model(SPACED))
    assert body(chapters)[-1] == SPACED
    assert run.repaired == 1 and run.refused == 0
    assert "firstsheet" in run.words


def test_a_refused_reply_leaves_the_passage_as_the_file_had_it():
    chapters, run = respace(_scanned_book(), Model(SPACED.replace("undated", "undated!")))
    assert body(chapters)[-1] == JOINED
    assert run.refused == 1 and run.repaired == 0 and not run.changed


def test_a_call_that_fails_leaves_the_passage_alone_and_the_book_comes_back():
    chapters, run = respace(_scanned_book(), Model(fail=True))
    assert body(chapters)[-1] == JOINED
    assert run.failed == 1 and run.repaired == 0


def test_the_chapters_come_back_whole_and_in_order():
    chapters = [Chapter("I", "Le Départ", ["is very good"] * 3),
                Chapter("II", None, ["the first sheet of it"] * 3 + [JOINED])]
    out, run = respace(chapters, Model(SPACED))
    assert [(c.number, c.title, len(c.paragraphs)) for c in out] == \
        [("I", "Le Départ", 3), ("II", None, 4)]
    assert out[1].paragraphs[-1] == SPACED


def test_only_the_suspect_passage_is_paid_for():
    model = Model(SPACED)
    respace(_scanned_book(), model)
    assert len(model.asked) == 1
    assert JOINED in model.asked[0]


def test_came_apart_names_the_word_that_was_repaired():
    assert came_apart(JOINED, SPACED) == ["firstsheet", "isvery"]


def test_progress_is_reported_per_passage():
    seen = []
    respace(_scanned_book(), Model(SPACED), on_progress=lambda *a: seen.append(a))
    assert seen == [("respace", 1, 1)]


@pytest.mark.parametrize("reply", ["", "   ", "\n"])
def test_an_empty_reply_is_not_mistaken_for_an_empty_paragraph(reply):
    chapters, run = respace(_scanned_book(), Model(reply))
    assert body(chapters)[-1] == JOINED
    assert run.refused == 1


def test_nothing_the_model_typed_reaches_the_page():
    """Even a perfect reply is not the text that is kept: the passage is rebuilt
    from the book's own characters, which is why a straightened quotation mark
    cannot survive into the book and a rewritten word cannot be missed."""
    original = "l’autre firstsheet, “forge”"
    out = respaced(original, "l'autre first sheet, \"forge\"")
    assert out == "l’autre first sheet, “forge”"
    assert "'" not in out and '"' not in out
