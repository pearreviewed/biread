"""The instrument that scores an alignment without anyone labelling one.

What cannot be tested here is the matching itself: that needs two real editions
and a real embedding model, which is the whole reason `biread.score` exists as a
command and not as a test. What is tested is the arithmetic it reports and the
machinery that has to survive twenty minutes of network to produce it.
"""
import gzip
import json

import pytest

from biread.cleanup import Chapter
from biread.errors import BireadError
from biread.llm.embed import BATCH
from biread.score import ATTEMPTS, Score, _Cached, compare, place
from biread.translate import hash_text

FRENCH = [Chapter(None, None, [
    "Le chat dort sur la table.",
    "Le chien court dans la rue.",
    "La maison est vide ce matin.",
])]


def placed(*texts):
    """One reading of a translation: French paragraph hash -> English."""
    return {hash_text(p): t for p, t in zip(FRENCH[0].paragraphs, texts)}


def test_two_readings_of_one_translation_that_agree():
    score = compare(FRENCH, placed("The cat sleeps.", "The dog runs.", "The house is empty."),
                    placed("The cat sleeps.", "The dog runs.", "The house is empty."))
    assert (score.agreed, score.disagreed) == (3, 0)
    assert score.accuracy == 1.0
    assert score.answered == 1.0


def test_a_disagreement_means_one_of_them_is_wrong():
    # The point of the whole instrument: neither file is labelled, and yet this
    # is a fact. Both carry the same translation, so the same French paragraph
    # cannot honestly hold two different passages.
    score = compare(FRENCH, placed("The cat sleeps.", "The dog runs.", "The house is empty."),
                    placed("The cat sleeps.", "The mountain is far off.", "The house is empty."))
    assert (score.agreed, score.disagreed) == (2, 1)
    assert score.accuracy == pytest.approx(2 / 3)
    assert score.examples[0][0] == "Le chien court dans la rue."


def test_the_same_passage_read_off_a_scan_still_agrees():
    # One file is OCR and the other is not, so the two never match character for
    # character. Containment is what forgives that, and the misreadings, and one
    # side carrying more of the passage than the other.
    score = compare(
        FRENCH,
        placed("The cat sleeps on the table.", "The dog runs.", "The house is empty."),
        placed("The cat sleeps on the tabIe. He was afraid.", "The dog runs.", "The house is empty."),
    )
    assert (score.agreed, score.disagreed) == (3, 0)


def test_a_paragraph_only_one_edition_answered_is_not_evidence():
    score = compare(FRENCH, placed("The cat sleeps.", "", ""), placed("The cat sleeps.", "The dog runs.", ""))
    assert (score.agreed, score.disagreed) == (1, 0)
    assert (score.only_a, score.only_b, score.neither) == (0, 1, 1)
    assert score.judged == 1


def test_a_matcher_cannot_buy_agreement_by_declining_to_answer():
    """Accuracy is reported beside how much was answered at all, because a
    matcher that places one paragraph and blanks the rest scores 100%."""
    score = compare(FRENCH, placed("The cat sleeps.", "", ""), placed("The cat sleeps.", "", ""))
    assert score.accuracy == 1.0
    assert score.answered == pytest.approx(1 / 3)


def test_nothing_comparable_is_not_a_score_of_zero():
    score = compare(FRENCH, placed("", "", ""), placed("", "", ""))
    assert score.accuracy is None
    assert score.answered == 0.0


def test_an_empty_score_reports_nothing_rather_than_dividing_by_zero():
    assert Score().accuracy is None and Score().answered == 0.0


def test_a_french_edition_with_no_paragraph_breaks_is_refused():
    """It is re-cut to each counterpart's shape, so its paragraphs are different
    text in the two runs and there is nothing left to key the comparison on. That
    would read as a total failure of the matcher, which is the one wrong answer
    an instrument must not give."""
    flat = [Chapter(None, None, [" ".join(f"Une phrase de plus, la {i}eme." for i in range(400))])]
    counterpart = [Chapter(None, None, [f"Sentence number {i}." for i in range(40)])]
    with pytest.raises(BireadError, match="no paragraph breaks"):
        place(flat, counterpart, lambda texts: [[1.0, 0.0] for _ in texts])


# ---- the cache, which is what makes a re-run free and a timeout survivable ----

def vectors(texts):
    return [[float(len(t)), 1.0] for t in texts]


class Counting:
    def __init__(self, fail_first=0, embed=vectors):
        self.calls, self.embedded, self.fail_first = 0, [], fail_first
        self._embed = embed

    def __call__(self, texts):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise RuntimeError("read timed out")
        self.embedded.extend(texts)
        return self._embed(texts)


def test_a_text_already_embedded_is_never_paid_for_twice(tmp_path):
    counting = Counting()
    cached = _Cached(counting, tmp_path / "v.json.gz")
    first = cached(["one", "two"])
    assert cached(["two", "one"]) == [first[1], first[0]]
    assert counting.embedded == ["one", "two"]


def test_one_call_asking_for_the_same_text_twice_pays_once(tmp_path):
    counting = Counting()
    cached = _Cached(counting, tmp_path / "v.json.gz")
    assert cached(["same", "same", "other"]) == [[4.0, 1.0], [4.0, 1.0], [5.0, 1.0]]
    assert counting.embedded == ["same", "other"]


def test_the_cache_outlives_the_run(tmp_path):
    path = tmp_path / "v.json.gz"
    _Cached(Counting(), path)(["one", "two"])
    counting = Counting()
    assert _Cached(counting, path)(["one", "two"]) == [[3.0, 1.0], [3.0, 1.0]]
    assert counting.embedded == []


def test_vectors_are_kept_to_four_decimals(tmp_path):
    path = tmp_path / "v.json.gz"
    _Cached(lambda texts: [[0.123456789, 0.987654321]], path)(["one"])
    with gzip.open(path, "rt") as handle:
        assert list(json.load(handle).values()) == [[0.1235, 0.9877]]


def test_a_request_that_times_out_is_asked_again(tmp_path):
    counting = Counting(fail_first=2)
    cached = _Cached(counting, tmp_path / "v.json.gz", sleep=lambda _: None)
    assert cached(["one"]) == [[3.0, 1.0]]
    assert counting.calls == 3


def test_a_model_that_stops_answering_says_the_work_is_kept(tmp_path):
    counting = Counting(fail_first=ATTEMPTS)
    cached = _Cached(counting, tmp_path / "v.json.gz", sleep=lambda _: None)
    with pytest.raises(BireadError, match="resumes rather than starting again"):
        cached(["one"])
    assert counting.calls == ATTEMPTS


def test_a_batch_that_fails_does_not_lose_the_batches_before_it(tmp_path):
    """The lesson the first real run taught, and it cost nineteen minutes of paid
    embedding: the cache is written after every batch, not at the end of a call."""
    path = tmp_path / "v.json.gz"
    texts = [f"paragraph number {i}" for i in range(BATCH + 5)]

    calls = {"n": 0}

    def flaky(batch):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("read timed out")
        return vectors(batch)

    with pytest.raises(BireadError):
        _Cached(flaky, path, sleep=lambda _: None)(texts)
    with gzip.open(path, "rt") as handle:
        assert len(json.load(handle)) == BATCH
