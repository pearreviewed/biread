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

> [!NOTE]
> **Candide now loads clean on both sides.** The diagnosis below is kept because
> the reasoning still governs, but two of its findings are fixed and the account
> of the damage has moved twice. Chapter detection was repaired first (all 30
> found on both sides, `normalize.py`). The fault that remained was **paragraph
> segmentation**: the published PDF came apart into 120 lumps against the
> French's 630, one of them four pages long, because that PDF does not put a
> blank line between every paragraph and `_blocks` fused whole runs of dialogue.
> `normalize._unfuse_paragraphs` restores the breaks — a line stopping well short
> of the page's measure, closing a sentence, followed by one opening a sentence,
> ended its paragraph. Now 632 against 713, both opening on Candide's real first
> line. **Gated to PDFs**, because a text or EPUB file that omits blank lines is
> saying something about itself and a PDF cannot; that gate is what keeps the
> verified Micromégas corpus untouched, which three ungated versions of the rule
> did not. *(Since widened by one case — a file of any format that never came
> apart **at all** gets the same repair; see the decision row on a book with no
> paragraph breaks. The corpus is still untouched, and that is measured.)*
> Ligature glyphs (`ﬁnd`, `ﬂurried` — 323 of them) are expanded too,
> ungated, because a ligature codepoint is a shape and never a meaning.
>
> **Built end to end, and it reads.** `build_aligned` on the two PDFs, matched by
> embeddings: 242 pages, coverage 72.6%, 127 French paragraphs with no counterpart
> left honestly blank, nothing degraded, $0.012. Spot-checked across the book —
> Pangloss's *"Il est démontré…"* faces *"It is demonstrable,"* paragraph for
> paragraph. Candide is the second book that works, and the first that ever
> failed. What is still missing is the rest of the corpus: an EPUB with
> interleaved notes, and editions whose chapter counts disagree.

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

### The shelf (built)

A reader who arrives holding nothing can still leave with a book. **Pick from the
shelf** is a third route on the builder's front door: five books out of
copyright, both editions fetched from Wikisource by the reader's own browser and
matched by meaning. biread stores two page names per book and never a word of
text — that is what keeps it a tool rather than a host.

Two screens. The shelf itself (`#shelf`, inside step one) is browsed and
searched, six to a page, with filters that are computed from the books rather
than declared — a filter matching all five, or none, is not shown at all. Beyond
it, `#s-lookup` searches Wikisource for anything else out of copyright.

What each card may say is governed by the same rule as the file cards: only what
the source itself says. `wikisource.credits` reads the translator and year off
the page's own header, so *Smollett · 1920* is quoted, not inferred, and 20,000
Leagues shows a bare *1911* because its translator is unnamed. Coverage appears
only for the two books someone has read end to end; the other three say so.

A book found on the lookup screen can be **kept**, by a checkbox that is off by
default: it is saved in this browser and stands among the cards next visit under
*Kept by you*. Nothing of the book is kept — only its two page names.

`python -m biread.shelf` lists the shelf; `--check` re-measures every entry
against the live wiki and reports what has drifted.

### Glossing (built)

> gloss is needed. any word on the right side (og language) shoudl be hoverable translated in context, but no articles prepositions and pronouns separately, they should be selected tpgetehr with the connected word and trasnlated in thier context. if the hoverable word is in french passe simple it should also show passe compose version and if the hoverable word is a verb in a form other tahn infinitif, then it should also show inifinitif form

> i dont want citations footnotes and handls and anything non core text be hoverable, i dont wanna pay for that

> yes then lets do gloss by demand like you suggested bot be defualt everything

Which resolves to:

- Hover targets are **units**, not words — function words (articles,
  prepositions, pronouns) merge with the content word they attach to and are
  glossed as a phrase in context. `Sur la table` is one target, not three.
- Verbs show the **infinitive** when they are in any other form.
- Verbs in **passé simple** also show the **passé composé**. *(Built, and
  withdrawn on 2026-08-10 along with the French headword and the part of speech:
  see the decision row on what the panel says.)*
- **Core body text only.** No citations, footnotes, Wikisource `↑` back-links,
  headings, or other apparatus — it is not worth paying to gloss.
- **Opt-in `--gloss`.** Never on by default.
- Cost is reported in the terminal only. See Never below.

> [!NOTE]
> "right side (og language)" — the original language is French, which is the
> **left** page in this layout. Read as French/left, flagged, not contradicted,
> and built that way: the glosses are on the French.

*(Built. `gloss.py` per paragraph, `language.py` for what French itself
contributes, `--gloss` on the CLI and a checkbox on both builder routes.)*

### Page navigation (built)

> can we get rid of the scrubber adn replace it with another way to find a page? like a funciotnality taht allows to find page number

Remove the scrubber. Replace with a way to go to a page number. *(Built: the
`12 / 33` counter in the header **is** the control — `#counter` is a button that
becomes `#counter-input` when clicked. The thing that says where you are is the
thing that takes you elsewhere.)*

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

> in the entire biread builder adn shelf i want you to go through all the texts
> and get rid of very long dashes

**No em dashes anywhere a reader of the builder or the shelf can see.** Every one
was rewritten rather than swapped for a hyphen, taking a colon, a full stop, a
parenthesis or a conjunction as the sentence wanted, so the copy reads the same
and no line acquired a dash-shaped hole. It covers the page itself, the shelf
records in `shelf.py`, and the engine errors that surface in the builder's alert
(`llm/pyodide_*.py`, `extract/`). The `1–6 of 8` pager keeps its en dash, which
is a numeric range and not a dash of punctuation.

**Where a card does want a parenthetical dash, it is an en dash, not an em.** The
shelf blurbs are the one copy here that reaches for one: a clause set aside inside
a sentence, where a colon is already taken and a comma would not hold. Spaced
`–`, which is what "very long dashes" was never about. Rewriting still comes
first and the whole shelf carries exactly one of these, in Madame Bovary's
drawer. *(Not yet done in the reader:
the ⓘ note and the `targets.py` UI strings in all five languages still use them,
and changing those means re-wrapping the built books.)*

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
| Builder — what shape is the flow? | **Two steps, and the book is the door.** Step one asks only which book and by which route — off the shelf, translated, or aligned against an edition you own. Step two asks who does the work (**your own machine** or **your own key**, a two-card choice at the head of the left column), then key, model and hover, and on the right a real sample page above the price and the button. Day and night, chosen by the reader and remembered. |
| Builder — why does the book come before the engine? | Because *who does the work* is a question **about a book**, and asking it first made a reader commit to Ollama-or-a-key before they knew what they were building — the shelf, the route, and the size of the job were all still hidden. Folding the fork into step two removes a screen rather than reordering one, which is the actual complaint. The cost of it: a shelf card can no longer quote "Reading both ≈ $0.01", since that figure needs the engine. It is simply not shown; the price lives on step two, where it is real. |
| Builder — how does a reader know the translation is any good before paying? | **They read one page of it.** `sample.sample_translate` runs the chosen model over three real paragraphs of their own book; `sample_align` matches three against the edition they brought. It costs a fraction of a cent, renders in a miniature of the reader's own spread, and "Another page" buys the next one. The estimate stops being a promise about prose quality and becomes a price on prose already seen. |
| Builder — does the progress screen show real work? | Yes. `translate_book(on_batch=…)` hands finished pairs up through `build_reader(on_text=…)` to the page, so the spread fills with the book actually being made, and the time left is computed from the rate observed so far. Nothing on that screen is decorative. |
| Does the align route gloss? | **Yes.** `build_aligned(gloss=…, gloss_client=…, gloss_cfg=…)` glosses the original — exactly the body it renders, so no call is paid for on a paragraph nobody sees — while the reading column stays the translator's, word for word. Glossing is chat-model work, so the builder asks for a model on that route *only* once the hover is wanted; without a client the book builds the same, minus the hover, rather than being refused. This was the one place the two routes were not equal. |
| Where does a book come from when the reader has no files? | **The shelf** — a third route on the builder's front door, beside translate and align. Two page names on Wikisource are all biread stores; the reader's own browser fetches both editions and the book is built by `build_aligned`, exactly as if they had brought the files. Gutenberg was ruled out: its files refuse browser downloads, so using it would need a server that stores books, which copyright rules out. |
| How many books, and what may a shelf card claim? | **Five, and only what someone has checked.** A shelf that is *read*, not searched. A card shows title, author, the translator and year **the wiki itself names** (`wikisource.credits`), chapter count, and a build time computed from both editions' size; where the wiki names no translator the card names none. Two of the five have been read through and carry a measured coverage; the other three say plainly that nobody has, rather than borrowing the tone of the two that have. |
| A book with more than one English translation? | **Offered on the card, with a default, never a demanded choice.** Wikisource lists them and `resolve` reads that list; the shelf carries each one measured. Micromégas has two — Phalen follows the French chapter for chapter, Fleming's 1906 runs as one piece — which is how the default was picked, by looking. |
| A book that is not on the shelf? | **Its own screen** (`s-lookup`), not a dead end on the shelf. It searches Wikisource for whole works, asks the wiki itself which have an English counterpart (`langlinks`, never a guessed title), and resolves the pairs it finds. A hit with one side only says which side is missing; a search with nothing behind it says the book is probably still in copyright and why we cannot hold it either. A book taken from there joins the shelf marked *Added by a reader*, with no figures it has not earned. |
| Lookup — what happens to the results it does not show? | **They are counted, and offered.** Four works at a time, with the line above them saying what was left behind — *4 works shown · at least 3 more* — and a button that fetches the next four beside them. The number is a floor: `wikisource.Results.more` counts whole works among the rows the search actually read, never the wiki's own `totalhits`, which counts forty chapters of Germinal as forty results. Every hit with a counterpart is now probed; the old quota of three drew a card that read *Looking for both editions…* forever, which showed less **and** lied. And when probing ends, any hit still unanswered says it was never checked rather than spinning — the page tells the truth even if the engine goes quiet. |
| A section of the wiki's page that is not the book? | **Named on the shelf record, never guessed.** The wiki's Salammbô is fifteen chapters of Flaubert followed by an edition's apparatus — a notice, its sources, 626 paragraphs of textual variants, and the letters Flaubert was sent — sitting among the chapters under names of their own, every one of them calling itself "book" in its header. `Book.skip` names them, because on a curated shelf a person has looked. Deliberately not a rule that drops a trailing run of unmatched sections: that rule also drops the last chapters of a translation that stops early, and losing those silently is much the worse failure. A skip list matching nothing raises, so a wiki rename cannot quietly put the apparatus back. |
| A note's marker inside the prose? | **Dropped on the file's own say-so.** Standard Ebooks marks its endnote references in the text and they arrive glued to the word before — "Down with the Pope!1", and on the last line of Les Misérables "…lorsque le jour s'en va.115". 104 of them in that book, 37 in Notre-Dame. Removed by `epub:type="noteref"`, never by hunting for digits: Salammbô's one apparent case was the real number 3,200, and a digit rule would take the year out of every date. |
| A chapter the translator left out entirely? | **The page says so, once, under the heading.** The 1911 Twenty Thousand Leagues drops the French chapter XI outright, which is 48 blank right-hand pages; blank is the honest thing to show, but blank with no reason reads as a broken book. `build_book_data` marks a chapter whose body has nothing facing it (`enBlank`/`pubBlank`, read off the finished pairs so it cannot disagree with the page) and the reader prints *The translator did not include this chapter.* under that chapter's heading, in the apparatus's italic rather than the book's voice. Per column, because a chapter absent from a published edition may still have been translated. |
| An edition that sets its headings as ordinary paragraphs? | **Lifted into headings, but only where the wiki corroborates it.** Every chapter of the 1911 Twenty Thousand Leagues opened on a body paragraph reading `CHAPTER XIII THE BLACK RIVER`, and every chapter opened on a beheaded first word — `HE year 1866` — because that edition draws its drop cap as a *picture* and the letter lives only in the image's `alt`. Both are read now, neither is guessed: the alt is the wiki naming the letter, and a heading is lifted only when the edition also set it centred, since shape alone would read "Chapter XI was the best of them" as a title. Blast radius checked page by page against every shelf book with the old parser beside the new — 0 changes to Candide, Bovary, Micromégas, Eighty Days or any French side; the rule fires only on the two Verne volumes that carry the fault. |
| Two editions counting their chapters differently? | **Said out loud, and sized.** 47 against 46 is two editions; 4 against 22 is the same book divided quite differently and is described that way, because the aligner drops the numbering and matches by meaning. Both are normal; neither is silent. |
| How are a book's notes found and taken out? | **By corroboration, never by shape.** `notes.py` removes a paragraph only where the prose actually refers to it (`Micromégas[1]` … `[1] De micros`), or where it belongs to the run of notes closing a chapter, numbered in order. A paragraph opening `1.` is a footnote in one book and an ordinary list in another and there is no telling them apart by looking, so an uncorroborated one is left where it is: a note left in is untidy, a deleted sentence is silent and unrecoverable. Every note taken out is reported to the terminal like any other removal. Scanned per chapter, because markers restart at 1 in each. Verified inert across the whole corpus — all six files come out with the same paragraph count and nothing removed, which is right, because none of them was leaking apparatus. |
| Builder — what does a file card claim about a book? | Only what the file says: `meta.describe` reads an EPUB's OPF for title, author and language, a PDF for its page count, and counts paragraphs from the parsed text. Everything else stays None and is simply not shown — a filename is not an author, and a confident wrong byline is worse than a blank one. |
| A book Wikisource cannot supply? | **A second library, English only** — `standardebooks.py`. It carries translations Wikisource does not have (Salammbô, Les Misérables, Notre-Dame de Paris). Structure is read from the file's own EPUB semantics (`epub:type="chapter"`), the same principle as `ws-noexport` in another vocabulary, and the translator is in the URL so a card costs no second request. Wikisource stays preferred where both have a work, because only it can supply *both* halves. |
| Lookup — what happens when the wiki names no English edition? | **The second library is asked, by author, and what it says is offered rather than claimed.** "No counterpart" is a fact about Wikisource's interwiki links, not about the book: Germinal and Candide both carry none, and both have English editions on Standard Ebooks. So an unpaired hit is read for whose book it is (`shelf.probe_alone`) and `standardebooks.by_author` returns that author's shelf there — held to the author, because a search for a title alone returns Voltairine de Cleyre's poetry under *germinal*. The card names what it is: *your author's shelf there, not a match we can vouch for*. **Nothing is preselected** and the button stays dead until the reader picks — preselecting the first is a quiet claim that it is the right one, and a wrong pairing would build, render, and look perfectly fine. |
| Should biread publish AI translations of books nobody has translated? | **Surveyed, and the set is too small to build a shelf on.** The premise was that French Wikisource holds a great many works with no English edition anywhere, which only a model could open. It holds 8,084 whole works marked ready for export; 440 have an English Wikisource counterpart and 7,644 do not — but of those 7,644, only **48** are written about in twelve or more wikis, 21 in twenty or more, 7 in thirty. The rest is long tail: occasional poems, pamphlets, a cookbook, three translations of Xenophon. The notable remainder is dominated by **minor Jules Verne** — seventeen of the top forty — with Paul et Virginie, Les Aventures de Télémaque and Gil Blas beside them, and some of the list is not books at all (Carmen's libretto, Für Elise, Haiti's national anthem, a Franco-Soviet treaty). A worthwhile niche, *the Verne you cannot read in English*; not a strategy. Two limits on the finding, both making it a floor: "no English edition" is measured by Wikisource's own interwiki links, which are sparse enough that Candide and Germinal carry none, and the check against the second library is by **author**, not title — so "author absent" is real evidence and "author present" is not. |
| How does a book get onto the shelf? | **One command to make it, another to approve it.** `python -m biread.publish <slug>` fetches both editions, matches them by meaning, renders the book into `web/books/`, and then *looks at it* — opening, a middle chapter, the end, in headless Chromium, saving a screenshot of each and reporting any spread that is nearly empty or lopsided (`check.py`). `--approve` is a separate act, refused outright when the check found a fault, because a book that merely aligned is not a book somebody vouched for. `--dry-run` prices it and calls nothing. The approved list moved from Python in `web/build.py` to `web/books/published.json`, since a command editing a list of rows beats a command editing source. Publishing from this machine also needed an embedder that was not there: `llm/embed.py` mirrors the browser's over `requests`, so alignment runs on a local Ollama for free or a cloud model for pennies. |
| Must a published book carry glosses to go out? | **No — glossing is optional at publication, and a reader may buy it.** Glossing costs about four times translating, so requiring it would have kept Candide off the shelf over 28 cents. A book published without glosses says so on its card and offers them: **Hover to translate** in the reader's header glosses *the page in front of you*, on the **reader's own key**, one call for the page rather than one per paragraph. The card states the fact plainly (*no hover translations*) and makes no offer: the sentence that did, price and all, ran to two lines on seven cards of eight and put the rule inside each card at a different height from its neighbours'. The offer is met in the reader, where the header carries it and the reader is the one about to want it. A bought gloss is a private local override kept by paragraph hash, exactly as a correction is. |
| Reader-side glossing — how does it not drift from the Python? | **The algorithms are written twice; the French is written once.** `gloss.protocol()` hands the reader the prompt, the field separator, the fold map, the closed class, the coordinators, the prepositions and the perfect auxiliaries, and the book carries them — so a word added to `language.py` reaches the reader in the next build rather than in a second edit to a second language. `tests/test_gloss_parity.py` lifts `fold`/`parseUnits`/`anchorUnits`/`displayableUnits` **out of the shipped reader.js** and runs them beside `gloss.py` on the same paragraphs: curly apostrophes, an ellipsis folding one character into three, an over-broad noun-of-noun, a perfect that only echoes its surface, and a reply that will not anchor at all. The safety argument is unchanged: what the model returns is a *proposal*, only offsets are kept, and a model that rewrites a word cannot put its version on the page. |
| A published book carries the reader it was built with — how does it not go stale? | **It is re-set in today's reader when the bundle is assembled.** `render.rewrap` lifts a finished book's text out and renders it in the current templates, carrying paragraphs, offsets, alignment and any embedded EPUB or PDF across untouched. Found by shipping it: Candide could not offer glosses because the code that offers them did not exist on the day it was built, and Micromégas was handing out a reader a fortnight behind the repository. The UI labels are refreshed too — they belong to the reader, not the book, and an old book in a new reader shows blanks wherever a control has been added since. |
| Can a reader have a book without building it? | **Where somebody approved one, yes.** A card offers a finished book as a download only if it was built, read and **approved** here — a book going out under biread's name is something a person decided, not something that happened to align. Every other card is untouched: tap it and build the book yourself, on your own key or your own machine. What the card *claims* is measured off the file by `web/build.py` (`measure`), never declared, so replacing a build updates the card and cannot drift from it; only the English edition inside and the approval date are stated by hand, because no file can say either about itself. A slug that names no shelf book, or a file that is not there, stops the build rather than shipping a promise that 404s. `BOOKS_AT` is where the finished books are served from — empty today, meaning beside the builder; one absolute URL the day there is a server. |
| What does a shelf card do when you press it? | **The card is the button.** Where a finished book stands behind it, pressing the card takes that file; where none does, pressing it builds one — and either way the card ends with the line that names what it does, arrowed, so it reads as pressable without a pointer a touchscreen never sends. The filled *Ready to read* pill inside the card is gone: it was a second target on a surface that was already one, and a reader had to guess which of the two to press. Building your own drops to a small underlined line under a finished book. What the card *says* was cut with it — the description of the file is a middot line rather than a sentence, the caveats are one line, and everything else (what nobody has read, which English, how loosely the two pair) waits until a build is actually being chosen, where it is about to matter. Cards came down from 326–463px to 267–380px, and to 327 flat once the description became one line. |
| What is the book *about*? | **One sentence on the face, the rest under the pointer.** A summary is the first thing a reader wants and the last thing the card had room for, so the lead sentence sits on the card (see the pills row below) and the rest lives in a drawer that slides out of the card's foot and over the row beneath — the shelf itself never moves, which is the whole point of the two fixes above it. Written per book in `shelf.py` beside the rest of the record, not fetched: a curated shelf is one somebody has read, and an encyclopaedia's opening line is as often about an edition's publication history as about the story. A book taken from the lookup screen carries none and its card simply does not open. Pointer only (`hover: hover`) — on a touchscreen a drawer would stay open on whatever was last tapped. |
| A row of uppercase pills on the card face? | **Gone, and the space went to the book.** `ABRIDGED`, `NOT CHAPTERED`, `47 AGAINST 46 CHAPTERS` fired on three cards of seven and left the other four with a blank band, and the worst of them inverted its own meaning: *364 against 365* is Les Misérables' two editions agreeing on all but two chapters, set in the dress of a defect stamp, where nothing tells a reader whether the number is a fault. One of the four never fired on the shelf at all. What survives goes where it belongs — abridgement and the second library are facts about *that* English, so they are said on the line naming it (`Towle · 1873 · abridged`), which also lets a reader switching to the unabridged 1911 watch the word go; differing chapter counts are said in the book's own note, where a build is being chosen and it can change something. In their place, the one thing a reader picks a book on: `Book.lead`, one sentence that stands alone, clamped at two lines so a card is sized by its book and not by its blurb, with `Book.summary` carrying on in the drawer rather than repeating it. Costs 5px a card, measured — 318 to 324, and no lead over two lines at 1440 or 1100. This also closes half of the drawer's touchscreen hole: a phone cannot open the drawer, but it can now read what the book is. |
| What may a shelf blurb claim? | **Only what the book says, checked against the book — and what is worth saying is what the criticism keeps saying.** Written from memory, seven blurbs carried four errors, every one of them the popular version rather than the novel: Emma marries a *country doctor* (Flaubert's Charles is an **officier de santé** and the phrase "docteur Bovary" appears **nowhere** in the text), Valjean is a *pardoned* man (he is **libéré**, on a yellow passport, which is the engine of the whole plot), Quasimodo is among the three who *destroy* Esmeralda (he is the one shouting **Asile!**), and Candide comes *home* (he ends on a *petite métairie* outside Constantinople). Grep the built book before writing a claim about it; the six shelf files under `web/books/` carry both editions and settle these in seconds. Then the second pass, which is what makes a blurb worth reading rather than merely true: what does the literature on this book actually foreground? The cathedral is Notre-Dame's protagonist and Hugo wrote it to stop Paris pulling its Gothic down; Nemo's silence is a Polish nobleman's vengeance that Hetzel struck out because France was allied to Russia; *Micromégas* is one of the first stories where the visitors come to **us**. None of that is in the text to grep, and all of it is what a reader choosing a book wants. |
| Does hosting those books make biread a host? | **No — it is the opposite question.** "Not a host" is about *readers' own editions*, where someone else owns the text and a takedown would follow. The books on the shelf are out of copyright on the original side and carry either the wiki's public-domain translation or one biread generated itself, so nobody else has a claim on either half. Holding a reader's uploaded PDF is still refused; publishing a book we made from public-domain sources is simply publishing. |
| Can a reader put a book of their own on the shelf? | **A book they *found*, yes; a book they *own*, no.** A find on the lookup screen is two Wikisource page names — the shelf's whole currency — so a checkbox, **off by default**, keeps it: saved in this browser, shown among the cards next visit under *Kept by you*, and taken off again from the card. The align route gets no such control, because an uploaded PDF has nothing shareable in it: passing it on would mean holding the text, which is the one thing biread does not do. "Shared with other readers" in the literal sense — one list everyone sees — waits on the parked server and on someone to moderate it. |
| A book that arrives with no paragraph breaks? | **Repaired where anything is left to read, refused by name where nothing is.** A reader's Word file — a PDF saved as .docx — came in as **one** paragraph of 411,928 characters, and biread blamed PDFs for it and pointed at an EPUB the reader did not have. Two fixes, both about telling the truth. The break-rescue in `normalize.py` was gated to PDFs on the grounds that any other format means what it omits; that holds for a file that omits *some* blank lines and not for one that came apart nowhere, so it now also runs wherever the median block is longer than any prose is set in (`_never_broke`, 2,000 characters). Verified inert on the corpus — every example EPUB and text reports `never_broke=False`, so not one of them parses differently — and it recovers a flattened `.txt` in full. Where even the lines are gone, as in that .docx, the refusal names **the reader's own file**, says it arrived as one unbroken block, and names the format that lost the marks and the file to bring instead. The card that had sat on *Reading…* under the refusal now says *Couldn't be read*, because a page must not contradict itself. Deliberately **not** built: reconstructing paragraphs out of a blob by sentence and dialogue shape. It would make any file build, and the paragraphing on the page would be ours rather than the author's. *(Superseded in one case, and only one — where a second edition is in play, its paragraphing can be borrowed. See the row below.)* |
| One edition has its paragraph breaks and the other has none? | **The flat one is cut to the other's shape.** This is the case the refusal above could not see, because it judged each file alone: a reader bringing two editions has, in the good one, a real publisher's account of how the book divides — how many paragraphs the passage runs to and how long each is. That is not ours and not a guess, so borrowing it is not the invention the row above refuses. `segment.py` splits the flat side into sentences and places each break at the piece nearest where the counterpart's own paragraph ends, as a share of the whole. **Free, instant, no model.** Measured over the body — what is actually rendered, front matter being trimmed before a reader sees a page — by flattening real books and cutting them back: **98%** of Bovary's paragraphs come back whole in both languages, **99%** of Candide's published PDF, **100%** of Micromégas. Against ceilings of 99–100%, so what is lost is now almost entirely what *cannot* be found. Three arithmetic bugs cost two thirds of a book each and passed every small example — breaks poured rather than placed absolutely (3%), positions counted without the joining space (21%), a break landing exactly on a sentence end counted as inside it (40%) — which is why the test measures a whole book and not a fixture. Runs on every route, and says so: on the terminal, and in the ⓘ panel, because a page whose paragraphing came off the other edition must admit it. |
| A paragraph that ends without a full stop? | **Found where speech opens, which is nearly all of them.** Cutting only at sentence ends left a ceiling of ~89%: a line introducing speech closes on a colon or a dash, and no sentence ends there. Those are **96%** of what English Bovary could not recover and **91%** of the French. `SPEECH_RE` takes the break where a line *introducing* speech (`:` `;` `—` or a closing quotation) is followed by the mark that *opens* it (`—` `«` `“`). Both halves are required, which is what makes it corroboration and not shape — a dash alone is a French parenthesis. The two-language detail that matters: English sets `“Monsieur` with no gap and French sets `— Monsieur` with one, and a pattern demanding the word immediately fired on every English break and no French one, 98% against 79% of the same novel. A related fix in `_sentences`: French closes a quotation `. »` with a space before the guillemet, which the splitter did not allow for — Micromégas went from 53% to 100% on that alone. Extra candidates are close to free, because the cut takes the one *nearest* the position it wants; being generous costs nothing and being wrong costs a break, not a word. |
| A flat book with no second edition at all? | **The model is asked, and asked in the safest form there is.** Last resort, reached only where nothing free could work — `segment_like` is exact and costs nothing, so it always goes first. The text is cut into sentences, the model is shown them *numbered*, and it answers with the numbers that begin a paragraph. It therefore cannot rewrite a word even in principle: the same reasoning as glossing, one step further, where the model's text is thrown away after anchoring — here it never has any. A reply that is nonsense costs a badly placed break, never a sentence of Voltaire, and a window whose call fails is left unbroken while the rest of the book comes back. About a third of what translating the same book costs — **$0.06** on Balanced, $0.32 on Haiku, $0.96 on Sonnet for a book of Bovary's size. |
| A book that numbers no chapters at all? | **Left as one section, because ascending is not a spine.** Nausea is a diary, and the bare-numeral pass read four chapters into it: the page numbers 99 and 146, and two lines reading `one.` — the tail of a sentence the PDF had wrapped alone onto a line. 1, 99, 146, 1 ascends, and ascending was the whole test. What that cost was not the headings but `trim_matter`, which dropped the 411 paragraphs standing before the first of them as front matter: a third of the book, deleted in silence, and differently on each side, so the reader opened on prose facing *nothing in this edition answers to it*. Three conditions now. A run must step by one oftener than not, since chapters are numbered without gaps — not always, because an extractor that loses one heading would otherwise break a real spine in two. A bare heading written in letters must be capitalized, since `One.` heads a chapter and `one.` ends a sentence and both read as 1. And under both of them, trimming refuses to drop a leading section worth more than a quarter of the file, because a title page and an introduction are small beside the book: the cost of falling back is an introduction left in and unmatched, and the cost of not is the book. Measured inert on every example — Bovary, Candide and Micromégas come out with the same chapters, numbers and paragraph counts on both sides. Bovary's published edition is what keeps the capitalization rule honest: Eleanor Marx heads her chapters *One*, *Two*, *Three*, bare and spelled out, and they are found exactly as before. |

| One edition opens on an introduction and the other on the book? | **Cut, because the other edition says where the book begins.** Not a tidiness question: `_embedding_pivot` must place *every* published paragraph somewhere, so an introduction only one side carries is not left unmatched — it is poured over the opening pages. `trim_matter` cuts to the first numbered chapter, which is the right answer and no answer at all for a book that numbers nothing; Nausea is a diary, and thirty-one paragraphs of a critic's essay and an editors' note sat in front of it with nothing in the file to mark their end. `align.open_together` embeds each edition's own first page, finds where it lands in the other's opening stretch, and drops whatever stands in front of it — both directions, since either side may be the one carrying it, and neither where the two matches contradict each other. Bounded twice: only the first sixty paragraphs are searched, and the drop is held to the same quarter of the file trimming allows front matter, because one confident wrong match would otherwise take a short book whole. Runs before `recut` — a flat edition cut to a counterpart that still carries an introduction is cut wrong by the whole length of it — and in `sample_align`, so the page shown before paying is page one. Measured on the pair that prompted it: 31 dropped from the published side, 0 from the original, both editions opening on the same sentence and lining up paragraph for paragraph. Inert on Bovary and Micromégas; on Candide it takes seven paragraphs of Gutenberg notice and Modern Library title page, which is right. The align route only — the CLI's pivot path has chapter numbering and is untouched. |

| A scan that marks its paragraphs by indenting them? | **Read the indent — it is the compositor speaking, where everything else here is us inferring.** A printed page marks a paragraph twice: by where a line *ends* short of the measure, which `_unfuse_paragraphs` guesses from, and by where the next one *begins*, set in from the margin. The second is strictly better evidence and an extractor hands it over intact, and biread was throwing it away — `cleanup._blocks` collapses every run of spaces before anything looks at it. Two scans of Nausea came apart into 1,289 and 1,873 lumps and agreed on **60% and 43%** of the paragraph openings they share, which is why the reader opened on *nothing in this edition answers to it*. Reading the indent takes them to 1,527 and 1,668 — **94% and 91%**, and within 9% of each other in scale. Three conditions, each measured. The convention holds only where one indent accounts for a real share of the lines and is still outnumbered by the flush ones, since a paragraph runs to several lines and its openings must be the minority: every book in the corpus sits under 3% at any one indent and the two scans sit at 18% and 25%, so the gate at 10% is nowhere near either. Blank lines then stop counting, because a scan sets its leading wherever a line measured tall — three of them inside Nausea's opening paragraph — and trusting both marks at once cut that edition into 3,166 pieces. And an indent is declined where the prose runs straight through it, the line above stopping mid-clause *and* the line below resuming mid-clause: that is a scanner mismeasuring a margin, and it was 421 false breaks on one side. Measured inert on the whole corpus — Candide, Bovary and Micromégas come out with the same chapters and the same paragraph counts, to the paragraph, on both sides. **Both editions of the same book is what made this measurable**, and it needs no model and no money: the two Nausea files carry the same English translation, so how far one edition's paragraph openings fall on the other's is a real score, not a judgement. |

| Page numbers that count perfectly? | **Not a spine, because the prose under them does not begin.** The rule above that ascending is not enough was written against page numbers that ascend *raggedly* — 99 and 146 among a diary's stray lines. A clean scan is the harder case: its printed folios ascend, step by one without a single gap, are written as headings, and have a page of prose beneath each. They satisfy every condition `_numeral_headings` had, and the second Nausea came back as **175 chapters** of a novel with none. What separates them is the one thing a chapter always does and a folio never does — start a sentence. `_opens_a_chapter` reads the first line under each numeral: every edition in the corpus scores **100%**, the page numbers score **15%**, and the gate at 80% sits in a gap wide enough that the figure is immaterial. Scoped to the bare-numeral path, where the ambiguity actually lives; a written-out `CHAPTER IV` needs no corroboration and gets none. |

| A heading the file sets flush left? | **Cut before it, because a file that indents says nothing about a line beginning no paragraph.** Reading the indent (the row above) fixed where paragraphs *begin* and quietly broke where they *end*: `_split_on_indent` breaks only before an indented line, so a heading, which is set flush, joined whatever preceded it. Both scans of Nausea came out reading `Il ne faut pas avoir peur. JEUDI.` and `1 must not be afraid. Thursday:` — 21 headings swallowed in the French, 18 in the English, and with them the only structure the book has. `_stands_alone` cuts before a flush line on three conditions together: it is short (under half the measure — `JEUDI.` is seven characters against ninety), the line below opens a paragraph at the indent, and what stands above it has finished, by a blank line or a closed sentence. A paragraph's own last line fails the middle condition or the one above it, which is why Candide, Bovary and Micromégas come out to the paragraph unchanged, both sides. |

| A book divided by date rather than by number? | **A spine, and the dates are it.** Nausea is a diary: no numerals, no heading word, nothing `_numeral_headings` or `CHAPTER_RE` can see, so the whole novel arrived as one section of 1,500 paragraphs and aligned as one unanchored run. `_dated_headings` reads the days it is kept in — 22 sections in the French against 19 in the English, pairing 17-for-17 at 128/136, 96/95, 36/36, 71/71 paragraphs, which is two editions of the same book. A day name is nowhere near enough: the French offers **twenty** wrapped lines carrying *dimanche* or *samedi* mid-sentence against twenty-two real headings, enough to sink the spine on shape alone. Three marks together settle it, and each comes from the file rather than from us — the line stands as a block of its own with a blank either side, which a line inside a paragraph never does; prose *begins* under it (`_opens_a_chapter` again); and it is not **spoken**, because both editions set `— Toi, tu me l'as dit dimanche. »` and `"You did. You told me Sunday."` apart exactly as they set a heading and nothing about the shape tells them apart. Last resort by construction — it runs only where no numbered spine was found, so a novel whose chapters open on a weekday is untouched. Measured inert on the whole corpus. |

| Two editions divided but numbered by neither? | **Paired by content, not collapsed into one run.** Discarding untrustworthy numbering and discarding the *division* were the same code path, and they are not the same thing: sections carrying no numbers pair on nothing, so a diary fell all the way back to whole-book-against-whole-book — the regime `_chapter_pairs`'s own docstring says cannot be carried. `_pair_by_content` already existed for the case where numbering pairs and lies; it now also serves the case where numbering cannot pair at all. Bounded by `DIVISION_AGREES`, and the bound is the whole of it: that matcher is **one to one**, so it is right for 22 sections against 19 and wrong for six chapters against three merged ones, where half the book would be stranded by construction. The merged case keeps the whole-book path, which is many-to-one — and it is a test, not a hope: the first cut of this change took that case from 100% coverage to 50%. |

| Both editions open on apparatus? | **Cut where they first say the same thing.** `open_together` asked which paragraph answers to *the other edition's first page*, which assumes one edition opens on the book. La Nausée and its translation both open on apparatus — a Gallimard title page and an epigraph on one side, twenty-nine paragraphs of Hayden Carruth on the other — so both probes were front matter, nothing was found, nothing was dropped, and the reader met `GALLIMARD Au CASTOR` facing a paragraph of Existentialism. `_where_they_first_agree` instead finds the earliest **mutual** best match in the two opening windows: one-sided is the whole definition of apparatus here, and mutual is what keeps an introduction discussing Roquentin by name for pages from matching itself in. Both bounds are unchanged and are what make a wrong answer survivable — only the first sixty paragraphs are searched, and neither drop may exceed the quarter of the file trimming allows. Measured on the real pair with a real multilingual model, which is the run the spec said was owed: **4 dropped from the French, 32 from the English**, both editions opening on *Ces cahiers ont été trouvés* / *These notebooks were found*, and closing on the same sentence too. *(Superseded in one respect: the **first** agreement is not enough. See the row below.)* |

| A paragraph that is only a colon? | **Dropped, and only where there is not a letter or a digit in it.** A scan leaves stray marks standing as paragraphs of their own — `:`, `;;`, `: :`, `."` — and each one takes an alignment slot facing a real paragraph of the other edition. The Internet Archive Nausea arrives with **35** of them; Candide, Bovary and Micromégas have **none**, and the French Nausea has one, a `*` used as a scene break, which goes with them because a mark is not a sentence. The rule that reads better is *nothing with a letter in it is prose*, and it is wrong: it took a line of Roquentin's dates (`1924, 1925,`) and the `(1857)` off Bovary's title page, 105 paragraphs where this takes 35. What it would additionally catch is `44 44`, OCR reading a quotation mark as the page number beside it — left in, because no rule can tell that from a year, and untidy beats deleted. |

| Is the file a photograph of a book? | **Weighed, said once on the terminal, and never corrected.** OCR misreads words — `lloquentin` for Roquentin, `itwas`, `I'llgive`, a quotation mark read as the page number — and biread does not fix them, because fixing them means a model writing words into the book, which is the thing refused everywhere else here. So the reader is told what kind of file they brought instead, before anything is paid for. The measure is physical and needs no model: a scan stores an image of every page beside the characters read off it, so it carries **80.6 bytes of file per character of text** where every digitally typeset PDF in the corpus sits between **1.1 and 4.1** — Gutenberg, Wikisource and a converted EPUB alike. Measured against the text and not the page count on purpose: the Gutenberg Eighty Days is printed as seven enormous pages and reads as 330 KB a page while being no scan at all. Terminal only, like every other figure that would clutter a page someone is reading. |

| A heading a scan sets at the top of a page? | **Read the space below it, and the sentence above.** A printed page marks a heading with space on both sides, and `_dated_headings` demanded both — which is what a clean file offers and a scan does not: an entry beginning a page arrives with the foot of the previous page's last line directly above it, and that lost **7 of the 20** entries in the Internet Archive scan of the 1949 Nausea. What stands above has still *finished*, which is the mark that is left to read, and it is the one `normalize._stands_alone` already reads in the same order. Two more marks came with it, each from the file rather than from us. A line that **closes** a quotation is speech: OCR read the opening quotation of *"No, Tuesday, you know because of the …"* as the page number stamped beside it and handed over `44No, Tuesday, you know because of the . ..”`, which opens on a digit and passed `SPOKEN_RE` untouched. And a dateline **opens on its day**, or puts one word in front of it (*Shrove Tuesday*, *MARDI GRAS*); a sentence about a day puts it further in, which is how *The usual Sunday sauerkraut ?* was being read as a chapter. Measured: the scan goes from 15 headings, 2 of them false, to **20 real ones**, against the French's 21 — where it had been 13. Carruth's edition gains one. Candide, Bovary and Micromégas come out to the paragraph unchanged on both sides. The heading's own spacing is collapsed for the page, since a dated heading is the one heading that keeps its own words and the body escapes OCR spacing only because `_blocks` collapses it in passing — but the **length bound stays on the line as the file sets it**, because collapsing first loosens it by however far the scanner spaced the page out, and a 74-character line of newspaper small ads came under 60 that way and was read as a chapter of the novel. |

| One file has more pages than the other — is the surplus apparatus? | **No, and it is not even the longer text.** The instinct is sound and the measure is not: a page is a unit of type size, leading and margin, and two editions never share them. La Nausée against the New Directions scan is 233 pages to 243, which reads as ten pages of editorial matter and is nothing of the kind — the French carries **442,210** characters and the English **413,707**, so the file with ten pages *more* has 6% **less** book in it, at 1,702 characters to the page against 1,898. Cutting by the difference would have taken ten pages out of the edition that had fewer to spare. What the instinct is actually about is that apparatus is carried by one side alone, which is a question about *where the two editions correspond*, not about how long either is — and that is what `open_together` measures. |

| Both editions carry the same title page? | **Then they agree, and it means nothing — the book is where they agree and keep agreeing.** Apparatus is one-sided, which is true of an introduction and false of a title page: two editions of one book name the same author on their first page. A second scan of Nausea arrived carrying one, and `JEAN-PAUL SARTRE LA NAUSÉE` read against `Jean-Paul Sartre` at **0.64** with a floor of 0.57 — mutual, over the floor, and nothing to do with the novel. The rule cut at paragraph zero and dropped nothing, so the reader met a title page facing a title page and Sartre's fictional editors' note facing the real translator's. Candide had been failing the same way and invisibly: `CANDIDE` matched `CANDIDE` seven paragraphs into the Modern Library edition, so Littell's introduction and the table of contents were kept as though they were the book, and the spec recorded that as correct. What separates the two is that apparatus agrees **once** and a book goes on agreeing, so the cut is made at the head of the first *run* of three, never at a lone match. A run continues where both editions move on and **at most one** of them skips a paragraph — one side skipping is a translator merging two into one or a scan setting a footnote among the prose; both skipping at once is matter neither edition answers to, which is the definition of apparatus here and exactly what stands between La Nausée's title page and its first page. Measured on five pairs, old rule against new: Nausea/scan **0 / 0 → 4 / 4**, Nausea/Carruth **4 / 32 → 4 / 32** unchanged, Candide **0 / 7 → 5 / 31**, Bovary **0 / 9 → 5 / 3**, Micromégas **0 / 34** unchanged. Four of the five now open both editions on the book's own first sentence, and Bovary on the dedication both editions carry. The bounds are untouched. **The fixtures had to be rewritten to find it**: every test here paired editions agreeing on exactly one paragraph, which is the shape of a title page and not of a book, so all of them passed either rule. |

| A PDF that names itself? | **Read, like an EPUB's OPF, and refused where it is the converter talking.** `meta.describe` read an EPUB's title and author and, for a PDF, only counted pages — so two scans that both carry `/Title` and `/Author` in their document information produced a reader headed with the literal word `book`. La Nausée names itself and its author exactly. The English scan says `Jean-Paul Sartre - Nausea.rtf`, which is the file Acrobat was pointed at: a title ending in a document extension is a filename, and the rule that a filename is not an author applies to it unchanged. The author field is not checkable that way and is taken as given — shown as the file's claim, beside its other claims, never as ours. |

| An apparatus run together into one paragraph? | **Split back out where the numbers count.** `notes.scan` reads how a paragraph *opens*, so an edition whose notes are set close together defeats it entirely: the French Nausea ends on `FIN [1] - Un mot laissé en blanc. [2] - …`, twelve editor's notes and the novel's last word in one paragraph of fourteen hundred characters, and every one of them was translated, glossed and set against the other edition's ending. The corroboration is the one `_trailing_run` already uses, looked for inside a paragraph instead of across several — numbers that open notes and **count**, 1, 2, 3, because prose does not enumerate itself. Three of them, where a paragraph of its own needs two, since a break that is not in the file is weaker evidence than one that is; and the run must start at 1, since a note numbered 5 with nothing before it points into an apparatus printed elsewhere. Inline markers go with them: `FOOTNOTE_REF_RE` demanded a non-space before the bracket, which caught Micromégas's `Micromégas[1]` and missed all 24 of Nausea's `ce serait si [4]`, so it now anchors on anything at all except the head of the line — where a note's own marker identifies it. |

| What does the progress spread show while two editions are being matched? | **The pair it actually placed.** The translate route streams finished prose to the spread and both pages fill; the align route had nothing to stream, so `web/worker.js` seeded the page with every French paragraph against an **empty string** and the right page stayed blank for the whole of a run — the left turned, the right did nothing, which reads as a stalled build. `_by_embeddings` finishes a whole chapter at a time and that is exactly what the counter is already counting (`5 of 22` is chapter pairs), so `align_published(on_pairs=…)` hands each chapter's matches up as they land and `build_aligned(on_text=…)` carries them to the page, the same seam the translate route uses. The last pair **that found something** is the one shown, since a chapter always has some paragraph facing nothing and that tells a reader watching nothing at all. Before the first chapter lands there is no pair to show, so the left page keeps turning on the count and the right says what it is waiting for: a one-run book with no chapter numbering would otherwise sit on a blank spread for the whole build. |

| A build that says it needs two days? | **Clock each stage from its own start, quote the wait in rungs, and say what is already finished.** One clock ran from the press of Build and the estimate divided *all* of it by the items the *current* stage had done, so glossing — which runs last — was charged with the whole of the reading and the translating: 7.4 real minutes over four glosses read **"About 2806 minutes left"** on a book with well under an hour to go, then collapsed through hours to minutes as the count climbed, which reads as a build in trouble twice over. Each stage now times itself from its **first report**, which also leaves out the warm-up, and nothing is quoted until the rate has held for four items and fifteen seconds. What is then said is a rung — 2, 5, 10, 15, 20, 30, 45 minutes, an hour, an hour and a half — never a figure counting down, because a number moving every second is a thing to watch and this screen is asking to be left alone; a rung is climbed only where the estimate clears the one it is on by a tenth, so an estimate resting on a boundary does not flip between thirty minutes and forty-five. And glossing says the one thing that makes its length bearable: *Both pages are finished. This last pass adds the hover translations.* Deliberately **not** built, and offered: a "stop here and take the book" button, a build-time quote on the price screen, and a shelf card whose `about N min` counts the glossing it currently ignores. |

| Why does glossing take an afternoon? | **Because none of the waiting overlapped, and now six of them do.** The engine's browser client is a *synchronous* XHR, chosen so the whole pipeline could be written straight through and reused unchanged — which is right everywhere except the one pass that is nothing but network. 1,518 paragraphs of Nausea batch into about 150 requests, each of them a minute or so of a model writing, one after another. The judgement stays where it was and the transport moved out: `gloss.plan_gloss` hands over every batch it means to send, `absorb` takes a reply and anchors it, `written_off` puts what would not anchor to the rescue pass, and `web/gloss-pool.js` makes the calls **six at a time**. What may be kept is still gloss.py's and only gloss.py's, whoever is driving, and a test glosses one book both ways — batches answered in order, and answered backwards — and requires the two to land on the same glosses. A model on the reader's own machine gets **one** hand, because a second request there queues on the same card rather than overlapping. Two things fell out of it: a batch may now be retried through a provider's 429 instead of being lost to it, and the gloss bill on the browser is right for the first time — one client did both stages, so `gloss.cost` was the running total of *both* and the translation was charged twice in what the finished screen reported. The CLI, which has always made a second client, was never wrong. Splitting the build in two is what allows any of it: `build.Draft` is a book made but not glossed, `finish` sets it in type, and both routes go through them. |
| A build that ends with a closed laptop lid? | **It carries on, because every paragraph paid for was written down as it landed.** Nothing survived the tab: the browser's cache was `Cache(None)`, in memory, so three hours of glossing and a machine switched off came to nothing and the same book began again at full price. `Cache` now takes an `on_write` hook — a caller with no filesystem is not a caller with nothing to persist — and the page keeps each entry in IndexedDB under a hash of the book's own text, one record per entry rather than one per book, since rewriting a megabyte after every batch would have the storage doing more work than the model. Coming back, the reader picks the same file (a browser cannot hold one across a shutdown, and a shelf book is refetched for nothing) and the engine is handed what is held **before the estimate runs**, so the price screen quotes what is left and says why: *1,204 passages of this book are already made from an earlier session, and are not charged again.* The page read prices the remainder too, being a rate and not a total. Filed per language, because the same paragraphs in German are not the translation bought in English. This is not biread holding anybody's book: the keys are hashes, the values are the reader's own text, and all of it is in the reader's own browser. |
| Must a reader wait for the hover before they can read at all? | **No: the build makes the opening and the book finishes itself while it is read.** Glossing costs about four times translating and runs *after* both pages are written, so on a long book it is the whole of the wait — and every minute of it is spent on pages nobody has reached. The builder's default is now the first 40 paragraphs, and the finished book carries the protocol (`finish(..., gloss_on_demand=…)`) so the rest is made on the reader's own key as they read: the spread in front of them first, then the rest of the book behind it, **one request at a time**, because this runs under somebody who is reading and six would be a build wearing a book's clothes. It never starts by itself — turning it on is a press, and the key panel says what it will go on doing rather than taking a key for one page and spending it on a book. Left on, it is picked up again next time the book is opened; three refusals in a row turn it off, since going on would be spending a reader's money on nothing. The spread is repainted only when the page in front of the reader actually changed, because a repaint every ten seconds takes the tooltip out from under the pointer. This also reaches the seven shelf books published without glosses: they were built before the code that offers them existed, and now anyone can finish one by reading it. |
| A build that glosses forty paragraphs and says fifteen hundred? | **The count is the job, not the book.** `plan_gloss` asked for the opening and then handed the progress screen the whole book as its denominator, so a build doing forty paragraphs read *36 of 1,518* — and, worse, the clock divides the rate by what it thinks is left, so seven real minutes were quoted as **over two hours**. The feature above worked exactly as designed and every figure a reader could see said it had not. `GlossRun.total` is now what the run was asked for and `held` is what an earlier session already made, so `done` counts from there: a build resuming with a thousand paragraphs in hand does not open at zero, and glosses bought *beyond* the opening by a reader still reach the rebuilt book without pushing the count past its own end. |
| A book that jumps about while it is being made? | **It keeps the book's own 7:5 and never moves.** The progress spread was sized by whatever paragraph had just landed — 236px, 337px, 236px on three consecutive turns, measured — so the one screen a reader watches for an hour was the one that would not sit still. A page that overruns is faded out at the foot, which is nearer to what a page does than slicing a line of type in half. And it now turns during the **glossing** pass, which is the longest and had nothing repainting it at all: every finished pair is kept in order as it arrives, so the last pass turns through the book that has just been made, with folio numbers under each page, since a spread that changes only its words does not read as a page being turned. |
| An align build that stops halfway through? | **Every chapter it matched is kept, and no chapter is matched twice.** Translations and glosses already survived a closed lid; the matching did not, so the one route that buys no translation at all was the one route that bought its whole book again — 365 chapters of Les Misérables re-embedded because a reader closed the tab at chapter 300. `_by_embeddings` writes each chapter pair's finished placements into the same drawer as they land, under **both** editions and the embedding model: a match is a fact about the two editions together, so bringing a different published translation must not be handed the placements made for the last one, and each model scores in a space of its own. An entry that does not answer paragraph for paragraph is passed over rather than trusted, whatever it is filed under. What a resume still buys is **bounded and does not grow with the book** — `open_together` re-reads the first sixty paragraphs of each edition and `_chapter_pairs` a gist per chapter, where the matching itself re-reads nothing. Deliberately **not** cached with it: `open_together`'s own answer, because it decides where a book begins and a wrong held answer would silently behead an edition, which is a poor trade for a fraction of a cent. And the price screen is untouched, so a resumed align build is quoted the whole run and charged for what is left of it: under-charging against the quote, which is the safe direction, and not yet said out loud the way the translate route says it. |
| A book on the shelf with no file to take away? | **Given one out of itself, and the whole shelf carries the same one.** The reader's download control was intact and correct to hide itself: seven of eight books simply had nothing inside them. Micromégas was the exception because it was made by the CLI with `--epub --pdf` before the shelf existed, and everything published since goes through `publish.py`, which typesets nothing — so the format quietly stopped travelling with the books, and nobody could see it stop, because a book with no file looks exactly like a book with the button hidden. Rebuilding to reach the format would mean fetching both editions, matching them again and paying for a book already on disk, so the book is read back out of its own page: `export/refit.book_from_html` re-derives the chapters and the translation, and it is exact rather than nearly right — re-deriving the pairs and the chapter headings from a finished book lands on the ones that book already carries, to the paragraph, which is what the test asserts and what a wrong reconstruction would break invisibly, a heading gone or a paragraph facing the wrong page. `python -m biread.publish all --formats` puts the file **inside** the book, where a download has always lived, and leaves alone anything already there, so it costs only what is missing. **EPUB everywhere; both where both exist**, which is Micromégas, and the same command makes a PDF for any book that should have one. What it costs is the whole book twice: Candide 0.6 → 1.2 MB, Bovary 1.6 → 3.6, Notre-Dame 2.4 → 5.4, and Les Misérables **6.9 → 15.9 MB**, which is the figure to weigh if a reader ever complains about opening that one. |
| A book somebody built for themselves, with nothing inside it? | **Given the same file, by the same means, on any machine that has the engine.** Fixing the shelf left the readers' own books exactly where they were: a build in the browser cannot typeset, so a reader's La Nausée came out of the builder with the download hidden and no way whatever to ask for it — and the file was sitting on their disk, holding everything the exporters need. `python -m biread.formats <book.html>` is `publish --formats` with the shelf taken out of it: same reading-back, same putting-inside, no slug and no manifest, so it works on a book biread never published. It is what `refit` was for and the shelf was only its first caller. Measured on the book that prompted it: 1,518 paragraphs, **473 spreads**, 0.9 MB of EPUB, the file 1.25 → 2.5 MB, opening on *Ces cahiers ont été trouvés* facing *These notebooks were found*. The author is not asked for and not guessed — a finished book does not say whose it is, and the title page simply does not claim one. |
| Why did the EPUB lose the last lines of its pages? | **Because it was measured in a face the book is not set in, and what overran was clipped rather than shown.** The paginator lays the book out in headless Chromium and then awaited `document.fonts.ready` — which answers about the fonts a page is *already using*, and the harness at that moment is two empty divs. So it resolved instantly, Charis SIL was never fetched, and every page was measured in the fallback: Charter is narrower, and one real page of La Nausée measured 24 lines where the emitted page needs 28. The pages then overran by up to **49px** into the folio and past the paper, and `.page` sets `overflow: hidden`, so the surplus was not merely crowded but **gone from the book**. Asking for the face by name is the fix (`document.fonts.load`), and *checking afterwards* is the point, because the failure it replaces was silent and produced a plausible-looking book. Measured on the book that showed it: 0 pages reaching the page number and 0 clipped, against 39 in 120 and up to three lines lost; the book honestly needs 480 spreads where it claimed 473. Guarded by a test that renders the emitted pages and holds each to its own text box — the old harness passes every test about *what* is on a page and could not fail one about how much fits. |
| A reader who brings a photograph of a book? | **Told so before the money, in the browser as well as the terminal.** `looks_scanned` weighs bytes of file against characters of text and has been right since it was written; it was wired into the CLI alone, so the web builder took a scan without a word. A reader brought the Internet Archive Nausea at **80.6 bytes per character**, paid to align it, and got `isvery`, `itsent`, `firstsheet` through the English column, while the same translation sat in their own downloads digitally typeset at **1.1** with every one of those words correct. The measure now rides in `BookInfo`, so the card says *scanned* among the file's other facts and the price screen says what it means, above the figure and not under it. Deliberately not a refusal: a scan is often the only edition anybody has, and the reader is owed the choice rather than a locked door. |
| Can a model repair what an OCR ran together? | **Yes, and only its spacing is kept.** `spacing.py` asks about a passage and then throws the reply away: the passage is rebuilt from **the book's own characters** with the model's spaces, so nothing it typed reaches the page even when it is perfect. A word mended, a clause dropped, a line translated, an apology: each stops aligning and the passage is left as the file had it. This is the glossing argument one step further, where only offsets survive. Two findings paid for it. The free rule that finds candidates (a word the book never uses, whose halves it uses constantly) is a fine **filter** and a disastrous **actor** — 505 proposals, 208 of them wrong, taking `notebooks` and `reasonable` apart, because no rule about shape tells `notebooks` from `firstsheet`. And a first version compared the reply's own characters and refused half the good repairs, because Sonnet spaces correctly *and* straightens `’` to `'`; rebuilding from ours made the rule stronger and the refusals rarer at once. Measured live on the scan: 24% of paragraphs are worth asking about, 4 of 6 passages repaired and 2 refused, **14 words split and 14 corroborated** by the same book digitally typeset. `--respace`, opt-in, and only where a file actually weighs like a scan. |
| A format made by an exporter that has since been replaced? | **Remade on somebody's say-so, never sniffed.** Skipping a format the book already has is what makes `all --formats` cheap to re-run, and it is exactly how the one stale file survived: Micromégas carried the **reflowable** EPUB — the design built, shipped and reverted for the fixed-layout spread — and was passed over for having an EPUB at all. The book's *text* cannot go stale this way, since `make` writes a fresh file with no formats in it, but its *typesetting* can. A file carries no record of the exporter that made it and guessing from its shape would be a rule about EPUBs pretending to be a rule about versions, so `--remake` is asked for by whoever changed the exporter, who is the only one who knows. A remade format keeps its **place in the menu**: replacing Micromégas's EPUB moved it behind the PDF, which is a control a reader has used before quietly rearranging itself. |
| What does the hover panel say? | **What the phrase means, and for a verb which verb it is. Nothing else.** The panel opened with the French phrase set in bright type — the phrase the pointer is resting on, printed a second time an inch above itself — then the part of speech, then the translation, then the infinitive, then the passé composé: five lines where the reader asked one question. It now carries the translation and, on a conjugated verb, `inf · se détacher`. The passé composé went with the rest, and it went **out of the prompt** rather than just off the page, which is the expensive half of the decision: the gloss cache is keyed on the prompt's own hash, so editing it invalidates every gloss ever bought. That was weighed and chosen, because a field asked for, paid for and thrown away is worse than a one-off re-buy. Two rules moved with it. An infinitive that only echoes its surface is dropped, since a verb already in the infinitive would have the panel repeat the word under the pointer — the same duplication, in miniature. And a field the prompt no longer asks for is ignored where a model offers it anyway, so no model can put a line back on the page by being generous. |
| A book whose spine the reader never sees? | **The number was made a condition of having one, and a diary has no numbers.** `_dated_headings` reads La Nausée's entries correctly — 22 in the French against 20 in the English, paired and rendered — and then `build_book_data` dropped every one of them, because it wrote a chapter into the book only `if chapter.number`. So the novel arrived with no headings on either page, an empty Chapters menu, and fifteen hundred paragraphs running together: a detection stage doing its work and a render stage quietly discarding it. A division that is *named* now reaches the page too, with no eyebrow, since `Chapitre III` is not what stands over `VENDREDI.` and an empty band above the date reads as a heading with a piece missing. The English one is **looked up, never translated**: `align.AlignmentReport.chapter_titles` carries the counterpart edition's own dateline up from `_by_embeddings`, merged into the book *after* the coverage arithmetic, because a heading is not a paragraph that landed and counting it would flatter the figure. Where the two editions divide the book differently enough that a section pairs with nothing, the English heading is simply blank — which is what the rest of the page already does. The EPUB carries the same headings, by the same rule. |
| What does the reader's header call the hover? | **What it does, in the gesture the reader will use.** *Add glosses* named it in a scholar's word and said nothing about where it would appear, while the builder selling the same pass called it *Hover-to-translate*: one product, two vocabularies, and the obscure one on the control that asks for a key. The pill now reads **Hover to translate**, then *Translating…*, then *Translating as you read*, with the key panel as *Your key, your translations*. What rules out the plainer wording is the book itself, since an edition with an English page facing the French cannot carry a button called *Translate the French* without it reading as a switch for that page: the label has to name the gesture or the phrase, never the text. The card and the price line follow it (*no hover translations*, *hover translations ($0.02)*), because a reader meets both of those before the header. Five languages carry it, and every state stays inside the pill's own width, which is the constraint that governs any label up there. |
| Where does a book you built for yourself live? | **On a row of your own above the shelf, in your own browser, and it needs no account.** A finished book was a download and nothing else: the file landed in Downloads among everything else a browser has ever fetched, and the way back to it was to remember what it was called. Every build now also goes into the reader's own storage and stands at the top of the front door, opened again in one press. **This is not the shelf and must never read as it**, which is the whole design of the band: the shelf below is published, built here, read through and vouched for by somebody, and these are one person's own hour-old files. So they are set apart rather than sorted together, the band names itself *Yours only · Books you built* and says in its own words that nobody else can see them, and every card carries the mark. Nothing about it reaches a server: the file is the reader's own, it is in the reader's own browser, no server is told it exists, and *Take it off my shelf* removes it. Kept apart from the build cache in a storage of its own, so clearing either leaves the other whole, and in two stores rather than one, since painting the cards must not read a fifteen-megabyte book to print its title. The done screen says where the copy is and offers to drop it there and then, because a reader on somebody else's computer is owed the offer at the moment the book is made, not a setting to go and find. Distinct from the shelf's *Kept by you*, which holds two Wikisource page names and no text at all: that is a book you **found**, this is a book you **made**. |
| How much of a book does a build gloss up front? | **A stretch of reading, not a count of paragraphs.** The opening was a flat 40, which is the whole of Micromégas and **thirteen spreads of La Nausée's four hundred and ninety-seven** — 38 paragraphs of 1,518, so a reader met plain text on page twenty-seven of a book they had just paid to have glossed, and the builder's promise that "the book fills in the rest as you read it" was carrying almost the entire book. A count of paragraphs cannot buy the same stretch twice, because a book set in short dialogue lines and a book set in long ones share nothing but the number: `gloss.opening` counts **characters of the original** instead, 40,000 of them, floored at 40 paragraphs so a book of very long ones still gets a few and capped at 400 so a book of very short ones does not run away with the build. Measured across the corpus at 40k: Nausea 85 paragraphs, Bovary 93, Candide 95, Les Misérables 126, 80 Days 173, Notre-Dame 216, and Micromégas **whole**, which is what makes this scale rather than merely cap — a book that fits leaves a reader nothing to buy. The sizing lives in the engine and not on the page, because only the engine holds the paragraphs; the page knows a total and an average, and an average is exactly the ruler this row throws out. And the price line now names the figure (*hover translations for the opening 85 passages*), since "the opening" alone is the difference between a chapter and four pages. |
| A book built with the hover unticked? | **Still carries the offer, or it is sealed for good.** The reader-side pass — buy the hover as you read, on your own key — appears only where the book carries the protocol, and the browser wrote that protocol only when the build had made a chat client. The align route asks for a chat model *only once the hover is wanted*, so a book aligned with the box unticked came out with no hover **and no way for anyone ever to add one**: the header pill hides itself, correctly, because there is nowhere to send the request. Two real Nausea builds were dead this way. The model is chosen on the page whether or not the build uses it, so the offer is written for every book; a local build names **Ollama**, since a model on the builder's own machine is not somewhere a finished book can send a reader. The same fault ran through `rewrap`, which attached the offer only to a book with *no* glosses at all — the test was written when a build gave a book all of its hover or none, and under the row above every book is glossed **in part**, so republishing one would have quietly stripped the offer from exactly the books that need it. It is now attached wherever a body paragraph lacks one, and Micromégas, glossed 34 of 34, is still correctly offered nothing. |
| A quote that comes in under the bill? | **Read the meter before guessing the number.** The quote has run about 30% under since it was first measured and the cause has been known as long: an estimate prices one clean pass and nothing counts the retries. The tempting fix is a constant — and the last constant in this code, a hand-fitted 5.3× for how much a model writes, is exactly what the sample page had to be built to abolish, so fitting another one against a single remembered figure would be repeating the mistake in the same file. So the run counts what it spends beyond a clean pass and says so at the end, beside what it was quoted: `retry_in`/`retry_out` in tokens, `resent` and `rescued` in passages, `retry_cost` in the model's own money where there is a rate and in tokens where there is not. **Every send past the first of each batch is in it**, which is the invariant the test asserts arithmetically rather than against a threshold — the batch re-asked with the stricter note, the passage re-done alone, and each ~700-character piece after that. Reported by the CLI and by `publish`, which are the builds anybody here can read; a reader's own browser counts the same figures and shows them nowhere, since a number they cannot report back is clutter on a screen about money. A run that retried **nothing** says so too, because a rate averaged only over the runs that went badly is not a rate. |
| What may a shelf card spend a line on? | **Only what tells this book from the one beside it.** A card carried eleven lines and three rules, and the longest, greyest of them read `French + published translation · no hover translations · EPUB` **identically on six cards of seven** — the same line as the one on either side of it, which is furniture and not information. What they have in common is now said once above the shelf (*Unless a card says otherwise: …*), read off the cards actually on show rather than declared, so a shelf whose books stop agreeing stops claiming they do. Taken from **more than half** of them rather than all, since one glossed book must not put the line back on the other six; a card that differs prints its own line in full, which is what the wording allows for. The two-column table under it becomes one line of type, `English: Smollett · 1920 · 30 chapters`, where the colon does the work the `English` label did — and both facts stay on the **face** rather than going into the drawer, which only a pointer opens and a book somebody looked up does not have at all. The weight of the file goes to the drawer except where a download is big enough to be felt before it starts: Les Misérables says 15.9 MB, the other six said a figure nobody weighs a novel by. Measured: 346px a card to 240–295, the shelf 1,994px to 1,803. The cost is that the odd card out is now a line taller than its neighbours, so the slack in a levelled row grows to about 60px of air above the divider — the side this shelf has already chosen twice, and cheaper than a reserved blank band, which is the fault the pills row was removed for. **The fixture had to grow a fourth book to find any of this**: the stub's three books agreed on nothing, which is the one shape in which a rule about what cards have in common cannot fire.
| Two measures on one screen? | **One left edge, and the headline docks once it has been answered.** The hero and the controls sat in a 640px column centred on the page and the shelf broke out to 1180 beneath them, so pressing *Pick from the shelf* moved the content **270px to the left** — the eye has to find the margin again, and centring a narrow thing above a wide one always does this. Step one is now laid out in the shelf's own width and left-aligned: type keeps a reading measure inside it (headline, question, the note under the tabs), and the panels a reader aims at — the file cards, the foot, the shelf itself — span the column, so a route with no shelf on it still has an edge on the right rather than reading as a page pushed into its own left half. The headline then docks on the **first press** and never on arrival: the subtitle goes, one line replaces two, and the front door is untouched for whoever is standing at it. **Instantly, not eased** — the press that docks it is the press that brings up the shelf, and a fifth of a second of animation is three rows of cards sliding under a hand already reaching for one; two existing tests caught it doing exactly that, one of them by reading pixels at a box that had moved since it was measured. The dead `Next` under the shelf went with it, since a card is the thing you press there and a disabled button was a third arrow competing with the card and the line inside it; it arrives when there is somewhere for it to go, and the line beside it still says nothing is fetched until then. Measured at 1440: 600px above the first card to **478**, the page 1,803 to **1,659**, and hero, tabs, foot and cards all starting at x=130 on every route. One edge then cost a gap on the other side, which is the second half of this row: the panels spanned the shelf's width on routes with no shelf, leaving **540px** of nothing between the end of the type and the end of the dropzone, and a page holding its content in its left half is the same complaint arriving from the right. They stop at 860px there, so the gap is a constant **220px** at every width from 1000 up. The left edge is untouched, which is the one that must not move; the right is ragged anyway, and an edge the eye is not keeping.
| An empty half of the front door? | **A page of the book it is offering, where step two has its sample.** Step one asked its questions in a column and left the rest of the screen bare, so at 1800px the content sat with 310px on its left and 630px on its right and read as a page pushed aside. Every width fix made it worse somewhere else: matching the panels to the type moved the imbalance from inside the block to around it, matching the container to the panels gave the shelf back its 160px jump, and narrowing everything to one measure cost the shelf its card size, which is measured elsewhere in this file at 277px and a truncated lead. The screen was not too wide; it was **missing a column**. What goes in it is the answer to the question a reader is actually asking at the door, and it is the one thing the builder never showed before the price screen: a finished spread, at the book's own 7:5, set in the reader's own face, with folio numbers and a page's worth of type **overrunning at the foot** the way a page does rather than two paragraphs floating in a box. The text is real and comes from the Candide on the shelf, so the two columns correspond because they were aligned and not because they were written to fit. It stands down on the shelf route, which wants the whole column for its cards, and below 1260px, which is exactly where the container stops growing: any narrower and the tab strip would shrink on the two routes that carry the page and not on the one that does not. Lifted 58px clear of the row it sits in, so its label stands level with the **headline** it answers rather than with the question below it: level with the masthead was tried and is too high, since the page then reads as a second thing the screen opens with instead of the answer to what the screen is asking. And what the panel says under it names the gesture rather than the property, since *the French hoverable phrase by phrase* is an adjective doing an adverb's work: **any phrase in the French translated under the pointer**. Two faults found by using it. In the flow it hung off the step, so the first press — which docks the headline — moved it **122px up the page and left it there**, a page of a book leaping the height of a paragraph for a reason that has nothing to do with it; it is out of the flow now and holds one place in every state, which also settles the lift argument above, since the position no longer depends on how tall the question is. And it was set like a column of newsprint rather than a page of a book: type to the edges, lines close, one paragraph ending where the next begins. It has a book's margins, a book's leading and an indent that can be seen, which costs it four lines a side and buys the only thing the panel is for. |
| Five panels, all open, every visit? | **What was settled last time is one line, and the price stops scrolling away.** Step two asked five questions of equal weight down an 880px column beside a 500px one, so the figure a reader was changing sat halfway up an empty half-page. Three changes, all of them about what a *returning* reader meets. Who does the work and which key are answered once and remembered, so on a second visit they were two open panels asking for a confirmation of what had already been said: they fold to *Your own key · OpenRouter · remembered in this browser* with **change** beside it, and a first visit, having nothing to fold, sees exactly what it always saw. Which engine a reader chose is now kept as well, like the theme, because it is a preference and no secret; the key is still kept only where the box was ticked. The right column is **sticky**, so the price and the button hold their place while the column beside them is worked. And the per-tier rate, which is evidence rather than the answer, is kept for the tier that is pressed and for whichever is under the pointer, its space held either way so the row does not jump as a reader reads along it; the model-id field, an escape hatch every reader met at the weight of a field, is a line of type that opens one. The left column comes down from 880px to about 600 on a second visit. Deliberately **not** folded with them: the model, the hover and the language, which are answered per book and change with the book. |
| What does a card say about the hover? | **What the reader's own header calls it, as a state and not a quantity.** `French + Phalen · hover translations · EPUB + PDF` said three things in one middot run and two of them belonged elsewhere. The **edition** is named on the credit line two lines above and in the sentence above the shelf, so saying it a third time, as an equation, on a page that speaks in phrases everywhere else, was the last of that dialect: gone. The **formats** are a fact about the download wearing the dress of a fact about the book, so they moved to the drawer, beside the weight, which is the same kind of fact. What is left is the hover, and it was a bare noun that does not say whether the book has it or is merely about it: the reader's header settled on **Hover to translate** on the grounds that one product must not be spoken of in two vocabularies, and the shelf was the last place still calling it something else. So a card says `Hover to translate: included` or `not made yet`, and **part-glossed is not a third state** — it is a quantity, and in a slot whose other values are states it reads as one that does not exist. A book with its opening bought says *not made yet*, which is true of the book and **under-claims**, the safe direction: a reader who hovers the first page and finds a gloss has been given something rather than misled. The count goes to the drawer, where the quantities are. The hoisting above the shelf is now **fact by fact** rather than line by line, since two books can agree on what is on their pages and differ about the hover; on today's shelf that leaves six cards saying nothing at all under the action line and one saying the two things that are its own. Refines the row above, which is otherwise unchanged. |

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
- **Reusing the whole-book matcher for a sample page** was built, tested, shipped,
  and wrong — caught on the first run against a real embedding model, which paired
  a French paragraph with the opening line of the book. `_embedding_pivot` is
  monotonic and many-to-one: it must place *every* published paragraph somewhere.
  Over a whole chapter that is exactly right. Over a sample window running
  twenty-five times the length of the page it hands the entire window out among
  three paragraphs. `embed_nearest` matches each paragraph to the one counterpart
  that stands clearly above the rest, or to nothing.
  Two lessons, and the second is the expensive one: a threshold is judged against
  the window's own median rather than an absolute cosine, because each embedding
  model scores on its own scale and a number tuned to one would quietly blank every
  page on another. And **every test passed through this bug**, because they all
  aligned three paragraphs against three — the one regime where the old code is
  fine. A fake embedder proves the wiring, not the matching; the fixture has to
  have the shape of the real problem.
- **The reflowable EPUB with tap-to-reveal glosses** was built, shipped, and
  reverted. Two faults, seen in Apple Books: glossing every phrase makes every
  phrase a footnote link, which Apple Books renders in hyperlink **blue** — the
  whole French page turned blue and unreadable; and a reflowable book cannot hold
  the reader's French-left/English-right spread, so it read as one interleaved
  column, not the book. Replaced by a fixed-layout spread with no glosses. The
  cost is that `--epub` now needs the browser engine (it paginates by measuring)
  and is best on a tablet or desktop — accepted, because the spread is the point.
- **Anchoring the cut by embedding** was built, measured, and removed. Cutting a
  flattened edition purely by length must drift where two editions differ, so the
  good edition was taken in runs of forty paragraphs and each run *found* in the
  flat text by embedding — coarse pass over a window as long as the run, fine pass
  over its opening — before the lengths shared out the sentences inside it. It
  worked, and it lost: on a book whose two sides correspond, proportional alone
  recovered **69%** of the paragraphs and the anchored version **40%**, because a
  wrongly moved anchor takes all forty of its paragraphs with it and there are more
  of those than of anchors that save a run. It won only where four chapters had been
  cut out of the counterpart — 5% against 17% — and 17% is not a book either.
  Two lessons. The acceptance threshold could not be calibrated: the codebase's
  existing margin is in cosines, these scores are means over eighty sentences, and
  every scale I could measure came from a fake embedder, which is the one thing
  known not to stand in for a real one. And the arithmetic underneath mattered far
  more than the model on top — three off-by-one and unit bugs each cost more than
  the entire anchoring mechanism could add. Worth revisiting only with a real
  multilingual model on two real editions, and only for the drifted case.
- **"A card is as tall as the book it describes"** was reasoned, built, and
  overruled by looking at it. Each card kept its own height so a filter could
  not resize it — but a row of three then ended on three different lines, and
  the shelf read as out of true twice over, once in a multicol flow and once in
  a grid. Cards in a row now end level, with the action line pushed to the foot
  so the slack falls above the divider rather than under the last word. The cost
  stands as it was described: the same book is a little taller in one category
  than in another. The ragged row is the worse of the two.

---

## Known open issues

- **All seven shelf books are built and carry an EPUB; none but Micromégas is
  glossed.** Micromégas (34 paragraphs, glossed throughout, the published column
  beside ours, EPUB and PDF inside), Candide (98.9%), Bovary (87%), Eighty Days (79%),
  20,000 Leagues (58.8%), Notre-Dame (86%) and Les Misérables (92%, 12,208
  paragraphs — the largest by three times). An unglossed book is no longer a book
  without hover: a reader finishes one by reading it, on their own key, a page
  ahead of themselves. What the shelf is short of now is *glosses somebody has
  paid for* and more titles, not builds.
- **A book built in the browser gains its EPUB afterwards, not during.** Both
  exporters paginate by measuring real type in headless Chromium, which the
  builder's own tab has no way to run, so a book a reader makes for themselves
  still comes out of the browser with nothing inside it and the download control
  hidden. `python -m biread.formats <book.html>` puts one in later, on any machine
  with the engine, which is the whole of what `refit` is for. What is left open is
  the browser itself: closing it there means paginating in the reader's own page
  (the algorithm is already there, in reader.js) or a server, and the second is
  ruled out on the same grounds as everything else here.
- **Salammbô is off the shelf for now.** It was the eighth, built and approved at
  90%; its `Book` record and its published row were taken out on 2026-08-06 and
  its built file left in `web/books/`, unlisted. Restoring it is one `Book` back
  in `shelf.py` and one row back in `published.json` — both whole in the history.
- **Glossing still runs one book at a time on the CLI.** The six-at-once pass is
  the browser's; `gloss_book` is unchanged and sequential, which is what
  `python -m biread.publish` uses. Putting the shelf's remaining books through it
  is the case for lifting the same trick into the CLI, where a thread pool is a
  far easier thing to write than it was in a worker.
- **Glossing costs roughly four times translating, and that governs the budget.**
  Priced off Candide's real French (469 paragraphs, 184,197 characters) against
  live OpenRouter rates: on DeepSeek v3.1 the translation is $0.077 and the
  glosses $0.275. Scaled by each book's own character count, translating **and**
  glossing the whole eight-book shelf from nothing is about **$13** on Balanced
  and about **$200** on Sonnet — which is the argument for Balanced, stated in
  money. Both figures are floors: the quote runs ~30% under (see below) and the
  gloss estimate does not count its rescue retries at all. What this changes is
  planning — the hover, not the prose, is what a shelf costs.
- **The browser builder still refuses a flat file that has nothing beside it.**
  The engine repairs it (`build.repair_flat` on the model), and the CLI reaches
  that path, but `judge()` in `web/worker.js` refuses at *inspect* — before the
  price screen — and opening the gate needs two things it does not have: a sample
  page cut from a book that has no paragraphs yet, and a quote that counts the
  repair. Both are doable (the sample could repair only its own window, one call,
  a fraction of a cent, exactly as it already pays to translate three paragraphs)
  and neither is built. Until then the browser's answer to a lone `book.docx` is
  the honest refusal, and the CLI's is a repaired book.
- **A cut edition holds only while the two editions keep step.** `segment.py`
  places every break by proportion, which is right to 90% of the ceiling where
  the editions correspond and collapses to **5%** where they do not: measured by
  dropping four chapters out of the counterpart, after which everything past the
  gap is shifted and no paragraph lands whole again. The text is all there and in
  order — it is the boundaries that go wrong — and the aligner still matches by
  meaning on top of it, so the book reads. The obvious next rung is free and not
  built: a flattened file usually still carries its chapter *headings* as words in
  the text ("CHAPTER XIV"), and matching those against the counterpart's numbered
  chapters would re-anchor the cut exactly, where an embedding could not.
- **Coverage is not a grade, and 20,000 Leagues is the case that proves it.** It
  sits at 58.8% against Candide's 98.9%, and it is nonetheless matched about as
  well as it can be: the placed English runs to 68% of the French by characters,
  which is the whole of the 1911 translation. That edition condenses, and cuts
  chapter XI outright. What a low figure means is *this translator left things
  out*, not *the aligner lost its way* — the two are told apart by weighing the
  English that landed against the English that exists, and nothing on the card or
  in the check does that arithmetic yet.
- **`--approve` re-makes the book it is approving.** The flag runs the whole
  fetch-and-match again before writing the manifest row, so approving the file
  you just read costs another fourteen minutes and another nickel — and approves
  a *fresh* build rather than the one that was checked. 20,000 Leagues was put on
  the shelf by calling `publish.approve` directly for that reason. Approval
  should act on the artifact, not re-derive it.
- **The published edition's own chapter titles are extracted and then dropped.**
  `A SHIFTING REEF` is now lifted off the 1911 Twenty Thousand Leagues, but the
  reader's English heading is built from the *French* chapter's title translated,
  so a French chapter with no title shows a bare `CHAPTER XI` beside an English
  edition that names it. No worse than before — it used to sit in the body as
  junk — but the title is now in hand and unused.
- **A shelf card's build time is one measurement extrapolated.** Madame Bovary's
  5,449 paragraphs took about fourteen minutes in the spike, and every other
  figure is that rate scaled. It is the network's pace, not the model's, so a slow
  connection will beat the estimate in the wrong direction.
- **A find-failure still discards the whole paragraph.** `anchor()` returns None
  if any one unit will not match in order, so one bad unit loses the other
  eighty. The rescue pass hides this in practice — it retries such a paragraph
  alone, then sentence by sentence, and the last full run left none plain — but
  the underlying anchor is still all-or-nothing, paid around with extra calls
  rather than fixed.
- **A failed paragraph records nothing about why it failed.** The model's reply
  is not kept, so diagnosing a failure means paying to reproduce it. That is how
  the curly-apostrophe run cost $1.64 to explain.
- **A book built before dated headings reached the page cannot get them from
  itself.** `rewrap` re-sets a finished book in today's reader and can restore
  anything the reader draws, but not something the *data* never carried: the
  dates were consumed at cleanup and dropped at render, so they are simply not in
  the file. Recovering them means going back to the source — the French PDF says
  where each entry begins, and the alignment already inside the book says which
  English paragraph faces the first one, so the counterpart's dateline is looked
  up rather than paid for. Done by hand for the two La Nausée builds on this
  machine (21 headings, 20 and 21 of them with English, $0). Not a command,
  because it is one book on one disk; it becomes one if a second reader ever
  needs it.
- **An English dateline sometimes carries the entry's first sentence with it.**
  `Tuesday, 30 January: Nothing new.` is one printed line in the New Directions
  edition, so the heading takes the sentence the French sets as its opening
  paragraph. One entry of twenty in that file. Cutting at the colon would be a
  rule about punctuation pretending to be a rule about headings, and `Friday,
  3.00 -p.m.` shows what it would do to the rest.
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
  reader — Apple Books is the target. What *is* now tested is that a page holds
  what it was measured to hold, which is where the real fault was.
- **`--respace` is the CLI's, and the browser cannot ask for it yet.** The engine
  is shared, so wiring it into the builder is a checkbox, a line on the price
  screen and a number in the estimate; none of the three is built. A reader who
  brings a scan to the browser is now *told* it is a scan, which is the half that
  mattered most, and is offered no repair.
- **A scan's misread words are still misread, and always will be.** Respacing puts
  spaces back; it cannot turn `lloquentin` into Roquentin, and the check refuses
  any reply that tries, because a model allowed to mend one word is a model
  writing into a book. The honest fix for a bad scan remains a better file.
- **Revise crosses browsers by a link, not by sync.** Corrections live
  per-browser; the *edits link* carries them across, but automatic cross-device
  sync needs a server and is parked (`design-reference/revise-spec.md`). On mobile
  the correction control is off (touch) — a phone reader sees corrections that
  arrived by link but makes new ones only on a desktop-width window.
- **A book on your own row is in one browser, and that is the whole of it.** It
  is the same limit revise has and for the same reason: crossing to a phone means
  a server, and the parked accounts design would sync the row and not the book
  (`design-reference/accounts-spec.md`). Clearing site data takes the row with it,
  which is why the file is still offered on the card and on the finished screen;
  a reader who downloaded it loses only the shortcut. The row is on the builder's
  front door alone, so a book is found where books are made.
- **The quote runs about 30% under, and the gap is retries.** Pricing the book by
  weighing the sample page fixed the model-verbosity error — translation now
  quotes at 0.91× of the true bill on a model it has never seen, where the old
  fixed 5.3 constant managed 0.61× overall. What is left is the gloss rescue path:
  a paragraph whose gloss comes back malformed is re-done alone and then sentence
  by sentence, and no estimate has ever counted that output. Ruled out as the
  cause: input overhead, since a sample carries *more* system prompt per character
  than a book does (2.5× against 1.6×). Measured on Micromégas/DeepSeek: quoted
  $0.0807, charged $0.1160. Accepted for now — the figure wears an ≈ and the sums
  are pennies — but it is under-promising, which is the wrong direction to be
  wrong in, and it will matter on a long book. **The meter is now read**: every
  run reports what its retries cost beside what it was quoted (see the decision
  row), so the uplift waits on two real builds rather than on a guess. Two things
  found while wiring it. The retries are not only the rescue pass — a batch whose
  first reply will not anchor is *asked for again whole*, and that second send is
  the same uncounted surplus, so `resent` is counted beside `rescued`. And the
  weakest instrument turns out to be the **default** path: a build glossing only
  the opening prices the hover from the counted estimate, which is the fixed 5.3×
  constant calibrated once on Micromégas and DeepSeek, because the sample page is
  weighed only when the whole book is glossed
  (`web/builder.html`, `measured()`). Sizing the opening by characters made that
  path the ordinary one without anybody noticing it was the guess.
- **An embedding run is priced only when OpenRouter lists the model.** The align
  route's cost gate shows a dollar figure when the rate is known and an honest
  token count when it is not, rather than a plausible cent.
- **`open_together` has been rewritten twice by real embedding models, and the
  debt recorded here is paid.** Both rewrites came from running
  `text-embedding-3-large` over real pairs rather than from reasoning: the first
  because both editions of La Nausée open on apparatus, the second because a
  second scan of the same book opens on a title page. See the two decision rows.
  The case "only *one* side carries an introduction", owed since the first
  rewrite, has now been measured on three books — Candide (31 published
  paragraphs of Gutenberg notice, Modern Library front matter and Philip
  Littell's introduction), Micromégas (34, Beuchot's publisher's preface and the
  Firmin Didot title pages) and Bovary (5 and 3, both title pages, the dedication
  kept because both editions carry it). Nothing here is owed a model any more.
- **Eleven English paragraphs still carry a footnote through the middle of a
  sentence.** The 1964 Nausea scan interleaves its page-foot notes with the
  prose, so `…I must finally realize 1 Ogier P . . . , who will be often
  mentioned in this journal.` arrives as one paragraph — 11 of 1,313, about 0.8%.
  Deliberately not fixed: the marker is a bare digit with nothing around it, and
  a twelfth candidate found by the same pattern is `Nyam-Nyams, 34 Malgaches`,
  where 34 is a page number. That is exactly the ambiguity `notes.py` refuses to
  guess at, and the standing rule applies — a note left in is untidy, a deleted
  sentence is silent and unrecoverable. The French side of the same book is
  clean, because its notes are bracketed and countable.
- **The deployed site lags main by hand.** As of 2026-08-06 prod
  (`vps-bab9636f.vps.ovh.net`) served engine wheel `02aba59a8` against a local
  `0731760f4`, and a builder page 119 lines behind. Nothing deploys itself; the
  prod bundle is whatever was last copied up. Diagnosing "it's broken on prod"
  starts by fetching `/worker.js` and the wheel it names and diffing them against
  the tree, because half of what looks like a live bug is a fix that never left
  this machine.
- **Now on GitHub.** LICENSE (MIT), CI (GitHub Actions), and CONTRIBUTING notes
  are in place; the repo has a remote (`origin`) and has been pushed, so CI now
  runs on real GitHub.

---

## Layout

```
biread/
  cli.py          argument parsing and everything the user sees printed
  extract/        source file -> raw text
  normalize.py    raw text -> repaired: the injuries an extractor inflicts, and
                  the paragraph breaks a conversion dropped, undone first
  cleanup.py      raw text -> chapters of clean paragraphs
  segment.py      an edition that lost its paragraph breaks -> cut to the shape
                  of the other edition, where there is one
  spacing.py      words an OCR ran together -> put back apart, the model deciding
                  only where the spaces go and never what the characters are
  wikisource.py   two page names -> two editions, resolved and fetched; no I/O
                  of its own, so the CLI reads through requests and the browser
                  through its own fetch
  standardebooks.py  a second library, English only: the translations
                  Wikisource lacks
  shelf.py        the curated books, and what each one honestly claims
  translate.py    paragraphs -> English, batched and cached
  align.py        a published translation -> matched to the French by meaning:
                  through the generated translation as a pivot (the CLI), or
                  directly in a shared embedding space (the web builder)
  anchor.py       vestigial: two editions pinned by the names and numbers they
                  share — the removed surface-token path. Reachable only from
                  tests; kept until it is deleted outright
  build.py        the pipeline shared by the CLI and the in-browser builder;
                  `Draft` is a book made but not glossed, `finish` sets it in
                  type, and the browser runs the pass between them its own way
  gloss.py        per-paragraph hover units; width judged at render, not cache
  language.py     what glossing needs to know about the source language
  render/         book -> one HTML file (templates/ holds the real reader)
  export/         static copies: epub.py (fixed-layout spread), pdf.py (print) — both headless Chromium
                  refit.py reads a finished book back out of its own page, so a
                  format can be made long after the build and without paying twice
  llm/            one thin client per provider
  publish.py      shelf book -> a file ready to hand out, then approved by hand
  formats.py      any finished book -> the same book with its EPUB inside it, for
                  the books a browser built and could not typeset
  check.py        a finished book looked at where books break: opening, middle, end
  cache.py        content-hash JSON cache, merges on write; `on_write` is how a
                  caller with no filesystem (the browser) keeps one anyway
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
pip install -e ".[dev]" && pytest              # ~438 Python tests, no network
pip install -e ".[browser]" && playwright install chromium webkit
pytest tests/test_reader_js.py                 # 58 tests × 2 engines, the reader
pytest tests/test_builder_js.py                # 66 tests × 2 engines, the builder
pytest tests/test_gloss_pool_js.py             # 8 tests × 2 engines, the gloss pool
BIREAD_ENGINES=chromium pytest tests/test_reader_js.py   # one engine, when it must be quick
```

**Both suites run in Chromium and in WebKit**, once each, from one parameterized
`browser` fixture in `tests/conftest.py`. WebKit is there because Safari carries
faults Chromium cannot see: on the `columns: 3` shelf, Safari **broke a card
across the column boundary** in spite of `break-inside: avoid`, and the piece
that began the next column had no top border — so the card read as open at the
top, most visibly under the pointer, where the border brightens. Safari reported
that card's box as 675×710 where Chromium reported 330×356, which is the
fragmentation showing through. A sweep of every width from 1000 to 1920px at
four pixel densities in Chromium saw nothing. An engine that is not installed
skips; `BIREAD_ENGINES` narrows the list. WebKit is roughly six times slower, so
a quick loop is worth narrowing and a merge is not.

`test_a_hovered_card_keeps_the_whole_of_its_frame` guards it, and it is the one
test here that reads **pixels**: the fault was pure paint, and every computed
style was correct throughout. It measures the top edge against the card's own
side edge rather than a fixed brightness, so it holds in both themes and both
engines, and it refuses to pass when the side reads flat too — that is what a
fragmented card looks like from the outside.

The builder's tests serve `web/builder.html` beside `tests/builder_worker_stub.js`,
which answers the worker protocol with canned replies. The page reaches its engine
by a relative `new Worker("worker.js")`, so swapping it needs **no seam in the
page** — what runs is the shipped builder, unmodified, and the suite stays offline
and fast (14s) instead of booting Pyodide from a CDN. A test steers the stub by
what it puts *inside* the uploaded file: text beginning `SCENARIO:` followed by
JSON overrides any reply, so error paths and odd metadata are reachable without a
control the reader could ever meet.

`test_gloss_pool_js.py` drives `web/gloss-pool.js` with a stub in place of both
Pyodide and the network, which is why that file is a script of its own rather
than more of `worker.js`: what is worth testing there is how many requests are in
flight, what a 429 costs, and that a batch nothing anchors in still reaches the
rescue pass, and none of that needs a Python runtime to be wrong.

The Python written *inside* `worker.js` — half the browser's engine lives in JS
string arrays — is compiled by `test_web_build.py`, because a typo there is
invisible until a reader is halfway through paying for a book.

`test_engine_js.py` is the one test that runs the **real** engine: Pyodide, the
wheel, the gloss plan, the pool and the finished book, with the provider
intercepted so it costs nothing. It boots from a CDN and reads `web/dist`, so it
is opt-in and skips by default:

```sh
python web/build.py && BIREAD_ENGINE_SMOKE=1 pytest tests/test_engine_js.py
```

It is what proved the resume: a book built, the page reloaded, the same file
brought back, and the second build asking the provider for **nothing** while
producing a byte-identical file.

The EPUB and PDF export tests also need `[browser]` — the exporters paginate and
print in headless Chromium — and skip themselves without it.

The reader's expensive bugs have all been layout and timing — pagination
measured against a box that was not laid out yet, a drag target destroyed
mid-gesture, a layout mode chosen from a stale width. None are reachable without
a rendering engine. Drive the real thing before believing it works.
