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
    #: The half of the gloss prompt that is a fact about the language rather than
    #: about glossing — how units divide, and which verb forms earn a second line.
    gloss_rules: str


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
très bien trop peu assez tant si
suis es est sommes êtes sont étais était étions étiez étaient
fus fut fûmes fûtes furent serai seras sera serons serez seront
serais serait serions seriez seraient sois soit soyons soyez soient
été être étant
ai as avons avez ont avais avait avions aviez avaient
eus eut eûmes eûtes eurent aurai auras aura aurons aurez auront
aurais aurait aurions auriez auraient aie aies ait ayons ayez aient
eu avoir ayant
deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze
quinze seize vingt trente quarante cinquante soixante cent cents
mille million millions milliard milliards premier première second seconde demi
""".split())

FRENCH_GLOSS_RULES = """\
WHAT A UNIT IS:
- One phrase and never more. A phrase is a single content word — one noun, verb, \
adjective or adverb — with the function words leaning on it: articles, determiners, \
prepositions, pronouns, auxiliaries, negation. An adjective sitting on its noun stays \
with it.
      Sur la table          ONE unit
      il se leva            ONE unit
      un jeune homme        ONE unit
      l'escalier            ONE unit

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
      dont le bout fort effilé venait donner auprès du vaisseau
          -> dont le bout | fort effilé | venait donner | auprès du vaisseau

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

FRENCH = Language(
    name="French",
    function_words=FRENCH_FUNCTION_WORDS,
    gloss_rules=FRENCH_GLOSS_RULES,
)
