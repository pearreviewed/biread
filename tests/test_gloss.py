import pytest

from biread.cache import Cache
from biread.cleanup import Chapter
from biread.errors import GlossError
from biread.gloss import (
    chunks,
    displayable,
    over_broad,
    spans_coordination,
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
                      "gloss": "on the table", "infinitive": ""}]


def test_parses_the_optional_verb_field():
    units = parse_units(line("il se leva", "verb", "he rose", "inf=se lever"))
    assert units[0]["infinitive"] == "se lever"


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
        line("il se leva", "verb", "he rose", "inf=se lever")))
    assert decode(encode(units)) == units


# ---------- the run ----------

@pytest.fixture
def book():
    return [Chapter("I", "Le Départ", [PARAGRAPH, "Il monta l'escalier."])]


@pytest.fixture
def good_reply():
    return response(
        (0, [line("Sur la table", "prep. phrase", "on the table"),
             line("il se leva", "verb", "he rose", "inf=se lever")]),
        (1, [line("Il monta", "verb", "he climbed", "inf=monter"),
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


# ---- glossing the opening only ----

class Obliging:
    """Glosses the first word of every paragraph it is shown, whatever it is."""

    input_tokens = output_tokens = 0

    def __init__(self):
        self.prompts = []

    def complete(self, system, user, max_tokens=None):
        self.prompts.append(user)
        import re
        blocks = re.findall(
            r"=== PARAGRAPH (\d+) ===\n(.*?)(?=\n\n=== PARAGRAPH |\Z)", user, re.S)
        return response(*[(int(n), [line(t.strip().split()[0], "noun", "a word")])
                          for n, t in blocks])


@pytest.fixture
def long_book():
    return [Chapter("I", None, [f"Paragraphe {n} du texte." for n in range(60)])]


def test_glossing_the_opening_asks_for_the_opening_only(tmp_path, long_book, config):
    client = Obliging()
    run = gloss_book(long_book, client, Cache.load(tmp_path / "g.json"), config(), limit=40)

    assert run.glossed == 40
    assert "Paragraphe 40" not in "\n".join(client.prompts)


def test_the_count_is_the_job_not_the_book(tmp_path, long_book, config):
    """The progress screen quotes its wait from this count. Counting the whole
    book while forty paragraphs were being made read `36 of 1,518` on a book of
    Nausea's length, and turned seven real minutes into over two hours left."""
    seen = []
    gloss_book(long_book, Obliging(), Cache.load(tmp_path / "g.json"), config(),
               on_progress=lambda done, total: seen.append((done, total)), limit=40)

    assert seen[-1] == (40, 40)
    assert {total for _, total in seen} == {40}


def test_glosses_kept_from_an_earlier_session_start_the_count(tmp_path, long_book, config):
    path = tmp_path / "g.json"
    gloss_book(long_book, Obliging(), Cache.load(path), config(), limit=10)

    seen = []
    run = gloss_book(long_book, Obliging(), Cache.load(path), config(),
                     on_progress=lambda done, total: seen.append((done, total)), limit=40)
    assert run.held == 10
    assert seen[0][0] == 11        # not 1: ten were already made
    assert seen[-1] == (40, 40)


def test_a_gloss_beyond_the_opening_is_carried_but_not_counted(tmp_path, long_book, config):
    """A reader who glossed further while reading keeps those glosses in the
    rebuilt book, and they do not make the next build's count read past its end."""
    path = tmp_path / "g.json"
    gloss_book(long_book, Obliging(), Cache.load(path), config())        # the whole book

    run = gloss_book(long_book, Obliging(), Cache.load(path), config(), limit=5)
    assert run.total == 5
    assert run.held == 5
    assert len(run.glosses) == 60


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
    # anchor locates everything; displayable is where width is judged.
    text = "Sur la table, il mit les femmes de son côté et monta."
    units = anchor(text, parse_units("\n".join([
        line("Sur la table", "prep. phrase", "on the table"),
        line("il mit les femmes de son côté", "clause", "he won the women over"),
        line("monta", "verb", "climbed", "inf=monter"),
    ])))
    assert [text[u.start:u.end] for u in displayable(text, units)] == ["Sur la table", "monta"]


def test_a_wide_unit_anchors_but_still_does_not_reach_the_reader():
    # It is located — anchor keeps it, so the model's proposal survives in the
    # cache — but displayable filters it before it becomes a hover.
    text = "Il monta le grand escalier de pierre lentement."
    units = anchor(text, parse_units("\n".join([
        line("Il monta le grand escalier de pierre", "clause", "he climbed it"),
        line("lentement", "adverb", "slowly"),
    ])))
    assert [text[u.start:u.end] for u in units] == \
        ["Il monta le grand escalier de pierre", "lentement"]
    assert [text[u.start:u.end] for u in displayable(text, units)] == ["lentement"]


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
    shown = displayable(text, units)
    assert [text[u.start:u.end] for u in shown] == ["sur la table", "il se leva"]


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


# ---- coordination is a boundary, not something to hover across ----

def test_a_coordination_of_two_content_words_is_too_wide():
    for surface in ["de Moscovie ou de la Chine", "plus simple et plus ordinaire",
                    "de blondes et de brunes", "Leuwenhoek et Hartsoeker"]:
        assert over_broad(surface, "noun phrase"), surface


def test_a_leading_conjunction_is_not_a_coordination():
    # "et son beau visage" attaches et to the previous unit; nothing content-
    # bearing precedes it, so it is not two parts glued together.
    assert not over_broad("et son beau visage", "noun phrase")
    assert not over_broad("et de grands calculs", "noun phrase")


def test_two_nouns_joined_by_a_preposition_are_two_units():
    # A noun with a "de/à + noun" complement is two nouns, so two hovers.
    for surface in ["citoyens de la terre", "les lois de la gravitation",
                    "pieds de roi", "de la tête aux pieds", "la musique de Lulli"]:
        assert over_broad(surface, "noun phrase"), surface


def test_an_adjective_stays_with_its_noun():
    # No preposition between the two content words: one describes the other.
    for surface in ["un jeune homme", "sa petite fourmilière", "un bon observateur",
                    "cent vingt mille pieds", "ce beau visage"]:
        assert not over_broad(surface, "noun phrase"), surface


def test_a_single_noun_with_a_leading_preposition_is_fine():
    # "de la terre" on its own is one noun; the preposition leads, it does not join.
    for surface in ["de la terre", "sur la table", "dans le globe", "à Saturne"]:
        assert not over_broad(surface, "prepositional phrase"), surface


def test_displayable_drops_the_coordinated_unit_and_keeps_its_neighbours():
    text = "Les États de Moscovie ou de la Chine sont petits."
    units = anchor(text, parse_units("\n".join([
        line("Les États", "noun phrase", "the states"),
        line("de Moscovie ou de la Chine", "prepositional phrase", "of Muscovy or China"),
        line("sont petits", "verb", "are small"),
    ])))
    shown = displayable(text, units)
    assert [text[u.start:u.end] for u in shown] == ["Les États", "sont petits"]


# ---- modal verbs and intensifiers are grammatical, not extra content ----

def test_a_modal_verb_does_not_count_as_a_second_content_word():
    # "il faut avouer", "on peut faire" are one verb idea, not verb + object.
    for surface in ["il faut avouer", "on peut faire", "il ne peut", "veut contredire"]:
        assert not over_broad(surface, "verb"), surface


def test_an_intensifier_stays_with_what_it_modifies():
    for surface in ["un livre fort curieux", "gens toujours utiles", "fort plaisante"]:
        assert not over_broad(surface, "noun phrase"), surface


def test_recovering_intensifiers_does_not_reopen_two_nouns():
    # The point of the recovery is to keep genuine two-noun phrases out.
    for surface in ["au-delà de nos usages", "citoyens de la terre", "la force de son esprit"]:
        assert over_broad(surface, "noun phrase"), surface


def test_a_field_the_prompt_no_longer_asks_for_is_ignored():
    """The panel carries the translation and, on a verb, the infinitive. Nothing
    else: the French is under the pointer already. A model offering a passé
    composé unbidden must not be able to put a line back on the page."""
    from biread.gloss import FIELD, parse_units

    (unit,) = parse_units(
        f"il disséqua{FIELD}verb{FIELD}dissected{FIELD}inf=disséquer{FIELD}pc=il a disséqué")
    assert unit == {"surface": "il disséqua", "pos": "verb",
                    "gloss": "dissected", "infinitive": "disséquer"}


def test_an_infinitive_that_only_echoes_the_surface_is_dropped():
    """A verb already in the infinitive earns no second line — it would repeat
    the word under the pointer, which is the duplication the panel was cut back
    to avoid. Caught through case and punctuation, since a model straightens the
    curly apostrophe however firmly it is told not to."""
    from biread.gloss import FIELD, parse_units

    echoed, curly, real = parse_units(
        f"parler{FIELD}verb{FIELD}to speak{FIELD}inf=parler\n"
        f"S’attirer{FIELD}verb{FIELD}to attract{FIELD}inf=s'attirer\n"
        f"il se leva{FIELD}verb{FIELD}he rose{FIELD}inf=se lever")
    assert echoed["infinitive"] == ""
    assert curly["infinitive"] == ""
    assert real["infinitive"] == "se lever"


def test_an_echoed_infinitive_already_in_the_cache_is_not_shown():
    """The parse-time guard is newer than the caches. A line saying nothing
    should not reach the page on the strength of being old."""
    from biread.gloss import GlossUnit, displayable

    para = "Il ne savait plus parler à personne."
    start = para.index("parler")
    (shown,) = displayable(para, [GlossUnit(start, start + 6, "verb", "to speak", "parler")])
    assert shown.infinitive == ""


# ---------- how much of a book the build glosses ----------

def _book_of(count, chars):
    return [Chapter("I", None, ["Il monta l'escalier. " * (chars // 20) for _ in range(count)])]


def test_a_book_smaller_than_the_opening_is_glossed_whole():
    """Which is what makes this scale rather than merely cap: nothing is left for
    a reader to buy on a book that fits."""
    from biread.gloss import OPENING_CHARS, opening

    book = _book_of(30, OPENING_CHARS // 60)
    assert opening(book) == 30


def test_the_opening_is_a_stretch_of_reading_not_a_count_of_paragraphs():
    """Two books of the same length in paragraphs and different lengths in prose
    must not be given the same opening: 40 paragraphs is the whole of Micromégas
    and thirteen spreads of La Nausée's four hundred and ninety-seven."""
    from biread.gloss import OPENING_CHARS, OPENING_MIN, opening

    short_paragraphs = opening(_book_of(4000, 200))
    long_paragraphs = opening(_book_of(4000, 2000))
    assert short_paragraphs > long_paragraphs
    for book, taken in ((_book_of(4000, 200), short_paragraphs),
                        (_book_of(4000, 2000), long_paragraphs)):
        paragraphs = book[0].paragraphs
        assert sum(len(p) for p in paragraphs[:taken]) >= OPENING_CHARS
        # And no further than it must go: one paragraph fewer falls short of the
        # budget, unless the floor is what set the count.
        assert (taken == OPENING_MIN
                or sum(len(p) for p in paragraphs[:taken - 1]) < OPENING_CHARS)


def test_the_opening_is_bounded_at_both_ends():
    """A book of very long paragraphs still gets a few, and a book of very short
    ones does not run away with the build."""
    from biread.gloss import OPENING_MAX, OPENING_MIN, opening

    assert opening(_book_of(200, 40_000)) == OPENING_MIN
    assert opening(_book_of(20_000, 20)) == OPENING_MAX


def test_the_opening_is_what_the_run_then_asks_for(tmp_path):
    from biread.gloss import opening, plan_gloss

    book = _book_of(4000, 200)
    plan = plan_gloss(book, Cache.load(tmp_path / "g.json"), limit=opening(book))
    assert plan.run.total == opening(book)


# ---------- driven from outside: the browser's several-at-once pass ----------

def _long_book(count=14):
    return [Chapter("I", None, [
        f"Paragraphe {n} du texte, et puis une suite un peu plus longue pour occuper "
        f"la place qu'il faut pour remplir plusieurs lots." for n in range(count)
    ])]


def _reply_for(plan, n):
    """A well-formed answer for one batch: the opening clause of each paragraph."""
    blocks = []
    for i, index in enumerate(plan.groups[n]):
        head = plan.units[index].text.split(",")[0]
        blocks.append((i, [line(head, "noun phrase", "a paragraph")]))
    return response(*blocks).text


def test_batches_answered_out_of_order_gloss_the_same_book(tmp_path, config, make_client):
    """The browser sends six batches at once and the network settles them in
    whatever order it likes. What may be kept is gloss.py's judgement whoever is
    driving, so the two paths cannot be allowed to disagree."""
    from biread.gloss import absorb, plan_gloss, rescue_failures, written_off

    book = _long_book()
    straight = Cache.load(tmp_path / "a.json")
    order = plan_gloss(book, straight)
    assert len(order.groups) > 1, "the fixture must run to several batches"
    expected = gloss_book(
        book, make_client(script=[Completion(_reply_for(order, n), False)
                                  for n in range(len(order.groups))]),
        straight, config(),
    )

    backwards = Cache.load(tmp_path / "b.json")
    plan = plan_gloss(book, backwards)
    for n in reversed(range(len(plan.groups))):
        absorb(plan, n, _reply_for(plan, n), backwards)
        written_off(plan, n)
    rescue_failures(plan, make_client(), backwards)

    assert plan.run.glosses == expected.glosses
    assert plan.run.glossed == expected.glossed
    assert not plan.run.unglossed
    assert len(Cache.load(tmp_path / "b.json")) == len(Cache.load(tmp_path / "a.json"))


def test_a_batch_that_will_not_anchor_reaches_the_rescue_pass(tmp_path, config, make_client):
    """Written off is not lost: the driven path must hand a failed batch on to
    the same one-paragraph-at-a-time retry the sequential path makes."""
    from biread.gloss import absorb, plan_gloss, rescue_failures, written_off

    book = [Chapter("I", None, [PARAGRAPH])]
    cache = Cache.load(tmp_path / "g.json")
    plan = plan_gloss(book, cache)
    assert absorb(plan, 0, "I cannot do that.", cache) == 0
    written_off(plan, 0)
    assert [u.text for u in plan.failed] == [PARAGRAPH]

    saved = response((0, [line("Sur la table", "prep. phrase", "on the table")]))
    rescue_failures(plan, make_client(script=[saved]), cache)
    assert plan.run.rescued == 1
    assert hash_text(PARAGRAPH) in plan.run.glosses


def test_glosses_already_paid_for_are_not_asked_for_again(tmp_path, config, make_client):
    """The resume the browser's storage buys: a plan made against a cache that
    already holds half the book asks for the other half only."""
    from biread.gloss import plan_gloss

    book = _long_book()
    cache = Cache.load(tmp_path / "g.json")
    first = plan_gloss(book, cache)
    gloss_book(book, make_client(script=[Completion(_reply_for(first, n), False)
                                         for n in range(len(first.groups))]), cache, config())

    again = plan_gloss(book, Cache.load(tmp_path / "g.json"))
    assert again.groups == []
    assert len(again.run.glosses) == 14
