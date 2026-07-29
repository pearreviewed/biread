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

### Universal alignment — bringing any book (not yet built)

> these are xamples where alignment failed, we need to be ready for users to
> bring any books and be able to align the, properly
>
> collect the thoughts needed to make a universal alignng tool for all books

The goal: a user drops in *their own* published edition — any PDF, EPUB, TXT,
DOCX, HTML — and it lands beside the French correctly, or fails **loudly** with a
reason. Today it can fail **silently**.

**The failure that prompted this (Candide, Gutenberg PDF).** The built reader
shipped with `publishedAvailable: false`, no published column at all, and a note
claiming the translation was "placed beside the French by position" — when in
fact *no* published text made it in. Traced end to end:

- The aligner itself is not the weak link. **Extraction and cleanup are.** The
  aligner is fed garbage and has nothing to work with.
- pypdf extracted each chapter heading as the bare word `CHAPTER` on its own
  line, with the numeral (`I`, `II`, … `XXX`) stranded on a *different* line
  amid huge whitespace runs — 30 orphaned roman-numeral lines in all.
- `cleanup.CHAPTER_RE` anchors the word **and** the number on **one** line
  (`^\s*(?:CHAPITRE|CHAPTER)\s+(NUM)\s*$`). Split across lines, it matched
  **zero** of 30 chapters.
- Zero numbered chapters ⇒ `trim_matter` can't trim (it no-ops when nothing is
  numbered), `_pair_by_number` has nothing to pair, and the whole edition
  collapses into **one 183-paragraph blob** that still carries the transcriber's
  note, the TOC, and the Gutenberg licence. Alignment against that is worthless,
  so the published column was dropped.

**What a universal tool has to get right, in order:**

1. **Extraction damage is the real problem — repair it before anything reads
   it.** A normalization layer between extract and cleanup that undoes the
   standard PDF injuries: collapse whitespace runs, de-hyphenate line-broken
   words, drop running headers/footers and bare page numbers, and **rejoin a
   heading word to a numeral marooned on the next line**. Every downstream stage
   assumes clean paragraph text; give it that.

2. **Chapter detection must tolerate layout noise, not assume clean input.**
   `^…$` single-line matching is too strict. Detect `CHAPTER` / `CHAPITRE`
   followed by a numeral within a small window even across a line break; treat a
   lone roman-numeral / integer line as a candidate heading. It must also survive
   editions that number differently on each side (already handled by
   `chapter_number`) — but only once headings are found at all.

3. **Alignment must degrade gracefully, never all-or-nothing.** Losing chapter
   detection should not zero the published column. The content-similarity
   **pivot** (English↔English through the generated translation) needs no chapter
   structure and carries any book that was translated; where there is no
   translation to pivot through, `_by_embeddings` matches the two editions
   directly by meaning. Both are model work — the surface-token fallback is gone.
   Where either comes out thin, say so; a proportional fill must never be the
   silent default it became here.

4. **Front-matter / boilerplate stripping must not depend on chapter numbering.**
   `trim_matter` only fires when chapters were numbered, so a detection miss
   leaves licences and notes *inside* the aligned text. Gutenberg boilerplate,
   transcriber's notes, TOC, and licence need removal that stands on its own.

5. **Fail loudly and honestly.** If chapters can't be found or coverage is poor,
   the reader must say so plainly ("couldn't locate chapters in your published
   file — alignment is degraded/unavailable, because …"), never emit a confident
   note over an empty column. `AlignmentReport` already tracks
   dropped/unmatched; that signal has to reach the reader UI and the terminal,
   and a near-empty published column should trip a visible warning at build time.

6. **Prove it on more than Micromégas.** The one verified book (34 paragraphs,
   clean source) is not evidence of universality. Build a corpus of awkward real
   inputs — Gutenberg PDFs with split headings, EPUBs with interleaved notes,
   editions whose chapter counts differ — and test extraction → cleanup →
   alignment against each. This Candide PDF is the first corpus member.

Sample inputs for the corpus live in the user's Downloads
(`candide - bilingual reader.html` = the broken build,
`The Project Gutenberg eBook of Candide, by Voltaire..pdf` = the published PDF
that failed). Copy them into `examples/` before relying on them.

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

**The web builder ships from `web/dist`, not from the repo.** It loads a
pre-built wheel into Pyodide, and `web/dist` is gitignored, so a fix on main is
not a fix in the builder until `python web/build.py` rebuilds that folder and it
is served again. Any change touching `web/` or the pipeline behind it needs that
rebuild before it counts as delivered — say so plainly when handing work back.
There is no host and no deploy pipeline yet; when there is one, automate this in
CI so it stops depending on anyone remembering.

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
| Server — does it ever hold users' books? | **No — biread stays a tool, not a host.** Translation runs in the reader's browser on the reader's own key; the finished edition is the reader's own file; the server holds only the app, accounts, and edits — never the book. A DMCA takedown agent is avoidable only by not hosting the books. Accounts sync the *bookmark, not the book* (source hash + reading position + fixes + light metadata), the file re-opened locally or pulled from the reader's own cloud. Full design in [`design-reference/accounts-spec.md`](design-reference/accounts-spec.md). |
| Builder — how does a reader choose the translation model, and where? | On the web builder's price screen, a clickable **three-tier** choice — **Finest / Balanced / Cheapest**, price beside each, model id in fine print — plus a field for any other model id. One OpenRouter key reaches all of them, and every rate is read live from OpenRouter's models API, so a model with no built-in `PRICING_PER_MTOK` row still prices exactly. Cheap to show because the estimate is model-independent: `translate.estimate()` counts tokens from the text alone, so every tier prices off the same counts with no extra API calls. Builder-only — does **not** touch the "never show price in the reader" rule. |
| Builder — is there a free way to read two editions side by side? | **Yes, but a different one.** The original free path — algorithmic cross-lingual matching on shared names, numbers and sentence lengths — was built and removed: two translations of one book share meaning, not words, so a surface-token matcher has a ceiling that tuning does not raise, and it failed quietly rather than loudly. Free came back on a different footing: **Local · Ollama**, where the models (a chat model to translate, BGE-M3 to align) run on the reader's own machine — no key, nothing leaves the computer, and still meaning-based. Paid is **OpenRouter**, priced live before anything runs. The axis that matters is meaning vs. surface tokens, not free vs. paid. |
| Alignment — does it still need a generated translation to pivot through? | Not always. The pivot is the CLI's path and the trustworthy default. `align_published(embed=…)` instead matches the two editions directly in a shared multilingual space (`_by_embeddings`), so a reader who owns both books gets them aligned by meaning with no translation of our own — free on a local model, pennies on a cloud one. That is what the web builder uses when a published edition is brought. |
| Builder — what shape is the flow? | **A fork, then two steps.** The door asks only who does the work (your own machine, or your own key). Step one is the book and the route — translate it, or align an edition you own — and nothing else. Step two puts key, model and hover on the left and, on the right, a real sample page above the price and the button. Day and night, chosen by the reader and remembered. Replaces the single dense screen plus a separate cost-confirm screen. |
| Builder — how does a reader know the translation is any good before paying? | **They read one page of it.** `sample.sample_translate` runs the chosen model over three real paragraphs of their own book; `sample_align` matches three against the edition they brought. It costs a fraction of a cent, renders in a miniature of the reader's own spread, and "Another page" buys the next one. The estimate stops being a promise about prose quality and becomes a price on prose already seen. |
| Builder — does the progress screen show real work? | Yes. `translate_book(on_batch=…)` hands finished pairs up through `build_reader(on_text=…)` to the page, so the spread fills with the book actually being made, and the time left is computed from the rate observed so far. Nothing on that screen is decorative. |
| Does the align route gloss? | **Yes.** `build_aligned(gloss=…, gloss_client=…, gloss_cfg=…)` glosses the original — exactly the body it renders, so no call is paid for on a paragraph nobody sees — while the reading column stays the translator's, word for word. Glossing is chat-model work, so the builder asks for a model on that route *only* once the hover is wanted; without a client the book builds the same, minus the hover, rather than being refused. This was the one place the two routes were not equal. |
| Builder — what does a file card claim about a book? | Only what the file says: `meta.describe` reads an EPUB's OPF for title, author and language, a PDF for its page count, and counts paragraphs from the parsed text. Everything else stays None and is simply not shown — a filename is not an author, and a confident wrong byline is worse than a blank one. |

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
- **The builder has no automated browser tests.** The reader has 54; the builder
  has none, because every path through it boots Pyodide from a CDN and the suite
  is offline by design. It is driven by hand with Playwright against
  `web/dist` instead, which is not a regression net.
- **An embedding run is priced only when OpenRouter lists the model.** The align
  route's cost gate shows a dollar figure when the rate is known and an honest
  token count when it is not, rather than a plausible cent.
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
  align.py        a published translation -> matched to the French by meaning:
                  through the generated translation as a pivot (the CLI), or
                  directly in a shared embedding space (the web builder)
  anchor.py       vestigial: two editions pinned by the names and numbers they
                  share — the removed surface-token path. Reachable only from
                  tests; kept until it is deleted outright
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
