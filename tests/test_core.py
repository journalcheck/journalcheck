"""Offline tests: run with `pytest` (no network needed)."""
from journalcheck import config, features, scoring
from journalcheck.report import to_html, to_markdown
from journalcheck.util import find_issns, issn_checksum_ok, normalize_issn, registered_domain


def test_issn_checksum():
    assert issn_checksum_ok("2169-3536")      # IEEE Access
    assert issn_checksum_ok("0957-4174")      # Expert Systems with Applications
    assert issn_checksum_ok("2395-0056")      # IRJET
    assert not issn_checksum_ok("2169-3537")
    assert normalize_issn("21693536") == "2169-3536"
    assert find_issns("e-ISSN: 2395-0056 | p-ISSN 2395 0072, fake 1234-5678") == ["2395-0056", "2395-0072"]


def test_registered_domain():
    assert registered_domain("https://www.ijert.org/papers") == "ijert.org"
    assert registered_domain("http://journal.example.ac.in/x") == "example.ac.in"


def _evidence(site_text, links, emails, oa=None, cr=None, dj=None, lists=None, rdap=None, url="https://www.example-journal.org/"):
    return {
        "issn": "2395-0056",
        "openalex": oa or {"status": "not_found"},
        "crossref": cr or {"status": "not_found"},
        "doaj": dj or {"status": "not_found"},
        "site": {"status": "found", "url": url, "final_url": url, "title": "Example Journal", "site_name": "",
                 "heading": "", "all_text": site_text, "links": links, "emails": emails, "https": True},
        "rdap": rdap or {"status": "found", "domain": "example-journal.org", "registered_year": 2014},
        "lists": lists or {"hijacked": {"listed": False, "matched_title": None},
                           "bealls": {"listed": True, "hits": ["journal title: Example Journal"]},
                           "scopus": False, "integrity": {"alert": False, "reasons": [], "retractions": 0}},
    }


PREDATORY_TEXT = ("International Research Journal of Engineering, Science and Management. Impact Factor 8.315 (SJIF). "
                  "UGC Approved Journal. ISO 9001:2008 certified. Review status: in 1 week. Online publication within 3 days. "
                  "Free certificate of publication and hard copy to each author. Indexed in Scopus and Google Scholar.")


def test_predatory_profile_is_high_risk():
    ev = _evidence(PREDATORY_TEXT, [{"text": "Home", "href": "/"}], ["editor.irjet@gmail.com"])
    f = features.compute(ev)
    ind = f["indicators"]
    assert ind["I6"]["result"] == "fail" and ind["I7"]["result"] == "fail"
    assert ind["I8"]["result"] == "fail" and ind["I12"]["result"] == "fail"
    assert ind["I13"]["result"] == "fail" and ind["I14"]["result"] == "fail"
    assert f["flags"]["k3_false_claims"], "Scopus claim without Scopus listing must trigger K3"
    rule = scoring.rule_score(ind)
    d = scoring.decide(rule, None, f["flags"])
    assert d["verdict"] == "High risk"
    assert rule["trust"] < 50


LEGIT_OA = {"status": "found", "title": "Example Journal", "publisher": "IEEE", "homepage_url": "https://www.example-journal.org",
            "is_in_doaj": True, "apc_usd": 1995, "first_publication_year": 2013, "works_count": 5000, "cited_by_count": 90000,
            "two_yr_mean_citedness": 3.2, "h_index": 150, "top_field": "Computer Science", "top_field_share": 0.62,
            "counts_by_year": [{"year": y, "works": 800 + 50 * i} for i, y in enumerate(range(2015, 2026))]}


def test_legitimate_profile_is_low_risk():
    text = "Example Journal is a peer-reviewed open access journal. Article processing charge: US$1,995. Editorial Board. Publication ethics and retraction policy."
    links = [{"text": "Editorial Board", "href": "/eb"}, {"text": "Peer Review Process", "href": "/pr"}, {"text": "Publication Ethics", "href": "/ethics"}]
    lists = {"hijacked": {"listed": False, "matched_title": None}, "bealls": {"listed": False, "hits": []},
             "scopus": True, "integrity": {"alert": False, "reasons": [], "retractions": 0}}
    ev = _evidence(text, links, ["access@example-journal.org"], oa=LEGIT_OA,
                   cr={"status": "found", "title": "Example Journal", "total_dois": 5000, "licenses_current": 1.0},
                   dj={"status": "found", "title": "Example Journal", "url": "https://www.example-journal.org", "has_apc": True, "licenses": ["CC BY"]},
                   lists=lists)
    f = features.compute(ev)
    rule = scoring.rule_score(f["indicators"])
    assert rule["trust"] >= 90, rule
    d = scoring.decide(rule, None, f["flags"])
    assert d["verdict"] == "Low risk"
    assert "Low risk" in to_markdown({"journal": {"title": "Example"}, "issn": "2395-0056", "collected_at": "now", "decision": d,
                                      "rule": rule, "indicators": f["indicators"], "flags": f["flags"], "ml_trust": None, "ml_factors": []})


def test_clone_triggers_k1():
    lists = {"hijacked": {"listed": True, "matched_title": "Annals of RSCB"}, "bealls": {"listed": False, "hits": []},
             "scopus": True, "integrity": {"alert": False, "reasons": [], "retractions": 0}}
    oa = dict(LEGIT_OA, homepage_url="https://genuine-journal.ro", first_publication_year=1995)
    ev = _evidence("Annals of RSCB. Submit your paper.", [], [], oa=oa, lists=lists,
                   rdap={"status": "found", "domain": "clone.com", "registered_year": 2020}, url="https://clone.com/")
    f = features.compute(ev)
    assert f["indicators"]["I3"]["result"] == "fail" and f["indicators"]["I4"]["result"] == "fail"
    d = scoring.decide(scoring.rule_score(f["indicators"]), None, f["flags"])
    assert d["verdict"] == "High risk" and any(o.startswith("K1") for o in d["overrides"])


def test_speed_parser_ignores_slow_promises():
    assert features.speed_promises("First decision within 30 days on average") == []
    assert features.speed_promises("Publication within 48 hours of acceptance")
    assert features.speed_promises("Review Status: In 1 week")


def test_points_total():
    assert config.TOTAL_POINTS == 40
