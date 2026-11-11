"""Question understanding (Phase 3): a member's question -> a Query with an intent and slots.

Rules, not a model: fast (< 1 ms), deterministic (the repeat check), and testable. Every slot maps onto the
fact keys built at ingest (facts.py R1, prose.py), so the answer is a lookup in store.resolved(as_of).

    intent   rate | link | branch_count | routing_number | address | hours | closure | closure_alternatives |
             forbes_recognition | vto_employees | employees | members | assets | eligibility | phone | general
    slots    products, segment, account, purpose, flags, attribute, term_months, x (model year / amount),
             superlative, premise (a % stated in the question), unpublished (a product variant the site
             describes but publishes no rate for), named_branch, date_ref (a date stated in the question)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Optional

from .normalize import clean_text
from .prose import DATE_RE, parse_date

# ----------------------------------------------------------------------------- vocabulary
# Question words -> product families. Order matters: the first match wins, specific before generic.
# A family can be several products: "credit cards" means all four cards (E-list questions 034, 040).
CARDS = ["platinum visa", "rewards visa"]
QUERY_PRODUCTS: list = [
    (["platinum visa"], r"\bplatinum\b"),
    (["rewards visa"], r"\brewards? (?:visa|credit card|card)\b"),
    (CARDS, r"\bcredit cards?\b|\bvisa\b|\bcards? (?:apr|rate)"),
    (["launchpad savings"], r"\blaunch ?pad\b"),     # before IRA: Launchpad questions mention moving money to an IRA
    (["ira certificate"], r"\bira\b.*\b(?:certificate|cd)s?\b|\b(?:certificate|cd)s?\b.*\bira\b"),
    (["ira savings"], r"\bira\b"),
    (["certificate"], r"\bcertificates?\b|\bcds?\b|\bshare certificates?\b|\bterm.?share"),
    (["bright savings"], r"\bbright savings\b"),
    (["you name it savings"], r"\byou.?name.?it\b"),
    (["holiday club savings"], r"\bholiday club\b"),
    (["health savings account"], r"\bhealth savings\b|\bhsa\b"),
    (["high-yield savings"], r"\bhigh.?yield\b"),
    (["investor's choice money market"], r"\binvestor'?s choice\b"),
    (["achieve money market"], r"\bachieve\b"),
    (["investor's choice money market", "achieve money market"], r"\bmoney markets?\b"),
    (["1st rate checking"], r"\b1st rate\b|\bfirst rate\b"),
    (["free checking"], r"\bfree checking\b"),
    (["free checking", "1st rate checking"], r"\bchecking\b"),
    (["share savings"], r"\bshare savings\b|\bsavings (?:account|tiers?|rates?|apy)\b|\bregular savings\b"),
    (["atv loan"], r"\batv\b|\bsnowmobile\b|\bjet ?ski\b|\bpowersports?\b"),
    (["boat & rv loan"], r"\bboats?\b|\brvs?\b|\bcampers?\b|\brecreational vehicle"),
    (["auto loan"], r"\bauto\b|\bcar\b|\bcars\b|\bvehicles?\b|\btrucks?\b|\bmotorcycles?\b|\bsuv\b"),
    (["heloc"], r"\bheloc\b|\bhome equity line\b"),
    (["home equity loan"], r"\bhome equity\b"),
    (["home improvement loan"], r"\bhome improvement\b"),
    (["mortgage"], r"\bmortgages?\b|\bhome loans?\b|\bhome purchase\b|\brefinanc|\bfixed conventional\b|"
                   r"\b(?:\d{2}|fifteen|twenty|thirty)[- ]year fixed\b"),
    (["personal loan"], r"\bpersonal loans?\b|\bsignature loans?\b"),
    (["share savings"], r"\bsavings\b"),
]
_QUERY_PRODUCTS = [(names, re.compile(rx, re.I)) for names, rx in QUERY_PRODUCTS]

# Mortgage variants the site DESCRIBES but publishes no rate for (dup-145: 7/1 ARM). The rate sheet lists fixed
# purchase / refinance terms only, so a rate question about one of these must be declined, never answered with
# the fixed rate (R9). A rate question that matches NO product (dup-147 construction loan) is declined anyway.
MORTGAGE_VARIANTS = re.compile(r"\b(?:adjustable|arms?|\d/\d|construction|land loans?|lot loans?|fha|va|usda|"
                               r"jumbo|interest.only|bridge|reverse)\b", re.I)

# Numbers written as words, 1-99 ("seventy-two-month", "thirty-year", "fifteen grand"): blind set C wrote terms and
# balances this way, and "seventy-two-month" was read as a 2-month term.
_ONES = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_NUMBER_WORDS = {w: i + 1 for i, w in enumerate(_ONES)}
for _t, _tens in enumerate(_TENS, start=2):
    _NUMBER_WORDS[_tens] = _t * 10
    for _o in range(1, 10):
        for _sep in ("-", " "):
            _NUMBER_WORDS[f"{_tens}{_sep}{_ONES[_o - 1]}"] = _t * 10 + _o
_NUMBER_WORD_RX = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))   # longest first: "seventy-two", not "two"
_TERM = re.compile(r"\b(\d{1,3}|" + _NUMBER_WORD_RX + r")\s*-?\s*(months?|mos?|yrs?|years?)\b", re.I)
# "fifteen grand", "10 thousand dollars": an amount written without a "$".
_AMOUNT_WORDS = re.compile(r"\b(\d{1,3}|" + _NUMBER_WORD_RX + r")\s+(grand|thousand)\b", re.I)
_YEAR = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")
_AMOUNT = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k|thousand|million|m)?\b", re.I)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_MONTH_YEAR = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+(20\d\d)\b", re.I)
# "in 2019", "back in 2024": in a RATE question a year on its own is a date (its last day). Elsewhere it labels
# the fact ("employees who used VTO in 2023", R21), so it is not a date there.
_YEAR_ONLY = re.compile(r"\b(?:in|during|back in|as of|since)\s+(19\d\d|20\d\d)\b(?!\s*(?:model|-))", re.I)
# A question about the FUTURE value of a rate: the site only shows current and past rates (G3: decline).
_FUTURE = re.compile(r"\bwill\b.{0,40}\b(?:be|go|rise|fall|drop|increase|decrease|change)\b.{0,30}"
                     r"\b(?:next|tomorrow|future|later|in 20\d\d)\b|\b(?:predict|forecast|projected|projection)\w*\b|"
                     r"\bgoing to (?:be|go|rise|fall|drop|change)\b", re.I)
# "rate and APR", "APR / rate": both measures asked for, so no single attribute.
_BOTH_MEASURES = re.compile(r"\brates?\s*(?:and|&|/|\+)\s*aprs?\b|\baprs?\s*(?:and|&|/|\+)\s*(?:interest )?rates?\b|"
                            r"\bdividend rates?\s*(?:and|&|/|\+)\s*apys?\b|\bapys?\s*(?:and|&|/|\+)\s*dividend", re.I)
# A minimum to open / earn is a requirement, not "the lowest rate" (review: "minimum deposit" was a superlative).
_MINIMUM_FACT = re.compile(r"\bminimum (?:deposit|balance|amount|opening|to open|to earn|required|investment)|"
                           r"\bmin\.? to (?:open|earn)\b|\b(?:opening|deposit) minimum\b|"
                           r"\b(?:what|and|the) minimum (?:would|do|does|is|did|was|to|i)\b|\bminimum to maintain\b|"
                           r"\bhow much (?:do i need|is needed|must i deposit) to open\b", re.I)
# A fee question: an amount of money, not a rate ("What does Dupaco charge for a stop payment?").
_FEE_WORDS = re.compile(r"\bfees?\b|\bcharges?\b|\bcosts?\b|\bhow much\b|\bprices?\b", re.I)
_RATE_ASK = re.compile(r"\b(?:rates?|aprs?|apys?|interest|dividends?|yield)\b", re.I)
# Numbers about the COMPANY, not a member's product: never in the fee schedule, so declined (not searched).
_COMPANY_NUMBER = re.compile(r"\b(?:stock|share) prices?\b|\bprice of (?:\w+ )?(?:stock|shares)\b|"
                             r"\b(?:salary|salaries|compensation|revenue)\b", re.I)
# "the dividend rate rather than the APY": the measure after a contrast word is NOT the one asked for (in-09).
_CONTRAST = re.compile(r"\b(?:rather than|instead of|not the|not an?|other than|excluding|except|before the)\s+"
                       r"(?:the\s+|an?\s+)?"
                       r"(?:aprs?|apys?|annual percentage (?:rate|yield)|dividend rates?|interest rates?|rates?)\b",
                       re.I)
# Member-specific data the public website cannot hold: balances, transactions, an approval for "me" (in-24/25).
# A procedure question about one's own data is answerable ("How can I check my balance?", "Where do I see my
# statements?"); a request for the data itself is not, however it is phrased ("Can I see my balance?").
_HOW_TO = re.compile(r"\s*(?:how (?:can|do|would|should) i|where (?:can|do) i)\b|"
                     r"\s*can i\b.*\b(?:online|with|using|through|via|by (?:phone|text))\b")   # "...with the app?"
_PERSONAL = re.compile(r"\b(?:current |available )?balance (?:in|on|of) my\b|"
                       r"\bmy (?:current |available |account |checking |savings )?balance\b(?!\s*(?:of|is)?\s*\$)|"
                       r"\bmy (?:recent )?(?:transactions|statements?|account number|payoff|due date|credit score|"
                       r"application status|available credit)\b|"
                       r"\b(?:approved|pre-?approved|qualif\w*)\b[\w' ,]{0,40}\b(?:for me|me personally)\b|"
                       r"\bmy (?:approved|personal) (?:rate|apr)\b|"
                       r"\b(?:i|me) personally\b|\bi(?:'ll| will| would)? (?:be|get) approved\b", re.I)
# A date that names a DOCUMENT is not the as-of date: "the article published July 12, 2024", "the January 8, 2026
# grant announcement" ask about that document as it is on the site now (blind set A).
_DOC_BEFORE = re.compile(r"\b(?:published|posted|dated|issued|released|announced|article|announcement|release|"
                         r"blog|post|story|newsletter|news)\b[\w ,]{0,12}$", re.I)
_DOC_AFTER = re.compile(r"^[\w ,'&-]{0,60}?\b(?:article|announcement|press release|news release|release|blog|"
                        r"post|story|newsletter)s?\b", re.I)
# A product variant after a negation is excluded: "not jumbo", "non-jumbo", "rather than the jumbo version",
# "without the jumbo option" (blind set A). Same idea as _CONTRAST for measures.
_NOT_VARIANT = re.compile(r"\b(?:not|non|without|rather than|instead of|other than|excluding|except|no)\b[\s-]+"
                          r"(?:a |an |the )?(?:\w+ ){0,2}?(?:jumbo|specials?|promotional|intro(?:ductory)?)\b", re.I)
# "Looking at the June 9, 2026 website": the website OF A DATE is a time reference, not a link request.
_DATED_WEBSITE = re.compile(r"\b(?:20\d\d|\d{1,2}(?:st|nd|rd|th)?)\s+(?:web ?site|web ?page)s?\b", re.I)
# An explanation question ("What happens if I leave it there?") is not a rate lookup just because it names an amount.
_EXPLAIN = re.compile(r"\bwhat happens\b|\bwhat if\b|^\s*why\b|\bhow does\b.*\bwork\b", re.I)
# A rate AND its minimum in one question: "what APY and minimum deposit", "APY ..., and how much do I need to open".
_RATE_AND_MINIMUM = re.compile(r"\b(?:apys?|aprs?|rates?|dividend rates?|annual percentage (?:yield|rate)|yield)\b"
                               r".{0,80}\b(?:and|plus|,)\b.{0,40}"
                               r"\b(?:minimum|min\.?|how much do i need|to open)\b", re.I)
_DATE_WORDS = re.compile(r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
                         r"sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?,?"
                         r"(?:\s+20\d\d)?\b", re.I)
# "how much space / time": an amount, but not of money (blind set A: "how much space did Dupaco occupy").
_NOT_MONEY = re.compile(r"\bhow (?:much|many) (?:space|room|time|area|square|land|longer|people)\b|\bhow large\b", re.I)
# Two values of one slot compared in one question (blind set A): "the 60-month ... than the 36-month",
# "$30,000 versus $50,000", "from the May 12 ... to the June 9 ... website".
_COMPARE = re.compile(r"\b(?:vs\.?|versus|compared? (?:with|to)|than|same\b.{0,60}\bas|difference|between|both|"
                      r"or|and|change)\b", re.I)
# A conditional yes/no question about a product ("Can Bright Savings pay me dividends if I stay with paper
# statements?") asks about a rule of the account, which the text states: retrieval, not a rate lookup.
_RANGE = re.compile(r"\bbetween\s+\$[\d,.]+\w*\s+and\s+\$|\$[\d,.]+\w*\s*(?:-|–|to)\s*\$", re.I)
_CONDITIONAL = re.compile(r"^\s*(?:can|does|do|will|would|is|are)\b.*\bif\b", re.I)
_MEASURE_WORDS = [("apr", r"\baprs?\b|annual percentage rate"),
                  ("apy", r"\bapys?\b|annual percentage yield|(?<!high-)(?<!high )\byield\b"),
                  ("dividend_rate", r"\bdividend rates?\b"),
                  ("rate", r"\binterest rates?\b")]
_MONTH_END = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
           "nov": 11, "dec": 12}

# "the Mullan Avenue branch", "the Galena Branch", "your Sycamore Street office". Words that are not names:
_NAMED_BRANCH = re.compile(r"(?:\b(?:the|your|at)\s+|^\s*(?!(?i:which|what|where|when|who|how|is|are|do|does|"
                           r"can|any|each|every|your|our|my|a|an)\b))((?:[A-Z][\w.'-]*\s+){0,3}[A-Z][\w.'-]*)\s+"
                           r"(?i:branch|office|location)\b")
_NOT_A_NAME = {"dupaco", "main", "nearest", "closest", "local", "new", "each", "every", "any", "all", "a", "your",
               "same", "other", "different"}

# Prose intents: (intent, pattern). First match wins; checked before rate products.
PROSE_INTENTS = [
    ("routing_number", r"\brouting\b|\baba\b|\btransit number\b"),
    ("founded", r"\b(?:was|is) dupaco (?:founded|established|started)\b|\bdupaco (?:was )?founded\b|"
                r"\byear\b[\w' ]{0,20}\b(?:founded|established)\b|\bhow old is dupaco\b"),
    ("vto_employees", r"\bvolunteer time off\b|\bvto\b"),
    ("forbes_recognition", r"\bforbes\b"),
    ("branch_count", r"\b(?:how many|number of|total)\b[\w' ]{0,25}?\b(?:branch|location|office)"
                     r"|\bbranch (?:count|network)\b"),
    ("employees", r"\bhow many (?:employees|staff|people work)|\bnumber of employees\b"),
    ("members", r"\bhow many members\b|\bnumber of members\b|\bmembership (?:size|count)\b"),
    ("phone", r"\bphone number\b|\btelephone\b|\bcall (?:dupaco|you)\b|\bcontact number\b|\btoll.free\b|"
              # a lost or stolen card, an urgent card problem: the site says to call right away (blind C-026/027)
              r"\b(?:lost|stolen|stole|missing|urgent)\b.{0,30}\bcards?\b|\bcards?\b.{0,30}\b(?:lost|stolen|missing)\b"),
    ("assets", r"\b(?:total )?assets\b|\bhow big is\b|\bhow large is\b"),
    ("eligibility", r"\beligib\w*\b(?=.*\b(?:join|joining|member|membership|become)\b)|"   # not "eligible loans"
                    r"\b(?:join|member|membership)\b.*\beligib|\bwho (?:can|may) (?:join|become|bank)|\bqualify (?:for|to) (?:join|membership|become)"
                    r"|\bcan (?:i|anyone|anybody) (?:join|become a member)|\bmembership requirements?\b"),
    ("closure_alternatives", r"\bwhere (?:can|should|do|will)\b.*\b(?:go|bank|instead)\b"
                             r"|\balternatives?\b|\binstead\b"),
    ("closure", r"\bclos(?:e|es|ed|ing|ure)\b|\bstill open\b|\bshut(?:ting)? down\b|\blast day\b"),
    ("hours", r"\bhours?\b|\bwhat time\b|\bwhen (?:is|are|do|does)\b.*\bopen\b|\bopen on (?:saturday|sunday)\b"
              r"|\b(?:open|close)s? on (?:mon|tues|wednes|thurs|fri|satur|sun)day"),
    ("mailing_address", r"\bmailing address\b|\bmail(?:ing)? (?:a |my |you )?(?:letter|check|payment)\b|"
                        r"\bsend (?:dupaco |you |them )?(?:a )?(?:letter|mail)\b|\bp\.?\s?o\.? box\b"),
    ("address", r"(?<!my )(?<!your )\baddress\b(?! change)|\bwhere is\b|\blocated\b|\bdirections\b"),
]
_PROSE_INTENTS = [(name, re.compile(rx, re.I)) for name, rx in PROSE_INTENTS]
_LINK = re.compile(r"\b(?:link|url|web ?page|web ?site|website|online|sign up|apply online|which page)\b", re.I)
_LOCATOR = re.compile(r"\b(?:find|nearest|closest|near me|locator|locate)\b.*\b(?:branch(?:es)?|atms?|locations?)\b"
                      r"|\b(?:branch(?:es)?|atms?)\b.*\b(?:near me|nearest|closest|locator)\b", re.I)
_JOIN_WORDS = re.compile(r"\bbecome a member\b|\bsign up\b|\bopen (?:an|a new) account\b|\bmembership\b", re.I)
_RATE_WORDS = re.compile(r"\b(?:rates?|aprs?|apys?|interest|dividends?|yield|pays?|earns?|costs?|charges?)\b",
                         re.I)
# A request for a price: refused when no fact answers it. "Does Dupaco charge overdraft fees?" is a yes/no
# question for retrieval; "What do you charge for a construction loan?" asks for a number.
_PRICE_ASK = re.compile(r"\b(?:rates?|aprs?|apys?|interest|dividends?|yield)\b"
                        r"|\b(?:what|how much)\b[\w ]{0,20}\b(?:charge|cost|pay)", re.I)
# Phase 6: a number about the company ("stock price", "the CEO's salary", _COMPANY_NUMBER) is declined; a fee is
# different - the fee schedule states it - so a fee question is searched first (asks_fee).
_STOP = set("a an the of for to on in at is are was were be do does did i me my you your we our us it its this "
            "that what which who whom how when where why can could would should will shall may might must and or "
            "but with about from by as any all some there their they them have has had get give tell know please "
            "dupaco dupaco's current currently right now today "
            "if into onto someone somebody anyone something according whole each".split())   # blind set A


# ----------------------------------------------------------------------------- the query
@dataclass
class Query:
    text: str
    intent: str = "general"
    products: list = field(default_factory=list)
    segment: Optional[str] = None          # "business" / "personal" when the question says so
    account: Optional[str] = None          # "roth" / "traditional"
    purpose: Optional[str] = None          # "purchase" / "refinance" for mortgages
    flags: tuple = ()                      # ("intro",), ("special",), ("jumbo", "special"), ("relief",)
    attribute: Optional[str] = None        # apr / apy / dividend_rate / rate; None = the product's default
    term_months: Optional[int] = None
    x: Optional[float] = None              # model year, balance or loan amount that must fall inside a tier
    x_kind: Optional[str] = None           # "model_year" / "amount"
    superlative: Optional[str] = None      # "max" / "min"
    premise: Optional[float] = None        # "Do any tiers pay 0.35% APY?" -> 0.35
    unpublished: Optional[str] = None      # a mortgage variant with no published rate: "adjustable", "7/1"
    named_branch: Optional[str] = None     # "Mullan Avenue", "Galena"
    subject: Optional[str] = None          # prose subject: "hy-vee", a city, "lobby" / "drive-up" for hours
    date_ref: Optional[str] = None         # a date stated in the question ("as of May 2026" -> 2026-05-31)
    doc_date: Optional[str] = None         # a date naming a document ("the article published July 12, 2024")
    asks_rate: bool = False                # any rate/price word (promotes a product question to a rate lookup)
    asks_price: bool = False               # explicitly asks for a number: refused when nothing answers it
    future: bool = False                   # asks what a rate WILL be (Phase 6): declined, the site has no forecast
    asks_fee: bool = False                 # asks for a money amount, not a rate: search the fee schedule first
    asks_minimum: bool = False             # "minimum deposit / balance to open": a requirement, not a superlative
    asks_points: bool = False              # "rate, points and APR" (mortgage tables have a Points column)
    asks_payment: bool = False             # "what monthly payment does the example show" (Payment Example column)
    personal: bool = False                 # asks for member-specific data ("my balance"): not on a public site
    terms: list = field(default_factory=list)   # content words, for retrieval
    llm_route: Optional[str] = None        # Phase 9: the LLM's reading of the kind of question (interpret.py)
    decline: Optional[str] = None          # Phase 9: why the public site cannot answer (member_data, future...)
    rules_intent: Optional[str] = None     # Phase 9: what the rules parser read, before the LLM's correction
    alt_terms: list = field(default_factory=list)   # Phase 9: the LLM's search words, tried when ours find nothing


def content_words(text: str) -> list:
    return [w for w in re.findall(r"[a-z0-9$]+(?:'[a-z]+)?", text.lower()) if w not in _STOP and len(w) > 1]


def _date_in_question(text: str) -> Optional[str]:
    """'as of May 2026' / '(October 2026)' -> last day of that month; 'March 31, 2026' -> that day.
    A date that names a document ("the article published July 12, 2024") is not an as-of date: None."""
    m = DATE_RE.search(text)
    full = parse_date(text) if m else None
    if full and m is not None and not _names_document(text, m.start(), m.end()):
        return full
    if full:
        return None
    m = _MONTH_YEAR.search(text)
    if not m or _names_document(text, m.start(), m.end()):
        return None
    month, year = _MONTHS[m.group(1)[:3].lower()], int(m.group(2))
    return f"{year:04d}-{month:02d}-{_MONTH_END[month]:02d}"


def _document_date(text: str) -> Optional[str]:
    """The date of the document the question names ("the January 8, 2026 ... announcement"), if any."""
    m = DATE_RE.search(text)
    if m and _names_document(text, m.start(), m.end()):
        return parse_date(text)
    return None


def _names_document(text: str, start: int, end: int) -> bool:
    return bool(_DOC_BEFORE.search(text[:start]) or _DOC_AFTER.search(text[end:]))


def _without_dates(text: str) -> str:
    """The question with its dates blanked, so the year of "As of May 2026" is not read as a model year."""
    for rx in (DATE_RE, _MONTH_YEAR, _YEAR_ONLY):
        text = rx.sub(" ", text)
    return text


def _term(text: str) -> Optional[int]:
    m = _TERM.search(text)
    return _months(m) if m else None


def _months(m) -> int:
    raw, unit = m.group(1).lower(), m.group(2).lower()
    n = _NUMBER_WORDS[raw] if raw in _NUMBER_WORDS else int(raw)
    if unit.startswith(("y",)):
        return n * 12
    return n


def _amount(text: str) -> Optional[float]:
    m = _AMOUNT.search(text)
    if not m:
        w = _AMOUNT_WORDS.search(text)
        if not w:
            return None
        raw = w.group(1).lower()
        return float(_NUMBER_WORDS[raw] if raw in _NUMBER_WORDS else int(raw)) * 1_000
    value = float(m.group(1).replace(",", ""))
    mult = (m.group(2) or "").lower()
    if mult in ("k", "thousand"):
        value *= 1_000
    elif mult in ("m", "million"):
        value *= 1_000_000
    return value


def parse_question(question: str) -> Query:
    text = clean_text(question).strip()
    low = text.lower()
    q = Query(text=text, terms=content_words(_DATE_WORDS.sub(" ", text)))   # a date is not a topic word

    q.date_ref = _date_in_question(text)
    if q.date_ref is None:
        q.doc_date = _document_date(text)
    q.asks_rate = bool(_RATE_WORDS.search(low))
    q.asks_price = bool(_PRICE_ASK.search(low))
    q.segment = "business" if re.search(r"\bbusiness\b", low) else ("personal" if "personal" in low else None)
    if q.segment and re.search(r"\b(?:including|and|also|plus|both)\b[\w ]{0,12}\b(?:business|personal)\b", low):
        q.segment = None                                      # "including business cards": personal AND business
    q.account = "roth" if "roth" in low else ("traditional" if "traditional" in low else None)
    q.purpose = ("cash_out" if re.search(r"\bcash.?out\b", low)
                 else "refinance" if re.search(r"\brefinanc|\brefi\b", low)
                 else "purchase" if re.search(r"\bpurchas|\bbuy", low) else None)
    flags = []
    asked = _NOT_VARIANT.sub(" ", low)                       # "not jumbo": jumbo is excluded, not asked for
    if re.search(r"\bintro(?:ductory)?\b|\bbalance transfer\b|\bpromo", asked):
        flags.append("intro")
    if re.search(r"\bjumbo\b", asked) and "mortgage" not in low:
        flags.append("jumbo")
    if re.search(r"\bspecials?\b|\bpromotional\b|\bjumbo\b", asked) and "intro" not in flags and "mortgage" not in low:
        flags.append("special")
    if re.search(r"\brelief\b", low):
        flags.append("relief")
    q.flags = tuple(sorted(set(flags)))

    wanted = _CONTRAST.sub(" ", low)                         # "... rather than the APY": APY is not asked for
    if re.search(r"\baprs?\b|annual percentage rate", wanted):
        q.attribute = "apr"
    elif re.search(r"\bapys?\b|annual percentage yield|(?<!high-)(?<!high )\byield\b", wanted):   # not "High-Yield"
        q.attribute = "apy"
    elif re.search(r"\bdividend", wanted):
        q.attribute = "dividend_rate"
    elif re.search(r"\binterest rate\b|\brate\b", wanted) and re.search(r"mortgage|home loan|refinanc", wanted):
        q.attribute = "rate"
    named = [a for a, rx in _MEASURE_WORDS if re.search(rx, wanted)]
    if _BOTH_MEASURES.search(low) or len(named) >= 2:
        q.attribute = None                                    # "rate and APR", "the dividend rate and ... the APY"

    q.term_months = _term(text)
    year = _YEAR.search(_without_dates(text))               # "As of May 2026, ... a 2021 vehicle": 2021 (review)
    if year and re.search(r"\bmodel|\bvehicle|\bcar\b|\bauto|\btruck|\bmotorcycle|\batv|\bboat|\bused|\bnew\b",
                          low):
        q.x, q.x_kind = float(year.group(1)), "model_year"
    else:
        amount = _amount(text)
        if amount is not None:
            q.x, q.x_kind = amount, "amount"

    q.asks_minimum = bool(_MINIMUM_FACT.search(low))
    company_number = bool(_COMPANY_NUMBER.search(low))
    q.asks_price = q.asks_price or company_number
    q.asks_fee = bool(_FEE_WORDS.search(low)) and not _RATE_ASK.search(low) and not company_number \
        and not (_NOT_MONEY.search(low) and not re.search(r"\bfees?\b|\bcharges?\b|\bcosts?\b|\$", low))
    if re.search(r"\b(?:highest|best|top|maximum|max|most)\b", low):
        q.superlative = "max"
    elif re.search(r"\b(?:lowest|cheapest|minimum|least)\b", low) and not q.asks_minimum:
        q.superlative = "min"
    pct = _PERCENT.search(text)
    if pct and re.search(r"^\s*(?:do|does|is|are|can|will)\b", low):
        q.premise = float(pct.group(1))

    m = _NAMED_BRANCH.search(text)
    if m and not (len(m.group(1).split()) == 1 and m.group(1).lower() in _NOT_A_NAME) \
            and m.group(1).split()[0].lower() not in ("dupaco", "dupaco's"):
        q.named_branch = m.group(1)                       # "Main Street" is a name; "main branch" is not

    for names, rx in _QUERY_PRODUCTS:
        if rx.search(low):
            q.products = list(names)
            break
    um = MORTGAGE_VARIANTS.search(low)
    if um and q.products == ["mortgage"]:
        q.unpublished = um.group(0).lower()

    # Intent: a link request first, then prose facts, then rates, else general retrieval.
    if _JOIN_WORDS.search(low):
        q.terms.append("join")
    undated = _DATED_WEBSITE.sub(" ", low)                    # "the June 9, 2026 website" is a date, not a link
    if (_LINK.search(undated) and (re.search(r"\blink|\burl|\bweb ?page|\bwhich page|\bwebsite", undated)
                                   or re.search(r"\b(?:join|apply|sign up|enroll|become a member|open)\b.*\bonline\b",
                                                undated))
            and not re.search(r"\bhow many|\bwhat is the (?:rate|apr|apy)", low)) \
            or (_LOCATOR.search(low) and not q.named_branch):   # "where is the Peosta branch": its address
        q.intent = "link"
        return q
    timed = re.search(r"\bwhat time\b|\b(?:mon|tues|wednes|thurs|fri|satur|sun)days?\b|\bweekends?\b", low)
    opening = re.search(r"\bopen\b|\bclos(?:e|es|ing)\b|\blobby\b|\bdrive.?(?:up|thru|through)\b|"
                        r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)days?\b", low)
    counted = re.search(r"\bvolunteer|\btraining\b|\btotal\b", low) or (re.search(r"\bhow many\b", low)
                                                                         and not opening)
    for name, rx in _PROSE_INTENTS:
        permanent = re.search(r"\bclosed? (?:for good|permanently)", low)
        if name in ("closure", "closure_alternatives") and timed and not permanent:
            continue                                       # "What time do branches close on Saturday?" = hours
        if rx.search(low):
            if name in ("closure", "closure_alternatives") and not (q.named_branch or re.search(r"branch", low)):
                continue
            if name == "assets" and q.products:
                continue
            if name == "hours" and not re.search(r"(?<!24-)(?<!24 )\bhours?\b|\bwhat time\b|\bopen\b|\bclose", low):
                continue                                   # "a 24-hour ATM" is a service, not opening hours
            if name == "hours" and (q.products or counted):
                continue                                   # "how many volunteer hours" is a count, not opening hours
            if name == "branch_count" and opening:
                continue                                   # "how many hours is the branch open" is about hours
            q.intent = name
            break
    if q.intent == "hours":
        q.subject = "drive-up" if re.search(r"drive.?(?:up|thru|through)|drive", low) else "lobby"
    if not q.products and q.term_months and "special" in q.flags and q.attribute:
        q.products = ["certificate"]                          # "the 17-month fixed special": specials are certificates
        if q.intent == "general":
            q.intent = "rate"
    if q.products == ["ira savings"] and (q.term_months or "special" in q.flags):
        q.products = ["ira certificate"]                      # IRA terms and specials are certificates
    if q.products == ["mortgage"]:                           # mortgage tables also list points and a payment example
        q.asks_points = bool(re.search(r"\bpoints?\b", low))
        q.asks_payment = bool(re.search(r"\bpayments?\b", low))
    # "merchant Visa processing FEE": a fee, not card APRs. Only the word "fee" counts here: "how much does a CD pay"
    # and "what do the cards charge" ask for a rate.
    fee_only = bool(re.search(r"\bfees?\b", low)) and not _RATE_ASK.search(low)
    explain = (bool(_EXPLAIN.search(low)) and not _RATE_ASK.search(low)   # "what happens if I leave $1,000 there"
               or bool(_CONDITIONAL.search(low)) and not re.search(r"\bwhat\b|\bhow much\b", low))
    both = bool(_RATE_AND_MINIMUM.search(low)) and q.attribute is not None  # "what APY and minimum deposit"
    if q.intent == "general" and q.products and (not q.asks_minimum or both) and not fee_only and not explain and (
            q.asks_rate or q.attribute or q.term_months or q.x is not None):
        q.intent = "rate"
    q.future = bool(_FUTURE.search(low)) and (q.intent == "rate" or q.asks_rate)
    # "What is my balance?" asks for member data; "How can I check my balance?" asks for public guidance (review).
    q.personal = bool(_PERSONAL.search(low)) and not _HOW_TO.match(low)   # "Can I see my balance?" declines
    year_only = _YEAR_ONLY.search(text)
    if year_only and q.intent == "rate" and not q.date_ref:
        q.date_ref = f"{year_only.group(1)}-12-31"           # "the rate in 2019"; "VTO in 2023" is a label (R21)
    return q


# ----------------------------------------------------------------------------- two-part questions
def parts(q: Query) -> list:
    """A rate question comparing two values of ONE slot, split into one query per value (blind set A):
    two terms ("Is the 60-month paying more than the 36-month?"), two amounts ("$30,000 versus $50,000"), two
    as-of dates ("from the May 12, 2026 website to the June 9, 2026 website"). Anything else: [q]."""
    if q.intent != "rate" or not _COMPARE.search(q.text):
        return [q]
    undated = _without_dates(q.text)
    terms = _unique(_months(m) for m in _TERM.finditer(undated))
    if len(terms) >= 2:
        return [replace(q, term_months=t) for t in terms]
    if q.x_kind == "amount" and not _RANGE.search(undated):   # "between $10,000 and $24,999": one range
        amounts = _unique(_amount(m.group(0)) for m in _AMOUNT.finditer(undated))
        if len(amounts) >= 2:
            return [replace(q, x=a) for a in amounts]
    dates = _unique(parse_date(m.group(0)) for m in DATE_RE.finditer(q.text)
                    if not _names_document(q.text, m.start(), m.end()))
    if len(dates) >= 2:
        return [replace(q, date_ref=d) for d in dates]
    return [q]


def _unique(values) -> list:
    out = []
    for v in values:
        if v is not None and v not in out:
            out.append(v)
    return out
