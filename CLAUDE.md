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

**The book keeps book proportions at any window size.** Width follows height, so
a short window makes the book smaller rather than squatter; type and page
margins scale with it so line length stays roughly constant in characters.
*(Built.)*

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

---

## Known open issues

- **`cleanup.py` does not strip Wikisource footnotes.** They use `↑` back-links,
  which no pattern matches, so the end of Micromégas carries four paragraphs of
  apparatus — including one of Aristotle in Greek — into the book as body text.
  They get translated, and would get glossed. Fix before building the gloss
  stage.
- Nothing is committed. This repository has no commits at all.
- `.book-mobile` still has a fixed width, so a short landscape phone could
  squash the way the desktop spread used to.

---

## Layout

```
biread/
  cli.py          argument parsing and everything the user sees printed
  extract/        source file -> raw text
  cleanup.py      raw text -> chapters of clean paragraphs
  translate.py    paragraphs -> English, batched and cached
  align.py        a published translation -> matched to the French by content
  render/         book -> one HTML file (templates/ holds the real reader)
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
pip install -e ".[dev]" && pytest              # 128 Python tests, no network
pip install -e ".[browser]" && playwright install chromium
pytest tests/test_reader_js.py                 # 16 browser tests
```

The reader's expensive bugs have all been layout and timing — pagination
measured against a box that was not laid out yet, a drag target destroyed
mid-gesture, a layout mode chosen from a stale width. None are reachable without
a rendering engine. Drive the real thing before believing it works.
