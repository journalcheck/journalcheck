"""End-to-end check of one journal: resolve -> collect evidence -> indicators -> scores -> verdict."""
from __future__ import annotations

import csv
import re
import time

from . import config, features, scoring
from .collectors import lists as lists_mod
from .collectors import registries as reg
from .collectors.website import fetch_site
from .util import norm_title, normalize_issn, registered_domain, similarity


def _court_findings() -> list[dict]:
    path = config.LISTS / "court_findings.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def collect_evidence(issn: str | None = None, title: str | None = None, url: str | None = None,
                     deep: bool = True) -> dict:
    t0 = time.time()
    ev: dict = {"input": {"issn": issn, "title": title, "url": url},
                "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "notes": []}
    issn = normalize_issn(issn)
    site = fetch_site(url, deep=deep) if url else None

    # Resolve an ISSN when only a URL or a title was given.
    if not issn and site and site.get("issns_found"):
        for cand in site["issns_found"][:4]:
            if reg.openalex_source(cand)["status"] == "found":
                issn = cand
                break
        issn = issn or site["issns_found"][0]
        ev["notes"].append(f"ISSN {issn} read from the website")
    if not issn and (title or (site and site.get("status") == "found")):
        # search OpenAlex by the given title, or by the website's own title, and accept a candidate
        # whose title matches closely or whose homepage is this website
        site_dom = registered_domain(site.get("final_url")) if site and site.get("status") == "found" else None
        queries = [q for q in [title, (site or {}).get("site_name"), (site or {}).get("title"), (site or {}).get("heading")] if q]
        for q in queries:
            q = q.split("|")[0].split(" - ")[0].strip()
            q = re.sub(r"^[A-Z]{2,10}\s*[-:\u2013]\s*", "", q)[:150]  # drop a leading acronym such as "IRJET- "
            if len(q) < 4:
                continue
            cands = reg.openalex_search(q).get("candidates") or []
            pick = next((c for c in cands if site_dom and c.get("homepage_url") and registered_domain(c["homepage_url"]) == site_dom and c.get("issn_l")), None)
            if pick is None and title:
                best = max(cands, key=lambda c: similarity(c["title"], title), default=None)
                pick = best if best and best.get("issn_l") and similarity(best["title"], title) >= 0.9 else None
            if pick:
                issn = pick["issn_l"]
                ev["notes"].append(f"ISSN {issn} found by searching OpenAlex for '{q}'")
                break
    ev["issn"] = issn

    oa = reg.openalex_source(issn) if issn else {"status": "error"}
    issns = [i for i in dict.fromkeys([issn] + list(oa.get("issn") or [])) if i]
    ev["issns"] = issns

    def first_found(fn):
        out = {"status": "error"}
        for i in issns:
            out = fn(i)
            if out["status"] == "found":
                return out
        return out

    ev["openalex"] = oa
    ev["crossref"] = first_found(reg.crossref_journal) if issns else {"status": "error"}
    ev["doaj"] = first_found(reg.doaj_journal) if issns else {"status": "error"}

    if site is None:
        home = oa.get("homepage_url") or ev["doaj"].get("url")
        site = fetch_site(home, deep=deep) if home else {"status": "error", "error": "no website known"}
        if home:
            ev["notes"].append("Website taken from the registry record")
    ev["site"] = site
    site_url = site.get("final_url") or site.get("url")
    ev["rdap"] = reg.rdap_domain(site_url) if site_url else {"status": "error"}

    st = lists_mod.store()
    best_title = title or oa.get("title") or ev["crossref"].get("title") or site.get("title")
    publisher = oa.get("publisher") or ev["crossref"].get("publisher") or ev["doaj"].get("publisher")
    ev["lists"] = {
        "hijacked": st.hijacked(site_url),
        "bealls": st.bealls(best_title, publisher, site_url),
        "scopus": st.in_scopus(issns),
        "integrity": st.integrity(issns, best_title, oa.get("works_count")),
        "available": st.available,
    }
    court = []
    dom = registered_domain(site_url) if site_url else None
    for r in _court_findings():
        if (publisher and norm_title(r.get("publisher")) and norm_title(r.get("publisher")) in norm_title(publisher)) or \
           (dom and r.get("domain") and dom == r.get("domain")):
            court.append(f"{r.get('publisher')}: {r.get('finding')}")
    ev["court_findings"] = court
    ev["display"] = {"title": best_title, "publisher": publisher, "website": site_url}
    ev["seconds"] = round(time.time() - t0, 1)
    return ev


def assess_evidence(ev: dict, model=None) -> dict:
    f = features.compute(ev)
    f["flags"]["k2_court_finding"] = bool(ev.get("court_findings"))
    rule = scoring.rule_score(f["indicators"])
    row = scoring.feature_row(f)
    t_ml = scoring.ml_trust(model, row)
    decision = scoring.decide(rule, t_ml, f["flags"])
    return {
        "journal": ev.get("display", {}),
        "issn": ev.get("issn"),
        "collected_at": ev.get("collected_at"),
        "indicators": f["indicators"],
        "numeric": f["numeric"],
        "flags": f["flags"],
        "court_findings": ev.get("court_findings", []),
        "rule": rule,
        "ml_trust": t_ml,
        "ml_factors": scoring.explain_logistic(model, row),
        "decision": decision,
        "notes": ev.get("notes", []),
        "lists_available": (ev.get("lists") or {}).get("available", {}),
    }


def assess(issn: str | None = None, title: str | None = None, url: str | None = None,
           deep: bool = True, model="default") -> dict:
    if model == "default":
        model = scoring.load_model()
    ev = collect_evidence(issn=issn, title=title, url=url, deep=deep)
    out = assess_evidence(ev, model)
    out["seconds"] = ev.get("seconds")
    return out
