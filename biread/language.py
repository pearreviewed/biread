"""What the gloss stage needs to know about a source language.

Splitting a sentence into hover units is linguistics; markers, field separators
and the copy-exactly rule are protocol. The protocol lives in `gloss.py` and is
the same whatever the book is written in. Everything here is the other half, so
a second source language is a table rather than an edit to the stage that reads
it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    name: str
    #: The closed class: articles, determiners, prepositions, pronouns,
    #: conjunctions, auxiliaries, negation, numerals. A hover unit may carry any
    #: number of these; what it may not carry is a second word from outside it.
    function_words: frozenset[str]
    #: Coordinating conjunctions. One of these between two content words joins
    #: two logical parts — "Moscovie ou Chine", "simple et ordinaire" — and a
    #: hover explains one part, so it is a boundary, not something to glue across.
    coordinators: frozenset[str]
    #: Prepositions that introduce a noun complement. One between two content
    #: words marks a noun-of-noun — "citoyens de la terre", "pieds de roi" —
    #: which is two nouns, two units. An adjective sits flush against its noun
    #: with no preposition between, so this leaves "un jeune homme" alone.
    prepositions: frozenset[str]
    #: The half of the gloss prompt that is a fact about the language rather than
    #: about glossing — how units divide, and which verb forms earn a second line.
    gloss_rules: str
    #: Present-tense forms of the auxiliaries a compound past is built with. A
    #: perfect offered without one of these is some other tense wearing its name.
    perfect_auxiliaries: frozenset[str] = frozenset()


# Elided forms are listed bare (j, l, qu, n) because units are tokenised on
# apostrophes: "qu'il" is two tokens, and both belong to the closed class.
FRENCH_FUNCTION_WORDS = frozenset("""
le la les l un une des du de d au aux à a
ce cet cette ces c ceci cela ça celui celle ceux celles
mon ma mes ton ta tes son sa ses notre nos votre vos leur leurs
tout toute tous toutes chaque quelque quelques plusieurs certains certaines
tel telle tels telles même mêmes autre autres quel quelle quels quelles
je j tu il elle on nous vous ils elles me m te t se s lui y en
moi toi soi eux qui que qu quoi dont où lequel laquelle lesquels lesquelles
auquel auxquels duquel desquels chacun chacune quiconque
et ou mais donc or ni car si comme quand lorsque lorsqu puisque puisqu
quoique quoiqu afin ainsi alors aussi encore déjà puis
dans sur sous par pour avec sans chez vers entre depuis pendant contre selon
avant après derrière devant près loin jusque jusqu malgré parmi outre dès hors sauf
ne n pas plus jamais rien personne aucun aucune nul nulle guère point
très bien trop peu assez tant si beaucoup autant moins environ davantage
quant autour fort toujours souvent
suis es est sommes êtes sont étais était étions étiez étaient
fus fut fûmes fûtes furent serai seras sera serons serez seront
serais serait serions seriez seraient sois soit soyons soyez soient
été être étant
ai as avons avez ont avais avait avions aviez avaient
eus eut eûmes eûtes eurent aurai auras aura aurons aurez auront
aurais aurait aurions auriez auraient aie aies ait ayons ayez aient
eu avoir ayant
peut peux peuvent pouvait pouvais pouvaient pourra purent pu
faut fallait faudra fallu
veut veux veulent voulait voulais voulaient voulut voulu
doit dois doivent devait devais devaient dut dû
va vas vont allait allais allaient
deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze
quinze seize vingt trente quarante cinquante soixante cent cents
mille million millions milliard milliards premier première second seconde demi
""".split())

FRENCH_GLOSS_RULES = """\
WHAT A UNIT IS:
- Exactly one content word — one noun, or one verb, or one standalone adjective or \
adverb — with the grammatical words leaning on it: articles, determiners, prepositions, \
pronouns, auxiliaries, negation. Never two nouns, never two verbs, never a noun and a \
verb together.
      Sur la table          ONE unit   (preposition + article + one noun)
      il se leva            ONE unit   (pronoun + verb)
      l'escalier            ONE unit   (article + one noun)
- An adjective describing a noun stays on that noun; it is not a second content word.
      un jeune homme        ONE unit   ("a young man")
      sa petite fourmilière ONE unit
      un bon observateur    ONE unit

- TWO NOUNS ARE TWO UNITS. When a noun is followed by "de", "à", "en" and another noun, \
that is a noun with a complement — split before the preposition, one unit each:
      citoyens de la terre
          -> citoyens | de la terre
      les lois de la gravitation
          -> les lois | de la gravitation
      cent vingt mille pieds de roi
          -> cent vingt mille pieds | de roi
      de Moscovie ou de la Chine
          -> de Moscovie | ou de la Chine

- A unit NEVER spans two parts of a clause. A subject and its verb are separate units. \
A verb and its object are separate units. Break at every such boundary, however short \
the pieces become:
      il s'appelait Micromégas
          -> il s'appelait | Micromégas
      le procès dura
          -> le procès | dura
      Enfin le muphti fit condamner le livre
          -> Enfin | le muphti | fit condamner | le livre
      Ils entendaient des mites parler d'assez bon sens
          -> Ils entendaient | des mites | parler | d'assez bon sens

- Two things joined by "et", "ou", "ni" are two units. Split at the conjunction:
      attractives et répulsives   -> attractives | et répulsives
      de blondes et de brunes     -> de blondes | et de brunes

- A relative pronoun opens a new unit with the verb after it: "qui tournent".
- Punctuation between units belongs to no unit.
- Cover the paragraph in order, from beginning to end.

PART OF SPEECH: one of noun, verb, adjective, adverb, pronoun, noun phrase, \
prepositional phrase. Never "clause" or "sentence" — both are too big to be a unit.

VERB FORMS. Every verb not already in the infinitive carries inf=. A verb in the passé \
simple carries inf= AND pc= — both, always, never one without the other:
- inf=<infinitive> — the infinitive. "il disséqua" -> inf=disséquer, "ils virent" -> \
inf=voir, "elle s'assit" -> inf=s'asseoir. Omit it only when the verb already IS an \
infinitive.
- pc=<passé composé> — the same verb rewritten into the passé composé, with the right \
auxiliary and agreement: "il monta" -> pc=il est monté, "elle s'assit" -> pc=elle s'est \
assise, "ils virent" -> pc=ils ont vu.
A passé simple verb that carries pc= but not inf= is incomplete. Always give both."""

FRENCH_COORDINATORS = frozenset("et ou ni mais car".split())

# Elided "d'" is listed as "d" because units tokenise on the apostrophe.
FRENCH_PREPOSITIONS = frozenset(
    "de d à au aux du des en dans sur sous par pour avec sans chez vers entre "
    "contre selon parmi".split()
)

# A passé composé is an auxiliary in the *present* plus a participle — the rules
# above say so and give worked examples. Nothing else counts, and that is what
# tells it from the two tenses models offer in its place: "avait" is the
# imparfait of the auxiliary, "n'avait pas pu" the plus-que-parfait. Neither
# carries a present auxiliary, and no passé composé lacks one.
FRENCH_PERFECT_AUXILIARIES = frozenset(
    "ai as a avons avez ont suis es est sommes êtes sont".split()
)

FRENCH = Language(
    name="French",
    function_words=FRENCH_FUNCTION_WORDS,
    coordinators=FRENCH_COORDINATORS,
    prepositions=FRENCH_PREPOSITIONS,
    gloss_rules=FRENCH_GLOSS_RULES,
    perfect_auxiliaries=FRENCH_PERFECT_AUXILIARIES,
)
