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
    "blur": "Cover the English",
    "showTranslation": "Show the English",
    "translation": "AI translation",
    "published": "Published",
    "aboutPublished": "About the published translation",
    "chapters": "Chapters",
    "chapterMissing": "The translator did not include this chapter.",
    "bookmark": "Bookmark this spread",
    "removeBookmark": "Remove bookmark",
    "bookmarks": "Bookmarks",
    "noBookmarks": "No bookmarks yet — tap the star to save your place.",
    "syncOffer": "Keep my place on your other devices",
    "syncSignIn": "Sign in with GitHub",
    "syncKept": "Your place is kept · {handle}",
    "syncSignOut": "Sign out",
    "pageAbbr": "p.",
    "smallerText": "Smaller text",
    "largerText": "Larger text",
    "dayMode": "Day",
    "nightMode": "Night",
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
    "glossAdd": "Hover to translate",
    "glossKeepingUp": "Translating as you read",
    "glossKeyBody": "The phrases on this page first, then the rest of the book while you read it. Stop it whenever you like.",
    "glossAdding": "Translating…",
    "glossKeyTitle": "Your key, your translations",
    "glossFailed": "That page would not translate. Try again.",
    "reviseForget": "Forget key",
    "reviseKeyManage": "Key",
    "reviseError": "Couldn't reach the model. Check your key, or type the fix by hand.",
    "reviseUnreachable": "This book's model can't be reached from the browser — you can still edit by hand.",
    "reviseCopyEdits": "Copy a link to your corrections",
    "builderLink": "Builder",
}

_SPANISH_UI = {
    "copyLink": "Copiar un enlace a esta página",
    "goToPage": "Ir a una página",
    "pageNumber": "Número de página",
    "blur": "Cubrir el español",
    "showTranslation": "Mostrar el español",
    "translation": "Traducción con IA",
    "published": "Publicada",
    "aboutPublished": "Sobre la traducción publicada",
    "chapters": "Capítulos",
    "chapterMissing": "El traductor no incluyó este capítulo.",
    "bookmark": "Marcar esta página",
    "removeBookmark": "Quitar el marcador",
    "bookmarks": "Marcadores",
    "noBookmarks": "Aún no hay marcadores — toca la cinta para guardar tu sitio.",
    "syncOffer": "Guarda mi sitio en tus otros dispositivos",
    "syncSignIn": "Entrar con GitHub",
    "syncKept": "Tu sitio se guarda · {handle}",
    "syncSignOut": "Salir",
    "pageAbbr": "pág.",
    "smallerText": "Texto más pequeño",
    "largerText": "Texto más grande",
    "dayMode": "Día",
    "nightMode": "Noche",
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
    "glossAdd": "Traducir al pasar",
    "glossKeepingUp": "Traduciendo mientras lees",
    "glossKeyBody": "Primero las frases de esta página, y el resto del libro mientras lo lees. Puedes detenerlo cuando quieras.",
    "glossAdding": "Traduciendo…",
    "glossKeyTitle": "Tu clave, tus traducciones",
    "glossFailed": "Esta página no se pudo traducir. Inténtalo de nuevo.",
    "reviseForget": "Olvidar la clave",
    "reviseKeyManage": "Clave",
    "reviseError": "No se pudo contactar con el modelo. Revisa tu clave o escribe la corrección a mano.",
    "reviseUnreachable": "El modelo de este libro no se puede contactar desde el navegador — aún puedes editar a mano.",
    "reviseCopyEdits": "Copiar un enlace a tus correcciones",
    "builderLink": "Creador",
}

_ITALIAN_UI = {
    "copyLink": "Copia un link a questa pagina",
    "goToPage": "Vai a una pagina",
    "pageNumber": "Numero di pagina",
    "blur": "Copri l'italiano",
    "showTranslation": "Mostra l'italiano",
    "translation": "Traduzione con IA",
    "published": "Pubblicata",
    "aboutPublished": "Informazioni sulla traduzione pubblicata",
    "chapters": "Capitoli",
    "chapterMissing": "Il traduttore non ha incluso questo capitolo.",
    "bookmark": "Aggiungi un segnalibro",
    "removeBookmark": "Rimuovi il segnalibro",
    "bookmarks": "Segnalibri",
    "noBookmarks": "Ancora nessun segnalibro — tocca il nastro per salvare il tuo punto.",
    "syncOffer": "Conserva il mio punto sugli altri dispositivi",
    "syncSignIn": "Entra con GitHub",
    "syncKept": "Il tuo punto è conservato · {handle}",
    "syncSignOut": "Esci",
    "pageAbbr": "p.",
    "smallerText": "Testo più piccolo",
    "largerText": "Testo più grande",
    "dayMode": "Giorno",
    "nightMode": "Notte",
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
    "glossAdd": "Traduci al passaggio",
    "glossKeepingUp": "Traduce mentre leggi",
    "glossKeyBody": "Prima le frasi di questa pagina, poi il resto del libro mentre lo leggi. Puoi fermarlo quando vuoi.",
    "glossAdding": "Traduzione in corso…",
    "glossKeyTitle": "La tua chiave, le tue traduzioni",
    "glossFailed": "Questa pagina non si è potuta tradurre. Riprova.",
    "reviseForget": "Dimentica la chiave",
    "reviseKeyManage": "Chiave",
    "reviseError": "Impossibile raggiungere il modello. Controlla la chiave o scrivi la correzione a mano.",
    "reviseUnreachable": "Il modello di questo libro non è raggiungibile dal browser — puoi comunque modificare a mano.",
    "reviseCopyEdits": "Copia un link alle tue correzioni",
    "builderLink": "Creatore",
}

_GERMAN_UI = {
    "copyLink": "Link zu dieser Seite kopieren",
    "goToPage": "Zu einer Seite springen",
    "pageNumber": "Seitenzahl",
    "blur": "Das Deutsche verdecken",
    "showTranslation": "Das Deutsche zeigen",
    "translation": "KI-Übersetzung",
    "published": "Veröffentlicht",
    "aboutPublished": "Über die veröffentlichte Übersetzung",
    "chapters": "Kapitel",
    "chapterMissing": "Der Übersetzer hat dieses Kapitel nicht aufgenommen.",
    "bookmark": "Lesezeichen setzen",
    "removeBookmark": "Lesezeichen entfernen",
    "bookmarks": "Lesezeichen",
    "noBookmarks": "Noch keine Lesezeichen — tippe auf das Band, um deine Stelle zu speichern.",
    "syncOffer": "Meine Stelle auf deinen anderen Geräten behalten",
    "syncSignIn": "Mit GitHub anmelden",
    "syncKept": "Deine Stelle wird behalten · {handle}",
    "syncSignOut": "Abmelden",
    "pageAbbr": "S.",
    "smallerText": "Kleinerer Text",
    "largerText": "Größerer Text",
    "dayMode": "Tag",
    "nightMode": "Nacht",
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
    "glossAdd": "Übersetzen beim Zeigen",
    "glossKeepingUp": "Übersetzt beim Lesen",
    "glossKeyBody": "Zuerst die Wendungen auf dieser Seite, dann der Rest des Buches, während du liest. Du kannst jederzeit aufhören.",
    "glossAdding": "Wird übersetzt…",
    "glossKeyTitle": "Dein Schlüssel, deine Übersetzungen",
    "glossFailed": "Diese Seite ließ sich nicht übersetzen. Versuch es noch einmal.",
    "reviseForget": "Schlüssel vergessen",
    "reviseKeyManage": "Schlüssel",
    "reviseError": "Modell nicht erreichbar. Prüfe deinen Schlüssel oder korrigiere von Hand.",
    "reviseUnreachable": "Das Modell dieses Buchs ist vom Browser aus nicht erreichbar — du kannst trotzdem von Hand bearbeiten.",
    "reviseCopyEdits": "Link zu deinen Korrekturen kopieren",
    "builderLink": "Editor",
}

_PORTUGUESE_UI = {
    "copyLink": "Copiar a ligação para esta página",
    "goToPage": "Ir para uma página",
    "pageNumber": "Número da página",
    "blur": "Cobrir o português",
    "showTranslation": "Mostrar o português",
    "translation": "Tradução com IA",
    "published": "Publicada",
    "aboutPublished": "Sobre a tradução publicada",
    "chapters": "Capítulos",
    "chapterMissing": "O tradutor não incluiu este capítulo.",
    "bookmark": "Marcar esta página",
    "removeBookmark": "Remover o marcador",
    "bookmarks": "Marcadores",
    "noBookmarks": "Ainda não há marcadores — toca na fita para guardar o teu lugar.",
    "syncOffer": "Guardar o meu lugar nos teus outros dispositivos",
    "syncSignIn": "Entrar com GitHub",
    "syncKept": "O teu lugar fica guardado · {handle}",
    "syncSignOut": "Sair",
    "pageAbbr": "p.",
    "smallerText": "Texto mais pequeno",
    "largerText": "Texto maior",
    "dayMode": "Dia",
    "nightMode": "Noite",
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
    "glossAdd": "Traduzir ao passar",
    "glossKeepingUp": "A traduzir enquanto lês",
    "glossKeyBody": "Primeiro as frases desta página, depois o resto do livro enquanto o lês. Podes parar quando quiseres.",
    "glossAdding": "A traduzir…",
    "glossKeyTitle": "A tua chave, as tuas traduções",
    "glossFailed": "Esta página não se conseguiu traduzir. Tenta de novo.",
    "reviseForget": "Esquecer a chave",
    "reviseKeyManage": "Chave",
    "reviseError": "Não foi possível contactar o modelo. Verifica a tua chave ou escreve a correção à mão.",
    "reviseUnreachable": "O modelo deste livro não está acessível a partir do navegador — podes editar à mão à mesma.",
    "reviseCopyEdits": "Copiar uma ligação para as tuas correções",
    "builderLink": "Criador",
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
