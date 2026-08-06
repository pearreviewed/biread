import pytest

from biread.cleanup import Chapter
from biread.errors import ExtractError
from biread.sample import PAGE_CHARS, pages, sample_align, sample_translate


def chapter(number, paragraphs):
    return Chapter(number, f"Titre {number}", paragraphs)


#: Half a page each, so a page is two of them and the arithmetic below reads.
def para(i):
    return f"Paragraphe {i}." + " mot" * 170


def numbered(count):
    return [chapter("I", [para(i) for i in range(count)])]


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

def test_pages_fill_to_about_a_page_of_prose():
    # Short paragraphs: many to a page, and each page stops at the first that
    # would take it over.
    every = pages([chapter("I", ["x" * 500] * 7)])
    assert [len(p) for p in every] == [2, 2, 2, 1]
    assert all(sum(map(len, p)) <= PAGE_CHARS for p in every)


def test_a_paragraph_longer_than_a_page_is_still_a_page():
    # Sartre's are, and a page that refused to hold one would hold nothing.
    assert pages([chapter("I", ["y" * 4000, "Deux."])]) == [["y" * 4000], ["Deux."]]


def test_a_book_shorter_than_a_page_is_one_short_page():
    assert pages(numbered(2)) == [[para(0), para(1)]]


def test_pages_reads_across_chapters_in_order():
    # A page runs on across a chapter boundary rather than stopping at it.
    book = [chapter("I", ["A" * 600]), chapter("II", ["B" * 600, "C" * 600])]
    assert pages(book) == [["A" * 600, "B" * 600], ["C" * 600]]


def test_a_book_with_no_paragraphs_has_no_pages():
    assert pages([Chapter("I", "Titre", [])]) == []


# ---- translating a sample ----

def test_sample_translates_the_first_page(client, config):
    page = sample_translate(numbered(7), client, config(), "English")
    assert page.index == 0
    assert page.total == 4
    assert page.source == [para(0), para(1)]
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
    book = numbered(7)  # four pages
    assert sample_translate(book, client, config(), "English", index=4).index == 0
    assert sample_translate(book, client, config(), "English", index=5).index == 1
    assert sample_translate(book, client, config(), "English", index=-1).index == 3


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

    french = numbered(60)  # thirty pages of two paragraphs
    published = [chapter("I", [f"Paragraph {i}." for i in range(60)])]
    page = sample_align(french, published, watched, index=0, window=5)
    assert page.index == 0
    # Nothing before the first paragraph, and the window does not run away with
    # the whole book. The published window is the last thing embedded: the
    # openings are matched first, to drop any introduction only one side carries.
    window = seen[-1]
    assert window[0] == "Paragraph 0."
    assert len(window) == 5 + len(page.source)


def test_sample_align_window_clamps_at_the_end_of_the_book():
    seen = []

    def watched(texts):
        seen.append(texts)
        return embed(texts)

    french = numbered(60)  # thirty pages of two paragraphs
    published = [chapter("I", [f"Paragraph {i}." for i in range(60)])]
    page = sample_align(french, published, watched, index=29, window=5)
    window = seen[-1]
    assert window[-1] == "Paragraph 59."
    assert len(window) <= 5 + len(page.source) + 5


def test_sample_align_leaves_a_paragraph_blank_rather_than_guessing():
    french = [chapter("I", ["Le chat dort."])]
    page = sample_align(french, [chapter("I", ["[1] A note, and nothing else."])], embed)
    assert page.target == [""]


def test_sample_align_refuses_an_unusable_published_edition():
    french = [chapter("I", ["Le chat dort."])]
    blob = [Chapter("I", None, ["x" * 20_000])]
    with pytest.raises(ExtractError, match="published translation"):
        sample_align(french, blob, embed)


def test_a_sample_page_takes_its_matches_not_the_whole_window():
    """The window runs many times the length of the page, and a matcher that must
    place every published paragraph somewhere hands the whole window out among
    three. Each paragraph takes the one counterpart that answers to it."""
    filler = [f"The horse number {i} runs." for i in range(15)]
    french = [chapter("I", ["Le chat dort.", "Le chien court.", "L'oiseau vole."])]
    published = [chapter("I", filler + ["The cat sleeps.", "The dog runs.", "The bird flies."] + filler)]
    page = sample_align(french, published, embed, window=40)
    assert page.target == ["The cat sleeps.", "The dog runs.", "The bird flies."]


def test_a_sample_page_stays_blank_rather_than_guess():
    # Nothing in the window answers to the French: a wrong pairing shown as a
    # sample is worse than an honest gap, because it is what the reader judges on.
    french = [chapter("I", ["Le chat dort."])]
    published = [chapter("I", [f"The horse number {i} runs." for i in range(20)])]
    assert sample_align(french, published, embed).target == [""]


def test_a_sample_page_is_weighed_as_well_as_read(book, config, make_client):
    """The book's gloss bill is scaled from what the page actually cost, because
    how much a model writes per paragraph is the model's property, not the book's."""
    from biread.gloss import FIELD
    from biread.llm.base import Completion
    from biread.sample import sample_gloss

    reply = Completion("\n".join(
        f"@@@{n}@@@\n" + f" {FIELD} ".join([first, "adj.", "the first"])
        for n, first in enumerate(["Premier", "Deuxième", "Troisième"])
    ), False)
    client = make_client(script=[reply])
    cost = sample_gloss(["Premier paragraphe.", "Deuxième paragraphe.", "Troisième paragraphe."],
                        client, config(), "English")
    assert cost > 0


def test_weighing_a_page_bills_only_that_page(book, config, make_client):
    # A client that has already translated must not have its running total
    # charged to the gloss, or the second sample prices as though it were the third.
    from biread.gloss import FIELD
    from biread.llm.base import Completion
    from biread.sample import sample_gloss

    reply = Completion(f"@@@0@@@\n" + f" {FIELD} ".join(["Premier", "adj.", "the first"]), False)
    client = make_client(script=[reply])
    client.input_tokens, client.output_tokens = 500_000, 500_000  # a long run already behind it
    cost = sample_gloss(["Premier paragraphe."], client, config(), "English")
    assert cost < 0.01
