"""Registry collectors: OpenAlex, Crossref, DOAJ and RDAP (domain registration)."""
from __future__ import annotations

from ..util import fetch, normalize_issn, registered_domain

OPENALEX = "https://api.openalex.org"
CROSSREF = "https://api.crossref.org"
DOAJ = "https://doaj.org/api/search/journals"
RDAP = "https://rdap.org/domain"


def _status(res: dict) -> str:
    if res.get("ok") and res.get("status") == 200:
        return "found"
    if res.get("status") in (404, 410):
        return "not_found"
    return "error"


def openalex_source(issn: str) -> dict:
    """OpenAlex source record for an ISSN (journal-level metadata, yearly counts, topics)."""
    res = fetch(f"{OPENALEX}/sources/issn:{normalize_issn(issn)}")
    out = {"status": _status(res), "fetched_at": res.get("fetched_at"), "api_url": res.get("url")}
    d = res.get("data") or {}
    if out["status"] == "found":
        stats = d.get("summary_stats") or {}
        topics = d.get("topics") or []
        field_counts: dict[str, int] = {}
        for t in topics:
            field = ((t.get("field") or {}).get("display_name")) or "unknown"
            field_counts[field] = field_counts.get(field, 0) + int(t.get("count") or 0)
        total = sum(field_counts.values())
        top_field, top_count = (max(field_counts.items(), key=lambda kv: kv[1]) if field_counts else (None, 0))
        out.update({
            "id": d.get("id"),
            "title": d.get("display_name"),
            "alternate_titles": d.get("alternate_titles") or [],
            "issn": d.get("issn") or [],
            "issn_l": d.get("issn_l"),
            "publisher": d.get("host_organization_name"),
            "homepage_url": d.get("homepage_url"),
            "is_in_doaj": d.get("is_in_doaj"),
            "is_oa": d.get("is_oa"),
            "is_core": d.get("is_core"),
            "apc_usd": d.get("apc_usd"),
            "works_count": d.get("works_count"),
            "cited_by_count": d.get("cited_by_count"),
            "two_yr_mean_citedness": stats.get("2yr_mean_citedness"),
            "h_index": stats.get("h_index"),
            "first_publication_year": d.get("first_publication_year"),
            "last_publication_year": d.get("last_publication_year"),
            "counts_by_year": [{"year": c.get("year"), "works": c.get("works_count", 0)}
                               for c in (d.get("counts_by_year") or [])],
            "top_field": top_field,
            "top_field_share": (top_count / total) if total else None,
            "type": d.get("type"),
        })
    return out


def openalex_search(title: str) -> dict:
    """Best OpenAlex source match for a journal title (used when only a title is given)."""
    res = fetch(f"{OPENALEX}/sources", params={"search": title, "per-page": 5})
    results = ((res.get("data") or {}).get("results")) or []
    return {"status": _status(res) if results else ("not_found" if res.get("ok") else "error"),
            "candidates": [{"title": r.get("display_name"), "issn_l": r.get("issn_l"),
                            "publisher": r.get("host_organization_name"), "works_count": r.get("works_count"),
                            "homepage_url": r.get("homepage_url")}
                           for r in results]}


def crossref_journal(issn: str) -> dict:
    res = fetch(f"{CROSSREF}/journals/{normalize_issn(issn)}")
    out = {"status": _status(res), "fetched_at": res.get("fetched_at"), "api_url": res.get("url")}
    m = (res.get("data") or {}).get("message") or {}
    if out["status"] == "found":
        counts = m.get("counts") or {}
        cov = m.get("coverage") or {}
        out.update({
            "title": m.get("title"),
            "publisher": m.get("publisher"),
            "total_dois": counts.get("total-dois"),
            "current_dois": counts.get("current-dois"),
            "licenses_current": cov.get("licenses-current"),
            "licenses_backfile": cov.get("licenses-backfile"),
        })
    return out


def doaj_journal(issn: str) -> dict:
    res = fetch(f"{DOAJ}/issn:{normalize_issn(issn)}")
    out = {"status": "error", "fetched_at": res.get("fetched_at"), "api_url": res.get("url")}
    if res.get("ok") and res.get("status") == 200:
        results = (res.get("data") or {}).get("results") or []
        if not results:
            out["status"] = "not_found"
        else:
            bib = results[0].get("bibjson") or {}
            apc = bib.get("apc") or {}
            out.update({
                "status": "found",
                "title": bib.get("title"),
                "url": ((bib.get("ref") or {}).get("journal")),
                "publisher": ((bib.get("publisher") or {}).get("name")),
                "has_apc": apc.get("has_apc"),
                "apc_max": apc.get("max"),
                "licenses": [lic.get("type") for lic in (bib.get("license") or [])],
                "has_preservation": ((bib.get("preservation") or {}).get("has_preservation")),
            })
    elif res.get("status") in (404, 410):
        out["status"] = "not_found"
    return out


def rdap_domain(url_or_domain: str | None) -> dict:
    """Registration date of the website's domain from RDAP (the modern WHOIS)."""
    dom = registered_domain(url_or_domain)
    if not dom:
        return {"status": "error", "domain": None}
    res = fetch(f"{RDAP}/{dom}")
    out = {"status": _status(res), "domain": dom, "fetched_at": res.get("fetched_at")}
    if out["status"] == "found":
        events = (res.get("data") or {}).get("events") or []
        reg = next((e.get("eventDate") for e in events if e.get("eventAction") == "registration"), None)
        out["registered"] = reg
        out["registered_year"] = int(reg[:4]) if reg and reg[:4].isdigit() else None
    return out
