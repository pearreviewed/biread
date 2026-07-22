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
    "translation": "AI translation",
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
    "reviseEdit": "Edit",
    "reviseRegenerate": "Regenerate",
    "reviseWorking": "Regenerating…",
    "reviseNotePlaceholder": "What's off? (optional)",
    "reviseSave": "Save",
    "reviseCancel": "Cancel",
    "reviseUndo": "Undo",
    "reviseKeyTitle": "Your key, your edits",
    "reviseKeyBody": "Kept on this device, sent only to {provider} — never to us.",
    "reviseKeyPlaceholder": "Your {provider} key",
    "reviseRemember": "Remember on this device",
    "reviseForget": "Forget key",
    "reviseKeyManage": "Key",
    "reviseError": "Couldn't reach the model. Check your key, or type the fix by hand.",
    "reviseUnreachable": "This book's model can't be reached from the browser — you can still edit by hand.",
    "reviseCopyEdits": "Copy a link to your corrections",
}

_SPANISH_UI = {
    "copyLink": "Copiar un enlace a esta página",
    "goToPage": "Ir a una página",
    "pageNumber": "Número de página",
    "blur": "Difuminar la traducción",
    "showTranslation": "Mostrar la traducción",
    "translation": "Traducción con IA",
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
    "reviseEdit": "Editar",
    "reviseRegenerate": "Regenerar",
    "reviseWorking": "Regenerando…",
    "reviseNotePlaceholder": "¿Qué falla? (opcional)",
    "reviseSave": "Guardar",
    "reviseCancel": "Cancelar",
    "reviseUndo": "Deshacer",
    "reviseKeyTitle": "Tu clave, tus ediciones",
    "reviseKeyBody": "Se queda en este dispositivo y solo se envía a {provider} — nunca a nosotros.",
    "reviseKeyPlaceholder": "Tu clave de {provider}",
    "reviseRemember": "Recordar en este dispositivo",
    "reviseForget": "Olvidar la clave",
    "reviseKeyManage": "Clave",
    "reviseError": "No se pudo contactar con el modelo. Revisa tu clave o escribe la corrección a mano.",
    "reviseUnreachable": "El modelo de este libro no se puede contactar desde el navegador — aún puedes editar a mano.",
    "reviseCopyEdits": "Copiar un enlace a tus correcciones",
}

_ITALIAN_UI = {
    "copyLink": "Copia un link a questa pagina",
    "goToPage": "Vai a una pagina",
    "pageNumber": "Numero di pagina",
    "blur": "Sfoca la traduzione",
    "showTranslation": "Mostra la traduzione",
    "translation": "Traduzione con IA",
    "published": "Pubblicata",
    "aboutPublished": "Informazioni sulla traduzione pubblicata",
    "chapters": "Capitoli",
    "bookmark": "Aggiungi un segnalibro",
    "removeBookmark": "Rimuovi il segnalibro",
    "bookmarks": "Segnalibri",
    "noBookmarks": "Ancora nessun segnalibro — tocca il nastro per salvare il tuo punto.",
    "pageAbbr": "p.",
    "smallerText": "Testo più piccolo",
    "largerText": "Testo più grande",
    "download": "Scarica questo libro",
    "downloadTitle": "Scarica",
    "epubSub": "Per e-reader",
    "pdfSub": "Stampa · testo a fronte",
    "publishedPanelTitle": "Traduzione pubblicata",
    "publishedToggleHint": "Attiva l'interruttore per leggere la traduzione pubblicata invece di quella generata.",
    "bringYourOwn": "Puoi leggere una traduzione pubblicata accanto a questa. Porta una copia che possiedi e passala:",
    "privacyFoot": "Il tuo testo resta sul tuo dispositivo e non viene mai incluso nei file condivisi.",
    "resume": "Torna a dove eri rimasto",
    "resumeButton": "Riprendi",
    "dismiss": "Ignora",
    "close": "Chiudi",
    "loading": "Apertura del libro…",
    "damaged": "Questo file è danneggiato — rigeneralo con biread.",
    "reviseEdit": "Modifica",
    "reviseRegenerate": "Rigenera",
    "reviseWorking": "Rigenerazione…",
    "reviseNotePlaceholder": "Cosa non va? (facoltativo)",
    "reviseSave": "Salva",
    "reviseCancel": "Annulla",
    "reviseUndo": "Annulla modifica",
    "reviseKeyTitle": "La tua chiave, le tue modifiche",
    "reviseKeyBody": "Resta su questo dispositivo e va solo a {provider} — mai a noi.",
    "reviseKeyPlaceholder": "La tua chiave {provider}",
    "reviseRemember": "Ricorda su questo dispositivo",
    "reviseForget": "Dimentica la chiave",
    "reviseKeyManage": "Chiave",
    "reviseError": "Impossibile raggiungere il modello. Controlla la chiave o scrivi la correzione a mano.",
    "reviseUnreachable": "Il modello di questo libro non è raggiungibile dal browser — puoi comunque modificare a mano.",
    "reviseCopyEdits": "Copia un link alle tue correzioni",
}

_GERMAN_UI = {
    "copyLink": "Link zu dieser Seite kopieren",
    "goToPage": "Zu einer Seite springen",
    "pageNumber": "Seitenzahl",
    "blur": "Übersetzung verbergen",
    "showTranslation": "Übersetzung zeigen",
    "translation": "KI-Übersetzung",
    "published": "Veröffentlicht",
    "aboutPublished": "Über die veröffentlichte Übersetzung",
    "chapters": "Kapitel",
    "bookmark": "Lesezeichen setzen",
    "removeBookmark": "Lesezeichen entfernen",
    "bookmarks": "Lesezeichen",
    "noBookmarks": "Noch keine Lesezeichen — tippe auf das Band, um deine Stelle zu speichern.",
    "pageAbbr": "S.",
    "smallerText": "Kleinerer Text",
    "largerText": "Größerer Text",
    "download": "Dieses Buch herunterladen",
    "downloadTitle": "Herunterladen",
    "epubSub": "Für E-Reader",
    "pdfSub": "Druck · nebeneinander",
    "publishedPanelTitle": "Veröffentlichte Übersetzung",
    "publishedToggleHint": "Schalte um, um die veröffentlichte Übersetzung statt der generierten zu lesen.",
    "bringYourOwn": "Du kannst eine veröffentlichte Übersetzung neben dieser lesen. Bring ein eigenes Exemplar mit und füge es hinzu:",
    "privacyFoot": "Dein Text bleibt auf deinem Gerät und wird nie in geteilte Dateien aufgenommen.",
    "resume": "Zurück zu deiner letzten Stelle",
    "resumeButton": "Fortsetzen",
    "dismiss": "Verwerfen",
    "close": "Schließen",
    "loading": "Buch wird geöffnet…",
    "damaged": "Diese Datei ist beschädigt — erzeuge sie mit biread neu.",
    "reviseEdit": "Bearbeiten",
    "reviseRegenerate": "Neu generieren",
    "reviseWorking": "Wird neu generiert…",
    "reviseNotePlaceholder": "Was stimmt nicht? (optional)",
    "reviseSave": "Speichern",
    "reviseCancel": "Abbrechen",
    "reviseUndo": "Rückgängig",
    "reviseKeyTitle": "Dein Schlüssel, deine Änderungen",
    "reviseKeyBody": "Bleibt auf diesem Gerät, geht nur an {provider} — nie an uns.",
    "reviseKeyPlaceholder": "Dein {provider}-Schlüssel",
    "reviseRemember": "Auf diesem Gerät merken",
    "reviseForget": "Schlüssel vergessen",
    "reviseKeyManage": "Schlüssel",
    "reviseError": "Modell nicht erreichbar. Prüfe deinen Schlüssel oder korrigiere von Hand.",
    "reviseUnreachable": "Das Modell dieses Buchs ist vom Browser aus nicht erreichbar — du kannst trotzdem von Hand bearbeiten.",
    "reviseCopyEdits": "Link zu deinen Korrekturen kopieren",
}

_PORTUGUESE_UI = {
    "copyLink": "Copiar a ligação para esta página",
    "goToPage": "Ir para uma página",
    "pageNumber": "Número da página",
    "blur": "Desfocar a tradução",
    "showTranslation": "Mostrar a tradução",
    "translation": "Tradução com IA",
    "published": "Publicada",
    "aboutPublished": "Sobre a tradução publicada",
    "chapters": "Capítulos",
    "bookmark": "Marcar esta página",
    "removeBookmark": "Remover o marcador",
    "bookmarks": "Marcadores",
    "noBookmarks": "Ainda não há marcadores — toca na fita para guardar o teu lugar.",
    "pageAbbr": "p.",
    "smallerText": "Texto mais pequeno",
    "largerText": "Texto maior",
    "download": "Descarregar este livro",
    "downloadTitle": "Descarregar",
    "epubSub": "Para leitores eletrónicos",
    "pdfSub": "Impressão · lado a lado",
    "publishedPanelTitle": "Tradução publicada",
    "publishedToggleHint": "Muda o seletor para ler a tradução publicada em vez da gerada.",
    "bringYourOwn": "Podes ler uma tradução publicada ao lado desta. Traz um exemplar teu e passa-o:",
    "privacyFoot": "O teu texto permanece no teu dispositivo e nunca é incluído em ficheiros partilhados.",
    "resume": "Voltar ao ponto onde paraste",
    "resumeButton": "Retomar",
    "dismiss": "Ignorar",
    "close": "Fechar",
    "loading": "A abrir o livro…",
    "damaged": "Este ficheiro está danificado — gera-o novamente com o biread.",
    "reviseEdit": "Editar",
    "reviseRegenerate": "Regenerar",
    "reviseWorking": "A regenerar…",
    "reviseNotePlaceholder": "O que está errado? (opcional)",
    "reviseSave": "Guardar",
    "reviseCancel": "Cancelar",
    "reviseUndo": "Anular",
    "reviseKeyTitle": "A tua chave, as tuas edições",
    "reviseKeyBody": "Fica neste dispositivo e vai apenas para {provider} — nunca para nós.",
    "reviseKeyPlaceholder": "A tua chave {provider}",
    "reviseRemember": "Memorizar neste dispositivo",
    "reviseForget": "Esquecer a chave",
    "reviseKeyManage": "Chave",
    "reviseError": "Não foi possível contactar o modelo. Verifica a tua chave ou escreve a correção à mão.",
    "reviseUnreachable": "O modelo deste livro não está acessível a partir do navegador — podes editar à mão à mesma.",
    "reviseCopyEdits": "Copiar uma ligação para as tuas correções",
}

ENGLISH = Target("english", "English", "en", "Chapter", _ENGLISH_UI)
SPANISH = Target("spanish", "Spanish", "es", "Capítulo", _SPANISH_UI)
ITALIAN = Target("italian", "Italian", "it", "Capitolo", _ITALIAN_UI)
GERMAN = Target("german", "German", "de", "Kapitel", _GERMAN_UI)
PORTUGUESE = Target("portuguese", "Portuguese", "pt", "Capítulo", _PORTUGUESE_UI)

# Registry keyed by --lang value. Add a language by adding a row (and its ui
# table); every key in _ENGLISH_UI must be present, which `_check` enforces.
TARGETS: dict[str, Target] = {
    t.key: t for t in (ENGLISH, SPANISH, ITALIAN, GERMAN, PORTUGUESE)
}

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
