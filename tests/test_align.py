import pytest

from biread.align import _flow_anchored, align_published
from biread.cleanup import Chapter
from biread.errors import AlignmentError
from biread.translate import hash_text


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
