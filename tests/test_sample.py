import pytest

from biread.cleanup import Chapter
from biread.errors import ExtractError
from biread.sample import PAGE_PARAGRAPHS, pages, sample_align, sample_translate


def chapter(number, paragraphs):
    return Chapter(number, f"Titre {number}", paragraphs)


def numbered(count):
    return [chapter("I", [f"Paragraphe {i}." for i in range(count)])]


# A fake multilingual embedder, as in test_align: a concept maps to a fixed
# vector, so French and English land together though they share no characters.
CONCEPTS = {
    "chat": [1, 0, 0], "cat": [1, 0, 0],
    "chien": [0, 1, 0], "dog": [0, 1, 0],
    "oiseau": [0, 0, 1], "bird": [0, 0, 1],
}


def embed(texts):
    def vector(text):
        for word, v in CONCEPTS.items():
            if word in text.lower():
                return v
        return [0, 0, 0]

    return [vector(t) for t in texts]


# ---- slicing ----

def test_pages_slices_the_body_into_page_sized_runs():
    assert pages(numbered(7)) == [
        ["Paragraphe 0.", "Paragraphe 1.", "Paragraphe 2."],
        ["Paragraphe 3.", "Paragraphe 4.", "Paragraphe 5."],
        ["Paragraphe 6."],
    ]


def test_a_book_shorter_than_a_page_is_one_short_page():
    assert pages(numbered(2)) == [["Paragraphe 0.", "Paragraphe 1."]]


def test_pages_reads_across_chapters_in_order():
    book = [chapter("I", ["Un.", "Deux."]), chapter("II", ["Trois.", "Quatre."])]
    assert pages(book) == [["Un.", "Deux.", "Trois."], ["Quatre."]]


def test_a_book_with_no_paragraphs_has_no_pages():
    assert pages([Chapter("I", "Titre", [])]) == []


# ---- translating a sample ----

def test_sample_translates_the_first_page(client, config):
    page = sample_translate(numbered(7), client, config(), "English")
    assert page.index == 0
    assert page.total == 3
    assert page.source == ["Paragraphe 0.", "Paragraphe 1.", "Paragraphe 2."]
    assert all(t.startswith("English rendering of") for t in page.target)
    assert len(page.target) == len(page.source)


def test_sample_costs_only_what_it_spent(client, config):
    # Successive samples on one client must not bill the running total.
    first = sample_translate(numbered(9), client, config(), "English")
    second = sample_translate(numbered(9), client, config(), "English", index=1)
    assert first.cost > 0
    assert second.cost == pytest.approx(first.cost)


def test_sample_has_no_cost_without_pricing(client, config):
    assert sample_translate(numbered(4), client, config(price_per_mtok=None), "English").cost is None


def test_sample_index_wraps_so_another_page_can_count_forever(client, config):
    book = numbered(7)  # three pages
    assert sample_translate(book, client, config(), "English", index=3).index == 0
    assert sample_translate(book, client, config(), "English", index=4).index == 1
    assert sample_translate(book, client, config(), "English", index=-1).index == 2


def test_sample_names_the_target_language(client, config):
    sample_translate(numbered(3), client, config(), "Spanish")
    assert "into Spanish" in client.prompts[0]


def test_sample_opens_on_the_body_not_the_title_page():
    # The unnumbered front matter is trimmed, exactly as a full build trims it.
    book = [
        Chapter(None, None, ["Produced by a volunteer transcriber for the archive."]),
        chapter("I", ["Le chat dort.", "Le chien court."]),
    ]
    assert pages(book)[0][0].startswith("Produced by")
    page = sample_align(book, [chapter("I", ["The cat sleeps.", "The dog runs."])], embed)
    assert page.source == ["Le chat dort.", "Le chien court."]


def test_sample_refuses_a_book_that_never_broke_into_paragraphs(client, config):
    blob = [Chapter("I", None, ["x" * 20_000])]
    with pytest.raises(ExtractError, match="did not come apart into paragraphs"):
        sample_translate(blob, client, config(), "English")


# ---- aligning a sample ----

def test_sample_align_matches_by_meaning():
    french = [chapter("I", ["Le chat dort.", "Le chien court.", "L'oiseau vole."])]
    published = [chapter("I", ["The cat sleeps.", "The dog runs.", "The bird flies."])]
    page = sample_align(french, published, embed)
    assert page.target == ["The cat sleeps.", "The dog runs.", "The bird flies."]
    assert page.cost is None  # the caller prices its own embeddings


def test_sample_align_window_clamps_at_the_start_of_the_book():
    seen = []

    def watched(texts):
        seen.append(texts)
        return embed(texts)

    french = numbered(60)
    published = [chapter("I", [f"Paragraph {i}." for i in range(60)])]
    page = sample_align(french, published, watched, index=0, window=5)
    assert page.index == 0
    # Nothing before the first paragraph, and the window does not run away with
    # the whole book.
    window = seen[1]
    assert window[0] == "Paragraph 0."
    assert len(window) == 5 + PAGE_PARAGRAPHS


def test_sample_align_window_clamps_at_the_end_of_the_book():
    seen = []

    def watched(texts):
        seen.append(texts)
        return embed(texts)

    french = numbered(60)  # 20 pages
    published = [chapter("I", [f"Paragraph {i}." for i in range(60)])]
    sample_align(french, published, watched, index=19, window=5)
    window = seen[1]
    assert window[-1] == "Paragraph 59."
    assert len(window) <= 5 + PAGE_PARAGRAPHS + 5


def test_sample_align_leaves_a_paragraph_blank_rather_than_guessing():
    french = [chapter("I", ["Le chat dort."])]
    page = sample_align(french, [chapter("I", ["[1] A note, and nothing else."])], embed)
    assert page.target == [""]


def test_sample_align_refuses_an_unusable_published_edition():
    french = [chapter("I", ["Le chat dort."])]
    blob = [Chapter("I", None, ["x" * 20_000])]
    with pytest.raises(ExtractError, match="published translation"):
        sample_align(french, blob, embed)
