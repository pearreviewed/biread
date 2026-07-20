import pytest

from biread.cache import Cache
from biread.cleanup import Chapter
from biread.errors import GlossError
from biread.gloss import (
    chunks,
    over_broad,
    rescue,
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


# ---- typography: the failure that cost a real run ----

CURLY = "Il s’appelait Micromégas — « un nom qui convient », dit-il… l’escalier."


def test_a_straight_apostrophe_matches_a_curly_one():
    # French is one long chain of elisions and models return ' for ’ whatever
    # the prompt says. Byte-exact matching rejected 34 of 36 real paragraphs.
    units = anchor(CURLY, parse_units(line("Il s'appelait", "verb", "he was called")))
    assert units is not None
    assert CURLY[units[0].start:units[0].end] == "Il s’appelait"   # the ORIGINAL


def test_folded_punctuation_still_yields_original_offsets():
    for surface, expected in [
        ("un nom qui convient", "un nom qui convient"),
        ("l'escalier", "l’escalier"),
    ]:
        units = anchor(CURLY, parse_units(line(surface, "noun", "gloss")))
        assert units, surface
        assert CURLY[units[0].start:units[0].end] == expected


def test_an_ellipsis_written_as_three_dots_matches():
    units = anchor(CURLY, parse_units(line("dit-il...", "verb", "said he")))
    assert units is not None
    assert CURLY[units[0].start:units[0].end] == "dit-il…"


def test_folding_does_not_excuse_an_actual_word_change():
    # Tolerating typography must not tolerate invention.
    assert anchor(CURLY, parse_units(line("Il se nommait", "verb", "he was named"))) is None


# ---- rescuing a paragraph the batch could not anchor ----

SENTENCES = [
    f"Le voyageur numéro {n} monta l’escalier et regarda longuement la mer calme."
    for n in range(1, 11)
]
LONG = " ".join(SENTENCES)
MANGLED = response((0, [line("Sur la Table", "prep. phrase", "on the table")]))


@pytest.fixture
def one_long():
    return [Chapter("I", None, [LONG])]


def test_chunks_are_literal_slices_of_the_paragraph():
    # The offsets are only meaningful if a piece is exactly what it was cut from.
    pieces = chunks(LONG)
    assert len(pieces) > 1
    for offset, piece in pieces:
        assert LONG[offset:offset + len(piece)] == piece


def test_a_short_paragraph_is_one_chunk():
    assert len(chunks(PARAGRAPH)) == 1


def test_a_paragraph_that_failed_in_a_batch_is_retried_on_its_own(tmp_path, book, config, make_client):
    alone = response((0, [line("Sur la table", "prep. phrase", "on the table")]))
    client = make_client(script=[MANGLED, MANGLED, alone])
    run = gloss_book(book, client, Cache.load(tmp_path / "g.json"), config())

    assert run.rescued == 1
    assert run.glossed == 1
    units = run.glosses[hash_text(PARAGRAPH)]
    assert [PARAGRAPH[u.start:u.end] for u in units] == ["Sur la table"]


def test_a_paragraph_that_only_anchors_sentence_by_sentence(tmp_path, one_long, config, make_client):
    # "monta" appears in every sentence, so each piece anchors on its own copy.
    piece = response((0, [line("monta", "verb", "climbed", "inf=monter")]))
    expected = len(chunks(LONG))
    client = make_client(script=[MANGLED, MANGLED, MANGLED] + [piece] * expected)
    run = gloss_book(one_long, client, Cache.load(tmp_path / "g.json"), config())

    units = run.glosses[hash_text(LONG)]
    assert run.rescued == 1
    assert len(units) == expected
    assert all(LONG[u.start:u.end] == "monta" for u in units)
    assert [u.start for u in units] == sorted(u.start for u in units)


def test_a_piece_that_will_not_anchor_leaves_only_itself_plain(tmp_path, one_long, config, make_client):
    piece = response((0, [line("monta", "verb", "climbed")]))
    client = make_client(script=[MANGLED, MANGLED, MANGLED, MANGLED, piece])
    run = gloss_book(one_long, client, Cache.load(tmp_path / "g.json"), config())

    units = run.glosses[hash_text(LONG)]
    assert len(units) == len(chunks(LONG)) - 1     # the mangled piece contributed nothing
    assert not run.unglossed                        # the paragraph itself survives


def test_a_paragraph_nothing_can_rescue_stays_plain(tmp_path, book, config, make_client):
    client = make_client(script=[MANGLED] * 12)
    run = gloss_book(book, client, Cache.load(tmp_path / "g.json"), config())
    assert run.rescued == 0
    assert not run.glosses
    assert run.unglossed == [PARAGRAPH[:60], "Il monta l'escalier."]


# ---- a hover explains one phrase, not a clause ----

def test_function_words_ride_along_free():
    # The closed class is unlimited per unit; it is content words that are capped.
    for surface in ["Sur la table", "il se leva", "qu’il n’y en avait plus",
                    "vingt-quatre mille", "de ces planètes"]:
        assert not over_broad(surface), surface


def test_a_phrase_is_allowed_its_adjective():
    for surface in ["un jeune homme", "fort effilé", "sa petite fourmilière"]:
        assert not over_broad(surface), surface


def test_a_clause_is_too_wide_for_one_hover():
    # All observed on the first real run, each arriving as a single unit.
    for surface in [
        "Enfin le muphti fit condamner le livre",
        "dont le bout fort effilé venait donner auprès du vaisseau",
        "Ils entendaient des mites parler d’assez bon sens",
        "il mit les femmes de son côté",
    ]:
        assert over_broad(surface), surface


def test_an_over_broad_unit_is_dropped_and_its_neighbours_kept():
    text = "Sur la table, il mit les femmes de son côté et monta."
    units = anchor(text, parse_units("\n".join([
        line("Sur la table", "prep. phrase", "on the table"),
        line("il mit les femmes de son côté", "clause", "he won the women over"),
        line("monta", "verb", "climbed", "inf=monter"),
    ])))
    assert [text[u.start:u.end] for u in units] == ["Sur la table", "monta"]


def test_dropping_a_wide_unit_does_not_lose_the_reader_s_place():
    # The cursor still advances past what was dropped, so a later unit cannot
    # accidentally anchor inside it and come out in the wrong order.
    text = "Il monta l’escalier, puis il monta le grand escalier de pierre."
    units = anchor(text, parse_units("\n".join([
        line("Il monta le grand escalier de pierre", "clause", "he climbed it"),
        line("monta", "verb", "climbed"),
    ])))
    assert units is None or all(u.start >= text.index("puis") for u in units)


def test_a_verb_group_may_not_swallow_a_noun():
    # A verb group is the verb plus the function words leaning on it. A second
    # content word means a subject or an object came along with it.
    for surface, pos in [
        ("il s’appelait Micromégas", "verb"),
        ("le procès dura", "verb phrase"),
        ("ne sont qu’une faible image", "verb phrase"),
        ("que la nature a mises", "verb phrase"),
    ]:
        assert over_broad(surface, pos), surface


def test_a_verb_keeps_its_pronouns_auxiliaries_and_negation():
    for surface in ["il se leva", "qu’il fit", "n’avait jamais été", "ils s’en furent"]:
        assert not over_broad(surface, "verb"), surface


def test_a_noun_phrase_may_still_carry_its_adjective():
    # The same two content words that condemn a verb group are fine here.
    assert not over_broad("un jeune homme", "noun phrase")
    assert over_broad("un jeune homme", "verb")


def test_the_label_only_ever_costs_one_hover():
    # pos comes from the model. A wrong label drops the unit; it can never put
    # altered text on the page, because only offsets are ever kept.
    text = "Un jeune homme, sur la table, il se leva."
    units = anchor(text, parse_units("\n".join([
        line("Un jeune homme", "verb", "mislabelled on purpose"),
        line("sur la table", "prepositional phrase", "on the table"),
        line("il se leva", "verb", "he rose"),
    ])))
    assert [text[u.start:u.end] for u in units] == ["sur la table", "il se leva"]


def test_changing_the_rules_invalidates_what_they_produced(tmp_path, book, config, make_client, good_reply, monkeypatch):
    # A gloss is a cut made under a particular rule set. Keyed on the paragraph
    # alone it would outlive the rules, and nothing in the entry would say so.
    path = tmp_path / "g.json"
    gloss_book(book, make_client(script=[good_reply]), Cache.load(path), config())

    monkeypatch.setattr("biread.gloss.RULES_VERSION", "changed1")
    second = make_client(script=[good_reply])
    run = gloss_book(book, second, Cache.load(path), config())

    assert second.prompts, "new rules must re-ask rather than serve the old cut"
    assert run.glossed == 2
    assert len(Cache.load(path)) == 4      # both cuts kept, told apart by key


def test_the_same_rules_still_hit_the_cache(tmp_path, book, config, make_client, good_reply):
    path = tmp_path / "g.json"
    gloss_book(book, make_client(script=[good_reply]), Cache.load(path), config())
    second = make_client()
    gloss_book(book, second, Cache.load(path), config())
    assert second.prompts == []
