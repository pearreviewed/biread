import re
import pytest

from biread.align import (
    AlignmentReport, _flow_anchored, _shape_spread, align_published,
)
from biread.anchor import agreements
from biread.cleanup import Chapter
from biread.errors import AlignmentError
from biread.numbering import number_tokens
from biread.translate import hash_text


def test_spelled_numbers_read_to_the_same_token_across_languages():
    # A quantity survives translation like a name does, once read off the words.
    assert "num71" in number_tokens("seventy-one quarterings")
    assert "num71" in number_tokens("soixante et onze quartiers")
    assert "num350" in number_tokens("three hundred and fifty pounds")
    assert "num350" in number_tokens("trois cent cinquante livres")
    assert "num80" in number_tokens("quatre-vingts")  # four twenties, not four then twenty


def test_embedding_alignment_matches_by_meaning_not_words():
    # A fake multilingual embedder: each concept maps to a fixed vector, so a
    # French paragraph and its English translation embed identically though they
    # share no characters. Alignment must pair them by that meaning.
    concept = {"chat": [1, 0, 0], "cat": [1, 0, 0], "chien": [0, 1, 0], "dog": [0, 1, 0],
               "oiseau": [0, 0, 1], "bird": [0, 0, 1]}
    def vec(text):
        for word, v in concept.items():
            if word in text.lower():
                return v
        return [0, 0, 0]
    def embed(texts):
        return [vec(t) for t in texts]

    french = [chapter("I", ["Le chat dort.", "Le chien court.", "L'oiseau vole."])]
    english = [chapter("I", ["The cat sleeps.", "The dog runs.", "The bird flies."])]
    aligned, report = align_published(french, english, embed=embed)
    assert aligned[hash_text("Le chat dort.")] == "The cat sleeps."
    assert aligned[hash_text("Le chien court.")] == "The dog runs."
    assert aligned[hash_text("L'oiseau vole.")] == "The bird flies."
    assert report.method == "pivot" and not report.approximate


def test_length_fill_pairs_dialogue_and_merges_without_loss():
    # A run of terse dialogue with nothing to anchor on: the French sets each turn
    # on its own line, the English fuses two. Length alignment pairs short with
    # short, lets two lines meet one, and loses no text — where a proportional
    # pour would slide the answers a line out of step.
    left = ["—Oui.", "—Je le veux bien absolument.", "—Tout de suite, dit-il.", "Il sourit."]
    right = ["Yes.", "I should like nothing better.", "At once, said he.", "He smiled."]
    out = _shape_spread(left, right)
    assert len(out) == 4
    assert out[0] == "Yes."                       # short pairs with short, not a slice
    assert "nothing better" in out[1]             # long pairs with long
    assert out[-1] == "He smiled."                # the tail stays put
    joined = " ".join(out)
    assert "At once, said he." in joined          # nothing dropped
    assert joined.count("He smiled.") == 1        # nothing duplicated


def test_a_spelled_number_anchors_where_names_and_cognates_cannot():
    left = ["Bonjour à tous.", "Il possédait soixante et onze moutons.", "Au revoir donc."]
    right = ["Good morning, all.", "He owned seventy-one sheep.", "Goodbye then."]
    # These share no name or cognate; only the number ties the middle sentences.
    assert (1, 1) not in agreements(left, right)
    assert (1, 1) in agreements(left, right, number_tokens)


def test_anchored_flow_pins_names_so_the_columns_do_not_drift():
    # A published chapter arriving as one blob, several shared names in it: the
    # French paragraph naming Pangloss must draw the English naming Pangloss, not
    # a length-proportional slice that lands a sentence early.
    french = [
        "Candide vivait au château de Thunder-ten-tronckh fort paisiblement.",
        "Pangloss enseignait la métaphysique au jeune Candide chaque matin.",
        "Cunégonde était la fille unique du vieux baron de Thunder.",
        "Le baron chassa Candide du château à grands coups de pied.",
    ]
    english = [
        "Candide lived in the castle of Thunder-ten-Tronckh most peacefully. "
        "Pangloss taught metaphysics to young Candide every morning. "
        "Cunegonde was the only daughter of the old Baron of Thunder. "
        "The Baron drove Candide from the castle with great kicks."
    ]
    out = _flow_anchored(french, english)
    assert len(out) == 4 and all(out)
    assert "Pangloss" in out[1]
    assert "Cunegonde" in out[2]


def chapter(number, paragraphs):
    return Chapter(number, f"Titre {number}", paragraphs)


def test_matching_counts_align_one_to_one():
    french = [chapter("I", ["Un.", "Deux."])]
    published = [chapter("I", ["One.", "Two."])]
    aligned, report = align_published(french, published)
    assert aligned[hash_text("Un.")] == "One."
    assert aligned[hash_text("Deux.")] == "Two."
    assert report.exact == 1
    assert not report.approximate


def test_split_dialogue_is_grouped_proportionally():
    # The real case: a translator splits one French paragraph into several.
    french = [chapter("I", ["Un.", "Deux."])]
    published = [chapter("I", ["One.", "One and a half.", "Two.", "Two and a half."])]
    aligned, report = align_published(french, published)
    assert aligned[hash_text("Un.")] == "One. One and a half."
    assert aligned[hash_text("Deux.")] == "Two. Two and a half."
    assert report.grouped == 1
    assert report.approximate


def test_merged_paragraphs_still_get_a_counterpart():
    french = [chapter("I", ["Un.", "Deux.", "Trois."])]
    published = [chapter("I", ["Everything in one."])]
    aligned, _ = align_published(french, published)
    assert all(aligned[hash_text(p)] for p in ["Un.", "Deux.", "Trois."])


def test_every_french_paragraph_is_covered_in_order():
    french = [chapter("I", [f"FR{i}" for i in range(7)])]
    published = [chapter("I", [f"EN{i}" for i in range(19)])]
    aligned, _ = align_published(french, published)
    assert len(aligned) == 7
    joined = " ".join(aligned[hash_text(f"FR{i}")] for i in range(7))
    # Nothing dropped, nothing reordered.
    assert joined.split() == [f"EN{i}" for i in range(19)]


def test_chapters_resync_after_drift():
    french = [chapter("I", ["A1", "A2"]), chapter("II", ["B1"])]
    published = [chapter("I", ["a1", "a1b", "a2"]), chapter("II", ["b1"])]
    aligned, report = align_published(french, published)
    # Chapter II is unaffected by chapter I's uneven split.
    assert aligned[hash_text("B1")] == "b1"
    assert report.chapters_matched


def test_mismatched_chapter_counts_fall_back_to_whole_book():
    french = [chapter("I", ["Un."]), chapter("II", ["Deux."])]
    published = [chapter("I", ["One.", "Two."])]
    aligned, report = align_published(french, published)
    assert not report.chapters_matched
    assert report.approximate
    assert aligned[hash_text("Un.")] == "One."
    assert aligned[hash_text("Deux.")] == "Two."
    assert "Chapter structures differ" in report.notes[0]


def test_chapters_without_paragraphs_are_ignored():
    french = [Chapter("I", "Titre", []), chapter("II", ["Un."])]
    published = [chapter("II", ["One."])]
    aligned, report = align_published(french, published)
    assert report.chapters_matched
    assert aligned[hash_text("Un.")] == "One."


def test_empty_input_is_an_error():
    with pytest.raises(AlignmentError, match="French text has no paragraphs"):
        align_published([Chapter(None, None, [])], [chapter("I", ["One."])])
    with pytest.raises(AlignmentError, match="published translation has no paragraphs"):
        align_published([chapter("I", ["Un."])], [Chapter(None, None, [])])


# ---- matching against the generated translation (the trustworthy path) ----

def generated(*pairs):
    return {hash_text(fr): en for fr, en in pairs}


def test_pivot_matches_by_content_not_position():
    # Front matter shifts every paragraph by one, so a positional pass would
    # hand the transcriber's note to the first French paragraph. Both texts
    # still run in the same order — a translator does not reorder paragraphs,
    # and the alignment relies on that.
    french = [chapter("I", ["Le chat dort sur la table.", "Le chien court dans le jardin."])]
    published = [chapter("I", [
        "Produced by a volunteer transcriber for the archive.",
        "The cat is asleep upon the table.",
        "The dog runs about in the garden, happily.",
    ])]
    translations = generated(
        ("Le chat dort sur la table.", "The cat sleeps on the table."),
        ("Le chien court dans le jardin.", "The dog runs in the garden."),
    )
    aligned, report = align_published(french, published, translations)
    assert "cat" in aligned[hash_text("Le chat dort sur la table.")]
    assert "dog" in aligned[hash_text("Le chien court dans le jardin.")]
    assert report.method == "pivot"
    assert not report.approximate


def test_pivot_rejoins_a_paragraph_the_translator_split():
    french = [chapter("I", ["Le chat dort sur la table pendant des heures."])]
    published = [chapter("I", [
        "The cat sleeps upon the table.",
        "It sleeps there for hours on end.",
    ])]
    translations = generated(
        ("Le chat dort sur la table pendant des heures.",
         "The cat sleeps on the table for hours."),
    )
    aligned, _ = align_published(french, published, translations)
    joined = aligned[hash_text("Le chat dort sur la table pendant des heures.")]
    assert "upon the table" in joined and "hours on end" in joined


def test_pivot_drops_footnotes_and_front_matter():
    french = [chapter("I", ["Le chat dort sur la table."])]
    published = [chapter("I", [
        "[3] The 1773 edition reads otherwise; earlier printings differ.",
        "The cat is asleep upon the table.",
        "Produced by a volunteer. HTML version by another volunteer.",
    ])]
    translations = generated(("Le chat dort sur la table.", "The cat sleeps on the table."))
    aligned, report = align_published(french, published, translations)
    text = aligned[hash_text("Le chat dort sur la table.")]
    assert "1773" not in text and "volunteer" not in text
    assert report.dropped == 2


def test_pivot_leaves_a_paragraph_blank_rather_than_guessing():
    # The French citation line has no counterpart in the published edition.
    french = [chapter("I", ["Voltaire, Garnier, 1877, tome 21.", "Le chat dort sur la table."])]
    published = [chapter("I", ["The cat is asleep upon the table."])]
    translations = generated(
        ("Voltaire, Garnier, 1877, tome 21.", "Voltaire, Garnier, 1877, volume 21."),
        ("Le chat dort sur la table.", "The cat sleeps on the table."),
    )
    aligned, report = align_published(french, published, translations)
    assert aligned[hash_text("Voltaire, Garnier, 1877, tome 21.")] == ""
    assert "cat" in aligned[hash_text("Le chat dort sur la table.")]
    assert report.unmatched == 1


def test_pivot_keeps_reading_order():
    subjects = ["chat", "chien", "cheval", "oiseau"]
    animals = ["cat", "dog", "horse", "bird"]
    french = [chapter("I", [f"Le {s} traverse la cour tranquillement." for s in subjects])]
    published = [chapter("I", [f"The {a} crosses the courtyard, quite calmly." for a in animals])]
    translations = generated(*[
        (f"Le {s} traverse la cour tranquillement.", f"The {a} crosses the courtyard calmly.")
        for s, a in zip(subjects, animals)
    ])
    aligned, _ = align_published(french, published, translations)
    for subject, animal in zip(subjects, animals):
        assert animal in aligned[hash_text(f"Le {subject} traverse la cour tranquillement.")]


# ---- editions that divide the book differently ----

def _concepts():
    words = [("chat", "cat"), ("chien", "dog"), ("oiseau", "bird"),
             ("cheval", "horse"), ("arbre", "tree"), ("fleur", "flower")]
    vectors = {}
    for i, (fr, en) in enumerate(words):
        vector = [0.0] * len(words)
        vector[i] = 1.0
        vectors[fr] = vectors[en] = vector
    def embed(texts):
        out = []
        for text in texts:
            found = [0.0] * len(words)
            for word, vector in vectors.items():
                if word in text.lower():
                    found = vector
                    break
            out.append(found)
        return out
    return words, embed


ROMAN = ["I", "II", "III", "IV", "V", "VI"]


def test_a_published_edition_that_merges_chapters_still_aligns_whole():
    """Numbers that look pairable and are not: an edition merging six chapters
    into three leaves the French tail facing nothing, though every word of it is
    in the other book under a different number. Paired that way it covered 50%."""
    words, embed = _concepts()
    french = [Chapter(ROMAN[i], f"T{i}", [f"Le {fr} dort ici."]) for i, (fr, _) in enumerate(words)]
    merged = [
        Chapter("I", "T1", [f"The {words[0][1]} sleeps here.", f"The {words[1][1]} sleeps here."]),
        Chapter("II", "T2", [f"The {words[2][1]} sleeps here.", f"The {words[3][1]} sleeps here."]),
        Chapter("III", "T3", [f"The {words[4][1]} sleeps here.", f"The {words[5][1]} sleeps here."]),
    ]
    aligned, report = align_published(french, merged, embed=embed)
    assert report.coverage == 1.0
    assert not report.degraded
    assert aligned[hash_text("Le chat dort ici.")] == "The cat sleeps here."
    assert aligned[hash_text("Le fleur dort ici.")] == "The flower sleeps here."


def test_editions_that_divide_alike_are_still_paired_chapter_by_chapter():
    # The fallback must not swallow the common case: pairing by number keeps a
    # chapter's paragraphs from being matched against the whole book.
    from biread.align import _chapter_pairs

    words, _ = _concepts()
    french = [Chapter(ROMAN[i], f"T{i}", [f"Le {fr} dort ici."]) for i, (fr, _) in enumerate(words)]
    english = [Chapter(ROMAN[i], f"T{i}", [f"The {en} sleeps here."]) for i, (_, en) in enumerate(words)]
    assert len(_chapter_pairs(french, english)) == len(french)


# ---------- numbering that looks sound and is not ----------
# A translation that drops a chapter and renumbers what follows leaves both
# editions with contiguous, complete-looking numbers and every later pairing off
# by one. The 1911 Twenty Thousand Leagues omits French XI: 46 of 47 chapters
# "matched", 37 were the wrong chapter, and coverage fell to 24%.

TOPICS = 9


def topic_vector(text: str) -> list[float]:
    """A chapter about topic *n*, with a little of its neighbours in it — enough
    that the wrong chapter still scores something, as real prose does."""
    n = int(re.search(r"topic-(\d+)", text).group(1))
    vec = [0.0] * (TOPICS + 2)
    vec[n] = 1.0
    for near in (n - 1, n + 1):
        if 0 <= near < len(vec):
            vec[near] = 0.5
    return vec


def topics(texts):
    return [topic_vector(t) for t in texts]


def about(number, topic):
    return chapter(str(number), [f"Ceci traite de topic-{topic}, longuement et en détail.",
                            f"Encore topic-{topic}, pour faire trois paragraphes.",
                            f"Toujours topic-{topic}, et voilà."])


def test_a_translation_that_drops_a_chapter_stops_being_trusted_by_number():
    # French I-VI; the published edition omits French III and renumbers, so its
    # numbers run I-V and every one from III on names the wrong chapter.
    french = [about(n, n) for n in range(1, 7)]
    published = [about(i + 1, topic) for i, topic in enumerate([1, 2, 4, 5, 6])]

    texts, report = align_published(french, published, embed=topics)

    # Chapter IV's French must not be facing chapter V's English.
    fourth = french[3].paragraphs[0]
    assert "topic-5" not in texts[hash_text(fourth)]


def test_a_named_division_takes_the_other_edition_s_own_heading():
    """A diary's sections are dates, not numbers, and `Chapitre N` is not what
    stands over them. The English heading is the one the translator wrote —
    `VENDREDI.` faces `Friday:` because that edition says so, not because we
    turned a French date into an English one."""
    def dated(title, topic):
        return Chapter(None, title, [f"Ceci traite de topic-{topic}, longuement et en détail.",
                                     f"Encore topic-{topic}, pour faire trois paragraphes.",
                                     f"Toujours topic-{topic}, et voilà."])

    french = [dated(f"JOUR {n}.", n) for n in range(1, 5)]
    published = [dated(f"Day {n}:", n) for n in range(1, 5)]

    aligned, report = align_published(french, published, embed=topics)

    assert report.chapter_titles == {hash_text(f"JOUR {n}."): f"Day {n}:" for n in range(1, 5)}
    # Reported apart from the matched prose, not mixed into it: a heading is not
    # a paragraph that landed, and counting it would flatter the coverage figure.
    assert hash_text("JOUR 1.") not in aligned


def test_sound_numbering_is_still_trusted():
    """The check must not push good books onto the slower whole-book path."""
    french = [about(n, n) for n in range(1, 7)]
    published = [about(n, n) for n in range(1, 7)]

    texts, _ = align_published(french, published, embed=topics)

    for n, ch in enumerate(french, start=1):
        assert f"topic-{n}" in texts[hash_text(ch.paragraphs[0])]


def test_too_few_chapters_to_judge_leaves_the_numbering_alone():
    french = [about(1, 1), about(2, 2)]
    published = [about(1, 1), about(2, 2)]
    texts, _ = align_published(french, published, embed=topics)
    assert "topic-2" in texts[hash_text(french[1].paragraphs[0])]


def test_the_dropped_chapter_is_left_blank_not_filled_with_the_next_one():
    """An omitted chapter should face an empty page, never a plausible wrong one."""
    french = [about(n, n) for n in range(1, 7)]
    published = [about(i + 1, topic) for i, topic in enumerate([1, 2, 4, 5, 6])]

    texts, _ = align_published(french, published, embed=topics)

    third = french[2].paragraphs[0]          # French III — the chapter they dropped
    assert texts[hash_text(third)] == ""
    # And every chapter that does exist finds its own counterpart again.
    for n in (1, 2, 4, 5, 6):
        opening = french[n - 1].paragraphs[0]
        assert f"topic-{n}" in texts[hash_text(opening)]


def test_the_report_weighs_the_english_that_landed_against_what_there_was():
    """Coverage alone cannot tell a condensed translation from a failed match.

    20,000 Leagues leaves 41% of the French facing nothing and is matched about
    as well as it can be, because the 1911 English *is* two-thirds of the French.
    The same 59% with a tenth of the English placed would be a fault, and only
    this ratio separates them.
    """
    french = [chapter("I", ["Un.", "Deux.", "Trois."])]
    published = [chapter("I", ["One.", "Two.", "Three."])]
    _, report = align_published(french, published)
    assert report.published_chars == len("One.") + len("Two.") + len("Three.")
    assert report.placed_share == 1.0


def test_english_spread_over_several_french_paragraphs_is_counted_once():
    """Six French against two English: the same English lands more than once, and
    summing every landing would report three times the edition on the page."""
    french = [chapter("I", ["Un.", "Deux.", "Trois.", "Quatre.", "Cinq.", "Six."])]
    published = [chapter("I", ["One.", "Two."])]
    _, report = align_published(french, published)
    assert report.placed_share == 1.0, "all of it, and no more than all of it"


def test_a_report_with_no_published_side_measured_says_nothing_rather_than_zero():
    assert AlignmentReport(method="pivot", chapters_matched=True).placed_share is None


# ---------- a book divided but unnumbered ----------

def test_sections_with_no_numbers_are_paired_by_what_they_are_about():
    """A diary has a spine and no numbers in it. Pairing on nothing, Nausea fell
    all the way back to one run of fifteen hundred paragraphs against another —
    the regime the whole-book path exists to avoid, not to serve."""
    from biread.align import _chapter_pairs

    words, embed = _concepts()
    french = [Chapter(None, f"JEUDI {i}", [f"Le {fr} dort ici."]) for i, (fr, _) in enumerate(words)]
    english = [Chapter(None, f"Thursday {i}", [f"The {en} sleeps here."])
               for i, (_, en) in enumerate(words)]
    pairs = _chapter_pairs(french, english, embed)
    assert len(pairs) == len(french)
    assert all(pub is not None for _, pub in pairs)

    aligned, report = align_published(french, english, embed=embed)
    assert report.coverage == 1.0
    assert aligned[hash_text("Le chat dort ici.")] == "The cat sleeps here."


def test_an_edition_that_divides_the_book_far_more_finely_still_runs_whole():
    """The guard on the rule above. Pairing by content is one to one, so where
    one edition merges, half the book is stranded by construction — that case
    belongs to the whole-book path, which is many to one."""
    from biread.align import _chapter_pairs

    words, embed = _concepts()
    french = [Chapter(None, f"JEUDI {i}", [f"Le {fr} dort ici."]) for i, (fr, _) in enumerate(words)]
    merged = [Chapter(None, "Thursday", [f"The {en} sleeps here." for _, en in words[:3]]),
              Chapter(None, "Friday", [f"The {en} sleeps here." for _, en in words[3:]])]
    assert len(_chapter_pairs(french, merged, embed)) == 1
    assert align_published(french, merged, embed=embed)[1].coverage == 1.0


def test_a_spine_found_in_only_one_edition_does_not_blank_the_other():
    # Sections against a single undivided chapter would hand the whole of that
    # edition to one section and leave the rest of the book facing nothing.
    from biread.align import _chapter_pairs

    words, embed = _concepts()
    french = [Chapter(None, f"JEUDI {i}", [f"Le {fr} dort ici."]) for i, (fr, _) in enumerate(words)]
    whole = [Chapter(None, None, [f"The {en} sleeps here." for _, en in words])]
    assert len(_chapter_pairs(french, whole, embed)) == 1
    assert align_published(french, whole, embed=embed)[1].coverage == 1.0


# ---- a matching run that survives the tab ---------------------------------


def _counted(embed):
    """The same embedder, with a tally of how many texts it was asked to read."""
    calls = []
    def counting(texts):
        calls.extend(texts)
        return embed(texts)
    return counting, calls


def test_a_chapter_matched_once_is_not_matched_again():
    """The align route's long pass, kept as it lands. A build stopped halfway
    used to begin the whole of it again on the next visit."""
    from biread.cache import Cache

    cache = Cache(None)
    french = [about(n, n) for n in range(1, 7)]
    published = [about(n, n) for n in range(1, 7)]

    first, seen = _counted(topics)
    once, _ = align_published(french, published, embed=first, cache=cache, embed_id="bge-m3")
    assert seen, "the first run must actually embed the book"

    second, again = _counted(topics)
    twice, _ = align_published(french, published, embed=second, cache=cache, embed_id="bge-m3")
    assert twice == once, "a resumed match must place the book exactly as the first did"
    # What is left is the chapter pairing, which reads a gist per chapter and not
    # the prose: the paragraphs themselves are never sent a second time.
    body = {p for c in french + published for p in c.paragraphs}
    assert not (set(again) & body)
    assert len(again) < len(seen)


def test_another_edition_is_not_handed_the_last_one_s_placements():
    """A match is a fact about two editions together. Bring a different published
    translation and it is matched afresh, whatever is held for the old one."""
    from biread.cache import Cache

    cache = Cache(None)
    french = [about(n, n) for n in range(1, 4)]
    align_published(french, [about(n, n) for n in range(1, 4)],
                    embed=topics, cache=cache, embed_id="bge-m3")

    other = [Chapter(str(n), f"Titre {n}", [f"Another edition of topic-{n}, at length and in detail.",
                                            f"Still topic-{n}, to make three paragraphs.",
                                            f"Once more topic-{n}, and there it is."])
             for n in range(1, 4)]
    embed, seen = _counted(topics)
    aligned, _ = align_published(french, other, embed=embed, cache=cache, embed_id="bge-m3")
    assert set(seen) & {p for c in other for p in c.paragraphs}
    assert "Another edition" in aligned[hash_text(french[0].paragraphs[0])]


def test_a_model_that_scores_in_another_space_matches_afresh():
    """Each embedding model has its own scale, so what one placed is not what
    another would place, and the two are kept apart."""
    from biread.cache import Cache

    cache = Cache(None)
    french = [about(n, n) for n in range(1, 4)]
    published = [about(n, n) for n in range(1, 4)]
    align_published(french, published, embed=topics, cache=cache, embed_id="bge-m3")

    embed, seen = _counted(topics)
    align_published(french, published, embed=embed, cache=cache, embed_id="text-embedding-3-large")
    assert set(seen) & {p for c in french for p in c.paragraphs}


def test_a_held_match_that_does_not_answer_the_chapter_is_passed_over():
    """An entry is trusted only where it answers paragraph for paragraph. Anything
    else is not this chapter's, whatever it is filed under."""
    from biread.align import _held_match
    from biread.cache import Cache

    cache = Cache(None, {"k": '["One.", "Two."]', "short": '["One."]',
                         "junk": "not json", "wrong": '[1, 2]'})
    assert _held_match(cache, "k", 2) == ["One.", "Two."]
    assert _held_match(cache, "short", 2) is None
    assert _held_match(cache, "junk", 2) is None
    assert _held_match(cache, "wrong", 2) is None
    assert _held_match(cache, "missing", 2) is None
    assert _held_match(None, "k", 2) is None
