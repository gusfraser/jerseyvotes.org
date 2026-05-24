"""
Normalise Jersey-specific local words in hustings transcripts.

Speech-to-text (and even human transcribers) mangle local words in
recognisable ways: "St. Helier" gets heard as "Selia" / "San Helia" /
"St. Helia", "Connétable" gets heard as "conab" / "conet" /
"Conet tap" / "Konapa", etc. This script applies an idempotent
find-replace pass over a transcript.md (or every transcript.md under
pipeline/hustings/) using a curated mapping.

The mapping is deliberately conservative — we only fix unambiguous
garbles. Anything that could be a legitimate non-Jersey English word is
left alone for human review.

Speaker-line `**[mm:ss] Name:**` prefixes are NOT touched (those come
from the metadata.yaml roster and are already canonical). Only the body
text is normalised.

Run:
  python pipeline/normalise_local_terms.py                         # all transcripts
  python pipeline/normalise_local_terms.py --slug <event-slug>     # one event
  python pipeline/normalise_local_terms.py --dry-run               # report, don't write
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HUSTINGS_DIR = Path(__file__).resolve().parent / 'hustings'

# Substitutions are applied in order. Word-boundary-anchored regexes so
# (e.g.) "conet" only matches as a standalone word, not as a substring of
# "concert" or "Connecticut". Case-insensitive — the canonical form on the
# right is what gets written.
#
# Reading order:
#   1. Multi-word / specific phrase forms first
#   2. Single-word forms last (lest "Helia" matches before "St. Helia"
#      and produces "St. Helier" instead of "St Helier")
#
# Adding new entries: keep longest variants first within each section,
# and test with --dry-run.
SUBSTITUTIONS: list[tuple[str, str]] = [
    # ----- St Helier and parish-name patterns -----
    # Multi-word forms with stand-ins for "St"
    (r"\bSent\s+Hel(?:ier|ia|enos|on|a)\b", "St Helier"),
    (r"\bSan\s+Hel(?:ier|ia|enos|on|a)\b",  "St Helier"),
    (r"\bSan\s+Helon\s+tab\b",              "St Helier Connétable"),

    # "St." (with period) followed by any parish-style name → drop period
    # and canonicalise. Note: this must NOT touch "Mr." or "Mrs." or
    # similar — we explicitly anchor on "St."+space+capital + parish-like
    # word.
    (r"\bSt\.\s+Hel(?:enos|ino|ia|io|on|i|en)\b", "St Helier"),
    (r"\bSt\.\s+Helier\b",                        "St Helier"),
    (r"\bSt\.\s+Helia\b",                         "St Helier"),
    (r"\bSt\.\s+Saviour\b",                       "St Saviour"),
    (r"\bSt\.\s+Brelade\b",                       "St Brelade"),
    (r"\bSt\.\s+Clement\b",                       "St Clement"),
    (r"\bSt\.\s+Lawrence\b",                      "St Lawrence"),
    (r"\bSt\.\s+John\b",                          "St John"),
    (r"\bSt\.\s+Ouen\b",                          "St Ouen"),
    (r"\bSt\.\s+Peter\b",                         "St Peter"),
    (r"\bSt\.\s+Martin\b",                        "St Martin"),
    (r"\bSt\.\s+Mary\b",                          "St Mary"),
    # "St." (with period) followed by uppercase + non-parish word — leave alone
    # (covered by the explicit list above). No-op fallthrough.

    # "St Helia" with no period
    (r"\bSt\s+Helia\b",                           "St Helier"),
    (r"\bSt\s+Hel(?:enos|ino|io|on|i|en)\b",      "St Helier"),

    # Standalone "Selia" / "Helia" / "Halia" / "Helenos" — used as
    # shorthand for "St Helier" / "Helier" in the auto-transcript.
    (r"\bSelia\b",                                "St Helier"),
    (r"\bHelenos\b",                              "Helier"),
    (r"\bHelia\b",                                "Helier"),
    (r"\bHalia\b",                                "Helier"),
    (r"\bHela\b",                                 "Helier"),

    # ----- Connétable -----
    # Multi-word first
    (r"\b[Cc]onet\s+tap\b",                       "Connétable"),
    (r"\b[Cc]omer\s+tap\b",                       "Connétable"),
    (r"\b[Cc]onna?or\s+tap(?:ler)?\b",            "Connétable"),
    (r"\bcomet[a-z]*\s+tap\b",                    "Connétable"),
    # Single-word variants
    # NB: "comfortable" intentionally left alone — even though one STT
    # garble of Connétable produced it, the word is too common in normal
    # English to substitute blindly. Fix those by hand if they appear.
    (r"\b[Cc]omportable\b",                       "Connétable"),
    (r"\b[Cc]onnotabler\b",                       "Connétable"),
    (r"\b[Cc]onnotab\b",                          "Connétable"),
    (r"\b[Cc]onotabler\b",                        "Connétable"),
    (r"\b[Cc]onotab\b",                           "Connétable"),
    (r"\b[Cc]onetab\b",                           "Connétable"),
    (r"\b[Cc]onetable\b",                         "Connétable"),
    (r"\b[Kk]onapa\b",                            "Connétable"),
    (r"\b[Kk]onet\b",                             "Connétable"),
    (r"\b[Cc]onab\b",                             "Connétable"),
    (r"\b[Cc]onet\b",                             "Connétable"),
    # Additional speaker-specific Connétable garbles
    (r"\b[Cc]onotard\b",                          "Connétable"),
    (r"\b[Cc]onotope\b",                          "Connétable"),
    (r"\b[Cc]onotarb\b",                          "Connétable"),
    (r"\b[Cc]ony?\s*[Tt]arb\b",                   "Connétable"),
    (r"\b[Cc]onotarbe\b",                         "Connétable"),
    (r"\b[Cc]onnoisseur\b(?=\s*(?:of|for|,|\.|in|\s+St\s))",
                                                  "Connétable"),
    (r"\b[Cc]onetub\b",                           "Connétable"),

    # ----- Other Jersey words -----
    (r"\bBobbys\b",                               "Bobbies"),
    # "Bridging Island Plan" — STT garble
    (r"\bBridgen\s+Island\b",                     "Bridging Island"),
    # "Simon Crowcroft" — long-serving St Helier Constable, STT garble
    (r"\bCrocraftoft\b",                          "Crowcroft"),
    # "Dantelia" — another mis-hearing of St Helier
    (r"\bDantelia\b",                             "St Helier"),
    # St Andrew's Park (St Helier playground) — two distinct STT garbles
    (r"\bSt\.?\s+Andress\s+Park\b",               "St Andrew's Park"),
    (r"\bSt\.?\s+Andrew\s+Park\b",                "St Andrew's Park"),
    (r"\bSt\.?\s+Andrew\b(?!')",                  "St Andrew's"),
    # Reform Jersey leaflet/manifesto "Connorabler" form
    (r"\bConnorabler\b",                          "Connétable"),

    # American "Savior" → British "Saviour"
    (r"\bSt\.?\s+Savior's\b",                     "St Saviour's"),
    (r"\bSt\.?\s+Savior\b",                       "St Saviour"),

    # ----- St Saviour mis-transcriptions -----
    # Whisper renders "Saviour" as "Xavier" or "Pilar" with surprising
    # frequency (~28 hits across 25 transcripts). The 'pilar/xavier'
    # confusion comes from the 'vyer' vs 'pier' vowel + soft-stop ending.
    (r"\bSt\.?\s+Xavier's\b",                     "St Saviour's"),
    (r"\bSt\.?\s+Xavier\b",                       "St Saviour"),
    (r"\bSt\.?\s+Saviours\b(?!')",                "St Saviour"),  # missing apostrophe form
    (r"\bSt\.?\s+Pilar\b",                        "St Saviour"),

    # ----- St Ouen mis-transcriptions -----
    # "Ouen" is pronounced "wen"/"when", which Whisper hears as "Juan",
    # "Oven", or "Owen" depending on context (~22 hits). All variants
    # in a Jersey-hustings context are St Ouen.
    (r"\bSt\.?\s+Juan's\b",                       "St Ouen's"),
    (r"\bSt\.?\s+Juan\b",                         "St Ouen"),
    (r"\bSt\.?\s+Oven's\b",                       "St Ouen's"),
    (r"\bSt\.?\s+Oven\b",                         "St Ouen"),
    (r"\bSt\.?\s+Owen's\b",                       "St Ouen's"),
    (r"\bSt\.?\s+Owen\b",                         "St Ouen"),
    (r"\bSt\.?\s+Owens\b",                        "St Ouen"),

    # ----- St Brelade mis-transcriptions -----
    # "Brelade" gets garbled an extraordinary number of ways. Listed in
    # decreasing observed frequency. Word-boundary anchors prevent these
    # from eating substrings of unrelated words.
    (r"\bSt\.?\s+Brelard's\b",                    "St Brelade's"),
    (r"\bSt\.?\s+Brelards\b",                     "St Brelade's"),
    (r"\bSt\.?\s+Brelard\b",                      "St Brelade"),
    (r"\bSt\.?\s+Bralad's\b",                     "St Brelade's"),
    (r"\bSt\.?\s+Bralad\b",                       "St Brelade"),
    (r"\bSt\.?\s+Brillard's\b",                   "St Brelade's"),
    (r"\bSt\.?\s+Brillard\b",                     "St Brelade"),
    (r"\bSt\.?\s+Brilard's\b",                    "St Brelade's"),
    (r"\bSt\.?\s+Brilard\b",                      "St Brelade"),
    (r"\bSt\.?\s+Brilla\b",                       "St Brelade"),
    (r"\bSt\.?\s+Beryl\b",                        "St Brelade"),
    (r"\bSt\.?\s+Ballard's\b",                    "St Brelade's"),
    (r"\bSt\.?\s+Ballard\b",                      "St Brelade"),
    (r"\bSt\.?\s+Brouillard's\b",                 "St Brelade's"),
    (r"\bSt\.?\s+Brouillard\b",                   "St Brelade"),
    (r"\bSt\.?\s+Bralard\b",                      "St Brelade"),
    (r"\bSt\.?\s+Blard\b",                        "St Brelade"),
    # Non-"St" prefix garbles for St Brelade — same speaker in the
    # brelade Connétable hustings produces these four. All refer to
    # St Brelade Social Club (a real venue) and to "the coast of
    # St Brelade".
    (r"\bSombrilla\s+Social\s+Club\b",            "St Brelade Social Club"),
    (r"\bSunbrella\s+Social\s+Club\b",            "St Brelade Social Club"),
    (r"\bSombrellys\s+Social\s+Club\b",           "St Brelade Social Club"),
    # In-context Sunbrella/Sombrelly/Sombreros (NOT global replace —
    # we don't want to clobber the legitimate Mexican hat).
    (r"\b(in|of)\s+Sunbrella\b",                  r"\1 St Brelade"),
    (r"\b(coast|coastline)\s+of\s+[Ss]ombreros\b",r"\1 of St Brelade"),
    (r"\b[Ss]ombreros\s+is\s+about\b",            "St Brelade is about"),
    (r"\bsome\s+brellards\b",                     "St Brelade's"),
    # NB: "St Bernard" is intentionally left alone — there's a real
    # "St Bernard's School" reference that's legitimate. If a transcript
    # uses "St Bernard" to mean "St Brelade" the human reviewer can fix
    # it; we shouldn't auto-rewrite a real-saint name.

    # ----- St Aubin mis-transcriptions -----
    # St Aubin is a coastal village in St Brelade parish, not a parish
    # itself. Whisper renders it as "St Oban" (Scottish town), "St Obies"
    # etc. ~11 hits.
    (r"\bSt\.?\s+Oban's\b",                       "St Aubin's"),
    (r"\bSt\.?\s+Obans\b",                        "St Aubin's"),
    (r"\bSt\.?\s+Oban\b",                         "St Aubin"),
    (r"\bSt\.?\s+Obies\b",                        "St Aubin"),
    (r"\bSt\.?\s+Dobins\b",                       "St Aubin"),
    # St Aubin's Bay / St Aubin's Road etc.
    (r"\bSt\.?\s+Auben's\b",                      "St Aubin's"),
    (r"\bSt\.?\s+Auben\b",                        "St Aubin"),

    # ----- Grouville variants -----
    # Whisper hears as "Greville", "Grieville", "Groveville", "Grooville"
    (r"\bGrieville\b",                            "Grouville"),
    (r"\bGreville\b",                             "Grouville"),
    (r"\bGroveville\b",                           "Grouville"),
    (r"\bGroville\b",                             "Grouville"),
    (r"\bGrooville\b",                            "Grouville"),
    (r"\bGreaveville\b",                          "Grouville"),

    # ----- Sam Mézec (Reform Jersey leader; surname uses é + c) -----
    # Whisper anglicises "Mézec" → "Mezek" / "Mezzek" / "Mizek"
    (r"\bSam\s+Mezek\b",                          "Sam Mézec"),
    (r"\bSam\s+Mezzek\b",                         "Sam Mézec"),
    (r"\bSam\s+Mizek\b",                          "Sam Mézec"),
    (r"\bSam\s+Mezic\b",                          "Sam Mézec"),
    (r"\bSam\s+Mezeck\b",                         "Sam Mézec"),
    # Standalone "Mezek" (no first name) — appears as moderator
    # introducing him by surname. Match conservatively.
    (r"\b(?<!Sam\s)Mezek\b",                      "Mézec"),

    # ----- Other parish mis-transcriptions -----
    (r"\bSt\.?\s+Elliot's\b",                     "St Helier's"),
    (r"\bSt\.?\s+Elliot\b",                       "St Helier"),
    (r"\bSt\.?\s+Helius\b",                       "St Helier"),
    (r"\bSt\.?\s+Hallya\b",                       "St Helier"),
    (r"\bSt\.?\s+Halyard\b",                      "St Helier"),
    (r"\bSt\.?\s+Mums\b",                         "St Martin's"),  # tentative
    (r"\bSt\.?\s+Marlow\b",                       "St Martin"),    # tentative

    # ----- Coastal place names in St Brelade -----
    # La Pulente — long west-coast beach. Whisper hears as "La Pollen".
    (r"\bLa\s+Pollen\b",                          "La Pulente"),
    (r"\bLa\s+Polent\b",                          "La Pulente"),
    # Portelet — small bay south coast. Garbled as "Portlet".
    (r"\bPortlet\b",                              "Portelet"),
    (r"\bPort\s+let\b",                           "Portelet"),
    # Ouaisné — beach east of Portelet. Pronounced "way-nay".
    # Whisper hears as "Wainey", "Waney", "Way-nay", or "Wayne A"
    # (splitting the syllable across what it thinks is a name + letter).
    (r"\bWainey\b",                               "Ouaisné"),
    (r"\bWayney\b",                               "Ouaisné"),
    (r"\bWaney\b",                                "Ouaisné"),
    # "Smuggler's Inn at Wayne (A)" — real pub at Ouaisné Beach. The
    # multi-word context is unambiguous so we can rewrite both "Wayne"
    # and "Wayne A" → Ouaisné. Both "Smugglers Inn at" and "the
    # smugglers at" variants seen in transcripts.
    (r"\b[Ss]muggler'?s?\s+[Ii]nn?\s+at\s+Wayne(?:\s+A)?\b",
                                                  "Smuggler's Inn at Ouaisné"),
    (r"\bthe\s+[Ss]muggler'?s?\s+at\s+Wayne(?:\s+A)?\b",
                                                  "the Smuggler's Inn at Ouaisné"),
    # "I live at Wayne" — Ouaisné is a residential area; audience
    # members say this when introducing themselves. Specific multi-word
    # context avoids touching anyone named Wayne.
    (r"\b(?:I\s+)?live\s+at\s+Wayne\b",           "live at Ouaisné"),
    # Noirmont — WWII bunker site on St Brelade headland. Garbled as
    # "Warmore" / "Normor".
    (r"\bWarmore\b",                              "Noirmont"),
    (r"\bNoremore\b",                             "Noirmont"),
    # St Brelade Social Club — yet another speaker-specific garble.
    (r"\bUmbrella\s+Social\s+Club\b",             "St Brelade Social Club"),
    # Sunbella / Sombrella / Sombrellas — yet more "St Brelade" garbles
    # from a different speaker. NOT to be confused with the legitimate
    # English word "umbrella" used as a metaphor.
    (r"\bSunbella's\b",                           "St Brelade's"),
    (r"\bSunbella\b",                             "St Brelade"),
    (r"\bSombrella\s+Youth\s+Forum\b",            "St Brelade Youth Forum"),
    (r"\bSombrellas\s+Community\b",               "St Brelade Community"),

    # ----- Connétable as a role (not a name) -----
    # "Connacht Hub" / "Conacht Hub" — Whisper hears the Jersey role
    # title as the Irish province + business term. Single most absurd
    # garble in the corpus.
    (r"\b[Cc]onn?acht\s+[Hh]ubs\b",               "Connétables"),
    (r"\b[Cc]onn?acht\s+[Hh]ub\b",                "Connétable"),
    (r"\b[Cc]onn?achtab\b",                       "Connétable"),
    # Plain "Connetable" without the accent — restore it.
    (r"\bConnetable\b",                           "Connétable"),
    (r"\bconnetable\b",                           "Connétable"),

    # ----- Honorary Police -----
    # Parish-level law enforcement, frequently misheard.
    (r"\b[Hh]enry\s+[Pp]olice\b",                 "Honorary Police"),
    (r"\b[Hh]onor[ae]?\s+[Pp]olice\b",            "Honorary Police"),
    (r"\b[Hh]onery\s+[Pp]olice\b",                "Honorary Police"),
    (r"\b[Hh]onary\s+[Pp]olice\b",                "Honorary Police"),
    (r"\b[Oo]nery\s+[Pp]olice\b",                 "Honorary Police"),

    # ----- States Greffe / Judicial Greffe -----
    # "Greff" / "Gref" (incomplete) → Greffe; protect "Greffier(s)"
    # (real word) via negative lookahead.
    (r"\b[Ss]tates\s+[Gg]reff?\b(?!ier)",         "States Greffe"),
    # Judicial Greffe: postal-ballot recipient mentioned in every closing
    # statement. Whisper produces "judicial gref" / "judicial greff" /
    # "judicial graph" / "judicial grof". The `?` lets the regex match
    # either one or two `f`s.
    (r"\b[Jj]udicial\s+[Gg]ra(?:ph|f)\b",         "Judicial Greffe"),
    (r"\b[Jj]udicial\s+[Gg]reff?\b(?!ier)",       "Judicial Greffe"),
    (r"\b[Jj]udicial\s+[Gg]rof\b",                "Judicial Greffe"),

    # ----- Honorary Police: additional "u" form ('Honour' vs 'Honor') -----
    (r"\b[Hh]onour\s+[Pp]olice\b",                "Honorary Police"),

    # ----- Centenier / Vingtenier (parish-level Honorary Police ranks) -----
    # "centineer" / "centenear" / "centenya" → Centenier
    (r"\b[Cc]entineer\b",                         "Centenier"),
    (r"\b[Cc]entenear\b",                         "Centenier"),
    (r"\b[Cc]entenya\b",                          "Centenier"),
    # "ventineer" / "vingteneer" / "vingtnier" → Vingtenier
    (r"\b[Vv]entineer\b",                         "Vingtenier"),
    (r"\b[Vv]ingtene[ae]r\b",                     "Vingtenier"),
    (r"\b[Vv]ingtnier\b",                         "Vingtenier"),

    # ----- Coastal bay names -----
    # Bouley Bay (NE coast, motorsport hill climb venue)
    (r"\bBully\s+Bay\b",                          "Bouley Bay"),
    (r"\bBooley\s+Bay\b",                         "Bouley Bay"),
    (r"\bBowley\s+Bay\b",                         "Bouley Bay"),
    # Archirondel (NE coast, near Rozel)
    (r"\b[Aa]rcher\s+[Ll]ondon\b",                "Archirondel"),
    (r"\b[Aa]rchibald\b(?=.{0,40}(?:beach|bay|coast|tourist|board))",
                                                  "Archirondel"),
    # Rozel (NE coastal village)
    (r"\bRoselle\b(?=.{0,30}(?:bay|boathouse|in\s+the|village|fish|harbour))",
                                                  "Rozel"),

    # ----- Connétable: yet more variants -----
    (r"\b[Cc]onnetabla\b",                        "Connétable"),
    (r"\b[Cc]onetabla\b",                         "Connétable"),
    (r"\b[Cc]onatab\b",                           "Connétable"),
    (r"\b[Cc]ona\s+[Tt]arp\b",                    "Connétable"),

    # ----- School and place names commonly mangled -----
    # La Moye (St Brelade school + village)
    (r"\b[Ll]emoy\b",                             "La Moye"),
    (r"\bLe\s+Moy\b(?!s\b)",                      "La Moye"),
    # Les Quennevais (St Brelade school + sports centre + retail park)
    (r"\b[Ll]e\s+[Kk]enoa\b",                     "Les Quennevais"),
    (r"\b[Ll]es\s+[Kk]enovai\b",                  "Les Quennevais"),
    (r"\b[Ll]e\s+[Cc]anav[eé]\b",                 "Les Quennevais"),
    (r"\b[Kk]ennebay\b",                          "Les Quennevais"),
    (r"\b[Kk]enner\s+[Bb]ay\b",                   "Les Quennevais"),

    # ----- Procureur -----
    (r"\b[Pp]rocurer\s+du\s+Bien\b",              "Procureur du Bien"),
    (r"\b[Pp]rocurator\s+du\s+Bien\b",            "Procureur du Bien"),

    # ----- Andium Homes (Jersey's gov. housing association) -----
    # Surfaced by fuzzy audit at ~83% — below auto-apply threshold, so
    # we add explicit regex for these specific variants. Whisper
    # consistently hears "Andium" as "Andeum" (rounded vowel).
    (r"\bAndeum\s+Homes\b",                       "Andium Homes"),
    (r"\bAndeum\b",                               "Andium"),
    (r"\bAndium\s+Homes\b",                       "Andium Homes"),  # canonical form

    # ----- Honorary Police: more variants surfaced by fuzzy audit -----
    (r"\b[Hh]onoree\s+[Pp]olice\b",               "Honorary Police"),
    (r"\b[Hh]onourable\s+[Pp]olice\b",            "Honorary Police"),
    (r"\b[Oo]rnery\s+[Pp]olice\b",                "Honorary Police"),

    # ----- More place-name garbles surfaced by audit -----
    (r"\bGoree\b",                                "Gorey"),
    (r"\bGroovely\b",                             "Grouville"),
    (r"\bGrueville\b",                            "Grouville"),
    (r"\bLa\s+Poullante\b",                       "La Pulente"),
    (r"\bLa\s+Poulante\b",                        "La Pulente"),
    (r"\bPlont\b(?=.{0,30}(?:beach|coast|west|north|head))",
                                                  "Plémont"),
    (r"\bLe\s+Quenneve\b",                        "Les Quennevais"),
    (r"\bDelasalle\b",                            "De La Salle"),
    (r"\bLemaitre's\b",                           "Le Maistre's"),
    (r"\bLemaitre\b",                             "Le Maistre"),
    (r"\bLepavo\b",                               "Le Pavoux"),
    (r"\bLe\s+Pavo\b",                            "Le Pavoux"),

    # Severely truncated "St Helier" garbles: "St. Hi", "St. Hel" etc.
    # — only the unambiguous cases (no other Jersey parish starts with
    # Hi/Hel, and these only appear mid-sentence in the parish context).
    (r"\bSt\.?\s+Hel's\b",                        "St Helier's"),
    (r"\bSt\.?\s+Hel\b",                          "St Helier"),
    (r"\bSt\.?\s+Hi\b",                           "St Helier"),

    # Generic "St." drop-period rule. Applied last so all earlier specific
    # rules have had their chance. Matches "St." followed by whitespace
    # and a capitalised name (Andrew's, Paul's, Joseph, Ewolds, Thomas's,
    # Luke's, Mark's, George's, etc). The lookahead ensures we don't
    # accidentally match a stray "St." at the end of a sentence followed
    # by a sentence-start cap.
    (r"\bSt\.\s+(?=[A-Z][a-zA-Z']{2,})",          "St "),
]


def normalise(text: str, roster_names: set[str] | None = None) -> tuple[str, list[tuple[str, str, int]]]:
    """Two-pass normalisation:
      1. Regex SUBSTITUTIONS — high-confidence, unambiguous fixups
         (Henry Police → Honorary Police, St Xavier → St Saviour, …).
         Deterministic and free.
      2. Jersey lexicon fuzzy match — for everything regex didn't
         catch, see if any capitalised phrase looks like a canonical
         Jersey term within similarity threshold. Only AUTO-tier
         matches (>= AUTO_SIM, currently 88) get applied; lower-
         confidence matches are surfaced separately (via the audit
         tool) for human review.

    The lexicon pass is the long-tail solution — regex is fine for
    the ~80 patterns we've manually catalogued, but Whisper invents
    new garbles every transcript. The lexicon catches siblings of
    known terms automatically.

    Pass `roster_names` (candidate + moderator names from
    metadata.yaml) to prevent the lexicon from matching person names
    against parish names (e.g. "Mary Le Hegarat" → "St Mary").
    """
    changes: list[tuple[str, str, int]] = []
    for pattern, replacement in SUBSTITUTIONS:
        new_text, n = re.subn(pattern, replacement, text, flags=re.IGNORECASE)
        if n:
            changes.append((pattern, replacement, n))
            text = new_text

    # Whisper-large-v3 occasionally gets stuck repeating a short token
    # (e.g. "Sne Sne Sne Sne…" or "changed changed changed…") at moments
    # of unclear audio or speaker transitions. Detect runs of the same
    # word 4+ times in a row (case-insensitive, punctuation-tolerant) and
    # collapse to a single instance with a "[repetition removed]" marker
    # so the reader knows something was elided.
    new_text, n = _collapse_whisper_repetitions(text)
    if n:
        changes.append(('whisper repetition loops', '[repetition removed]', n))
        text = new_text

    # Lexicon-based fuzzy pass. Only applies AUTO-tier corrections
    # (≥ 88% similarity). Falls back to no-op if rapidfuzz isn't
    # installed.
    try:
        from jersey_lexicon import find_matches, apply_corrections
        matches = find_matches(text, roster_names=roster_names)
        text, n_auto = apply_corrections(text, matches)
        if n_auto:
            changes.append(('jersey lexicon (auto)', f'{n_auto} corrections', n_auto))
    except ImportError:
        pass

    return text, changes


_WHISPER_LOOP_RE = re.compile(
    r"\b(\w{1,12})(?:[\s,.\-]+\1\b){3,}",
    re.IGNORECASE,
)


# Marker we leave in place of a Whisper repetition loop. Deliberately
# honest about WHY the gap exists — the model failed to transcribe
# real speech and produced repeated nonsense tokens. The actual words
# spoken during the gap are LOST from the transcript; the only way to
# recover them is the YouTube link rendered alongside the segment.
WHISPER_GAP_MARKER = (
    '[automated transcription failed here — watch the YouTube link '
    'above to hear what was actually said]'
)


def _collapse_whisper_repetitions(text: str) -> tuple[str, int]:
    """Find runs of the same short word repeated 4+ times and replace
    with a marker that explicitly explains the gap. The matched run
    isn't real speech — it's Whisper's failure mode on unclear audio —
    so we drop it entirely rather than keep a single instance."""
    new_text, n = _WHISPER_LOOP_RE.subn(WHISPER_GAP_MARKER, text)
    return new_text, n


def _load_roster_names(path: Path) -> set[str]:
    """If `path` is a transcript.md in pipeline/hustings/<slug>/, read
    the sibling metadata.yaml to grab candidate and moderator names —
    these are passed to the lexicon to prevent person→parish matches.
    """
    meta_path = path.parent / 'metadata.yaml'
    if not meta_path.exists():
        return set()
    try:
        import yaml
        data = yaml.safe_load(meta_path.read_text()) or {}
    except Exception:
        return set()
    names: set[str] = set()
    for c in (data.get('candidates') or []):
        if c.get('name'):
            names.add(c['name'])
    for m in (data.get('moderator_names') or []):
        names.add(m)
    return names


def process_file(path: Path, dry_run: bool) -> int:
    """Returns the total number of substitutions made."""
    text = path.read_text(encoding='utf-8')
    roster = _load_roster_names(path)
    new_text, changes = normalise(text, roster_names=roster)
    total = sum(n for _, _, n in changes)
    if not changes:
        print(f'  no changes')
        return 0
    for pattern, replacement, n in changes:
        print(f'  {n:>4}× {pattern!r} → {replacement!r}')
    if dry_run:
        print(f'  [dry-run] would write {total} substitutions')
    else:
        path.write_text(new_text, encoding='utf-8')
        print(f'  wrote {total} substitutions')
    return total


def main():
    parser = argparse.ArgumentParser(
        description='Normalise Jersey-local terms in hustings transcripts.',
    )
    parser.add_argument('--slug', help='Process only this event slug')
    parser.add_argument('--dry-run', action='store_true',
                        help='Report changes but do not write')
    parser.add_argument('--path', help='Process a specific transcript file '
                                       'directly (overrides --slug)')
    args = parser.parse_args()

    if args.path:
        files = [Path(args.path)]
    else:
        folders = sorted(
            p for p in HUSTINGS_DIR.iterdir()
            if p.is_dir() and not p.name.startswith('_')
        )
        if args.slug:
            folders = [p for p in folders if p.name == args.slug]
            if not folders:
                sys.exit(f'No folder named {args.slug!r}')
        files = [f / 'transcript.md' for f in folders if (f / 'transcript.md').exists()]

    total = 0
    for f in files:
        print(f'[{f.relative_to(Path(__file__).resolve().parent.parent)}]')
        total += process_file(f, args.dry_run)
    print(f'\nTotal substitutions across {len(files)} file(s): {total}')


if __name__ == '__main__':
    main()
