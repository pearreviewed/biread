# accounts — a synced shelf that never holds the book

**Status: design note, unbuilt.** This is the top rung of the sync ladder in
[`revise-spec.md`](revise-spec.md) — *link now → a sync code → sign-in accounts*.
It is written down so that when accounts are built they extend the shape already
in place (source-hash-keyed overrides) rather than inventing a new one, and so the
copyright posture in [`CLAUDE.md`](../CLAUDE.md) survives contact with a login.

---

## The rule

**Save the bookmark, not the book.** Everything about a reader's *relationship* to
a book — where they are, the fixes they have made, what is on the shelf — is tiny,
non-infringing, and safe to keep. The book itself is the one thing the server never
holds.

This is not only privacy hygiene; it is the line that keeps biread a *tool* and not
a *host*. Translation runs in the reader's browser on the reader's own key, the
finished edition is the reader's own file, and the account stores only references
to books. Cross a login over that line — store the text, or the publisher's jacket —
and biread becomes a host of derivative works of copyrighted books, with the
safe-harbor obligations that follow. So the account is a **shelf of references, not
a shelf of books.**

---

## The record

One account, one shelf, one entry per book. The shape is identical for both modes
below; mode B adds a single field.

```
Account
  user          auth only; the LLM key never leaves the browser
  cloud         (mode B only) which cloud the reader connected, if any

  shelf[]       one entry per book —
    book_id     hash of the source file   <- the join key, NOT the book
    title       for the shelf list
    author      for the shelf list
    spine       cover generated from title + author — never the real jacket
    lang        which edition (english, …)
    position    a paragraph anchor + fraction — "where you are"
    edits[]     the reader's fixes, each keyed to a paragraph hash
    updated_at  for sorting, and for resolving two devices
    file_ref    (mode B only) a pointer into the reader's OWN cloud: { drive, file_id }
```

Every field is about the reader and the book. None of them *is* the book.

**Position is a content anchor, not a page number.** The book re-paginates to each
screen, so a raw spread index means a different place on a different device. The
anchor is the paragraph's source hash plus how far through it the reader was — the
same fraction-through-a-paragraph the pagination already computes to break a long
paragraph across pages. "Where you were" then survives the jump to a phone.

---

## Mode A — re-open locally (the default, zero setup)

1. The reader signs in on a new device. The shelf loads: covers, titles, "34%",
   "3 fixes." No books yet — these are references.
2. They tap a book → *"Open your copy to continue"* (file picker / drop).
3. They drop the file; the browser hashes it.
4. The hash matches the shelf entry → jump to the anchor, apply the fixes. Reading
   resumes exactly where it left off. Nothing was uploaded.
   - Mismatch → *"That's a different file — start it fresh, or find the right one?"*
5. Position and any new fixes sync up (a few hundred bytes). The book stays on the
   device.

The cost, stated plainly: the file has to be *on* that device. This is the floor —
it works for everyone with no permissions — and the pinch is the phone whose book
is on the laptop.

---

## Mode B — the reader's own cloud (seamless, opt-in)

A one-time connection turns the pinch off without moving the book to biread.

0. Once: *"Sync my library"* → the reader connects their Drive / Dropbox / iCloud at
   **app-folder scope** (biread sees only the files it put there, never the rest of
   the reader's cloud). From then on, opening a book tucks the file into that folder
   and fills in `file_ref`.
1. The reader signs in on a new device. The shelf loads.
2. They tap a book → biread pulls the file **straight from their cloud into the
   browser**, checks the hash, restores position and fixes. No re-dropping.
3. The bytes travel **browser ↔ the reader's cloud** — never through biread's
   server, which still holds only the pointer, the bookmark, and the fixes. Still
   not a host.

A and B are not a choice. A is the floor; B is an upgrade that reuses the same shelf
plus one field and an OAuth grant.

---

## Two things to get right

Both fall out of the source-hash keying that `--revise` already uses.

- **Two devices at once.** Position is last-write-wins by `updated_at`. Fixes
  **merge per paragraph** — different paragraphs union, the same paragraph is
  last-write-wins — because every fix is keyed to its own paragraph hash. No bespoke
  conflict logic.
- **The cloud token (mode B only)** is the single sensitive thing stored: minimal
  app-folder scope, encrypted at rest, revocable. That is the whole care list.

---

## Chosen in chat

| Question | Decision |
|---|---|
| Does the server ever store the book? | **No — never.** Bookmark, fixes, and light metadata only. |
| Translate server-side? | **No** — in the reader's browser, on the reader's own key. |
| A DMCA takedown agent? | **Avoided by not hosting the books.** Only needed if the server holds them. |
| How does the file return on a new device? | **A** (re-open locally, default) and **B** (the reader's own cloud, opt-in). |
| Store an encrypted blob on our server? | **Rejected** — encrypted or not, the bytes still rest on the server; that is still hosting. |
| Cover image? | A **generated spine** from title + author. Never the publisher's jacket (itself copyrighted). |

---

## Open decisions

- **Which cloud(s) for mode B**, and whether the file save is browser-direct or
  orchestrated through the reader's token. Browser-direct keeps the bytes off biread
  entirely and is preferred.
- **Metadata reach on the shelf** — title and author are facts and safe; a
  reader-set nickname and tags are theirs. No blurb or description copied from a
  source.
- Ties into the parked server work in [`revise-spec.md`](revise-spec.md): if a
  backend is ever built for edits sync, this shelf is the same backend, one rung up.
