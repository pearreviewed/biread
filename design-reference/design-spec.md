# Bilingual Book Reader — Requirements

Single Design Component: `Bilingual Reader.dc.html`. A paginated French↔English
language-learning book reader. Placeholder prose is original (not from a real book).

## Layout & pagination
- Open-book spread: **left page French, right page matching English**. Below 820px,
  drop the spread → one stacked, swipeable column (French paragraph then its English).
- **Pair/unit-based pagination measured at runtime.** Fill a page with paragraph units
  until overflow, push remainder to the next spread. Never split a pair's alignment.
  A paragraph MAY continue across pages (sentence-level split), aligned FR/EN.
- Recompute on resize and on font-size change (A− / A+). Never break by fixed line count.
- **Every paragraph that starts a page is indented** (tab), including the chapter opener
  and any paragraph beginning at the top of a page. Only mid-paragraph continuations were
  formerly flush — current rule: always indent page-starting paragraphs.
- Page numbers: **French pages only**, numbered 1, 2, 3… (one per spread), lower-left,
  sitting in a clean band below the text (~21px), clear of text at any zoom.
- Book aligned to the top of its area, close under the header.
- Chapter heading mirrored on BOTH pages (FR: "Chapitre premier / La maison au bord du
  fleuve"; EN: "Chapter one / The House by the River"), small gap below it (~14px).
- Tight within-paragraph line-height (~1.38); modest paragraph spacing (~0.34em).

## Page-turn animation
- Click right half / → / Space / swipe-left → next; left half / ← / swipe-right → prev.
- CSS-3D turn on the spine axis (transform-origin at gutter), ~550–580ms ease-in-out,
  moving light/shadow gradient reads as a gentle curved surface (not too pronounced),
  upright (non-mirrored) backface. Not interruptible mid-flight (queue/ignore input).
- **prefers-reduced-motion:** disable turn, cross-fade instead.
- Gutter: soft wide gradient with a THIN, light dark line exactly at center.

## Word interaction (French only)
- Every French word (and the French chapter title) is hoverable/focusable.
- Tooltip shows: the word/word-combo, part of speech (italic), and English gloss.
- **Function words merge into the following content word** as one hover target
  (articles, prepositions, pronouns, etc.) — e.g. "Sur la table".
- **Gloss is contextual for the whole phrase** ("Sur la table" → "on the table").
- **"from <infinitive>" line shows ONLY for verbs**, never nouns/others.
- **Verbs in passé simple also show a "passé composé:" line** with the rewritten form
  (correct être-auxiliary + agreement, e.g. monta → est montée; s'assit → s'est assise).
- Flip tooltip below when no room above; tap toggles/pins on touch; Escape dismisses.

## Translation-source control (header, beside Blur)
- Segmented **Translation | Published**. Translation selected by default.
- **Published disabled by default**: dimmed, `aria-disabled="true"`, not tab-focusable,
  no hover. A focusable circled "i" button beside it stays clickable while disabled.
- "i" opens a quiet dark panel in the tooltip's visual language. Copy (laconic):
  translation is generated for accuracy not artistry; bring a published one you love and
  read side by side; then the command `python biread.py french.txt --published english.txt`;
  and a line that your text stays on your machine, never in shared files.
- Panel dismisses on Escape, outside click, or × close. Full-width-with-margins on mobile.
- When published is available (prop `publishedAvailable`), the segment activates and
  switching **cross-fades the right page's text** — no layout shift, no effect on the
  French page or its hover behaviour.

## Blur toggle
- Header toggle labelled **Blur translation / Show translation**.
- Everything on the English side starts blurred; hovering a pair reveals only that pair,
  and moving the cursor away **re-blurs it** (no stuck-revealed paragraph). Works on
  desktop and mobile.

## Look / palette
- Warm paper pages on a dark desk; drop shadow under the book.
- **No ornaments / fleurons / vines / stains anywhere** (all rejected — do not add).
- Paper: light warm off-white center (rosy-cream, NOT yellow), with only the very outer
  edge easing into a subtle coffee-brown gradient. Keep it light; low center↔edge contrast.
- Very faint, sparse grain texture (`assets/paper-grain.png`) — barely visible.
- Serif body (EB Garamond), generous margins, printed-book feel. No bright accents.
- Active-pair warm tint and per-paragraph hover highlight were REMOVED — only the
  word/word-combo highlights on hover.

## Notes
- Runtime file `support.js` occasionally 404s and the page shows raw `{{ }}` holes;
  fix = regenerate via a DC edit and hard-reload the tab. Not a code bug.

## Navigation & session features
- **Chapters:** `CHAPTERS` array (pair-index + FR/EN eyebrow+title). Each chapter is
  forced to START a new spread; its heading renders mirrored at that page's top and
  pagination reserves the heading height. Currently 3 chapters (pairs 0 / 14 / 20).
- **Progress scrubber:** thin ink track in the bottom margin band of the spread,
  draggable (pointer). Dragging jumps live; hovering shows a dark bubble with
  "p. N · <chapter title>". Quiet, marginal — not app-chrome.
- **Bookmarks:** small bookmark-ribbon icon in the header toggles the current spread;
  fills brown-burgundy (~#8a3f42) when saved, outlined taupe when not. A "Signets · N"
  button opens a dark panel listing saved spreads (page + chapter) that jump on click,
  each with a × to remove. Persisted to localStorage key `biread:bookmarks`.
- **Velvet ribbon marker:** when the current spread is bookmarked, a short soft-burgundy
  velvet ribbon (~22×42px, low-contrast sheen) hangs from the top of the ENGLISH page
  just right of the gutter (centered on mobile). Clicking it (or Enter/Space) removes
  the bookmark and it disappears.
- **Resume banner:** on load, if `biread:last` > 0, a dismissible pill under the header
  offers to return to the last-read spread ("p. N, <chapter>"); Resume jumps, × dismisses.
  Last-read spread is written to `biread:last` on every spread change.
- **Keyboard:** ←/→ (or PageUp/Down, Space) = one spread; **Shift+←/→ = ten spreads**;
  chapter jump list ("Chapitres") is a focusable menu of buttons; Escape closes any
  open panel / resume banner.
- **Persistence rule:** only ever read/write the `biread:*` localStorage keys
  (`biread:last`, `biread:bookmarks`); never clear other keys.

## Files to hand to Claude Code
- `Bilingual Reader.dc.html` — the source (template + logic + props). This is everything.
- `assets/paper-grain.png` — the faint paper texture it references.
- `CLAUDE.md` — this spec (Claude Code auto-reads a root CLAUDE.md).
- `support.js` is the generated DC runtime; include it if you send the folder, but it
  is regenerated automatically and is not hand-authored.
- (Ignore `Bilingual Reader.html` / `*.standalone.dc.html` — those are export artifacts.)

