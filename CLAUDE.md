# biread — project spec and agreed requirements

Turn a plain-text French book into one self-contained HTML file: an open-book
spread, French on the left page, English on the right, paginated at runtime.

`design-reference/design-spec.md` is the original visual brief and still governs
the look. Where this file and that one disagree, **this file wins** — it records
decisions taken since.

Requirements below are quoted **verbatim**, in the words they were given in.
Typos are preserved so it stays clear which text is the brief and which is
commentary.

---

## The brief

> carefully review the entire code + logic in bilingual reader find weak spots and refactor what is needed
> cleanup all mess, rendundant/duplicated and not needed things, you have full allowance to redisign and enhance things to make them work better and in realistic conditions, without drasticly changing the business logic, make overall code and structure professional
>
> do tests to make sure things work correctly, fix any issues, quality is most important
> make sure to use less ai-slop, very improant to use less comments in code etc, less bloating, keep it elegant and clean, remove/rewrite slopy things agressively
>
> also you can use multiple agents if needed

---

## Standing requirements

### Reading experience

> dude wtf no the lages are tooo long its not okay to scroll down the page fix that

**Pages never scroll.** A paragraph taller than a page continues onto the next,
both columns broken at the same fraction through it so they meet again where it
ends. A resumed paragraph starts flush, not indented. *(Built.)*

> ok in th elocal host the book is so squished and narrow what the heck

**The book keeps book proportions at any window size, and fills the page.** The
spread is sized (in JS, `sizeBook`) to the largest **7:5** box that fits the
stage both ways — height-bound on a wide window, width-bound on a tall one,
capped at 1500px on a huge screen — so it fills ~78% of a laptop instead of
stranding in the middle, and the ratio never flattens. Width still follows
height on a short window; type and page margins scale with the book, so line
length stays roughly constant. *(Built. The earlier height-only 1.22 spread was
the reason it was "squished and narrow": it left ~230px of desk each side on a
1440 laptop and squared off to 1.08 on a 1080p screen, because a bare max-width
capped the width while the height kept growing.)*

### Alignment

> are you sure published and original are aligned

**The published column is aligned by content, not position.** The generated
translation is tied to each French paragraph exactly, so the published edition
is matched against *that* — English to English. Anything matching nothing is
left out; a French paragraph with no counterpart is left blank rather than
filled with a guess. *(Built. Verified: 34 body paragraphs, 0 suspect,
0 double-assignment.)*

Positional alignment was tried first and was wrong — see Reversals.

### Glossing (not yet built)

> gloss is needed. any word on the right side (og language) shoudl be hoverable translated in context, but no articles prepositions and pronouns separately, they should be selected tpgetehr with the connected word and trasnlated in thier context. if the hoverable word is in french passe simple it should also show passe compose version and if the hoverable word is a verb in a form other tahn infinitif, then it should also show inifinitif form

> i dont want citations footnotes and handls and anything non core text be hoverable, i dont wanna pay for that

> yes then lets do gloss by demand like you suggested bot be defualt everything

Which resolves to:

- Hover targets are **units**, not words — function words (articles,
  prepositions, pronouns) merge with the content word they attach to and are
  glossed as a phrase in context. `Sur la table` is one target, not three.
- Verbs show the **infinitive** when they are in any other form.
- Verbs in **passé simple** also show the **passé composé**.
- **Core body text only.** No citations, footnotes, Wikisource `↑` back-links,
  headings, or other apparatus — it is not worth paying to gloss.
- **Opt-in `--gloss`.** Never on by default.
- Cost is reported in the terminal only. See Never below.

> [!NOTE]
> "right side (og language)" — the original language is French, which is the
> **left** page in this layout. Read as French/left, flagged, not contradicted.
> Confirm before building.

### Page navigation (not yet built)

> can we get rid of the scrubber adn replace it with another way to find a page? like a funciotnality taht allows to find page number

Remove the scrubber. Replace with a way to go to a page number. Shape not yet
chosen — the standing proposal is that the `12 / 33` counter already in the
header becomes the control.

The scrubber caused three separate bugs (drag target destroyed mid-gesture,
stuck scrubbing flag, NaN spread index) which is more than the rest of the
reader combined.

### Reader-side correction (built)

> sometimes the llm translation is off like genrating got wind of it vs caught wind of it i dont want the user stuck with sentences that rub the, the wrong way ... a person can select a part in the ai translation ... and get a button option to regenerate it maybe with feedback what is wrong but again i dont wanna pay for it

**`--revise` lets a reader fix the AI translation in place** — because the reading
experience is the point, and a reader who loves the prose should not be stuck with
a phrase that rings false. Select a phrase in the generated column and a small
panel offers **Edit** (type the fix by hand — no key, no cost) and **Regenerate**
(rewrite the span in context, with an optional "what's wrong" note). Regenerate calls a model, so it runs on the **reader's own
key**, never the builder's, using the provider the book was built with; a reader
without that key still gets the hand-edit.

A fix is a private, reversible override stored in the reader's own browser (a ↺
puts the original back), keyed by source hash so a rebuild drops it only if that
paragraph is retranslated. Corrections carry to another browser through a
dedicated *edits link*, kept separate from the page link so a shared page never
leaks private edits. Cross-device sync needs a server and is **parked** — the
full design, local and server, is in
[`design-reference/revise-spec.md`](design-reference/revise-spec.md).

### Never

> will it constantly show the price in ui? because i dont want that

**No cost, price, token or spend information in the reader, ever.** All of it is
printed to the terminal during the build.

### Copy

> i want more empathetic text that also doesnt necesarrily ut down the generated text

Panel copy is laconic, warm, and never ranks the two translations against each
other. The privacy line stays as it is:

> privacy is good

---

## How to work on this

> you can give me optins in the chat and ill choose before you commit anything

For anything with a judgement call in it — copy, visual design, product
behaviour — **put options in chat and wait.** Do not implement and then ask.

Corollary learned the hard way: the pipeline spends real money. Never run a
build that may call the API without checking it is fully cached, and never run
two at once. `--dry-run` needs no API key.

---

## Decisions taken

| Question | Decision |
|---|---|
| `--published` — implement, remove, or stub? | Implement |
| Gloss-stage leftovers (`MODEL_GLOSS`, `json_mode`, spacy, tqdm) | Strip all of it |
| Blur — does the English chapter heading blur too? | Leave headings readable |
| Reader JS test coverage | Headless browser smoke tests (Playwright, `[browser]` extra) |
| ⓘ panel, no published translation | A3 — "You can read a published translation alongside this one. Bring a copy you own and pass it in:" |
| ⓘ panel, published loaded | B7d — "Your translation keeps pace with the French as closely as two editions allow. It has its own notes and front matter, which stay behind." |
| Download button — embed the EPUB/PDF, or link to sibling files? | Embed, as lazy base64 `<script type="application/octet-stream">` blobs (read only on click, so a multi-MB PDF is not parsed on every open). The book stays one shareable file; the button works offline. |
| Download button — where in the header? | Far right, paired with the "copy link" icon (moved there too) and set a little apart. Every other control works the book in place; these two hand it off — the link the current spot, the download the whole book. A quiet icon menu, shown only for formats actually built (`--epub`/`--pdf`), else hidden. |
| Translation language — where is it chosen, and who pays? | Build-time, per book: `--lang` (default `english`), one language per book. Every language is self-serve — whoever would like an edition builds it on their own key — so you only ever carry the languages you choose. English content is byte-identical; cache is per-language (`translations.<code>.json`). |
| Translation language — how far does localization reach? | Content **and** the full reader UI, except the `Lecteur bilingue` masthead, which stays French as the reader's signature. A curated, extensible `Target` table (`targets.py`) holds each language's name, hyphenation code, chapter word, and UI strings; adding a language is one row. |
| Revise — how does a reader fix an off translation, and who pays? | In the reader: **Edit** by hand (key-free) or **Regenerate** on the reader's **own** key — never the builder's — on the book's build provider, so a fix keeps the translation's voice. A fix is a private, reversible local override; it crosses browsers via a dedicated *edits link* kept separate from the page link. |
| Revise — automatic cross-device sync? | Spec'd (sign-in accounts) and **parked**; the shipped rung is the edits link. Full local+server design in `design-reference/revise-spec.md`. |
| EPUB — reflowable with tap glosses, or the reader's locked spread? | The **locked spread** (fixed-layout): French left, English right, like the reader. The reflowable version put the French and English in one interleaved column and turned every glossed phrase into an EPUB footnote, which **Apple Books paints blue** — the whole page went blue and unreadable, and it did not look like the reader. Fixed-layout is paginated at build time by the reader's own algorithm (in headless Chromium, so `--epub` now needs `[browser]`), and **drops glosses** — same reason the PDF does. Best on a tablet or a Mac; a phone shows one page at a time. |

## Reversals

Recorded because the reasoning matters more than the outcome.

- **"Paginate to the taller column"** was chosen, built, and reverted. Measuring
  the published column as a third page-break constraint interacts badly with
  alignment: Voltaire's `(1752)` is six characters and was paired with 2,514
  characters of front matter, which left the *translation* view — the one being
  read — about a tenth full. Pagination now measures French and generated
  English only.
- **Dice similarity** for alignment was replaced by **containment**. Dice
  punishes size asymmetry, but a translator splitting one long paragraph into a
  dozen dialogue lines makes the published fragment smaller *by construction*.
  Chapitre II was discarding 15 of 23 real paragraphs as unmatchable.
- **The reflowable EPUB with tap-to-reveal glosses** was built, shipped, and
  reverted. Two faults, seen in Apple Books: glossing every phrase makes every
  phrase a footnote link, which Apple Books renders in hyperlink **blue** — the
  whole French page turned blue and unreadable; and a reflowable book cannot hold
  the reader's French-left/English-right spread, so it read as one interleaved
  column, not the book. Replaced by a fixed-layout spread with no glosses. The
  cost is that `--epub` now needs the browser engine (it paginates by measuring)
  and is best on a tablet or desktop — accepted, because the spread is the point.

---

## Known open issues

- **A find-failure still discards the whole paragraph.** `anchor()` returns None
  if any one unit will not match in order, so one bad unit loses the other
  eighty. The rescue pass hides this in practice — it retries such a paragraph
  alone, then sentence by sentence, and the last full run left none plain — but
  the underlying anchor is still all-or-nothing, paid around with extra calls
  rather than fixed.
- **A failed paragraph records nothing about why it failed.** The model's reply
  is not kept, so diagnosing a failure means paying to reproduce it. That is how
  the curly-apostrophe run cost $1.64 to explain.
- **Mobile renders no hover units at all.** Reasonable for touch. The 640px
  breakpoint keeps most laptop windows on the spread, so the "hover works but
  does nothing on a narrow desktop window" surface is smaller than it was, but a
  phone-width reader gets no glosses.
- `.book-mobile` still has a fixed width (the desktop spread's sizing moved to
  JS, but mobile did not), so a short landscape phone could squash.
- **The EPUB and PDF are validated structurally and eyeballed, not tested across
  readers.** The fixed-layout EPUB has been opened in Apple Books (the spread
  faces up, the title page opens the book); no one has checked it on Kindle or
  another reader, or printed the PDF, in a test. Fixed-layout support varies by
  reader — Apple Books is the target.
- **Revise crosses browsers by a link, not by sync.** Corrections live
  per-browser; the *edits link* carries them across, but automatic cross-device
  sync needs a server and is parked (`design-reference/revise-spec.md`). On mobile
  the correction control is off (touch) — a phone reader sees corrections that
  arrived by link but makes new ones only on a desktop-width window.
- **Now on GitHub.** LICENSE (MIT), CI (GitHub Actions), and CONTRIBUTING notes
  are in place; the repo has a remote (`origin`) and has been pushed, so CI now
  runs on real GitHub.

---

## Layout

```
biread/
  cli.py          argument parsing and everything the user sees printed
  extract/        source file -> raw text
  cleanup.py      raw text -> chapters of clean paragraphs
  translate.py    paragraphs -> English, batched and cached
  align.py        a published translation -> matched to the French by content
  anchor.py       two editions pinned to each other by the names and numbers
                  they share, for when there is no generated translation to
                  pivot through (no model, no headings, no shared vocabulary)
  build.py        the pipeline shared by the CLI and the in-browser builder
  gloss.py        per-paragraph hover units; width judged at render, not cache
  language.py     what glossing needs to know about the source language
  render/         book -> one HTML file (templates/ holds the real reader)
  export/         static copies: epub.py (fixed-layout spread), pdf.py (print) — both headless Chromium
  llm/            one thin client per provider
  cache.py        content-hash JSON cache, merges on write
  config.py       environment, models, pricing
```

The reader is `biread/render/templates/reader.{html,css,js}` — plain files,
edited as plain files. `render/__init__.py` only inlines the fonts and paper
texture and substitutes the book data.

Pagination is measured in an offscreen twin of the book that carries the real
classes and is sized from the real book's box, so measurement cannot drift from
the stylesheet. **That probe is in the DOM and shares those classes**, so every
selector must be scoped to `#stage-wrap`.

## Tests

```sh
pip install -e ".[dev]" && pytest              # ~230 Python tests, no network
pip install -e ".[browser]" && playwright install chromium
pytest tests/test_reader_js.py                 # 54 browser tests
```

The EPUB and PDF export tests also need `[browser]` — the exporters paginate and
print in headless Chromium — and skip themselves without it.

The reader's expensive bugs have all been layout and timing — pagination
measured against a box that was not laid out yet, a drag target destroyed
mid-gesture, a layout mode chosen from a stale width. None are reachable without
a rendering engine. Drive the real thing before believing it works.
