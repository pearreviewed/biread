from biread.build import build_reader
from biread.cache import Cache
from biread.translate import flatten


def body(book):
    return flatten(book[1:])  # build_reader trims the unnumbered preamble


def test_build_streams_the_translation_as_it_arrives(book, client, config):
    """The builder's progress screen fills its right-hand page with real prose
    while the book is still being translated."""
    seen = []
    build_reader(
        title="Micromégas", chapters=book, client=client, cache=Cache(None), cfg=config(),
        on_text=lambda pairs: seen.extend(pairs),
    )
    assert [french for french, _ in seen] == [u.text for u in body(book)]
    assert all(english for _, english in seen)


def test_build_without_a_text_callback_is_unchanged(book, client, config):
    result = build_reader(
        title="Micromégas", chapters=book, client=client, cache=Cache(None), cfg=config()
    )
    assert result.translation.translated == len(body(book))
    assert "Micromégas" in result.html
