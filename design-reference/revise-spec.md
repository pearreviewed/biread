# revise — reader-side correction of the AI translation

**Status: local mode built and tested; server mode is phase 2 (unbuilt).** This
spec covers *both* delivery shapes, as requested: a serverless local mode, now
implemented, and a server-backed mode that remains a separate project. Where a
decision is still open it is listed under [Open decisions](#open-decisions).

**What shipped (local mode):** `--revise` embeds the provider, model, target,
endpoint, and wire style, plus each body pair's source hash; the reader adds the
`generatedEnglish()` accessor (feeding both painting and measurement), selection
→ offset mapping, splice, the local override store with the stale-safe base
check, one-click revert, the floating control (manual **Edit** + key-based
**Regenerate** with a "what's wrong" note), a browser client per wire style
(Anthropic / OpenAI-compatible / Ollama), and the key panel (remember-on-device
default, session fallback, one-click forget), plus an **edits link** that carries a
reader's corrections to another browser in its own `#e=` fragment — a separate link
from the page-share so private edits never ride a shared page, imported and stripped
on open (a `file://` link reaches other browsers on the same machine; a hosted book's
link travels anywhere). All strings run through
`targets.py` in the five shipped languages. Covered by Python tests (config +
hashes embedded only with the flag; plain builds stay URL-free) and Playwright
tests (manual edit persists + reverts, regenerate calls only the provider endpoint
with the reader's key, no cost/token figures anywhere, a correction reflows the
page without clipping; an edits link carries corrections to a fresh browser and never
rides the page link). Full suite: 280 passing.

The edits link is the no-server rung of the sync ladder (link now → a "sync code" when
any backend is on the table → sign-in accounts for automatic cross-device sync, still
parked). The same correction bundle flows through all three, so nothing here is throwaway.

---

## The problem

The reading experience is the whole point — biread is read by people who care
about the prose. The generated English is usually good, but occasionally a phrase
lands wrong — "got wind of it" where the French wants "caught wind of it" — and
one false phrase pulls a careful reader out of the book. A reader should be able
to select that phrase, say what's off, and get it fixed, or just type the fix
themselves. **The person who built the book must never pay for this.** A
correction is an LLM call, and the shipped reader is one static file with no
backend, so the spend can only land on the *reader's* own key.

Chosen in chat before this spec:

| Question | Decision |
|---|---|
| What does a fix change? | **Only the selected span.** Nothing is regenerated automatically — the reader selects, a control appears with a "what's wrong" note field and a button, and only then does it run. |
| Manual edits too? | **Yes.** The reader can also hand-type the fix — no key, no cost. Same storage as a regenerated fix. |
| Whose key? | The **reader's own**, never the builder's. |
| Where does the key live? | **Remembered on the reader's device by default** (one-click forget), with a session-only option and, optionally, server-backed. See [Key handling](#key-handling). |
| Cost shown in the UI? | **Never** — the standing rule holds. No tokens, prices, or estimates anywhere. |

---

## Architecture: one seam, two back ends

Everything above the actual API call is identical in both modes: selecting a
span, mapping it to paragraph offsets, prompting, splicing the result back,
storing the override, and re-paginating. Only *where the key lives and who makes
the call* differs. So the reader defines one interface:

```
Reviser.revise({ paragraphFr, paragraphEn, span:[start,end], note }) -> Promise<string>
```

returning the revised span text. Two implementations satisfy it:

- **`LocalReviser`** — calls the provider directly from the browser with the
  reader's in-browser key.
- **`ServerReviser`** — calls the builder's service, which holds the key and
  makes the call.

The UI, offset mapping, splice, override store, and repagination sit *above* this
seam and never change. This is what makes "both options" cheap on the reader
side: the server is the only separable, heavy piece, and it drops in without
reworking the reader.

---

## Local mode (serverless) — ships first

### Build changes

- **New opt-in flag, off by default: `--revise`.** A book built without it
  carries no revise config and no key field — exactly as `--gloss` works today. Only core body paragraphs are correctable;
  titles, chapter headings, and any apparatus are excluded, matching the gloss
  boundary.
- The build embeds, into the existing `#book-data` JSON:
  ```
  "revise": { "enabled": true, "provider": "anthropic", "model": "claude-sonnet-4-6" }
  ```
  provider and model come straight from the same `Config` that produced the
  translation, so a regeneration speaks in the same voice as the book.
- **Each pair gains its source hash**, `pairs[i].h` — the same
  `hash_text(french)` the build cache is keyed by ([translate.py:73](../biread/translate.py)).
  A few KB across a book, and it buys override stability across rebuilds (below).

### The flow

1. The reader selects text inside the **AI-translation column only** (the right
   page; the French left page is the source and carries the hover glosses, which
   are untouched). Selection in the published column or the French does nothing.
2. A small floating control appears by the selection — positioned the way the
   gloss tooltip already is ([reader.js:759](../biread/render/templates/reader.js)) — offering
   two co-equal ways to fix the span:
   - **Edit manually** — turn the span into an editable field and type the fix.
     No key, no call. This path always works, with or without a key set.
   - **Regenerate** — run the `Reviser` with an optional one-line **"what's
     wrong"** note. Needs a key.
3. On regenerate, the `Reviser` is called with the whole paragraph (French *and*
   current English) plus the selected span and the note. The French source is
   included deliberately: it is the ground truth that tells the model "caught
   wind" is right, not a guess.
4. The returned span is spliced into the full paragraph text, stored as a local
   override, and the page **re-paginates** (see below).
5. A corrected paragraph shows a quiet revert affordance to restore the original.

### Selection → offsets, and splicing

A paragraph can be split across spreads: the DOM `<p>` holds a *slice*
`textSpan(englishText(p), from, to)`, not the whole paragraph
([reader.js:321](../biread/render/templates/reader.js)). So a selection must be mapped back to
character offsets in the *full* paragraph text before it can be stored:

- the node knows its `pair` index and the `[from, to]` fraction it renders;
- the slice's base offset in the full text is `sliceAt(fullText, from)`, the same
  function pagination uses;
- selection offsets within the node add onto that base.

A selection that straddles a page break is clamped to the visible slice (or
refused), mirroring how a gloss unit that straddles a break is rendered as plain
text ([reader.js:281](../biread/render/templates/reader.js)). The override stores the full
corrected paragraph, not the fragment, so it is independent of where the break
happened to fall when the fix was made.

### Override storage

Reuse the existing namespaced store (`lsGet`/`lsSet`, keyed by `DATA.slug`).
Overrides live under their own key so older readers ignore them:

```
biread:<slug>:overrides = {
  v: <version>,
  byHash: {
    "<sourceHash>": { base: "<english this was derived from>", text: "<corrected english>" }
  }
}
```

Keyed by **source hash**, not pair index, so a rebuild that leaves the paragraph's
source unchanged keeps the fix even if other paragraphs shifted. `base` records
the English the correction was made against; the override applies **only while
the current generated English still equals `base`.** If a later build retranslates
that paragraph, `base` no longer matches and the stale override is quietly
ignored rather than pasted onto different prose. Corrections attach to the
**generated** column only — never the published one.

### Pagination — the part that will bite if ignored

Pagination measures `PAIRS[i].en` directly in `measurementColumns`
([reader.js:354](../biread/render/templates/reader.js)); it deliberately does not measure the
published column. A correction changes that text's height, so:

- Route the generated English through a single accessor,
  `generatedEnglish(i)` = override-or-`PAIRS[i].en`, and use it in **both**
  `englishText` (for painting) **and** the measurement column's `en` reader.
  Miss the second and pages overflow or under-fill silently.
- On applying or reverting an override, call `repaginate(currentPosition())`
  so the reader keeps their exact place inside the paragraph while the book
  reflows ([reader.js:578](../biread/render/templates/reader.js)).
- **Scope every new selector and listener to `#stage-wrap` / `overlay-root`.**
  The offscreen measurement twin in `#measure-host` carries the same `.pair-en`
  classes; a global handler would fire against the probe. This is the reader's
  oldest class of bug and the spec calls it out on purpose.

### Provider browser client

The reader gains a small `fetch`-based client for the build's provider only. The
key is sent to **the provider's official endpoint and nowhere else**:

| Provider | Endpoint | Notes |
|---|---|---|
| anthropic | `POST api.anthropic.com/v1/messages` | needs `anthropic-dangerous-direct-browser-access: true` + `x-api-key` + `anthropic-version` |
| openai | `POST api.openai.com/v1/chat/completions` | `Authorization: Bearer`; CORS-allowed from browsers |
| openrouter | `POST openrouter.ai/api/v1/chat/completions` | browser calls supported |
| ollama | `POST localhost:11434/api/chat` | **no key** — the free path; requires the reader to set `OLLAMA_ORIGINS` to allow the page origin |

Exact headers, `anthropic-version`, and current model ids will be confirmed
against the API docs (via the `claude-api` skill) at build time, not from memory.
If a book was built with a provider that cannot be reached from the browser, the
reader degrades to **manual-edit-only** rather than showing a dead button.

### Key handling

- **Local, remember on this device (default):** the key is persisted in
  `localStorage` with a one-click **forget**, so the reader doesn't re-paste on
  each visit.
- **Local, session-only (option):** the key lives in the tab and is cleared when
  it closes — offered for a shared machine.
- **Server-backed (if the book embeds a server):** see the next section.

Manual editing needs no key at all, so a reader who never sets one still gets the
whole hand-typed correction path.

The key-entry panel reuses the `info-panel` idiom
([reader.js:1435](../biread/render/templates/reader.js)) and states plainly where the key
goes. No numbers, ever.

### Copy (locked — spare & warm)

English strings below; every one goes through the `Target.ui` table in
[targets.py](../biread/targets.py) with a `data-i18n` key, so other languages get
their own equivalents and the feature is localized like the rest of the reader.
`{provider}` is filled at build with the book's provider name.

- **Control** — manual button `Edit`, regenerate button `Regenerate`, note field
  placeholder `What's off? (optional)`. Pressing `Regenerate` with no key set opens
  the key panel rather than erroring.
- **Key panel** — title `Your key, your edits`; body *"Paste a key and the reader
  can rewrite a phrase that lands wrong — on your key, never ours. It stays on
  this device and talks only to {provider}. Forget it anytime. Or just type the
  fix yourself."*; key-field placeholder `Your {provider} key`; remember toggle
  `Remember on this device` (on by default); action `Forget key`.
- **Error** — `Couldn't reach the model. Check your key, or type the fix by hand.`
- **Model unreachable from the browser** — `This book's model can't be reached
  from the browser — you can still edit by hand.`
- **Revert** — `Undo`.

Server-mode strings (sign-in, saved key) are drafted when phase 2 is built.

### Failure and edge behaviour

- Network / auth / rate-limit errors surface as a quiet inline message ("couldn't
  reach the model — check your key"), never a number.
- While **blur** is on, correction is offered only on the revealed active
  paragraph.
- Mobile: manual edit works; live regeneration follows the same 640px reasoning
  as glossing (a phone gets manual edit, not necessarily the hover-driven
  control).

---

## Server-backed mode — a separate project

Offered so a reader's key can live off their device. It buys cross-device
convenience; it does **not** make the reader's key safer, and it turns biread
from a shareable file into a hosted service. Presented in full so the commitment
is legible.

### What it is

- **Auth: email magic-link** — chosen as the easiest for the reader: no password,
  no OAuth consent screen. Readers still need an identity to attach a stored key
  to, so this is a real auth system, just the lightest one.
- **Encrypted key store** — each reader's provider key, encrypted at rest
  (envelope encryption; master key in a secrets manager, never in the repo). This
  is the liability centre: a breach leaks other people's LLM keys.
- **Proxy endpoint** — `POST /revise`, authenticated. Body carries
  `{ bookSlug, sourceHash, paragraphFr, paragraphEn, span, note }`; the server
  decrypts the reader's key, calls the provider, returns `{ revised }`, and
  **never** returns the key. Per-reader rate limiting.
- **The build embeds** an optional `revise.serverBase` URL; when present, the
  reader offers server mode and calls `serverBase/revise` with its session.

### The caveat that constrains it

A downloaded file opened as `file://` has a **null origin** — cookies and CORS
against a real server are effectively unusable. So server mode realistically
requires the **book to be web-hosted at an http(s) origin**, not opened locally.
That breaks the "one file you open from your desktop" identity for this mode. It
must be stated to any builder who turns it on.

### Obligations

Encryption at rest, never logging keys, scoped/expiring sessions, rate limits,
key deletion on request, rotation, and breach disclosure. Hosting, a database,
TLS, and monitoring are ongoing. This is custodianship of other people's secrets,
run like a service.

### Why phase 2

It is several times the size of local mode, is an ongoing operational and legal
commitment, and forces web-hosting. Local mode already delivers the entire
*reading* win. Build local first behind the seam; take on the server
deliberately, if and when reader accounts are a goal in their own right. I can
scaffold and document the service, but I cannot host or operate it, and the repo
has no remote yet.

---

## Tests

**Local mode is fully testable here.**

Python (no network):
- `--revise` embeds `revise` config and per-pair `h`; absent without the flag.
- Provider/model in the embedded config match the build `Config`.

Browser (Playwright, provider `fetch` **mocked** — no real key, no spend):
- Manual edit applies, persists across reload, reverts, and re-paginates (page
  count and overflow stay sane).
- Span selection maps to correct full-paragraph offsets; splice is correct across
  a page break.
- Regeneration path: mocked provider returns a revised span → splice →
  repaginate. Assert the key is sent **only** to the mocked provider endpoint and
  appears in no other request.
- No cost/number text renders anywhere.
- New listeners do not fire against the `#measure-host` probe twin.

**Server mode** cannot be exercised in this environment (no hosting). Its test
plan — auth, encrypt/decrypt round-trip, proxy never leaks the key, rate limits,
CORS to the book origin — is documented for when it is built.

---

## Open decisions

Resolved in chat: flag is **`--revise`**; the local key **remembers on the
reader's device by default** (one-click forget), with session-only and
server-backed as the other choices; server auth (phase 2) is **email magic-link**;
**manual correction stays** as a co-equal, key-free path; copy voice is
**spare & warm** (locked strings above).

**Nothing open — every design decision is resolved.** Local mode is ready to
build; the server remains a deliberate phase 2.

## Risks and honest limits

- Direct-from-browser API calls expose the key to the page's own JS. A biread
  file is self-contained and offline and will only ever send the key to the
  provider — but a reader who received the file from someone untrusted is
  extending trust to it. Session-only default and one-click forget mitigate; they
  do not erase this.
- Ollama's local path needs the reader to set `OLLAMA_ORIGINS`, a config step
  outside the reader.
- Server mode's null-origin constraint means it is not a drop-in for locally
  opened files.
