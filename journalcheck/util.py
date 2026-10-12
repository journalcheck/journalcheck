"""Small helpers: ISSN checks, domains, text normalisation, cached HTTP."""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlparse

import requests
import urllib3

from . import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------- ISSN

def normalize_issn(value: str | None) -> str | None:
    """Return 'NNNN-NNNC' or None."""
    if not value:
        return None
    s = re.sub(r"[^0-9Xx]", "", str(value)).upper()
    if len(s) != 8:
        return None
    return f"{s[:4]}-{s[4:]}"


def issn_checksum_ok(issn: str | None) -> bool:
    """ISO 3297 check digit: weights 8..2 on the first seven digits, mod 11."""
    issn = normalize_issn(issn)
    if not issn:
        return False
    digits = issn.replace("-", "")
    if not digits[:7].isdigit():
        return False
    total = sum(int(d) * w for d, w in zip(digits[:7], range(8, 1, -1)))
    check = (11 - total % 11) % 11
    expected = "X" if check == 10 else str(check)
    return digits[7] == expected


def find_issns(text: str) -> list[str]:
    """All ISSNs with a valid check digit found in a block of text, in order."""
    out: list[str] = []
    for a, b in config.ISSN_PATTERN.findall(text or ""):
        issn = normalize_issn(a + b)
        if issn and issn_checksum_ok(issn) and issn not in out:
            out.append(issn)
    return out

# ---------------------------------------------------------------- domains

_TWO_LEVEL_SUFFIXES = {
    "co.in", "ac.in", "org.in", "net.in", "gov.in", "edu.in", "res.in", "nic.in",
    "co.uk", "ac.uk", "org.uk", "com.au", "edu.au", "org.au", "net.au", "co.nz", "ac.nz",
    "com.br", "org.br", "edu.br", "com.cn", "edu.cn", "org.cn", "ac.cn", "co.jp", "ac.jp",
    "com.my", "edu.my", "com.ng", "edu.ng", "com.pk", "edu.pk", "ac.id", "co.id", "or.id",
    "com.tr", "edu.tr", "org.tr", "ac.ir", "ac.za", "co.za", "com.mx", "edu.mx", "com.ua",
    "com.sg", "edu.sg", "com.eg", "edu.eg", "ac.th", "co.th", "com.ph", "edu.ph",
}


_SECOND_LEVEL_WORDS = {"co", "ac", "or", "go", "ne", "re", "com", "edu", "org", "net", "gov", "gob", "mil", "nic",
                       "res", "sch", "info", "biz", "nom", "lg", "ed", "in", "web"}


def hostname(url: str | None) -> str | None:
    if not url:
        return None
    if "://" not in url:
        url = "http://" + url
    host = (urlparse(url).hostname or "").lower().strip(".")
    return host or None


def registered_domain(url_or_host: str | None) -> str | None:
    """'https://www.ijert.org/x' -> 'ijert.org'; handles common two-level suffixes."""
    host = hostname(url_or_host) if url_or_host and ("/" in url_or_host or ":" in url_or_host) else (url_or_host or "").lower()
    if not host:
        return None
    parts = host.split(".")
    if len(parts) >= 3 and (".".join(parts[-2:]) in _TWO_LEVEL_SUFFIXES or
                            (len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL_WORDS)):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host

def same_site(url_a: str | None, url_b: str | None) -> bool:
    """True when two web addresses belong to the same site or to one publisher's platforms."""
    a, b = registered_domain(url_a), registered_domain(url_b)
    if not a or not b:
        return False
    if a == b:
        return True
    return any(a in group and b in group for group in config.PUBLISHER_DOMAIN_GROUPS)

# ---------------------------------------------------------------- text

def norm_title(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"\bthe\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def similarity(a: str | None, b: str | None) -> float:
    a, b = norm_title(a), norm_title(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def contains_title(haystack: str | None, title: str | None) -> bool:
    h, t = norm_title(haystack), norm_title(title)
    return bool(t) and len(t) >= 8 and t in h

# ---------------------------------------------------------------- HTTP with a file cache

_session = requests.Session()
_session.headers.update({"User-Agent": config.USER_AGENT, "Accept-Language": "en"})


def _cache_path(key: str):
    config.CACHE.mkdir(parents=True, exist_ok=True)
    return config.CACHE / (hashlib.sha1(key.encode()).hexdigest() + ".json")


def fetch(url: str, *, params: dict | None = None, as_json: bool = True, use_cache: bool = True,
          timeout: int | None = None, verify: bool = True) -> dict:
    """GET a URL and return {'ok', 'status', 'data' | 'text', 'url', 'error', 'fetched_at'}.

    Answers are cached on disk so a dataset run can be repeated and audited.
    'ok' is False on network errors; 'status' 404 means "checked and not found".
    """
    key = url + ("?" + json.dumps(params, sort_keys=True) if params else "") + ("#json" if as_json else "#text")
    path = _cache_path(key)
    if use_cache and path.exists():
        cached = json.loads(path.read_text())
        if time.time() - cached.get("fetched_ts", 0) < config.CACHE_DAYS * 86400:
            return cached
    result: dict = {"url": url, "params": params, "ok": False, "status": None, "error": None,
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "fetched_ts": time.time()}
    for attempt in range(3):
        try:
            r = _session.get(url, params=params, timeout=timeout or config.HTTP_TIMEOUT,
                             verify=verify, allow_redirects=True)
            result["status"] = r.status_code
            result["final_url"] = r.url
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            result["ok"] = r.status_code < 400 or r.status_code == 404
            if r.status_code < 400:
                if as_json:
                    try:
                        result["data"] = r.json()
                    except ValueError:
                        result["ok"] = False
                        result["error"] = "invalid JSON"
                else:
                    r.encoding = r.encoding or r.apparent_encoding
                    result["text"] = r.text[:2_000_000]
            break
        except requests.exceptions.SSLError as e:
            if verify:  # many questionable sites have broken certificates; retry once without checking
                result["tls_error"] = True
                verify = False
                continue
            result["error"] = f"SSL: {e.__class__.__name__}"
            break
        except requests.RequestException as e:
            result["error"] = e.__class__.__name__
            time.sleep(1 + attempt)
    if use_cache and (result["ok"] or result["status"] in (404, 410)):
        _cache_path(key).write_text(json.dumps(result))
    return result
