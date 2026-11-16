"""Finding money in free text. Pure Python, no LLM.

A reply may only contain prices that tools returned this turn, so this must find an amount however
it is written: digits in any script, `₹`/`Rs`/`rupees` in front or behind, lakh and thousand words,
a price cue ("rate is 200", "200 mein ho jayega"), spelled-out numbers ("two hundred rupees",
"do sau rupaye"), foreign currency, and tricks such as zero-width characters or `2oo`.

What is found always becomes paise. An amount we cannot read exactly (spelled out, foreign, or more
precision than a paisa) is UNREADABLE, which never matches a real price. Legitimate replies write
prices as digits (`format_inr`), so refusing a spelled-out amount costs nothing.

Known limit: a spelled-out amount with no price cue and no currency word ("five hundred") is not
told apart from a quantity ("five hundred cards") and is not flagged. See DECISIONS.md.
"""

import re
import unicodedata

from app.ingestion.price_parser import parse_inr

UNREADABLE = -1  # an amount we could not read exactly never matches a real price

_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿­‎‏"))
# Devanagari and Gujarati digits to ASCII so "₹२५०" is checked like "₹250".
_DIGITS = str.maketrans("०१२३४५६७८९૦૧૨૩૪૫૬૭૮૯", "01234567890123456789")
_O_FOR_ZERO = re.compile(r"\b(?=[\doO]*\d)[\doO]+\b")  # "2oo" -> "200"


def normalise(text: str) -> str:
    """NFKC folds full-width digits and the rupee sign `₨` into plain forms; invisible characters
    that split a word are dropped."""
    text = unicodedata.normalize("NFKC", text).translate(_INVISIBLE).translate(_DIGITS)
    return _O_FOR_ZERO.sub(lambda m: m[0].replace("o", "0").replace("O", "0"), text)


_NUMBER = r"\d+(?:,\d+)*(?:\.\d+)?"
_UNIT = r"(?:k|l|lacs?|lakhs?|cr|crores?)"
_PREFIX = r"(?:₹|rs\.?|r\s?s\.?|inr|रु\.?|रुपये|रुपया|રૂ\.?)"
_SUFFIX = r"(?:₹|rupees?|rupaye|rupiya|rs\.?|inr|/-|/=|रुपये|रुपया|રૂપિયા|રૂ)"
_AMOUNT = re.compile(
    rf"(?<![\w.])(?:{_PREFIX}\s*(?P<n1>{_NUMBER})(?:\s*(?P<u1>{_UNIT})\b)?"
    rf"|(?P<n2>{_NUMBER})(?:\s*(?P<u2>{_UNIT})\b)?\s*{_SUFFIX})",
    re.IGNORECASE,
)
# Money in a currency we never charge in: always wrong, whatever the number.
_FOREIGN = re.compile(
    rf"(?<![\w.])(?:[$€£]\s*{_NUMBER}|{_NUMBER}\s*(?:dollars?|bucks|usd|euros?|eur|pounds?|gbp)\b"
    rf"|(?:usd|eur|gbp)\s*{_NUMBER})",
    re.IGNORECASE,
)

# What a number may count instead of rupees.
_QUANTITY = set(
    "pcs pc pieces piece cards card copies copy sheets sheet pages page units unit nos items item "
    "days day hours hour hrs hr mins min weeks week months month years year people persons guests "
    "photos photo videos video prints print packs pack boxes box sets set colours colors sides "
    "side gsm mm cm inch inches ft feet kg am pm percent din ghante ghanta dino दिन घंटे घंटा नग "
    "પીસ દિવસ કલાક".split()
)
_MONTHS = set(
    "jan feb mar apr may jun jul aug sep sept oct nov dec january february march april june july "
    "august september october november december".split()
)

_MAGNITUDE_WORDS = {
    **dict.fromkeys(["lakh", "lakhs", "lac", "lacs", "लाख", "લાખ"], "l"),
    **dict.fromkeys(["crore", "crores", "करोड़", "કરોડ"], "cr"),
    **dict.fromkeys(["thousand", "hazaar", "hajar", "hazar", "हज़ार", "हजार", "હજાર"], "k"),
}
_BARE_MAGNITUDE = re.compile(
    rf"(?<![\w.])(?P<n>{_NUMBER})\s*(?P<u>{'|'.join(map(re.escape, _MAGNITUDE_WORDS))})(?!\w)",
    re.IGNORECASE,
)

# Words that make a nearby number a price.
_CUES = set(
    "price prices pricing rate rates cost costs charge charges fee fees total amount only just "
    "quote quoted quotation worth pay payable payment discount discounted off offer deal each "
    "budget bill bas बस બસ kimat keemat qeemat bhav bhaav daam dam paisa paise kharcha "
    "lagega lagegi lagenge padega padegi milega milegi jayega jaega denge dena "
    "rupee rupees rupaye rupiya rs "
    "कीमत भाव दाम रेट कुल छूट शुल्क लगेगा पड़ेगा मिलेगा लगेंगे जाएगा जायेगा रुपये रुपया "
    "ભાવ કિંમત દર રેટ કુલ છૂટ ચાર્જ થશે લાગશે પડશે મળશે રૂપિયા".split()
)
_CURRENCY_WORDS = set("rupee rupees rupaye rupiya rupiye rs रुपये रुपया રૂપિયા".split())
_CURRENCY_SIGNS = {"₹", "rs", "inr", "रु", "રૂ"}  # a sign BEFORE the words: "₹ two fifty"

_UNITS = set(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty thirty forty fourty fifty sixty seventy eighty "
    "ninety ek do teen char chaar paanch panch chhe chhah saat aath nau das gyarah barah terah "
    "chaudah pandrah solah satrah atharah bees pachees tees chalis pachas saath sattar assi nabbe "
    "dedh dhai sava savaa be tran chha nav vees pachaas sitter dodh "
    "एक दो तीन चार पाँच पांच छह छः सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह पन्द्रह सोलह सत्रह "
    "अठारह उन्नीस बीस पच्चीस तीस चालीस पैंतालीस पचास साठ सत्तर पचहत्तर अस्सी नब्बे डेढ़ ढाई सवा "
    "એક બે ત્રણ ચાર પાંચ છ સાત આઠ નવ દસ વીસ પચ્ચીસ ત્રીસ ચાળીસ પચાસ સાઠ સિત્તેર પંચોતેર એંસી "
    "નેવું દોઢ અઢી".split()
)
_MAGNITUDES = set(
    "hundred thousand lakh lakhs lac lacs crore crores sau sao hazaar hazar hajar "
    "सौ हज़ार हजार लाख करोड़ સો હજાર લાખ કરોડ".split()
)
# Gujarati multiples written as one word: baso = 200, traso = 300, ...
_FUSED = set(
    "baso aaso traso charso paanchso pachso chhaso satso athso navso dedhso "
    "દોઢસો બસો ત્રણસો ચારસો પાંચસો છસો સાતસો આઠસો નવસો અઢીસો સવાસો".split()
)
_NUMBER_WORDS = _UNITS | _MAGNITUDES | _FUSED

_TOKEN = re.compile(r"[^\s,;:()\[\]{}\"'!?।|]+")
_SENTENCE = re.compile(r"(?<=[.!?।])\s+|\n+")
_NUMERIC = re.compile(rf"^{_NUMBER}$")
_WINDOW = 4  # tokens either side in which a price cue counts


_GROUPED = re.compile(r"^\d{1,3}(?:,\d{2})*,\d{3}(?:\.\d+)?$|^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")


def _paise(number: str, unit: str = "") -> int:
    # "25,0" would otherwise be read as 250: commas must group as 1,20,000 or 120,000.
    if "," in number and not _GROUPED.match(number):
        return UNREADABLE
    try:
        return parse_inr(f"{number}{unit}")
    except ValueError:
        return UNREADABLE


def _tokens(sentence: str) -> list[str]:
    words = (t.strip(".-").lower() for t in _TOKEN.findall(sentence.replace("-", " ")))
    return [w for w in words if w]


def _near_cue(tokens: list[str], start: int, end: int) -> bool:
    around = tokens[max(0, start - _WINDOW) : start] + tokens[end : end + _WINDOW]
    return any(t in _CUES for t in around)


def _is_quantity(word: str) -> bool:
    # Gujarati and Hindi attach endings to the unit ("દિવસમાં" = in days), so match the stem.
    return word in _QUANTITY or word.startswith(("દિવસ", "કલાક", "મહિન", "दिन", "घंटे", "महीन"))


def _counts_something(tokens: list[str], start: int, end: int) -> bool:
    """The number is a quantity, a date, or a rate per pack, not a price."""
    after = tokens[end] if end < len(tokens) else ""
    before = tokens[start - 1] if start else ""
    return (
        _is_quantity(after)
        or after in _MONTHS
        or before in _MONTHS
        or before in {"per", "x", "प्रति", "પ્રતિ"}
    )


def _cue_amounts(text: str) -> list[int]:
    """Bare numbers and spelled-out numbers that sit next to a price cue."""
    found: list[int] = []
    for sentence in _SENTENCE.split(text):
        tokens = _tokens(sentence)
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if _NUMERIC.match(token):
                if not _counts_something(tokens, i, i + 1) and _near_cue(tokens, i, i + 1):
                    found.append(_paise(token))
                i += 1
            elif token in _NUMBER_WORDS:
                j = i
                while j < len(tokens) and tokens[j] in _NUMBER_WORDS:
                    j += 1
                run = tokens[i:j]
                before_currency = (j < len(tokens) and tokens[j] in _CURRENCY_WORDS) or (
                    i > 0 and tokens[i - 1] in _CURRENCY_SIGNS
                )
                # "do sau" / "two hundred" / "baso": a multiple, not a lone "one" or "do".
                is_multiple = (len(run) > 1 and any(w in _MAGNITUDES for w in run)) or any(
                    w in _FUSED for w in run
                )
                if (before_currency or (is_multiple and _near_cue(tokens, i, j))) and (
                    not _counts_something(tokens, i, j)
                ):
                    found.append(UNREADABLE)
                i = j
            else:
                i += 1
    return found


def extract_amounts(text: str) -> list[int]:
    """Every rupee amount mentioned in text, in paise. An amount with more than paisa precision,
    spelled out, or in a foreign currency comes back as UNREADABLE, so it is never waved through."""
    text = normalise(text)
    amounts: list[int] = []
    for match in _AMOUNT.finditer(text):
        amounts.append(_paise(match["n1"] or match["n2"], match["u1"] or match["u2"] or ""))
    text = _AMOUNT.sub(" ", text)

    amounts += [UNREADABLE for _ in _FOREIGN.finditer(text)]
    text = _FOREIGN.sub(" ", text)

    for match in _BARE_MAGNITUDE.finditer(text):
        following = (_tokens(text[match.end() :]) or [""])[0]
        if not _is_quantity(following):  # "1 lakh copies" is a quantity
            amounts.append(_paise(match["n"], _MAGNITUDE_WORDS[match["u"].lower()]))
    text = _BARE_MAGNITUDE.sub(" ", text)

    return amounts + _cue_amounts(text)
