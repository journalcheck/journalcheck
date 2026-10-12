"""Snapshot lists kept in data/lists (built by scripts/build_lists.py).

hijacked.csv              title, hijacked_url                (Retraction Watch Hijacked Journal Checker)
bealls.csv                name, url, kind                    (Beall's list archive: journals and publishers)
scimago.csv               title, issns                       (SCImago Journal Rank = Scopus-indexed titles)
scopus_discontinued.csv   title, issns                       (Scopus discontinued titles)
doaj_withdrawn.csv        title, issns, reason               (journals removed from DOAJ)
retractions.csv           journal, retractions               (Retraction Watch database, counted per journal)

A missing file makes the indicators that depend on it "unknown" instead of failing.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache

from .. import config
from ..util import norm_title, normalize_issn, registered_domain

LIST_FILES = ["hijacked", "bealls", "scimago", "scopus_discontinued", "doaj_withdrawn", "retractions"]


def _read(name: str) -> list[dict] | None:
    path = config.LISTS / f"{name}.csv"
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _issns(cell: str | None) -> set[str]:
    out = set()
    for tok in re.split(r"[,;\s]+", cell or ""):
        n = normalize_issn(tok)
        if n:
            out.add(n)
    return out


class ListStore:
    def __init__(self):
        self.rows = {name: _read(name) for name in LIST_FILES}
        self.available = {name: rows is not None for name, rows in self.rows.items()}
        # hijacked: domains of clone sites
        self.hijacked_domains = {}
        for r in self.rows["hijacked"] or []:
            dom = registered_domain(r.get("hijacked_url") or "")
            if dom and dom not in _SHARED_HOSTS:
                self.hijacked_domains[dom] = r.get("title", "")
        # Beall's: titles, publisher names and domains
        self.beall_titles, self.beall_domains, self.beall_publishers = {}, {}, {}
        for r in self.rows["bealls"] or []:
            name = norm_title(r.get("name"))
            dom = registered_domain(r.get("url") or "") if r.get("url") else None
            if r.get("kind") == "publisher":
                if name:
                    self.beall_publishers[name] = r.get("name")
            elif name:
                self.beall_titles[name] = r.get("name")
            if dom and dom not in _SHARED_HOSTS:
                self.beall_domains[dom] = r.get("name")
        self.scopus_issns = set()
        for r in self.rows["scimago"] or []:
            self.scopus_issns |= _issns(r.get("issns"))
        self.discontinued = {}
        for r in self.rows["scopus_discontinued"] or []:
            for i in _issns(r.get("issns")):
                self.discontinued[i] = r.get("title")
        self.withdrawn = {}
        for r in self.rows["doaj_withdrawn"] or []:
            for i in _issns(r.get("issns")):
                self.withdrawn[i] = r.get("reason") or "withdrawn"
        self.retractions = {norm_title(r.get("journal")): int(float(r.get("retractions") or 0))
                            for r in self.rows["retractions"] or []}

    # ---- lookups (each returns None when the list is missing)
    def hijacked(self, url: str | None):
        if not self.available["hijacked"]:
            return None
        dom = registered_domain(url) if url else None
        return {"listed": bool(dom and dom in self.hijacked_domains),
                "matched_title": self.hijacked_domains.get(dom) if dom else None}

    def bealls(self, title: str | None, publisher: str | None, url: str | None):
        if not self.available["bealls"]:
            return None
        hits = []
        t, p = norm_title(title), norm_title(publisher)
        dom = registered_domain(url) if url else None
        if t and t in self.beall_titles:
            hits.append(f"journal title: {self.beall_titles[t]}")
        if p and p in self.beall_publishers:
            hits.append(f"publisher: {self.beall_publishers[p]}")
        if dom and dom in self.beall_domains:
            hits.append(f"website domain: {dom}")
        return {"listed": bool(hits), "hits": hits}

    def in_scopus(self, issns: list[str]):
        if not self.available["scimago"]:
            return None
        return any(normalize_issn(i) in self.scopus_issns for i in issns if i)

    def integrity(self, issns: list[str], title: str | None, works_count: int | None = None):
        if not any(self.available[k] for k in ("scopus_discontinued", "doaj_withdrawn", "retractions")):
            return None
        reasons = []
        for i in filter(None, (normalize_issn(x) for x in issns)):
            if i in self.discontinued:
                reasons.append("discontinued by Scopus")
            if i in self.withdrawn:
                reasons.append(f"removed from DOAJ ({self.withdrawn[i]})")
        n = self.retractions.get(norm_title(title), 0) if title else 0
        rate = n / works_count if works_count else None
        if n >= config.INTEGRITY_RETRACTIONS and (rate is None or rate >= config.INTEGRITY_RATE):
            reasons.append(f"{n} retractions in the Retraction Watch database" + (f" ({1000 * rate:.0f} per 1,000 papers)" if rate else ""))
        return {"alert": bool(reasons), "reasons": sorted(set(reasons)), "retractions": n, "retraction_rate": rate}


# Hosting platforms shared by many journals: a domain match there says nothing.
_SHARED_HOSTS = {"blogspot.com", "wordpress.com", "weebly.com", "wix.com", "google.com",
                 "sites.google.com", "github.io", "academia.edu", "researchgate.net"}


@lru_cache(maxsize=1)
def store() -> ListStore:
    return ListStore()
