"""Target languages: what changes when a book is built into a language other
than English.

The source stays French (that is `language.py`). This is the *target* — the
right-page translation, the glosses' explanation language, the chapter word, the
hyphenation code, and every functional label in the reader. Adding a language is
one `Target` row, the same way a source language is one `Language` row.

The `Lecteur bilingue` masthead is deliberately *not* here: it stays French for
every book, as the reader's signature. Everything else in `ui` follows the
target.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Target:
    key: str          #: the --lang value, e.g. "spanish"
    name: str         #: the language's English name, for the model prompts
    code: str         #: BCP-47 code for the translated column's hyphenation
    chapter_word: str #: the eyebrow word: "Chapter" / "Capítulo" / "Kapitel"
    ui: dict[str, str]  #: every functional reader string, keyed by role


# The reader strings, English. Each key is used once in reader.html/js; a new
# language supplies the same keys. Format names ("EPUB", "PDF") are not here —
# they are proper nouns. `{n}` placeholders are filled in the reader.
_ENGLISH_UI = {
    "copyLink": "Copy a link to this page",
    "goToPage": "Go to a page",
    "pageNumber": "Page number",
    "blur": "Blur translation",
    "showTranslation": "Show translation",
    "translation": "Translation",
    "published": "Published",
    "aboutPublished": "About the published translation",
    "chapters": "Chapters",
    "bookmark": "Bookmark this spread",
    "removeBookmark": "Remove bookmark",
    "bookmarks": "Bookmarks",
    "noBookmarks": "No bookmarks yet — tap the star to save your place.",
    "pageAbbr": "p.",
    "smallerText": "Smaller text",
    "largerText": "Larger text",
    "download": "Download this book",
    "downloadTitle": "Download",
    "epubSub": "For e-readers",
    "pdfSub": "Print · side by side",
    "publishedPanelTitle": "Published translation",
    "publishedToggleHint": "Switch the toggle to read the published translation instead of the generated one.",
    "bringYourOwn": "You can read a published translation alongside this one. Bring a copy you own and pass it in:",
    "privacyFoot": "Your text stays on your machine and is never included in shared files.",
    "resume": "Return to where you left off",
    "resumeButton": "Resume",
    "dismiss": "Dismiss",
    "close": "Close",
    "loading": "Opening the book…",
    "damaged": "This file is damaged — rebuild it with biread.",
}

_SPANISH_UI = {
    "copyLink": "Copiar un enlace a esta página",
    "goToPage": "Ir a una página",
    "pageNumber": "Número de página",
    "blur": "Difuminar la traducción",
    "showTranslation": "Mostrar la traducción",
    "translation": "Traducción",
    "published": "Publicada",
    "aboutPublished": "Sobre la traducción publicada",
    "chapters": "Capítulos",
    "bookmark": "Marcar esta página",
    "removeBookmark": "Quitar el marcador",
    "bookmarks": "Marcadores",
    "noBookmarks": "Aún no hay marcadores — toca la cinta para guardar tu sitio.",
    "pageAbbr": "pág.",
    "smallerText": "Texto más pequeño",
    "largerText": "Texto más grande",
    "download": "Descargar este libro",
    "downloadTitle": "Descargar",
    "epubSub": "Para lectores electrónicos",
    "pdfSub": "Impresión · a doble página",
    "publishedPanelTitle": "Traducción publicada",
    "publishedToggleHint": "Cambia el selector para leer la traducción publicada en lugar de la generada.",
    "bringYourOwn": "Puedes leer una traducción publicada junto a esta. Trae un ejemplar que tengas y pásalo:",
    "privacyFoot": "Tu texto permanece en tu equipo y nunca se incluye en los archivos compartidos.",
    "resume": "Volver a donde lo dejaste",
    "resumeButton": "Continuar",
    "dismiss": "Descartar",
    "close": "Cerrar",
    "loading": "Abriendo el libro…",
    "damaged": "Este archivo está dañado — vuelve a generarlo con biread.",
}

ENGLISH = Target("english", "English", "en", "Chapter", _ENGLISH_UI)
SPANISH = Target("spanish", "Spanish", "es", "Capítulo", _SPANISH_UI)

# Registry keyed by --lang value. Add a language by adding a row (and its ui
# table); every key in _ENGLISH_UI must be present, which `_check` enforces.
TARGETS: dict[str, Target] = {t.key: t for t in (ENGLISH, SPANISH)}

DEFAULT_LANG = ENGLISH.key


def get_target(key: str) -> Target:
    try:
        return TARGETS[key]
    except KeyError:
        options = ", ".join(sorted(TARGETS))
        raise KeyError(f"unknown --lang {key!r}; available: {options}") from None


def _check() -> None:
    """Every target carries the full set of ui keys — a missing one would render
    as a blank label, so fail loudly at import instead."""
    for target in TARGETS.values():
        missing = _ENGLISH_UI.keys() - target.ui.keys()
        if missing:
            raise ValueError(f"{target.key} ui missing keys: {sorted(missing)}")


_check()
