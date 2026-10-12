"""Framework settings: indicator weights, thresholds and phrase rules.

Everything a reviewer may want to tune lives here, so the report can cite one file
for every number the tool uses.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LISTS = DATA / "lists"
CACHE = DATA / "cache"
EVIDENCE = DATA / "evidence"
RESULTS = ROOT / "results"

# Optional contact address sent to OpenAlex and Crossref ("polite pool").
# Leave unset if you do not want to share an email address with these services.
MAILTO = os.environ.get("JOURNALCHECK_MAILTO", "")
USER_AGENT = "JournalCheck/0.1 (B.Tech research project; journal verification)" + (
    f" mailto:{MAILTO}" if MAILTO else ""
)
HTTP_TIMEOUT = 20          # seconds per request
CACHE_DAYS = 30            # cached API answers older than this are fetched again

# --------------------------------------------------------------------------------------
# Indicator catalogue: id -> (category, short name, points, used by the ML model)
# Points add up to 40, the same total as the mini-project checklist.
# --------------------------------------------------------------------------------------
INDICATORS: dict[str, dict] = {
    "I1":  {"cat": "A", "name": "ISSN valid and registered",               "points": 2, "ml": True},
    "I2":  {"cat": "A", "name": "Website title matches registry",          "points": 2, "ml": True},
    "I3":  {"cat": "A", "name": "Website domain matches registry",         "points": 2, "ml": True},
    "I4":  {"cat": "A", "name": "Domain age fits journal history",         "points": 2, "ml": True},
    "I5":  {"cat": "B", "name": "Indexed in DOAJ or Scopus",               "points": 2, "ml": False},
    "I6":  {"cat": "B", "name": "No unofficial impact factor",             "points": 3, "ml": True},
    "I7":  {"cat": "B", "name": "No misleading quality badges",            "points": 3, "ml": True},
    "I8":  {"cat": "C", "name": "No guaranteed speed or acceptance",       "points": 3, "ml": True},
    "I9":  {"cat": "C", "name": "Peer-review policy linked",               "points": 1, "ml": True},
    "I10": {"cat": "C", "name": "Editorial board linked",                  "points": 1, "ml": True},
    "I11": {"cat": "D", "name": "Fees disclosed",                          "points": 2, "ml": True},
    "I12": {"cat": "D", "name": "No add-on incentives",                    "points": 2, "ml": True},
    "I13": {"cat": "D", "name": "Professional contact email",              "points": 1, "ml": True},
    "I14": {"cat": "E", "name": "Focused scope",                           "points": 2, "ml": True},
    "I15": {"cat": "E", "name": "Plausible publication volume",            "points": 2, "ml": True},
    "I16": {"cat": "F", "name": "Licence declared",                        "points": 1, "ml": True},
    "I17": {"cat": "F", "name": "Crossref DOIs registered",                "points": 2, "ml": True},
    "I18": {"cat": "F", "name": "Ethics or retraction policy linked",      "points": 1, "ml": True},
    "I19": {"cat": "G", "name": "Not on the hijacked-journal list",        "points": 2, "ml": False},
    "I20": {"cat": "G", "name": "Not in the Beall's list archive",         "points": 2, "ml": False},
    "I21": {"cat": "G", "name": "No integrity alert",                      "points": 2, "ml": False},
}
TOTAL_POINTS = sum(v["points"] for v in INDICATORS.values())
assert TOTAL_POINTS == 40, TOTAL_POINTS
LIST_INDICATORS = [k for k, v in INDICATORS.items() if not v["ml"]]

CATEGORY_NAMES = {
    "A": "Identity and registration",
    "B": "Indexing and metrics",
    "C": "Editorial and peer review",
    "D": "Fees and business practices",
    "E": "Scope and volume",
    "F": "Licensing and preservation",
    "G": "External evidence",
}

MANUAL_CHECKS = {
    "M1": "Editors are real, in the field and listed with consent (check 3 on university pages)",
    "M2": "Three to five recent articles are relevant, coherent and properly referenced",
    "M3": "No flattering mass invitations or pressure to pay (check your inbox)",
    "M4": "Any claimed COPE membership is confirmed on publicationethics.org",
    "M5": "No court or regulator finding against the publisher",
}

# Points earned by an indicator that could not be checked (same convention as the mini project).
UNKNOWN_SHARE = 0.5

# --------------------------------------------------------------------------------------
# Decision rules
# --------------------------------------------------------------------------------------
BAND_LOW_RISK = 80     # trust score >= 80 -> Low risk
BAND_CAUTION = 50      # 50 <= trust score < 80 -> Caution; below 50 -> High risk
HYBRID_WEIGHT_RULES = 0.5
REVIEW_DISAGREEMENT = 30   # |T(rule) - T(ML)| at or above this needs a human review
REVIEW_MIN_COVERAGE = 0.60
INTEGRITY_RETRACTIONS = 10     # at least this many retractions in the Retraction Watch database ...
INTEGRITY_RATE = 0.005         # ... and at least 5 retractions per 1,000 papers trigger an integrity alert

# Indicator thresholds
TITLE_MATCH_RATIO = 0.85
DOMAIN_GRACE_YEARS = 2       # I4: domain may be registered up to this many years after the first issue ...
DOMAIN_WEB_YEAR = 1995       # ... or after this year, for journals that began before the web
# Domains run by one publisher: a journal page on one and a registry homepage on another is not a mismatch (I3)
PUBLISHER_DOMAIN_GROUPS = [
    {"elsevier.com", "sciencedirect.com", "cell.com", "thelancet.com"},
    {"springer.com", "springeropen.com", "biomedcentral.com", "nature.com", "springernature.com"},
    {"wiley.com", "onlinelibrary.wiley.com", "hindawi.com"},
    {"tandfonline.com", "taylorandfrancis.com", "routledge.com"},
    {"ieee.org", "computer.org"},
    {"acm.org"},
    {"oup.com", "academic.oup.com"},
    {"cambridge.org"},
    {"sagepub.com"},
    {"mdpi.com"},
    {"frontiersin.org"},
    {"iop.org", "iopscience.iop.org"},
]
VOLUME_MIN_PAPERS = 500      # I15: growth is only judged above this yearly output
VOLUME_MAX_GROWTH = 3.0      # I15: year-on-year growth factor that counts as a sudden jump
SCOPE_MIN_TOP_FIELD = 0.35   # I14: share of the journal's papers in its main field
SPEED_MAX_DAYS = 10          # I8: promises of review/publication within this many days are red flags

FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "ymail.com",
    "hotmail.com", "outlook.com", "live.com", "msn.com", "aol.com", "rediffmail.com",
    "mail.ru", "yandex.com", "yandex.ru", "163.com", "126.com", "qq.com", "protonmail.com",
    "proton.me", "gmx.com", "zoho.com", "icloud.com",
}

# --------------------------------------------------------------------------------------
# Phrase rules for the home page (case-insensitive regular expressions)
# --------------------------------------------------------------------------------------
def _rx(*patterns: str) -> list[re.Pattern]:
    return [re.compile(p, re.I) for p in patterns]

FAKE_METRIC_PATTERNS = _rx(
    r"\bSJIF\b", r"scientific journal impact factor", r"index\s+copernicus", r"\bICV\b",
    r"global impact factor", r"universal impact factor", r"cosmos impact factor",
    r"international impact factor", r"\bIIFS\b", r"journal impact factor services",
    r"\bI2OR\b", r"general impact factor", r"citefactor", r"innospace", r"\bIJIF\b",
    r"research\s?bib", r"advanced sciences index", r"scholarly impact factor",
    r"impact factor\s*\(?\s*(?:20\d\d)?\s*\)?\s*[:=-]\s*\d+\.\d{2,3}\b.{0,40}(?:sjif|icv|calculated|isra|gif|ijif)",
)
BADGE_PATTERNS = _rx(
    r"ugc[\s-]*(?:care\s*)?(?:approved|listed|recogni[sz]ed)", r"approved by ugc",
    r"ugc[\s-]*care\s*(?:group|list)", r"\bISO\s*9001", r"\bISO\s*(?:certified|certification)",
    r"\bMSME\b", r"(?:indexed|indexing)\s+(?:in|by)\s+google\s+scholar",
)
INCENTIVE_PATTERNS = _rx(
    r"certificate of publication", r"publication certificate", r"e-?certificates?",
    r"hard\s*-?\s*cop(?:y|ies)", r"printed cop(?:y|ies)", r"refer(?:ral)?\s+(?:and|&)\s+earn",
    r"referral (?:program|scheme|bonus)", r"mentorship program", r"free certificate",
)
SCOPE_PATTERNS = _rx(
    r"all (?:subjects|disciplines|areas of (?:science|engineering|research)|fields of (?:science|engineering|research))",
    r"engineering,?\s+(?:applied\s+)?sciences?,?\s+(?:and\s+)?(?:technology\s+)?(?:and\s+)?management",
    r"science,\s*technology,\s*engineering,?\s*(?:and\s+)?management",
    r"arts,\s*(?:humanities,\s*)?(?:commerce,\s*)?science",
    r"multidisciplinary (?:international )?(?:research )?journal (?:of|for) all",
)
# Speed promises: a number + a unit near a publishing verb. The number is judged in features.py.
SPEED_PATTERN = re.compile(
    r"(?:review|publish(?:ed|ing)?|publication|acceptance|accepted|decision|notification)"
    r"[^.\n]{0,40}?\b(?:within|in|on)\s+(\d{1,3}|one|two|three|four|five|six|seven)\s*-?\s*(hours?|hrs?|days?|weeks?)\b",
    re.I,
)
SPEED_EXTRA_PATTERNS = _rx(
    r"same[- ]day publication", r"publication\s*:\s*in\s*\d+\s*days", r"review status\s*:\s*in\s*\d",
    r"24\s*(?:hours|hrs)\s*(?:review|publication|acceptance)", r"instant (?:publication|acceptance)",
    r"guaranteed (?:publication|acceptance)",
)
INDEXING_CLAIM_PATTERNS = {
    "scopus": re.compile(r"(?:indexed|indexing|abstracted|covered|listed)\s+(?:in|by)[^.\n]{0,80}\bscopus\b|\bscopus[\s-]+indexed\b", re.I),
    "doaj": re.compile(r"(?:indexed|indexing|listed)\s+(?:in|by)[^.\n]{0,80}\b(?:DOAJ|directory of open access journals)\b|\bDOAJ[\s-]+indexed\b", re.I),
}
COPE_PATTERN = re.compile(r"\bCOPE\b|committee on publication ethics", re.I)

LINK_PATTERNS = {
    "peer_review": re.compile(r"peer[\s-]?review|review process|review policy|reviewer guidelines", re.I),
    "editorial": re.compile(r"editorial (?:board|team|committee)|editor[\s-]in[\s-]chief|editors\b", re.I),
    "ethics": re.compile(r"ethic|malpractice|retraction|plagiarism|misconduct|corrections policy", re.I),
    "fees": re.compile(r"\bAPCs?\b|article processing|publication (?:fee|charge)|fees|charges|pricing|open access fee", re.I),
    "deep": re.compile(r"call for papers|author guidelines|instructions for authors|guide for authors|submission|fees|charges|about|aims", re.I),
}
FEES_TEXT_PATTERN = re.compile(
    r"article processing charge|\bAPCs?\b|publication fee|processing fee|no (?:publication |submission )?(?:fee|charge)s?|free of charge|does not charge",
    re.I,
)

ISSN_PATTERN = re.compile(r"\b(\d{4})(?:\s?[-\u2010\u2011\u2012\u2013\u2014\u2212]\s?|\s)(\d{3}[\dXx])\b")
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
