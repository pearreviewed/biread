import pytest

from biread.cache import Cache
from biread.cleanup import Chapter
from biread.errors import TranslationError
from biread.llm.base import Completion
from biread.translate import (
    BATCH_MAX_CHARS,
    BATCH_SIZE,
    batch,
    build_prompt,
    estimate,
    flatten,
    hash_text,
    parse_response,
    pending_indices,
    translate_book,
)


def test_flatten_includes_titles_in_reading_order(book):
    assert [u.text for u in flatten(book)] == [
        "Preamble.",
        "Le Départ",
        "Premier paragraphe.",
        "Deuxième paragraphe.",
        "L'Arrivée",
        "Troisième paragraphe.",
    ]


def test_pending_skips_cached():
    units = flatten([Chapter(None, None, ["A", "B"])])
    assert pending_indices(units, {hash_text("A"): "done"}) == [1]


def test_pending_deduplicates_repeated_text():
    units = flatten([Chapter(None, None, ["* * *", "Body.", "* * *"])])
    # The repeat resolves from the first translation; paying twice is waste.
    assert pending_indices(units, {}) == [0, 1]


def test_batches_respect_the_count_limit():
    units = flatten([Chapter(None, None, ["x"] * 10)])
    groups = list(batch(units, list(range(10))))
    assert all(len(g) <= BATCH_SIZE for g in groups)
    assert [i for g in groups for i in g] == list(range(10))


def test_batches_respect_the_size_limit():
    units = flatten([Chapter(None, None, ["y" * (BATCH_MAX_CHARS // 2 + 10)] * 4)])
    groups = list(batch(units, list(range(4))))
    assert all(len(g) == 1 for g in groups)


def test_an_oversized_paragraph_still_gets_a_batch():
    units = flatten([Chapter(None, None, ["z" * (BATCH_MAX_CHARS * 3)])])
    assert list(batch(units, [0])) == [[0]]


def test_parse_tolerates_prose_that_would_break_json():
    raw = '@@@0@@@\n« Bonjour », dit-il.\n\nUne "citation" — et un tiret.\n@@@1@@@\nSecond.'
    parsed = parse_response(raw)
    assert parsed[0] == '« Bonjour », dit-il.\n\nUne "citation" — et un tiret.'
    assert parsed[1] == "Second."


def test_parse_rejects_a_response_with_no_markers():
    with pytest.raises(ValueError, match="no @@@N@@@ markers"):
        parse_response("Here is your translation!")


def test_prompt_carries_the_previous_paragraph_as_context(book):
    units = flatten(book)
    prompt = build_prompt(units, {units[0].hash: "Preamble in English."}, [1])
    assert "CONTEXT" in prompt
    assert "Preamble in English." in prompt
    assert "=== PARAGRAPH 0 ===\nLe Départ" in prompt


def test_first_unit_has_no_context(book):
    assert not build_prompt(flatten(book), {}, [0]).startswith("CONTEXT")


def test_translate_fills_every_unit(tmp_path, book, client, config):
    cache = Cache.load(tmp_path / "c.json")
    run = translate_book(book, client, cache, config())
    assert run.total == 6
    assert run.translated == 6
    assert len(run.translations) == 6
    assert all(v for v in run.translations.values())


def test_translations_are_cached_as_they_land(tmp_path, book, client, config):
    path = tmp_path / "c.json"
    translate_book(book, client, Cache.load(path), config())
    assert len(Cache.load(path)) == 6


def test_cached_work_is_not_resent(tmp_path, book, config, make_client):
    path = tmp_path / "c.json"
    translate_book(book, make_client(), Cache.load(path), config())

    second = make_client()
    run = translate_book(book, second, Cache.load(path), config())
    assert second.prompts == []
    assert run.translated == 0
    assert len(run.translations) == 6


def test_repeated_paragraphs_are_translated_once(tmp_path, config, make_client):
    chapters = [Chapter(None, None, ["* * *", "Body.", "* * *"])]
    client = make_client()
    run = translate_book(chapters, client, Cache.load(tmp_path / "c.json"), config())
    assert len(client.prompts) == 1
    assert run.translations[hash_text("* * *")]


def test_malformed_response_is_retried_then_succeeds(tmp_path, book, config, make_client):
    client = make_client(script=[Completion("I cannot do that.", False)])
    run = translate_book(book, client, Cache.load(tmp_path / "c.json"), config())
    assert len(client.prompts) == 3  # two batches, the first one retried
    assert run.translated == 6


def test_persistently_malformed_response_raises(tmp_path, book, config, make_client):
    client = make_client(script=[Completion("nope", False), Completion("still nope", False)])
    with pytest.raises(TranslationError, match="could not parse"):
        translate_book(book, client, Cache.load(tmp_path / "c.json"), config())


def test_missing_paragraph_in_response_is_caught(tmp_path, book, config, make_client):
    partial = Completion("@@@0@@@\nOnly the first.", False)
    client = make_client(script=[partial, partial])
    with pytest.raises(TranslationError, match="missing paragraph"):
        translate_book(book, client, Cache.load(tmp_path / "c.json"), config())


def test_truncated_completion_raises_instead_of_saving_half(tmp_path, book, config, make_client):
    client = make_client(script=[Completion("@@@0@@@\nCut off mid-", True)])
    with pytest.raises(TranslationError, match="output limit"):
        translate_book(book, client, Cache.load(tmp_path / "c.json"), config())


def test_run_stops_at_the_cost_cap_and_keeps_its_work(tmp_path, config, make_client):
    chapters = [Chapter(None, None, [f"Paragraphe {i}." for i in range(40)])]
    path = tmp_path / "c.json"
    # FakeClient bills 100 in / 50 out per call: one batch is $0.00105.
    run = translate_book(chapters, make_client(), Cache.load(path), config(max_cost_usd=0.002))
    assert run.stopped_at_cap
    assert run.translated < 40
    assert len(Cache.load(path)) == run.translated


def test_unpriced_model_cannot_stop_at_the_cap(tmp_path, book, config, make_client):
    run = translate_book(book, make_client(), Cache.load(tmp_path / "c.json"), config(price_per_mtok=None))
    assert run.cost is None
    assert not run.stopped_at_cap


def test_estimate_counts_only_uncached_work(tmp_path, book, config):
    cache = Cache.load(tmp_path / "c.json")
    cache.update({hash_text("Preamble."): "Preamble in English."})
    result = estimate(book, cache, config())
    assert result.total == 6
    assert result.cached == 1
    assert result.pending == 5
    assert result.cost > 0


def test_estimate_has_no_cost_without_pricing(tmp_path, book, config):
    result = estimate(book, Cache.load(tmp_path / "c.json"), config(price_per_mtok=None))
    assert result.cost is None


def test_progress_is_reported(tmp_path, book, client, config):
    seen = []
    translate_book(
        book, client, Cache.load(tmp_path / "c.json"), config(),
        lambda done, total: seen.append((done, total)),
    )
    assert seen[-1] == (6, 6)
