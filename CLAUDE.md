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
- Verbs in **passé simple** also show the **passé composé**.
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
| Must a published book carry glosses to go out? | **No — glossing is optional at publication, and a reader may buy it.** Glossing costs about four times translating, so requiring it would have kept Candide off the shelf over 28 cents. A book published without glosses says so on its card and offers them: **Add glosses** in the reader's header glosses *the page in front of you*, on the **reader's own key**, one call for the page rather than one per paragraph. The card states the fact in two words (*no glosses*) and makes no offer: the sentence that did, price and all, ran to two lines on seven cards of eight and put the rule inside each card at a different height from its neighbours'. The offer is met in the reader, where the header carries it and the reader is the one about to want it. A bought gloss is a private local override kept by paragraph hash, exactly as a correction is. |
| Reader-side glossing — how does it not drift from the Python? | **The algorithms are written twice; the French is written once.** `gloss.protocol()` hands the reader the prompt, the field separator, the fold map, the closed class, the coordinators, the prepositions and the perfect auxiliaries, and the book carries them — so a word added to `language.py` reaches the reader in the next build rather than in a second edit to a second language. `tests/test_gloss_parity.py` lifts `fold`/`parseUnits`/`anchorUnits`/`displayableUnits` **out of the shipped reader.js** and runs them beside `gloss.py` on the same paragraphs: curly apostrophes, an ellipsis folding one character into three, an over-broad noun-of-noun, a perfect that only echoes its surface, and a reply that will not anchor at all. The safety argument is unchanged: what the model returns is a *proposal*, only offsets are kept, and a model that rewrites a word cannot put its version on the page. |
| A published book carries the reader it was built with — how does it not go stale? | **It is re-set in today's reader when the bundle is assembled.** `render.rewrap` lifts a finished book's text out and renders it in the current templates, carrying paragraphs, offsets, alignment and any embedded EPUB or PDF across untouched. Found by shipping it: Candide could not offer glosses because the code that offers them did not exist on the day it was built, and Micromégas was handing out a reader a fortnight behind the repository. The UI labels are refreshed too — they belong to the reader, not the book, and an old book in a new reader shows blanks wherever a control has been added since. |
| Can a reader have a book without building it? | **Where somebody approved one, yes.** A card offers a finished book as a download only if it was built, read and **approved** here — a book going out under biread's name is something a person decided, not something that happened to align. Every other card is untouched: tap it and build the book yourself, on your own key or your own machine. What the card *claims* is measured off the file by `web/build.py` (`measure`), never declared, so replacing a build updates the card and cannot drift from it; only the English edition inside and the approval date are stated by hand, because no file can say either about itself. A slug that names no shelf book, or a file that is not there, stops the build rather than shipping a promise that 404s. `BOOKS_AT` is where the finished books are served from — empty today, meaning beside the builder; one absolute URL the day there is a server. |
| What does a shelf card do when you press it? | **The card is the button.** Where a finished book stands behind it, pressing the card takes that file; where none does, pressing it builds one — and either way the card ends with the line that names what it does, arrowed, so it reads as pressable without a pointer a touchscreen never sends. The filled *Ready to read* pill inside the card is gone: it was a second target on a surface that was already one, and a reader had to guess which of the two to press. Building your own drops to a small underlined line under a finished book. What the card *says* was cut with it — the description of the file is a middot line rather than a sentence, the caveats are one line, and everything else (what nobody has read, which English, how loosely the two pair) waits until a build is actually being chosen, where it is about to matter. Cards came down from 326–463px to 267–380px, and to 327 flat once the description became one line. |
| What is the book *about*? | **The card opens on it under the pointer.** A summary is the first thing a reader wants and the last thing the card had room for, so it lives in a drawer that slides out of the card's foot and over the row beneath — the shelf itself never moves, which is the whole point of the two fixes above it. Written per book in `shelf.py` beside the rest of the record, not fetched: a curated shelf is one somebody has read, and an encyclopaedia's opening line is as often about an edition's publication history as about the story. A book taken from the lookup screen carries none and its card simply does not open. Pointer only (`hover: hover`) — on a touchscreen a drawer would stay open on whatever was last tapped. |
| Does hosting those books make biread a host? | **No — it is the opposite question.** "Not a host" is about *readers' own editions*, where someone else owns the text and a takedown would follow. The books on the shelf are out of copyright on the original side and carry either the wiki's public-domain translation or one biread generated itself, so nobody else has a claim on either half. Holding a reader's uploaded PDF is still refused; publishing a book we made from public-domain sources is simply publishing. |
| Can a reader put a book of their own on the shelf? | **A book they *found*, yes; a book they *own*, no.** A find on the lookup screen is two Wikisource page names — the shelf's whole currency — so a checkbox, **off by default**, keeps it: saved in this browser, shown among the cards next visit under *Kept by you*, and taken off again from the card. The align route gets no such control, because an uploaded PDF has nothing shareable in it: passing it on would mean holding the text, which is the one thing biread does not do. "Shared with other readers" in the literal sense — one list everyone sees — waits on the parked server and on someone to moderate it. |
| A book that arrives with no paragraph breaks? | **Repaired where anything is left to read, refused by name where nothing is.** A reader's Word file — a PDF saved as .docx — came in as **one** paragraph of 411,928 characters, and biread blamed PDFs for it and pointed at an EPUB the reader did not have. Two fixes, both about telling the truth. The break-rescue in `normalize.py` was gated to PDFs on the grounds that any other format means what it omits; that holds for a file that omits *some* blank lines and not for one that came apart nowhere, so it now also runs wherever the median block is longer than any prose is set in (`_never_broke`, 2,000 characters). Verified inert on the corpus — every example EPUB and text reports `never_broke=False`, so not one of them parses differently — and it recovers a flattened `.txt` in full. Where even the lines are gone, as in that .docx, the refusal names **the reader's own file**, says it arrived as one unbroken block, and names the format that lost the marks and the file to bring instead. The card that had sat on *Reading…* under the refusal now says *Couldn't be read*, because a page must not contradict itself. Deliberately **not** built: reconstructing paragraphs out of a blob by sentence and dialogue shape. It would make any file build, and the paragraphing on the page would be ours rather than the author's. *(Superseded in one case, and only one — where a second edition is in play, its paragraphing can be borrowed. See the row below.)* |
| One edition has its paragraph breaks and the other has none? | **The flat one is cut to the other's shape.** This is the case the refusal above could not see, because it judged each file alone: a reader bringing two editions has, in the good one, a real publisher's account of how the book divides — how many paragraphs the passage runs to and how long each is. That is not ours and not a guess, so borrowing it is not the invention the row above refuses. `segment.py` splits the flat side into sentences and places each break at the piece nearest where the counterpart's own paragraph ends, as a share of the whole. **Free, instant, no model.** Measured over the body — what is actually rendered, front matter being trimmed before a reader sees a page — by flattening real books and cutting them back: **98%** of Bovary's paragraphs come back whole in both languages, **99%** of Candide's published PDF, **100%** of Micromégas. Against ceilings of 99–100%, so what is lost is now almost entirely what *cannot* be found. Three arithmetic bugs cost two thirds of a book each and passed every small example — breaks poured rather than placed absolutely (3%), positions counted without the joining space (21%), a break landing exactly on a sentence end counted as inside it (40%) — which is why the test measures a whole book and not a fixture. Runs on every route, and says so: on the terminal, and in the ⓘ panel, because a page whose paragraphing came off the other edition must admit it. |
| A paragraph that ends without a full stop? | **Found where speech opens, which is nearly all of them.** Cutting only at sentence ends left a ceiling of ~89%: a line introducing speech closes on a colon or a dash, and no sentence ends there. Those are **96%** of what English Bovary could not recover and **91%** of the French. `SPEECH_RE` takes the break where a line *introducing* speech (`:` `;` `—` or a closing quotation) is followed by the mark that *opens* it (`—` `«` `“`). Both halves are required, which is what makes it corroboration and not shape — a dash alone is a French parenthesis. The two-language detail that matters: English sets `“Monsieur` with no gap and French sets `— Monsieur` with one, and a pattern demanding the word immediately fired on every English break and no French one, 98% against 79% of the same novel. A related fix in `_sentences`: French closes a quotation `. »` with a space before the guillemet, which the splitter did not allow for — Micromégas went from 53% to 100% on that alone. Extra candidates are close to free, because the cut takes the one *nearest* the position it wants; being generous costs nothing and being wrong costs a break, not a word. |
| A flat book with no second edition at all? | **The model is asked, and asked in the safest form there is.** Last resort, reached only where nothing free could work — `segment_like` is exact and costs nothing, so it always goes first. The text is cut into sentences, the model is shown them *numbered*, and it answers with the numbers that begin a paragraph. It therefore cannot rewrite a word even in principle: the same reasoning as glossing, one step further, where the model's text is thrown away after anchoring — here it never has any. A reply that is nonsense costs a badly placed break, never a sentence of Voltaire, and a window whose call fails is left unbroken while the rest of the book comes back. About a third of what translating the same book costs — **$0.06** on Balanced, $0.32 on Haiku, $0.96 on Sonnet for a book of Bovary's size. |
| A book that numbers no chapters at all? | **Left as one section, because ascending is not a spine.** Nausea is a diary, and the bare-numeral pass read four chapters into it: the page numbers 99 and 146, and two lines reading `one.` — the tail of a sentence the PDF had wrapped alone onto a line. 1, 99, 146, 1 ascends, and ascending was the whole test. What that cost was not the headings but `trim_matter`, which dropped the 411 paragraphs standing before the first of them as front matter: a third of the book, deleted in silence, and differently on each side, so the reader opened on prose facing *nothing in this edition answers to it*. Three conditions now. A run must step by one oftener than not, since chapters are numbered without gaps — not always, because an extractor that loses one heading would otherwise break a real spine in two. A bare heading written in letters must be capitalized, since `One.` heads a chapter and `one.` ends a sentence and both read as 1. And under both of them, trimming refuses to drop a leading section worth more than a quarter of the file, because a title page and an introduction are small beside the book: the cost of falling back is an introduction left in and unmatched, and the cost of not is the book. Measured inert on every example — Bovary, Candide and Micromégas come out with the same chapters, numbers and paragraph counts on both sides. Bovary's published edition is what keeps the capitalization rule honest: Eleanor Marx heads her chapters *One*, *Two*, *Three*, bare and spelled out, and they are found exactly as before. |

| One edition opens on an introduction and the other on the book? | **Cut, because the other edition says where the book begins.** Not a tidiness question: `_embedding_pivot` must place *every* published paragraph somewhere, so an introduction only one side carries is not left unmatched — it is poured over the opening pages. `trim_matter` cuts to the first numbered chapter, which is the right answer and no answer at all for a book that numbers nothing; Nausea is a diary, and thirty-one paragraphs of a critic's essay and an editors' note sat in front of it with nothing in the file to mark their end. `align.open_together` embeds each edition's own first page, finds where it lands in the other's opening stretch, and drops whatever stands in front of it — both directions, since either side may be the one carrying it, and neither where the two matches contradict each other. Bounded twice: only the first sixty paragraphs are searched, and the drop is held to the same quarter of the file trimming allows front matter, because one confident wrong match would otherwise take a short book whole. Runs before `recut` — a flat edition cut to a counterpart that still carries an introduction is cut wrong by the whole length of it — and in `sample_align`, so the page shown before paying is page one. Measured on the pair that prompted it: 31 dropped from the published side, 0 from the original, both editions opening on the same sentence and lining up paragraph for paragraph. Inert on Bovary and Micromégas; on Candide it takes seven paragraphs of Gutenberg notice and Modern Library title page, which is right. The align route only — the CLI's pivot path has chapter numbering and is untouched. |

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

- **All eight shelf books are built, and none but Micromégas is glossed.**
  Micromégas (34 paragraphs, glossed throughout, the published column beside
  ours, EPUB and PDF inside), Candide (98.9%), Bovary (87%), Eighty Days (79%),
  20,000 Leagues (58.8%), Salammbô (90%), Notre-Dame (86%) and Les Misérables
  (92%, 12,208 paragraphs — the largest by three times). A reader adds glosses as
  they read, on their own key. What the shelf is short of now is *glosses* and
  more titles, not builds.
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
  wrong in, and it will matter on a long book. `GlossRun.rescued` already counts
  the retries, so the signal to fold in is there when it is worth doing.
- **An embedding run is priced only when OpenRouter lists the model.** The align
  route's cost gate shows a dollar figure when the rate is known and an honest
  token count when it is not, rather than a plausible cent.
- **`open_together` has never met a real embedding model.** The rule that drops a
  one-sided introduction was measured with a bag-of-words embedder, which is a
  fair stand-in on same-language text (the pair that prompted it is one English
  translation in two files) and no stand-in at all cross-lingual. Its fixtures
  use the concept embedder, which proves the wiring. What is owed is one run on
  a French/English pair with a real multilingual model, watching what it drops.
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
  build.py        the pipeline shared by the CLI and the in-browser builder
  gloss.py        per-paragraph hover units; width judged at render, not cache
  language.py     what glossing needs to know about the source language
  render/         book -> one HTML file (templates/ holds the real reader)
  export/         static copies: epub.py (fixed-layout spread), pdf.py (print) — both headless Chromium
  llm/            one thin client per provider
  publish.py      shelf book -> a file ready to hand out, then approved by hand
  check.py        a finished book looked at where books break: opening, middle, end
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
pip install -e ".[dev]" && pytest              # ~438 Python tests, no network
pip install -e ".[browser]" && playwright install chromium webkit
pytest tests/test_reader_js.py                 # 58 tests × 2 engines, the reader
pytest tests/test_builder_js.py                # 63 tests × 2 engines, the builder
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

The EPUB and PDF export tests also need `[browser]` — the exporters paginate and
print in headless Chromium — and skip themselves without it.

The reader's expensive bugs have all been layout and timing — pagination
measured against a box that was not laid out yet, a drag target destroyed
mid-gesture, a layout mode chosen from a stale width. None are reachable without
a rendering engine. Drive the real thing before believing it works.
