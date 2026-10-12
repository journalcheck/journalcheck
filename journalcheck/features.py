"""Turns collected evidence into the 21 indicators and the numeric ML features."""
from __future__ import annotations

import datetime as _dt
import math

from . import config
from .util import contains_title, issn_checksum_ok, registered_domain, same_site, similarity

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}


def _hits(patterns, text: str, limit: int = 3) -> list[str]:
    found = []
    for p in patterns:
        m = p.search(text or "")
        if m:
            found.append(" ".join(m.group(0).split())[:80])
        if len(found) >= limit:
            break
    return found


def speed_promises(text: str) -> list[str]:
    """Explicit promises of review/publication within SPEED_MAX_DAYS (hours always count)."""
    out = []
    for m in config.SPEED_PATTERN.finditer(text or ""):
        num, unit = m.group(1).lower(), m.group(2).lower()
        n = int(num) if num.isdigit() else _WORDS.get(num)
        if n is None:
            continue
        days = n / 24 if unit.startswith(("hour", "hr")) else n * 7 if unit.startswith("week") else n
        if days <= config.SPEED_MAX_DAYS:
            out.append(" ".join(m.group(0).split())[:80])
        if len(out) >= 3:
            break
    out += _hits(config.SPEED_EXTRA_PATTERNS, text, 3 - len(out)) if len(out) < 3 else []
    return out


def _links(site: dict, key: str) -> list[str]:
    pat = config.LINK_PATTERNS[key]
    return [l["text"] for l in site.get("links", []) if l.get("text") and pat.search(l["text"])][:3]


def _ind(iid: str, result: str, evidence: str) -> dict:
    pts = config.INDICATORS[iid]["points"]
    earned = pts if result == PASS else 0 if result == FAIL else pts * config.UNKNOWN_SHARE
    return {"id": iid, "name": config.INDICATORS[iid]["name"], "category": config.INDICATORS[iid]["cat"],
            "result": result, "points": earned, "max": pts, "evidence": evidence}


def compute(ev: dict) -> dict:
    oa, cr, dj = ev.get("openalex") or {}, ev.get("crossref") or {}, ev.get("doaj") or {}
    site, rd, lists = ev.get("site") or {}, ev.get("rdap") or {}, ev.get("lists") or {}
    issn = ev.get("issn")
    have_site = site.get("status") == "found"
    text = site.get("all_text", "") if have_site else ""
    site_url = site.get("final_url") or site.get("url")
    reg_found = oa.get("status") == "found" or cr.get("status") == "found"
    reg_checked = oa.get("status") in ("found", "not_found") and cr.get("status") in ("found", "not_found")
    inds = {}

    # ---------------- A. identity
    if not issn:
        inds["I1"] = _ind("I1", UNKNOWN if not site.get("issns_found") and not have_site else FAIL,
                          "No ISSN given or shown on the website")
    elif not issn_checksum_ok(issn):
        inds["I1"] = _ind("I1", FAIL, f"ISSN {issn} has an invalid check digit")
    elif reg_found:
        inds["I1"] = _ind("I1", PASS, f"ISSN {issn} resolves in " + " and ".join(
            n for n, s in (("OpenAlex", oa), ("Crossref", cr)) if s.get("status") == "found"))
    elif reg_checked:
        inds["I1"] = _ind("I1", FAIL, f"ISSN {issn} is valid but has no OpenAlex or Crossref record")
    else:
        inds["I1"] = _ind("I1", UNKNOWN, "Registries could not be reached")

    reg_titles = [t for t in [oa.get("title"), cr.get("title"), dj.get("title")] + list(oa.get("alternate_titles") or []) if t]
    if have_site and reg_titles:
        site_titles = [site.get("title"), site.get("site_name"), site.get("heading")]
        best = max(similarity(a, b) for a in reg_titles for b in site_titles if b) if any(site_titles) else 0
        contained = any(contains_title(" ".join(filter(None, site_titles)) + " " + text[:3000], t) for t in reg_titles)
        ok = best >= config.TITLE_MATCH_RATIO or contained
        inds["I2"] = _ind("I2", PASS if ok else FAIL,
                          f"Registry title '{reg_titles[0]}' {'found on' if ok else 'not found on'} the website (best similarity {best:.2f})")
    else:
        inds["I2"] = _ind("I2", UNKNOWN, "Website or registry title unavailable")

    reg_urls = [u for u in [oa.get("homepage_url"), dj.get("url")] if u]
    site_dom = registered_domain(site_url) if site_url else None
    if site_dom and reg_urls:
        reg_doms = {registered_domain(u) for u in reg_urls}
        ok = any(same_site(site_url, u) for u in reg_urls)
        inds["I3"] = _ind("I3", PASS if ok else FAIL,
                          f"Website domain {site_dom} {'matches' if ok else 'differs from'} registry homepage {', '.join(sorted(d for d in reg_doms if d))}")
    else:
        inds["I3"] = _ind("I3", UNKNOWN, "No registry homepage to compare with")

    first_year = oa.get("first_publication_year")
    dom_year = rd.get("registered_year")
    if dom_year and first_year:
        late = dom_year - max(first_year, config.DOMAIN_WEB_YEAR)
        ok = late <= config.DOMAIN_GRACE_YEARS
        inds["I4"] = _ind("I4", PASS if ok else FAIL,
                          f"Domain {rd.get('domain')} registered {dom_year}; journal publishing since {first_year}")
    else:
        inds["I4"] = _ind("I4", UNKNOWN, "Domain registration date or first publication year unavailable")

    # ---------------- B. indexing and metrics
    in_doaj = dj.get("status") == "found" or bool(oa.get("is_in_doaj"))
    in_scopus = lists.get("scopus")
    if in_doaj or in_scopus:
        inds["I5"] = _ind("I5", PASS, "Indexed in " + " and ".join(n for n, v in (("DOAJ", in_doaj), ("Scopus (SCImago list)", in_scopus)) if v))
    elif dj.get("status") == "not_found" and in_scopus is False:
        inds["I5"] = _ind("I5", FAIL, "Not found in DOAJ or in the SCImago (Scopus) list")
    else:
        inds["I5"] = _ind("I5", UNKNOWN, "DOAJ or SCImago list unavailable")

    for iid, pats, label in (("I6", config.FAKE_METRIC_PATTERNS, "Unofficial metric"),
                             ("I7", config.BADGE_PATTERNS, "Misleading badge")):
        if not have_site:
            inds[iid] = _ind(iid, UNKNOWN, "Website not reachable")
        else:
            h = _hits(pats, text)
            inds[iid] = _ind(iid, FAIL if h else PASS, f"{label}: " + "; ".join(f"'{x}'" for x in h) if h else f"No {label.lower()} found")

    # ---------------- C. editorial
    if not have_site:
        for iid in ("I8", "I9", "I10"):
            inds[iid] = _ind(iid, UNKNOWN, "Website not reachable")
    else:
        sp = speed_promises(text)
        inds["I8"] = _ind("I8", FAIL if sp else PASS, ("Speed promise: " + "; ".join(f"'{x}'" for x in sp)) if sp else "No promise of fast acceptance or publication")
        pr = _links(site, "peer_review") or (["(text)"] if config.LINK_PATTERNS["peer_review"].search(text) else [])
        inds["I9"] = _ind("I9", PASS if pr else FAIL, f"Peer-review link: {pr[0]}" if pr else "No peer-review policy found")
        eb = _links(site, "editorial") or (["(text)"] if config.LINK_PATTERNS["editorial"].search(text) else [])
        inds["I10"] = _ind("I10", PASS if eb else FAIL, f"Editorial link: {eb[0]}" if eb else "No editorial board found")

    # ---------------- D. fees and business
    fee_sources = []
    if oa.get("apc_usd") is not None:
        fee_sources.append(f"OpenAlex APC US${oa.get('apc_usd')}")
    if dj.get("status") == "found" and dj.get("has_apc") is not None:
        fee_sources.append("DOAJ fee record")
    if have_site and (_links(site, "fees") or config.FEES_TEXT_PATTERN.search(text)):
        fee_sources.append("fee information on the website")
    if fee_sources:
        inds["I11"] = _ind("I11", PASS, "Fees disclosed: " + "; ".join(fee_sources))
    elif have_site:
        inds["I11"] = _ind("I11", FAIL, "No fee information found")
    else:
        inds["I11"] = _ind("I11", UNKNOWN, "Website not reachable")

    if have_site:
        inc = _hits(config.INCENTIVE_PATTERNS, text)
        inds["I12"] = _ind("I12", FAIL if inc else PASS, ("Incentive: " + "; ".join(f"'{x}'" for x in inc)) if inc else "No add-on incentives found")
        emails = site.get("emails") or []
        free = [e for e in emails if e.split("@")[-1] in config.FREE_EMAIL_DOMAINS]
        if free:
            inds["I13"] = _ind("I13", FAIL, f"Free webmail contact: {free[0]}")
        elif emails:
            inds["I13"] = _ind("I13", PASS, f"Contact email: {emails[0]}")
        else:
            inds["I13"] = _ind("I13", UNKNOWN, "No contact email on the pages checked")
    else:
        for iid in ("I12", "I13"):
            inds[iid] = _ind(iid, UNKNOWN, "Website not reachable")

    # ---------------- E. scope and volume
    scope_hits = _hits(config.SCOPE_PATTERNS, text) if have_site else []
    share = oa.get("top_field_share")
    if scope_hits:
        inds["I14"] = _ind("I14", FAIL, "Unfocused scope: " + "; ".join(f"'{x}'" for x in scope_hits))
    elif share is not None and share < config.SCOPE_MIN_TOP_FIELD:
        inds["I14"] = _ind("I14", FAIL, f"Only {share:.0%} of topics in the main field ({oa.get('top_field')})")
    elif share is not None or have_site:
        inds["I14"] = _ind("I14", PASS, f"Main field {oa.get('top_field')} ({share:.0%} of topics)" if share is not None else "No all-subjects wording found")
    else:
        inds["I14"] = _ind("I14", UNKNOWN, "No scope information")

    growth, peak_year = max_growth(oa.get("counts_by_year") or [])
    if oa.get("status") == "found" and oa.get("counts_by_year"):
        bad = growth is not None and growth >= config.VOLUME_MAX_GROWTH
        inds["I15"] = _ind("I15", FAIL if bad else PASS,
                           f"Output grew {growth:.1f}x in {peak_year}" if bad else "No sudden jump in yearly output")
    else:
        inds["I15"] = _ind("I15", UNKNOWN, "No yearly publication counts")

    # ---------------- F. licensing and preservation
    lic = dj.get("licenses") or []
    lic_cr = cr.get("licenses_current")
    if lic or (lic_cr is not None and lic_cr >= 0.5):
        inds["I16"] = _ind("I16", PASS, "Licence: " + (", ".join(lic) if lic else f"{lic_cr:.0%} of recent Crossref records carry a licence"))
    elif cr.get("status") == "found" or dj.get("status") == "found":
        inds["I16"] = _ind("I16", FAIL, "No licence in DOAJ or Crossref metadata")
    else:
        inds["I16"] = _ind("I16", UNKNOWN, "No DOAJ or Crossref record")

    if cr.get("status") == "found" and (cr.get("total_dois") or 0) > 0:
        inds["I17"] = _ind("I17", PASS, f"{cr.get('total_dois')} DOIs registered with Crossref")
    elif cr.get("status") in ("found", "not_found"):
        inds["I17"] = _ind("I17", FAIL, "No Crossref DOIs for this ISSN")
    else:
        inds["I17"] = _ind("I17", UNKNOWN, "Crossref not reachable")

    if have_site:
        et = _links(site, "ethics") or (["(text)"] if config.LINK_PATTERNS["ethics"].search(text) else [])
        inds["I18"] = _ind("I18", PASS if et else FAIL, f"Ethics link: {et[0]}" if et else "No ethics or retraction policy found")
    else:
        inds["I18"] = _ind("I18", UNKNOWN, "Website not reachable")

    # ---------------- G. external evidence
    hj = lists.get("hijacked")
    if hj is None:
        inds["I19"] = _ind("I19", UNKNOWN, "Hijacked-journal list not loaded")
    else:
        inds["I19"] = _ind("I19", FAIL if hj["listed"] else PASS,
                           f"Website listed as a clone of '{hj['matched_title']}'" if hj["listed"] else "Website not on the hijacked list")
    bl = lists.get("bealls")
    if bl is None:
        inds["I20"] = _ind("I20", UNKNOWN, "Beall's archive not loaded")
    else:
        inds["I20"] = _ind("I20", FAIL if bl["listed"] else PASS, ("Beall's archive: " + "; ".join(bl["hits"])) if bl["listed"] else "Not in the Beall's archive")
    ig = lists.get("integrity")
    if ig is None:
        inds["I21"] = _ind("I21", UNKNOWN, "Integrity lists not loaded")
    else:
        inds["I21"] = _ind("I21", FAIL if ig["alert"] else PASS, ("Integrity alert: " + "; ".join(ig["reasons"])) if ig["alert"] else "No delisting or retraction alert")

    # ---------------- override flags
    claims = {k: bool(p.search(text)) for k, p in config.INDEXING_CLAIM_PATTERNS.items()} if have_site else {}
    false_claims = []
    if claims.get("scopus") and in_scopus is False:
        false_claims.append("claims Scopus indexing but is not in the SCImago (Scopus) list")
    if claims.get("doaj") and dj.get("status") == "not_found" and not oa.get("is_in_doaj"):
        false_claims.append("claims DOAJ indexing but is not in DOAJ")
    flags = {
        "k1_hijacked": inds["I19"]["result"] == FAIL,
        "possible_clone": inds["I3"]["result"] == FAIL and inds["I4"]["result"] == FAIL,
        "k3_false_claims": false_claims,
        "integrity_alert": inds["I21"]["result"] == FAIL,
        "cope_claim": bool(have_site and config.COPE_PATTERN.search(text)),
    }
    return {"indicators": inds, "numeric": numeric_features(ev, inds, growth), "flags": flags}


def max_growth(counts: list[dict]) -> tuple[float | None, int | None]:
    """Largest year-on-year growth factor among years with at least VOLUME_MIN_PAPERS papers.

    The current (incomplete) year is ignored.
    """
    this_year = _dt.date.today().year
    rows = sorted((c["year"], c.get("works") or 0) for c in counts if c.get("year") and c["year"] < this_year)
    best, best_year = None, None
    for (y0, w0), (y1, w1) in zip(rows, rows[1:]):
        if y1 == y0 + 1 and w1 >= config.VOLUME_MIN_PAPERS:
            g = w1 / max(w0, 1)
            if best is None or g > best:
                best, best_year = g, y1
    return best, best_year


def numeric_features(ev: dict, inds: dict, growth: float | None) -> dict:
    oa, site, rd = ev.get("openalex") or {}, ev.get("site") or {}, ev.get("rdap") or {}
    this_year = _dt.date.today().year
    counts = sorted((c["year"], c.get("works") or 0) for c in oa.get("counts_by_year") or [] if c.get("year") and c["year"] < this_year)
    text = site.get("all_text", "") if site.get("status") == "found" else ""
    red_flags = sum(len(_hits(p, text, 99)) for p in (config.FAKE_METRIC_PATTERNS, config.BADGE_PATTERNS, config.INCENTIVE_PATTERNS, config.SCOPE_PATTERNS)) + len(speed_promises(text))
    works = oa.get("works_count")
    cites = oa.get("cited_by_count")
    log = lambda v: math.log1p(v) if isinstance(v, (int, float)) and v >= 0 else None
    return {
        "papers_last_year": counts[-1][1] if counts else None,
        "log_works_count": log(works),
        "journal_age": (this_year - oa["first_publication_year"]) if oa.get("first_publication_year") else None,
        "domain_age": (this_year - rd["registered_year"]) if rd.get("registered_year") else None,
        "apc_usd": oa.get("apc_usd"),
        "two_yr_mean_citedness": oa.get("two_yr_mean_citedness"),
        "log_h_index": log(oa.get("h_index")),
        "cites_per_paper": (cites / works) if works and cites is not None else None,
        "top_field_share": oa.get("top_field_share"),
        "max_growth": growth,
        "red_flag_phrases": red_flags if site.get("status") == "found" else None,
        "site_reachable": 1.0 if site.get("status") == "found" else 0.0,
        "https": (1.0 if site.get("https") else 0.0) if site.get("status") == "found" else None,
        "tls_error": 1.0 if site.get("tls_error") else 0.0,
    }
