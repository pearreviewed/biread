import pytest

from biread.cache import Cache
from biread.cleanup import Chapter
from biread.errors import GlossError
from biread.gloss import (
    FIELD,
    anchor,
    body_units,
    coverage,
    decode,
    encode,
    estimate,
    gloss_book,
    parse_units,
)
from biread.llm.base import Completion
from biread.translate import hash_text

PARAGRAPH = "Sur la table, il se leva et monta l'escalier."


def line(*fields):
    return f" {FIELD} ".join(fields)


def response(*blocks):
    """Build a well-formed model reply: (paragraph number, [unit lines])."""
    out = []
    for number, lines in blocks:
        out.append(f"@@@{number}@@@")
        out.extend(lines)
    return Completion("\n".join(out), False)


# ---------- parsing ----------

def test_parses_the_three_required_fields():
    units = parse_units(line("Sur la table", "prep. phrase", "on the table"))
    assert units == [{"surface": "Sur la table", "pos": "prep. phrase",
                      "gloss": "on the table", "infinitive": "", "perfect": ""}]


def test_parses_the_optional_verb_fields():
    units = parse_units(line("il se leva", "verb", "he rose", "inf=se lever", "pc=il s'est levé"))
    assert units[0]["infinitive"] == "se lever"
    assert units[0]["perfect"] == "il s'est levé"


def test_ignores_malformed_lines():
    assert parse_units("just some prose the model added\n\n") == []
    assert parse_units(line("only", "two")) == []


# ---------- anchoring: the safety property ----------

def test_units_become_offsets_into_the_real_paragraph():
    proposed = parse_units("\n".join([
        line("Sur la table", "prep. phrase", "on the table"),
        line("il se leva", "verb", "he rose", "inf=se lever"),
    ]))
    units = anchor(PARAGRAPH, proposed)
    assert [PARAGRAPH[u.start:u.end] for u in units] == ["Sur la table", "il se leva"]


def test_a_model_that_alters_the_text_is_rejected_whole():
    # "l'escalier" returned as "l' escalier" — a plausible normalisation, and
    # displaying it would put French in the book that Voltaire did not write.
    proposed = parse_units("\n".join([
        line("Sur la table", "prep. phrase", "on the table"),
        line("l' escalier", "noun", "the staircase"),
    ]))
    assert anchor(PARAGRAPH, proposed) is None


def test_units_out_of_order_are_rejected():
    proposed = parse_units("\n".join([
        line("monta", "verb", "climbed", "inf=monter"),
        line("Sur la table", "prep. phrase", "on the table"),
    ]))
    assert anchor(PARAGRAPH, proposed) is None


def test_a_repeated_word_anchors_to_the_right_occurrence():
    text = "Il monta, puis il monta encore."
    proposed = parse_units("\n".join([
        line("Il monta", "verb", "he climbed"),
        line("il monta", "verb", "he climbed"),
    ]))
    units = anchor(text, proposed)
    assert units[0].start == 0
    assert units[1].start == text.index("il monta", 1)


def test_gaps_between_units_are_allowed():
    proposed = parse_units(line("monta", "verb", "climbed"))
    units = anchor(PARAGRAPH, proposed)
    assert len(units) == 1
    assert 0 < coverage(PARAGRAPH, units) < 1


def test_encode_round_trips():
    units = anchor(PARAGRAPH, parse_units(
        line("il se leva", "verb", "he rose", "inf=se lever", "pc=il s'est levé")))
    assert decode(encode(units)) == units


# ---------- the run ----------

@pytest.fixture
def book():
    return [Chapter("I", "Le Départ", [PARAGRAPH, "Il monta l'escalier."])]


@pytest.fixture
def good_reply():
    return response(
        (0, [line("Sur la table", "prep. phrase", "on the table"),
             line("il se leva", "verb", "he rose", "inf=se lever", "pc=il s'est levé")]),
        (1, [line("Il monta", "verb", "he climbed", "inf=monter", "pc=il est monté"),
             line("l'escalier", "noun", "the staircase")]),
    )


def test_chapter_titles_are_not_glossed(book):
    # Apparatus and headings are not what anyone hovers, and glossing them costs.
    assert [u.text for u in body_units(book)] == [PARAGRAPH, "Il monta l'escalier."]


def test_a_run_glosses_and_caches(tmp_path, book, config, make_client, good_reply):
    path = tmp_path / "glosses.json"
    run = gloss_book(book, make_client(script=[good_reply]), Cache.load(path), config())

    assert run.glossed == 2
    assert not run.unglossed
    units = run.glosses[hash_text(PARAGRAPH)]
    assert [PARAGRAPH[u.start:u.end] for u in units] == ["Sur la table", "il se leva"]
    assert units[1].infinitive == "se lever"
    assert units[1].perfect == "il s'est levé"
    assert len(Cache.load(path)) == 2


def test_cached_paragraphs_are_not_resent(tmp_path, book, config, make_client, good_reply):
    path = tmp_path / "glosses.json"
    gloss_book(book, make_client(script=[good_reply]), Cache.load(path), config())

    second = make_client()
    run = gloss_book(book, second, Cache.load(path), config())
    assert second.prompts == []
    assert run.glossed == 0
    assert len(run.glosses) == 2


def test_an_unanchorable_paragraph_is_skipped_not_shown_wrong(tmp_path, book, config, make_client):
    mangled = response(
        (0, [line("Sur la Table", "prep. phrase", "on the table")]),   # capital T
        (1, [line("Il monta", "verb", "he climbed", "inf=monter")]),
    )
    run = gloss_book(book, make_client(script=[mangled, mangled]),
                     Cache.load(tmp_path / "g.json"), config())

    assert hash_text(PARAGRAPH) not in run.glosses      # left plain, not corrupted
    assert run.unglossed == [PARAGRAPH[:60]]
    assert hash_text("Il monta l'escalier.") in run.glosses  # the good one survives


def test_a_malformed_response_is_retried(tmp_path, book, config, make_client, good_reply):
    client = make_client(script=[Completion("I cannot do that.", False), good_reply])
    run = gloss_book(book, client, Cache.load(tmp_path / "g.json"), config())
    assert len(client.prompts) == 2
    assert run.glossed == 2


def test_truncation_raises_rather_than_saving_half(tmp_path, book, config, make_client):
    client = make_client(script=[Completion(f"@@@0@@@\nSur {FIELD} prep {FIELD} on", True)])
    with pytest.raises(GlossError, match="token limit"):
        gloss_book(book, client, Cache.load(tmp_path / "g.json"), config())


def test_the_run_stops_at_the_cost_cap(tmp_path, config, make_client):
    chapters = [Chapter("I", None, [f"Paragraphe {n} du texte." for n in range(40)])]
    replies = [response((n, [line(f"Paragraphe {n}", "noun", f"paragraph {n}")]))
               for n in range(40)]
    run = gloss_book(chapters, make_client(script=replies),
                     Cache.load(tmp_path / "g.json"), config(max_cost_usd=0.002))
    assert run.stopped_at_cap
    assert run.glossed < 40


def test_estimate_counts_only_uncached_paragraphs(tmp_path, book, config):
    cache = Cache.load(tmp_path / "g.json")
    result = estimate(book, cache, config())
    assert result.total == 2
    assert result.pending == 2
    assert result.cost > 0
